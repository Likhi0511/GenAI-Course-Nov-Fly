"""
===============================================================================
enrich_pipeline_openai.py  -  Metadata Enrichment Pipeline  v2
===============================================================================

Author  : Prudhvi  |  Thoughtworks
Stage   : 3 of 5  (Extract -> Chunk -> Enrich -> Embed -> Store)

-------------------------------------------------------------------------------
SINGLE RESPONSIBILITY
-------------------------------------------------------------------------------

Per-chunk enrichment via a single GPT-4o-mini call that handles three tasks:

  1. PII DETECTION + REDACTION
     Identifies and redacts highly sensitive individual identifiers:
       - Personal names      -> [REDACTED_NAME]
       - Personal emails     -> [REDACTED_EMAIL]
       - Personal phones     -> [REDACTED_PHONE]
       - Home addresses      -> [REDACTED_ADDRESS]
     Result stored in chunk['content_sanitised'] — used by Stage 4 for embedding.
     Raw chunk['content'] is preserved unchanged for audit purposes.

  2. NAMED ENTITY RECOGNITION
     Extracts and categorises:
       - PERSON        (individual names)
       - ORGANIZATION  (companies, institutions)
       - DATE          (FY25, 2024-11-20, Q1 etc.)
       - GPE           (countries, cities, states)
       - MONEY         ($5.5M, £1000 etc.)
     Result stored in chunk['metadata']['entities'].

  3. KEY PHRASE EXTRACTION
     Top 5 noun phrases summarising the financial/business signal.
     Result stored in chunk['metadata']['key_phrases'].

  Plus: local regex for monetary values (free, zero API cost).

-------------------------------------------------------------------------------
STAGE CONTRACT
-------------------------------------------------------------------------------

Input  (from Stage 2 chunker output):
  chunk = {
    "content":  "raw text...",
    "metadata": { "breadcrumbs": "...", "chunk_types": [...], ... }
  }

Output (consumed by Stage 4 embedder):
  chunk = {
    "content":           "raw text...",          <- preserved unchanged
    "content_sanitised": "redacted text...",     <- Stage 4 embeds THIS
    "metadata": {
      "breadcrumbs":       "...",
      "chunk_types":       [...],
      "pii_redacted":      True,                 <- only set when PII found
      "entities":          { "PERSON": [...], ... },
      "key_phrases":       ["phrase1", ...],
      "monetary_values":   ["$5.5M", ...],       <- local regex, free
    }
  }

IMPORTANT for Stage 4:
  Stage 4 must embed content_sanitised when present, not raw content.
  In openai_embeddings.py:
    text_to_embed = chunk.get('content_sanitised') or chunk.get('content', '')

-------------------------------------------------------------------------------
UTF-8 DEFENCE
-------------------------------------------------------------------------------

Three layers protect against encoding issues:

  1. load_chunks_from_file() wraps read_json_robust() from utils.py
     Four-pass decode: charset-normalizer -> utf-8 -> windows-1252 -> latin-1

  2. enrich_chunk() has a defensive bytes guard on chunk content.
     Ray's object store or S3 reads can occasionally deliver bytes if an
     upstream stage skipped decoding.

  3. _safe_json_loads() handles OpenAI response as str or bytes.
     The SDK always returns str but this guards against edge cases.

-------------------------------------------------------------------------------
RESPONSE SHAPE RECOVERY
-------------------------------------------------------------------------------

OpenAI's json_object response_format guarantees valid JSON but NOT that the
top-level value is a dict. _recover_parsed_response() handles:

  dict   -> returned as-is                  (normal case)
  list   -> dicts merged, key_phrases deduped, entities unioned
  str    -> wrapped as redacted_text
  other  -> logged + empty dict returned    (safe defaults downstream)

-------------------------------------------------------------------------------
RAY / ASYNC NOTES
-------------------------------------------------------------------------------

- init_openai_client() returns AsyncOpenAI (required by Ray workers).
  Sync OpenAI() raises AttributeError when async coroutines try to use it.

- enrich_chunks_async() uses asyncio.Semaphore(max_concurrent) to bound
  concurrent API calls and prevent 429 rate-limit errors.

- STATS global is per-Ray-worker-process, not pipeline-wide.
  Ray isolates each worker process, so STATS reflects per-document counts.
  Pipeline-level counts come from the return dict in ray_tasks.py.

- asyncio.run() in ray_tasks.py starts a fresh event loop in the Ray worker
  and runs all enrichment coroutines to completion before returning.
"""

import re
import json as _json
import logging
import asyncio
from typing import Dict, List, Optional

from core.encoding import read_json_robust, write_json_utf8

# AsyncOpenAI required — sync client raises AttributeError in async coroutines
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
)
logger = logging.getLogger(__name__)

# Per-worker telemetry counters.
# NOTE: Ray workers are isolated processes — these are per-document counts,
# not pipeline totals. Pipeline-level metrics come from ray_tasks.py return dicts.
STATS = {
    'chunks_processed': 0,
    'openai_calls':     0,
    'openai_errors':    0,
    'entities_extracted': 0,
    'pii_replacements': 0,
}

# Local high-speed regex for financial extraction (zero API cost)
PATTERNS = {
    'monetary_values': re.compile(r'\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*([BMK])?'),
    'years':           re.compile(r'(?:FY|CY)?\s*20\d{2}'),
}

# Encoding fallback chain — ordered from strictest to most permissive.
# latin-1 is unconditional last resort: every byte maps to a codepoint.
_ENCODING_FALLBACKS = ("utf-8", "utf-8-sig", "windows-1252", "latin-1")


# ==============================================================================
# UTF-8 SAFE IN-MEMORY PARSING
# ==============================================================================

def _decode_bytes_robust(raw: bytes, label: str = "") -> str:
    """
    Decode a byte string to str using a four-pass strategy.
    Operates on an in-memory bytes object (not a file path).

    Pass 1: charset-normalizer auto-detection (ships with openai/requests)
    Pass 2: explicit fallback chain utf-8 -> utf-8-sig -> windows-1252 -> latin-1
    Pass 3: latin-1 + errors='replace' (unconditional, mathematically cannot fail)

    Used by:
      - _safe_json_loads()  when OpenAI response content arrives as bytes
      - enrich_chunk()      when chunk content arrives as bytes from S3/Ray

    Args:
        raw   : bytes to decode
        label : context string for log messages (chunk id, S3 key, etc.)

    Returns:
        Decoded str. Never raises UnicodeDecodeError.
    """
    text         = None
    detected_enc = None

    # Pass 1 — charset-normalizer
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw).best()
        if best is not None:
            detected_enc = best.encoding
            text         = str(best)
    except Exception:
        pass

    # Pass 2 — explicit fallback chain
    if text is None:
        for enc in _ENCODING_FALLBACKS:
            try:
                text         = raw.decode(enc)
                detected_enc = enc
                break
            except (UnicodeDecodeError, LookupError):
                continue

    # Pass 3 — unconditional latin-1 with replacement (cannot fail)
    if text is None:
        text         = raw.decode("latin-1", errors="replace")
        detected_enc = "latin-1-replace"
        logger.warning(
            "_decode_bytes_robust: %s — used latin-1 replace fallback", label
        )

    if detected_enc not in ("utf-8", "utf-8-sig", None):
        logger.warning(
            "_decode_bytes_robust: %s decoded as '%s' — check upstream encoding",
            label, detected_enc,
        )

    return text


def _safe_json_loads(raw, label: str = "") -> dict:
    """
    Parse JSON from either a str or bytes object, robustly.

    If raw is bytes it is decoded via _decode_bytes_robust before parsing
    so UnicodeDecodeError can never propagate to the caller.

    Args:
        raw   : str or bytes containing JSON
        label : context string for log messages

    Returns:
        Parsed object (dict, list, etc.) or {} on JSONDecodeError.
    """
    if isinstance(raw, bytes):
        raw = _decode_bytes_robust(raw, label=label)

    try:
        return _json.loads(raw)
    except _json.JSONDecodeError as e:
        logger.error(
            "_safe_json_loads: JSON decode error  label=%s  error=%s", label, e
        )
        return {}


# ==============================================================================
# CHUNK FILE I/O
# ==============================================================================

def load_chunks_from_file(path: str) -> List[Dict]:
    """
    Load a list of chunks from a JSON file, robustly handling any encoding.

    Wraps read_json_robust() from utils.py so all four encoding passes apply.
    Handles both list (multiple chunks) and dict (single chunk) top-level shapes.

    Args:
        path: Path to the chunks JSON file.

    Returns:
        List of chunk dicts. Empty list on any read/parse failure.
    """
    try:
        data = read_json_robust(path)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Bare dict = single chunk — wrap for uniform downstream handling
            logger.debug(
                "load_chunks_from_file: %s contains a single dict — wrapping in list",
                path,
            )
            return [data]
        logger.error(
            "load_chunks_from_file: unexpected type %s in %s",
            type(data).__name__, path,
        )
        return []
    except FileNotFoundError:
        logger.error("load_chunks_from_file: file not found — %s", path)
        return []
    except _json.JSONDecodeError as e:
        logger.error("load_chunks_from_file: JSON parse error in %s — %s", path, e)
        return []


def save_chunks_to_file(path: str, chunks: List[Dict]) -> None:
    """
    Persist enriched chunks to a JSON file in UTF-8 with ensure_ascii=False.

    Wraps write_json_utf8() from utils.py so non-ASCII characters in entity
    values, redacted text, and key phrases are stored as real Unicode rather
    than \\uXXXX escape sequences.

    Args:
        path   : Destination file path.
        chunks : List of enriched chunk dicts.
    """
    try:
        write_json_utf8(path, chunks)
        logger.info(
            "save_chunks_to_file: wrote %d chunks to %s", len(chunks), path
        )
    except Exception as e:
        logger.error(
            "save_chunks_to_file: failed to write %s — %s", path, e
        )


# ==============================================================================
# OPENAI CLIENT
# ==============================================================================

def init_openai_client(api_key: Optional[str] = None) -> Optional[AsyncOpenAI]:
    """
    Initialise the Asynchronous OpenAI client.

    AsyncOpenAI is required — Ray workers run async coroutines via asyncio.run()
    and the sync OpenAI() client raises AttributeError when async code tries
    to await its methods.

    On ECS the API key comes from Secrets Manager via config._parse_secret(),
    already unwrapped. Pass it explicitly rather than letting the client call
    os.getenv() which would return the raw JSON wrapper string and cause 401.
    """
    if not OPENAI_AVAILABLE:
        logger.error("OpenAI library not installed: pip install openai")
        return None
    return AsyncOpenAI(api_key=api_key)


# ==============================================================================
# RESPONSE SHAPE RECOVERY
# ==============================================================================

def _recover_parsed_response(parsed) -> Dict:
    """
    Normalise any JSON shape returned by the model into a usable dict.

    OpenAI's json_object response_format guarantees valid JSON but NOT that
    the top-level value is a dict. In practice the model occasionally returns:
      - A JSON array of dicts  -> merge all into one response
      - A plain string         -> wrap as redacted_text
      - Something else         -> log + return empty dict

    Recovery cases (evaluated in priority order):
      1. dict  -> returned as-is                           (normal path)
      2. list  -> merge dicts; deduplicate key_phrases;    (unusual but seen)
                  union entities per type
      3. str   -> wrap as redacted_text                    (rare)
      4. other -> log + return {}                          (safe defaults)

    Args:
        parsed: The result of _safe_json_loads() on the raw model response.

    Returns:
        A dict. Always has safe defaults for redacted_text / entities / key_phrases.
    """
    # ── 1. Already the correct shape ─────────────────────────────────────────
    if isinstance(parsed, dict):
        return parsed

    logger.warning(
        "_recover_parsed_response: unexpected type %s — attempting recovery",
        type(parsed).__name__,
    )

    # ── 2. List of dicts: merge all entries ───────────────────────────────────
    if isinstance(parsed, list) and parsed:
        merged: Dict = {
            "redacted_text": "",
            "entities":      {},
            "key_phrases":   [],
        }
        for item in parsed:
            if not isinstance(item, dict):
                continue
            # Last non-empty redacted_text wins
            if item.get("redacted_text"):
                merged["redacted_text"] = item["redacted_text"]
            # Union all entity dicts — merge lists within each entity type
            for entity_type, values in item.get("entities", {}).items():
                if entity_type not in merged["entities"]:
                    merged["entities"][entity_type] = []
                if isinstance(values, list):
                    merged["entities"][entity_type].extend(
                        v for v in values
                        if v not in merged["entities"][entity_type]
                    )
                else:
                    if values not in merged["entities"][entity_type]:
                        merged["entities"][entity_type].append(values)
            # Deduplicated key_phrases union
            merged["key_phrases"].extend(
                kp for kp in item.get("key_phrases", [])
                if kp not in merged["key_phrases"]
            )

        if any([merged["redacted_text"], merged["entities"], merged["key_phrases"]]):
            logger.info(
                "_recover_parsed_response: merged %d dict(s) from list response",
                sum(1 for i in parsed if isinstance(i, dict)),
            )
            return merged

        logger.error(
            "_recover_parsed_response: list response contained no recoverable dicts"
        )
        return {}

    # ── 3. Plain string: treat as redacted_text ───────────────────────────────
    if isinstance(parsed, str) and parsed.strip():
        logger.info(
            "_recover_parsed_response: plain string wrapped as redacted_text"
        )
        return {
            "redacted_text": parsed.strip(),
            "entities":      {},
            "key_phrases":   [],
        }

    # ── 4. Nothing recoverable ────────────────────────────────────────────────
    logger.error(
        "_recover_parsed_response: could not recover usable data — "
        "type=%s  value=%r",
        type(parsed).__name__, str(parsed)[:200],
    )
    return {}


# ==============================================================================
# OPENAI ENRICHMENT
# ==============================================================================

async def analyze_chunk_with_openai(
    text: str,
    client: AsyncOpenAI,
    model: str = "gpt-4o-mini",
) -> Dict:
    """
    Send a single text chunk to OpenAI for PII redaction, NER, and key phrases.

    One call covers all three enrichment tasks — cheaper than three separate
    Comprehend calls and more accurate on medical/scientific terminology.

    The system prompt and IMPORTANT instruction both assert that the response
    must be a single JSON object (not array) — reduces but does not eliminate
    the probability of the model returning an array. _recover_parsed_response()
    handles the remaining edge cases.

    Returns:
        Dict with keys: redacted_text, entities, key_phrases.
        Empty dict on any API or parse failure — caller uses safe defaults.
    """
    prompt = f"""
Act as a privacy expert and data analyst. Your goal is to identify PII while preserving the
analytical value of the document.

Analyze the following text and return a JSON object with:

1. "redacted_text":
   - Redact ONLY highly sensitive individual identifiers: Personal Names, Personal Emails,
     Personal Phone Numbers, and specific Home Addresses.
   - Use the format [REDACTED_TYPE].
   - **DO NOT REDACT**:
     * Dates like "2025", "Q1", "January", or fiscal years.
     * Geographies like "USA", "Japan", or "Europe".
     * Company names (e.g., "Morgan Stanley", "Apple").
     * Generic professional roles (e.g., "Analyst", "Manager").
   - **CONTEXT RULE**: If a date refers to a person's Birthday, redact it. If it refers to
     a report date or fiscal period, KEEP IT.

2. "entities":
   - Extract and categorize:
     - PERSON       (individual names)
     - ORGANIZATION (companies / institutions)
     - DATE         (temporal references like "FY25" or "2024-11-20")
     - GPE          (countries, cities, states)
     - MONEY        (financial amounts like "$5.5M")

3. "key_phrases":
   - A list of the top 5 noun phrases that summarize the core financial or business signal
     in this text.

IMPORTANT: Your response MUST be a single JSON object (not an array).
Start with {{ and end with }}.

Text:
{text}
"""
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a data analysis API. Always respond with a single JSON object "
                        "containing exactly three keys: 'redacted_text', 'entities', and 'key_phrases'. "
                        "Never respond with a JSON array."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        STATS['openai_calls'] += 1

        raw    = response.choices[0].message.content
        # _safe_json_loads handles bytes/str and catches JSONDecodeError
        parsed = _safe_json_loads(raw, label="openai_response")
        # _recover_parsed_response handles dict/list/str/other shapes
        return _recover_parsed_response(parsed)

    except _json.JSONDecodeError as e:
        logger.error("analyze_chunk_with_openai: JSON decode error: %s", e)
        STATS['openai_errors'] += 1
        return {}
    except Exception as e:
        logger.error("analyze_chunk_with_openai: API error: %s", e)
        STATS['openai_errors'] += 1
        return {}


# ==============================================================================
# CHUNK ENRICHMENT
# ==============================================================================

async def enrich_chunk(
    chunk: Dict,
    client: AsyncOpenAI,
    model: str = "gpt-4o-mini",
    **kwargs,
) -> Dict:
    """
    Enrich a single chunk with PII redaction, NER, key phrases, and monetary values.

    Steps:
      1. Defensive bytes guard — chunk content decoded if it arrives as bytes
         (can happen via Ray object store or S3 reads in some configurations)
      2. AI enrichment via OpenAI (PII + NER + key phrases in one call)
      3. Local regex pass for monetary values (free, no API cost)

    Output fields set on the chunk:
      chunk['content_sanitised']          — redacted text (Stage 4 embeds this)
      chunk['metadata']['pii_redacted']   — True when PII was found and redacted
      chunk['metadata']['entities']       — NER results dict
      chunk['metadata']['key_phrases']    — top 5 business phrases
      chunk['metadata']['monetary_values']— regex-extracted monetary amounts

    Note on content_sanitised vs content:
      chunk['content'] is NEVER modified — preserved for audit/debugging.
      Stage 4 must use:
        text_to_embed = chunk.get('content_sanitised') or chunk.get('content', '')
    """
    # ── Defensive bytes guard ─────────────────────────────────────────────────
    # Chunks should arrive as str but Ray's object store or S3 reads can
    # occasionally deliver bytes if an upstream stage skipped decoding.
    raw_text = chunk.get('content') or chunk.get('text', '')
    if isinstance(raw_text, bytes):
        logger.warning(
            "enrich_chunk: content arrived as bytes — decoding robustly  "
            "chunk_id=%s", chunk.get('id', 'unknown'),
        )
        raw_text = _decode_bytes_robust(raw_text, label=chunk.get('id', 'unknown'))
        # Write decoded str back so downstream stages see clean text
        if 'content' in chunk:
            chunk['content'] = raw_text
        else:
            chunk['text'] = raw_text

    text = raw_text
    if not text.strip():
        return chunk

    if 'metadata' not in chunk:
        chunk['metadata'] = {}

    # ── Step 1: OpenAI enrichment (async) ────────────────────────────────────
    analysis = await analyze_chunk_with_openai(text, client, model=model)

    if analysis:
        redacted = analysis.get('redacted_text', text)
        if redacted and redacted != text:
            # Store sanitised version separately — raw content is preserved
            chunk['content_sanitised']      = redacted
            chunk['metadata']['pii_redacted'] = True
            STATS['pii_replacements'] += 1

        chunk['metadata']['entities']    = analysis.get('entities',    {})
        chunk['metadata']['key_phrases'] = analysis.get('key_phrases', [])

        extracted_count = sum(
            len(v) if isinstance(v, list) else 1
            for v in analysis.get('entities', {}).values()
        )
        STATS['entities_extracted'] += extracted_count

    # ── Step 2: Local regex pass (monetary values) ────────────────────────────
    monetary = PATTERNS['monetary_values'].findall(text)
    chunk['metadata']['monetary_values'] = list(set(
        f"${amt}{sfx}" if sfx else f"${amt}"
        for amt, sfx in monetary
    ))

    STATS['chunks_processed'] += 1
    return chunk


# ==============================================================================
# ASYNC BATCH ENRICHMENT  —  ENTRY POINT FOR RAY_TASKS.PY
# ==============================================================================

async def enrich_chunks_async(
    chunks: List[Dict],
    client: AsyncOpenAI,
    max_concurrent: int = 20,
    model: str = "gpt-4o-mini",
    **kwargs,
) -> List[Dict]:
    """
    Enrich a full list of chunks in parallel with bounded concurrency.

    Entry point called by ray_tasks.py Stage 3:
      enriched_chunks = asyncio.run(
          enrich_chunks_async(
              chunks=chunks,
              client=openai_client,
              max_concurrent=20,
              model="gpt-4o-mini",
          )
      )

    Concurrency model:
      asyncio.Semaphore(max_concurrent) caps simultaneous OpenAI API calls.
      At max_concurrent=20: ~35 chunks at ~1s each takes ~2-3s vs ~35s sequential.
      Reduces to prevent 429 rate-limit errors on high-volume documents.

    Args:
        chunks        : List of chunk dicts from Stage 2 chunker output.
        client        : AsyncOpenAI instance from init_openai_client().
        max_concurrent: Max simultaneous API calls (default 20).
        model         : OpenAI model name (default "gpt-4o-mini").
        **kwargs      : Reserved for future params — not currently forwarded.

    Returns:
        List of enriched chunk dicts in the same order as input.
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def throttled_enrich(chunk: Dict) -> Dict:
        async with semaphore:
            return await enrich_chunk(chunk, client, model=model)

    tasks = [throttled_enrich(c) for c in chunks]
    return await asyncio.gather(*tasks)