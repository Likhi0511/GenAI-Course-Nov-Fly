"""
enrich_pipeline_openai.py
-------------------------
OpenAI-powered chunk enrichment pipeline — ASYNC / PARALLEL edition.

WHAT THIS PIPELINE DOES
------------------------
Takes a JSON file containing a list of text "chunks" (e.g. paragraphs extracted
from a PDF or document) and enriches each chunk with three AI-powered operations,
all performed in a single OpenAI API call per chunk:

  1. PII Redaction    — replaces sensitive personal identifiers with [REDACTED_TYPE]
                        while deliberately preserving business-relevant context like
                        company names, fiscal dates, and geographies.

  2. NER (Named Entity Recognition)
                      — extracts structured entities: PERSON, ORGANIZATION, DATE,
                        GPE (geopolitical), MONEY.

  3. Key Phrase Extraction
                      — pulls the top-5 noun phrases that carry the core
                        financial or business signal of the chunk.

Additionally, a fast local regex pass runs on every chunk for free — no API cost —
to extract structured monetary values ($5.5M, $1,200, etc.).

WHY ASYNC?
----------
The original pipeline processed chunks sequentially — one API call at a time.
For a document with 71 chunks at ~1s per GPT-4o-mini call, that is ~71s wall-clock.

This version fires ALL chunk enrichment calls concurrently using asyncio +
AsyncOpenAI.  Wall-clock time drops to the latency of the SLOWEST single call
(typically 2–4s), regardless of how many chunks there are.

  Sequential (old): 71 chunks × 1s  =  ~71s
  Async     (new):  71 chunks in parallel  =  ~3–5s   (18–24× faster)

CONCURRENCY CONTROL
-------------------
A semaphore (default: 20 concurrent calls) prevents hammering the API with all
71 calls at once, which would trigger rate-limit 429 errors.  The semaphore
acts as a sliding window — as soon as one call completes, the next one starts.

Rate-limit formula:
  - gpt-4o-mini default tier: ~500 RPM (requests per minute)
  - With 20 concurrent calls and ~1s latency each: ~20 RPS × 60 = 1200 RPM
  - Stay safe: use MAX_CONCURRENT = 10–20 for shared API keys

RETRY STRATEGY
--------------
Each API call retries up to MAX_RETRIES times on RateLimitError with
exponential backoff: 2^attempt seconds (2s, 4s, 8s).
Other errors (BadRequest, AuthenticationError) are NOT retried — they indicate
a permanent problem that retrying won't fix.

OUTPUT
------
Writes  <input_stem>_enriched_openai.json  to the same directory as the input
file by default, or to --output_dir if specified.

Each enriched chunk gains:
  - content_sanitised         : redacted version of the text (only if PII was found)
  - metadata.pii_redacted     : True flag (only if PII was found)
  - metadata.entities         : dict of entity lists by category
  - metadata.key_phrases      : list of top-5 business-signal phrases
  - metadata.monetary_values  : list of monetary strings found by local regex

USAGE
-----
  python enrich_pipeline_openai.py /path/to/chunks.json
  python enrich_pipeline_openai.py /path/to/chunks.json --model gpt-4o
  python enrich_pipeline_openai.py /path/to/chunks.json --max-concurrent 30
  python enrich_pipeline_openai.py /path/to/chunks.json --output_dir /tmp/out
  python enrich_pipeline_openai.py /path/to/chunks.json --api_key sk-...

DEPENDENCIES
------------
  pip install openai
  (asyncio is part of the Python standard library — no extra install needed)
"""

import re
import json
import asyncio
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Optional dependency guard
# The pipeline degrades gracefully if openai is not installed.
# ---------------------------------------------------------------------------
try:
    from openai import AsyncOpenAI, RateLimitError
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Concurrency + retry configuration
# ---------------------------------------------------------------------------

# Maximum simultaneous in-flight API requests.
# Higher = faster, but risks 429 rate-limit errors on shared keys.
# 20 is a safe default for gpt-4o-mini on standard tier accounts.
DEFAULT_MAX_CONCURRENT = 20

# How many times to retry a single chunk on RateLimitError before giving up.
MAX_RETRIES = 3

# Base for exponential backoff: attempt 0 → 2s, attempt 1 → 4s, attempt 2 → 8s
BACKOFF_BASE = 2


# ---------------------------------------------------------------------------
# Thread-safe statistics
# ---------------------------------------------------------------------------
# asyncio is single-threaded — coroutines never run truly in parallel within
# one event loop, so a plain dict is safe (no Lock needed).
# Each counter is updated only after an await returns — no interleaving.
STATS: Dict[str, int] = {
    'chunks_processed'  : 0,  # chunks that completed enrichment (AI + regex)
    'openai_calls'      : 0,  # successful API round-trips
    'openai_errors'     : 0,  # failed API calls (chunk still returned, un-enriched)
    'entities_extracted': 0,  # sum of all entity items across all chunks
    'pii_replacements'  : 0,  # chunks where at least one PII token was redacted
    'chunks_skipped'    : 0,  # empty chunks bypassed without API call
}


# ---------------------------------------------------------------------------
# Local regex patterns (zero-cost, deterministic extraction)
# ---------------------------------------------------------------------------
# These run on EVERY chunk regardless of API success/failure.
# They act as a structured supplement to the AI output — always consistent,
# no hallucination risk, and free to run.
PATTERNS = {
    'monetary_values': re.compile(r'\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*([BMK])?'),
    'years'          : re.compile(r'(?:FY|CY)?\s*20\d{2}'),
}


# ===========================================================================
# OpenAI Client Initialization
# ===========================================================================

def init_openai_client(api_key: Optional[str] = None) -> Optional['AsyncOpenAI']:
    """
    Creates and returns an AsyncOpenAI client instance.

    WHY AsyncOpenAI (not OpenAI)?
    The async client exposes coroutine-based methods (await client.chat...).
    Using the sync OpenAI client inside an async function would block the
    entire event loop for the duration of each HTTP round-trip, eliminating
    all concurrency benefits.

    Authentication priority:
      1. Explicit api_key argument (passed via --api_key CLI flag or Ray config)
      2. OPENAI_API_KEY environment variable (default OpenAI SDK behaviour)

    Returns None if the openai package is missing or initialisation fails.
    """
    if not OPENAI_AVAILABLE:
        logger.error("OpenAI library not installed: pip install openai")
        return None
    try:
        client = AsyncOpenAI(api_key=api_key)
        logger.info("AsyncOpenAI client initialised")
        return client
    except Exception as e:
        logger.error(f"Failed to init AsyncOpenAI: {e}")
        return None


# ===========================================================================
# Core AI Analysis — async, with retry on rate-limit
# ===========================================================================

async def analyze_chunk_with_openai(
    text: str,
    client: 'AsyncOpenAI',
    model: str = "gpt-4o-mini",
    semaphore: Optional[asyncio.Semaphore] = None,
) -> Dict:
    """
    Sends a single chunk of text to OpenAI and retrieves a structured JSON
    response covering PII redaction, NER, and key phrase extraction.

    CONCURRENCY MODEL
    -----------------
    This coroutine is fired for EVERY chunk simultaneously via asyncio.gather().
    The semaphore parameter limits how many are in-flight at once — without it,
    all 71 chunks would hit the API simultaneously, saturating rate limits.

    RETRY ON RATE LIMIT
    -------------------
    RateLimitError (HTTP 429) is the only retryable error — it means "slow down,
    try again later".  Other errors (400 BadRequest, 401 Unauthorized) indicate
    permanent problems that retrying cannot fix, so they fall through immediately.

    WHY ONE CALL FOR THREE TASKS?
    Batching PII redaction + NER + key phrase extraction into one prompt reduces
    latency and cost vs. three separate calls.  The model has full context to
    make consistent decisions across all three tasks simultaneously.

    Args:
        text      : raw text content of a single chunk
        client    : initialised AsyncOpenAI client (shared across all coroutines)
        model     : OpenAI model name (default gpt-4o-mini for cost efficiency)
        semaphore : asyncio.Semaphore controlling max concurrent in-flight calls

    Returns:
        Parsed dict with keys: redacted_text, entities, key_phrases.
        Returns {} on any API or parse error so the caller handles gracefully.
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
         - PERSON (Individual names)
         - ORGANIZATION (Companies/Institutions)
         - DATE (Temporal references like "FY25" or "2024-11-20")
         - GPE (Countries, Cities, States)
         - MONEY (Financial amounts like "$5.5M")

    3. "key_phrases": 
       - A list of the top 5 noun phrases that summarize the core "Financial or Business signal" 
         in this text.

    Text:
    {text}
    """

    # Acquire semaphore slot before making the API call.
    # If MAX_CONCURRENT slots are already in use, this line suspends (awaits)
    # until one slot is released — naturally throttling the request rate.
    ctx = semaphore if semaphore else _null_context()

    async with ctx:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    # json_object mode guarantees parseable output — no markdown fences.
                    response_format={"type": "json_object"},
                    timeout=60.0,  # per-call timeout; prevents hung coroutines
                )
                STATS['openai_calls'] += 1
                return json.loads(response.choices[0].message.content)

            except RateLimitError:
                # 429 — back off and retry.
                # 2^attempt: 2s → 4s → 8s between retries.
                wait = BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "RateLimitError on attempt %d/%d — retrying in %ds",
                    attempt + 1, MAX_RETRIES, wait,
                )
                await asyncio.sleep(wait)

            except Exception as e:
                # Non-retryable error (BadRequest, AuthError, network, etc.)
                # Log and return empty dict — enrich_chunk_async handles this.
                logger.error("OpenAI API error (non-retryable): %s", e)
                STATS['openai_errors'] += 1
                return {}

        # All retries exhausted on RateLimitError
        logger.error("All %d retries exhausted for a chunk — returning empty result.", MAX_RETRIES)
        STATS['openai_errors'] += 1
        return {}


class _null_context:
    """
    No-op async context manager — used when no semaphore is provided.
    Allows `async with ctx:` to work whether or not a semaphore exists.
    """
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass


# ===========================================================================
# Per-Chunk Enrichment — async
# ===========================================================================

async def enrich_chunk_async(
    chunk: Dict,
    client: 'AsyncOpenAI',
    semaphore: asyncio.Semaphore,
    **kwargs,
) -> Dict:
    """
    Enriches a single chunk dict with AI analysis and local regex results.

    This is the async equivalent of the original enrich_chunk().
    It is called concurrently for all chunks via asyncio.gather() in run_pipeline_async().

    Two-stage enrichment strategy:
      Stage 1 — AI (AsyncOpenAI): PII redaction, NER, key phrases — all in one call.
                                   Runs concurrently across chunks (up to MAX_CONCURRENT).
      Stage 2 — Regex (local):    Monetary value extraction — synchronous, instant, free.
                                   Runs in the same coroutine after the AI call returns.

    The chunk is ALWAYS returned, even if the API call fails — the pipeline
    continues processing all remaining chunks regardless of individual failures.

    Args:
        chunk     : dict with at minimum a 'content' or 'text' key
        client    : shared AsyncOpenAI client (one instance for all coroutines)
        semaphore : concurrency limiter shared across all enrich_chunk_async coroutines
        **kwargs  : passed through to analyze_chunk_with_openai (e.g. model=...)

    Returns:
        The same chunk dict, mutated in-place with new metadata fields.
    """
    # Support both 'content' and 'text' as the chunk text key — compatible
    # with LangChain, Docling, and other upstream chunking libraries.
    text = chunk.get('content') or chunk.get('text', '')

    # Skip empty chunks — nothing to enrich; avoid wasted API calls.
    if not text.strip():
        STATS['chunks_skipped'] += 1
        return chunk

    # Ensure metadata dict exists before writing sub-keys into it.
    if 'metadata' not in chunk:
        chunk['metadata'] = {}

    # ------------------------------------------------------------------
    # Stage 1: AI-powered enrichment (one async API call, three results)
    # ------------------------------------------------------------------
    analysis = await analyze_chunk_with_openai(
        text, client,
        model=kwargs.get('model', 'gpt-4o-mini'),
        semaphore=semaphore,
    )

    if analysis:
        # --- PII Redaction ---
        # Only write content_sanitised if the model actually changed the text.
        # This keeps the output clean — chunks with no PII stay unchanged.
        redacted = analysis.get('redacted_text', text)
        if redacted != text:
            chunk['content_sanitised']        = redacted
            chunk['metadata']['pii_redacted'] = True
            STATS['pii_replacements'] += 1

        # --- Named Entity Recognition ---
        # Expected format (dict of lists):
        #   { "PERSON": ["John Smith"], "MONEY": ["$5.5M"], "GPE": ["USA"] }
        #
        # GPT-4o-mini sometimes returns entities as a list of objects instead:
        #   [{"type": "PERSON", "value": "John Smith"}, ...]
        # Both formats are normalised to the dict-of-lists schema here so
        # downstream stages always receive a consistent structure.
        raw_entities = analysis.get('entities', {})
        if isinstance(raw_entities, list):
            # Convert list-of-objects → dict-of-lists
            normalised: Dict = {}
            for item in raw_entities:
                if isinstance(item, dict):
                    etype  = str(item.get('type', item.get('label', item.get('entity', 'UNKNOWN'))))
                    evalue = item.get('value', item.get('text', item.get('name', str(item))))
                    normalised.setdefault(etype, []).append(evalue)
            raw_entities = normalised
        elif not isinstance(raw_entities, dict):
            # Unexpected format (string, int, etc.) — discard gracefully
            logger.warning('Unexpected entities format: %s — discarding', type(raw_entities).__name__)
            raw_entities = {}

        chunk['metadata']['entities'] = raw_entities
        STATS['entities_extracted'] += sum(
            len(v) if isinstance(v, list) else 1
            for v in raw_entities.values()
        )

        # --- Key Phrases ---
        # Top-5 noun phrases capturing the financial/business signal.
        # Guard: model occasionally returns a dict or comma-joined string instead of a list.
        raw_phrases = analysis.get('key_phrases', [])
        if isinstance(raw_phrases, str):
            raw_phrases = [p.strip() for p in raw_phrases.split(',') if p.strip()]
        elif isinstance(raw_phrases, dict):
            raw_phrases = list(raw_phrases.values())
        elif not isinstance(raw_phrases, list):
            raw_phrases = []
        chunk['metadata']['key_phrases'] = raw_phrases

    # ------------------------------------------------------------------
    # Stage 2: Local regex extraction (synchronous, instant, free)
    # ------------------------------------------------------------------
    # Runs regardless of API success — always reliable, zero cost.
    monetary = PATTERNS['monetary_values'].findall(text)
    chunk['metadata']['monetary_values'] = [
        f"${amt}{sfx}" if sfx else f"${amt}"
        for amt, sfx in monetary
    ]

    STATS['chunks_processed'] += 1
    return chunk


# ===========================================================================
# Async Pipeline Orchestration
# ===========================================================================

async def run_pipeline_async(
    input_file: str,
    api_key: Optional[str],
    output_dir: Optional[str] = None,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    **kwargs,
) -> None:
    """
    Orchestrates the full enrichment pipeline end-to-end using async/await.

    CONCURRENCY MODEL
    -----------------
    asyncio.gather() fires one coroutine per chunk simultaneously.
    The semaphore(max_concurrent) limits how many are in-flight at once:

      max_concurrent=20, 71 chunks:
        - Slots 1–20  start immediately
        - Slots 21–71 each start as soon as one of the first 20 finishes
        - Wall-clock ≈ latency of the slowest call in the largest wave

    RETURN ORDER
    ------------
    asyncio.gather() preserves the order of results matching the order of
    input coroutines — enriched_chunks[i] always corresponds to chunks[i].
    Document reading order is preserved.

    Steps:
      1. Initialise AsyncOpenAI client
      2. Load chunks from the input JSON file
      3. Enrich ALL chunks concurrently (bounded by semaphore)
      4. Write the enriched output file
      5. Print final stats to stdout

    Args:
        input_file     : path to input JSON — must contain a top-level "chunks" list
        api_key        : optional OpenAI API key (falls back to env var if None)
        output_dir     : optional output directory override
        max_concurrent : max simultaneous in-flight API calls (default: 20)
        **kwargs       : forwarded to enrich_chunk_async (e.g. model=...)
    """
    start = datetime.now()

    client = init_openai_client(api_key)
    if not client:
        return

    input_path = Path(input_file).resolve()

    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    chunks = data.get('chunks', [])
    logger.info(
        "Processing %d chunks via AsyncOpenAI | max_concurrent=%d | model=%s",
        len(chunks), max_concurrent, kwargs.get('model', 'gpt-4o-mini'),
    )

    # ------------------------------------------------------------------
    # Create the shared semaphore — ONE instance for all coroutines.
    # All enrich_chunk_async coroutines share this semaphore so the
    # total number of in-flight API calls is always ≤ max_concurrent.
    # ------------------------------------------------------------------
    semaphore = asyncio.Semaphore(max_concurrent)

    # ------------------------------------------------------------------
    # Fire all enrichment coroutines concurrently.
    #
    # asyncio.gather() takes a list of coroutines and runs them all
    # "at the same time" (interleaved on the single-threaded event loop).
    # Each time a coroutine awaits (e.g. waiting for an HTTP response),
    # the event loop switches to another coroutine that is ready to run.
    #
    # return_exceptions=True: if one chunk's coroutine raises an unhandled
    # exception, gather() still completes the other chunks and returns the
    # exception as the result for that position (rather than cancelling all).
    # We then filter those out below.
    # ------------------------------------------------------------------
    tasks = [
        enrich_chunk_async(chunk, client, semaphore, **kwargs)
        for chunk in chunks
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------------
    # Handle any coroutines that raised unexpected exceptions.
    # return_exceptions=True means failed coroutines return an Exception
    # object instead of raising — we fall back to the original chunk so
    # the output file always contains all chunks.
    # ------------------------------------------------------------------
    enriched_chunks = []
    for original, result in zip(chunks, results):
        if isinstance(result, Exception):
            logger.error("Chunk enrichment raised unexpected exception: %s", result)
            STATS['openai_errors'] += 1
            enriched_chunks.append(original)   # original chunk, no enrichment
        else:
            enriched_chunks.append(result)

    # ------------------------------------------------------------------
    # Write output
    # ------------------------------------------------------------------
    out_dir = Path(output_dir).resolve() if output_dir else input_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    output_path = out_dir / (input_path.stem + "_enriched_openai.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({'chunks': enriched_chunks, 'stats': STATS}, f, indent=2)

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(
        "Done in %.1fs | %d chunks enriched | %d skipped | %d errors | saved to %s",
        elapsed, STATS['chunks_processed'], STATS['chunks_skipped'],
        STATS['openai_errors'], output_path,
    )

    # Print stats to stdout as JSON for piping / monitoring
    print(json.dumps(STATS, indent=2))


# ===========================================================================
# Public sync wrapper — callable from Ray tasks or other sync contexts
# ===========================================================================

def run_pipeline(
    input_file: str,
    api_key: Optional[str],
    output_dir: Optional[str] = None,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    **kwargs,
) -> None:
    """
    Synchronous entry point — wraps run_pipeline_async() with asyncio.run().

    WHY A SYNC WRAPPER?
    -------------------
    Ray tasks (ray_tasks.py enrich_chunks function) are synchronous Python
    functions — they cannot use `await` directly.  asyncio.run() starts a
    fresh event loop, runs the async pipeline to completion, then returns.

    Also used by the CLI entry point below.

    Args: same as run_pipeline_async().
    """
    asyncio.run(run_pipeline_async(
        input_file=input_file,
        api_key=api_key,
        output_dir=output_dir,
        max_concurrent=max_concurrent,
        **kwargs,
    ))


# ===========================================================================
# Async enrich_chunks — callable directly from async contexts
# ===========================================================================

async def enrich_chunks_async(
    chunks: List[Dict],
    client: 'AsyncOpenAI',
    max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    **kwargs,
) -> List[Dict]:
    """
    Enrich a list of chunk dicts in-memory without file I/O.

    Used by ray_tasks.enrich_chunks() which already has chunks loaded in memory
    and handles its own S3 I/O — it doesn't need the file-based run_pipeline().

    Example usage from ray_tasks:
        client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        enriched = asyncio.run(enrich_chunks_async(chunks, client, model="gpt-4o-mini"))

    Args:
        chunks         : list of chunk dicts (must have 'content' or 'text' key)
        client         : shared AsyncOpenAI client
        max_concurrent : max simultaneous in-flight API calls
        **kwargs       : forwarded to enrich_chunk_async (e.g. model=...)

    Returns:
        List of enriched chunk dicts in the same order as input.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    tasks = [
        enrich_chunk_async(chunk, client, semaphore, **kwargs)
        for chunk in chunks
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    enriched: List[Dict] = []
    for original, result in zip(chunks, results):
        if isinstance(result, Exception):
            logger.error("Chunk enrichment raised unexpected exception: %s", result)
            STATS['openai_errors'] += 1
            enriched.append(original)
        else:
            enriched.append(result)
    return enriched


# ===========================================================================
# CLI Entry Point
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Async OpenAI-powered chunk enrichment: PII redaction, NER, key phrases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python enrich_pipeline_openai.py data/chunks.json
  python enrich_pipeline_openai.py data/chunks.json --model gpt-4o
  python enrich_pipeline_openai.py data/chunks.json --max-concurrent 30
  python enrich_pipeline_openai.py data/chunks.json --output_dir /tmp/out

Performance reference (gpt-4o-mini, standard tier):
  Sequential (old): 71 chunks × ~1s  ≈  71s
  Async      (new): 71 chunks / 20 concurrent  ≈  4–6s
        """
    )
    parser.add_argument(
        'input_file',
        help="Path to input JSON file containing a top-level 'chunks' list",
    )
    parser.add_argument(
        '--api_key',
        default=None,
        help="OpenAI API key (default: reads from OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        '--model',
        default='gpt-4o-mini',
        help="OpenAI model to use (default: gpt-4o-mini). Use gpt-4o for higher accuracy.",
    )
    parser.add_argument(
        '--max-concurrent',
        type=int,
        default=DEFAULT_MAX_CONCURRENT,
        dest='max_concurrent',
        help=f"Max simultaneous API calls (default: {DEFAULT_MAX_CONCURRENT}). "
             f"Higher = faster but risks 429 rate-limit errors.",
    )
    parser.add_argument(
        '--output_dir',
        default=None,
        help="Directory to write enriched output (default: same directory as input file)",
    )
    args = parser.parse_args()

    run_pipeline(
        args.input_file,
        args.api_key,
        output_dir=args.output_dir,
        max_concurrent=args.max_concurrent,
        model=args.model,
    )