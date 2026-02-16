"""
enrich_pipeline_openai.py
-------------------------
OpenAI-powered chunk enrichment pipeline.

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

OUTPUT
------
Writes  <input_stem>_enriched_openai.json  to the same directory as the input
file by default, or to --output_dir if specified.

Each enriched chunk gains:
  - content_sanitised   : redacted version of the text (only if PII was found)
  - metadata.pii_redacted     : True flag (only if PII was found)
  - metadata.entities         : dict of entity lists by category
  - metadata.key_phrases      : list of top-5 business-signal phrases
  - metadata.monetary_values  : list of monetary strings found by local regex

USAGE
-----
  python enrich_pipeline_openai.py /path/to/chunks.json
  python enrich_pipeline_openai.py /path/to/chunks.json --model gpt-4o
  python enrich_pipeline_openai.py /path/to/chunks.json --output_dir /tmp/out
  python enrich_pipeline_openai.py /path/to/chunks.json --api_key sk-...

DEPENDENCIES
------------
  pip install openai
"""

import re
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Optional dependency guard
# The pipeline degrades gracefully if openai is not installed — the import
# error is caught here so the rest of the module still loads, and a clear
# error message is shown at runtime rather than at import time.
# ---------------------------------------------------------------------------
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Module-level logger so every function can emit structured log lines.
# Format: timestamp | level | message  — easy to grep in CI/CD logs.
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Runtime statistics
# ---------------------------------------------------------------------------
# A single mutable dict accumulates counts across the entire pipeline run.
# Printed as JSON at the end so it can be piped into monitoring / alerting.
STATS = {
    'chunks_processed': 0,   # total chunks that completed enrichment
    'openai_calls': 0,        # successful API round-trips
    'openai_errors': 0,       # failed API calls (chunk still returned, just un-enriched)
    'entities_extracted': 0,  # sum of all entity items across all chunks
    'pii_replacements': 0,    # number of chunks where at least one PII token was redacted
}


# ---------------------------------------------------------------------------
# Local regex patterns (zero-cost, deterministic extraction)
# ---------------------------------------------------------------------------
# These run on EVERY chunk regardless of API success/failure.
# They act as a structured supplement to the AI output — always consistent,
# no hallucination risk, and free to run.
#
# monetary_values: captures dollar amounts with optional B/M/K suffix
#   e.g. "$5.5M", "$1,200", "$ 3B"  →  groups: (amount_str, suffix)
#
# years: captures standalone fiscal/calendar year references
#   e.g. "FY2025", "CY 2024", "2023"
PATTERNS = {
    'monetary_values': re.compile(r'\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*([BMK])?'),
    'years':           re.compile(r'(?:FY|CY)?\s*20\d{2}'),
}


# ===========================================================================
# OpenAI Client Initialization
# ===========================================================================

def init_openai_client(api_key: Optional[str] = None) -> Optional['OpenAI']:
    """
    Creates and returns an OpenAI client instance.

    Authentication priority:
      1. Explicit api_key argument (passed via --api_key CLI flag)
      2. OPENAI_API_KEY environment variable (default OpenAI SDK behaviour)

    Returns None if the openai package is missing or initialisation fails,
    allowing the caller to exit cleanly rather than crash mid-pipeline.
    """
    if not OPENAI_AVAILABLE:
        logger.error("OpenAI library not installed: pip install openai")
        return None
    try:
        # Passing api_key=None here is intentional — the OpenAI SDK will
        # automatically fall back to the OPENAI_API_KEY environment variable.
        client = OpenAI(api_key=api_key)
        return client
    except Exception as e:
        logger.error(f"Failed to init OpenAI: {e}")
        return None


# ===========================================================================
# Core AI Analysis — one API call does all three enrichment tasks
# ===========================================================================

def analyze_chunk_with_openai(text: str, client: 'OpenAI', model: str = "gpt-4o-mini") -> Dict:
    """
    Sends a single chunk of text to OpenAI and retrieves a structured JSON
    response covering PII redaction, NER, and key phrase extraction.

    WHY ONE CALL FOR THREE TASKS?
    Batching all three operations into one prompt reduces latency and cost
    compared to three separate calls. The model has full context to make
    consistent decisions across all three tasks simultaneously.

    PROMPT DESIGN NOTES:
    - response_format={"type": "json_object"} forces the model to return
      valid JSON, eliminating the need for markdown-fence stripping.
    - The redaction rules are intentionally conservative: only redact genuine
      personal identifiers, never business context like company names or
      fiscal periods. This preserves downstream analytical value.
    - The CONTEXT RULE for dates handles the edge case where a date string
      (e.g. "01/15/1985") could be either a birthday (redact) or a report
      date (keep).

    Args:
        text   : raw text content of a single chunk
        client : initialised OpenAI client
        model  : OpenAI model name (default gpt-4o-mini for cost efficiency)

    Returns:
        Parsed dict with keys: redacted_text, entities, key_phrases.
        Returns {} on any API or parse error so the caller can handle gracefully.
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

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            # json_object mode guarantees parseable output — no need to strip
            # markdown fences or handle free-text preambles from the model.
            response_format={"type": "json_object"}
        )
        STATS['openai_calls'] += 1
        return json.loads(response.choices[0].message.content)

    except Exception as e:
        # Catch-all: network errors, rate limits, malformed responses, etc.
        # Log and return empty dict — enrich_chunk() handles the empty case
        # so the chunk is still returned (just without AI enrichment).
        logger.error(f"OpenAI API error: {e}")
        STATS['openai_errors'] += 1
        return {}


# ===========================================================================
# Per-Chunk Enrichment
# ===========================================================================

def enrich_chunk(chunk: Dict, client: 'OpenAI', **kwargs) -> Dict:
    """
    Enriches a single chunk dict in-place with AI analysis and local regex results.

    Two-stage enrichment strategy:
      Stage 1 — AI (OpenAI): handles nuanced tasks that need language understanding
                              (PII context, entity boundaries, semantic phrases).
      Stage 2 — Regex (local): handles precise, unambiguous patterns like monetary
                                amounts that a regex handles perfectly and for free.

    The chunk is always returned, even if the API call fails — in that case
    it simply won't have the AI-derived metadata fields, but the pipeline
    continues processing the remaining chunks uninterrupted.

    Args:
        chunk  : dict with at minimum a 'content' or 'text' key
        client : initialised OpenAI client
        **kwargs: passed through to analyze_chunk_with_openai (e.g. model=...)

    Returns:
        The same chunk dict, mutated with new metadata fields.
    """
    # Support both 'content' and 'text' as the chunk text key for flexibility
    # across different upstream chunking libraries (LangChain, Docling, etc.)
    text = chunk.get('content') or chunk.get('text', '')

    # Skip empty chunks — nothing to enrich, return as-is to avoid wasted API calls
    if not text.strip():
        return chunk

    # Ensure metadata dict exists before writing sub-keys into it
    if 'metadata' not in chunk:
        chunk['metadata'] = {}

    # ------------------------------------------------------------------
    # Stage 1: AI-powered enrichment (one API call, three results)
    # ------------------------------------------------------------------
    analysis = analyze_chunk_with_openai(text, client, model=kwargs.get('model', 'gpt-4o-mini'))

    if analysis:
        # --- PII Redaction ---
        # Only write content_sanitised if the model actually changed the text.
        # This keeps the output clean — chunks with no PII stay unchanged and
        # don't get a redundant duplicate of their own content.
        redacted = analysis.get('redacted_text', text)
        if redacted != text:
            chunk['content_sanitised'] = redacted          # redacted copy of the text
            chunk['metadata']['pii_redacted'] = True       # flag for downstream filtering
            STATS['pii_replacements'] += 1

        # --- Named Entity Recognition ---
        # Stored as a dict of lists, e.g.:
        # { "PERSON": ["John Smith"], "MONEY": ["$5.5M"], "GPE": ["USA"] }
        chunk['metadata']['entities'] = analysis.get('entities', {})
        STATS['entities_extracted'] += sum(
            len(v) for v in analysis.get('entities', {}).values()
        )

        # --- Key Phrases ---
        # Top-5 noun phrases capturing the financial/business signal of the chunk.
        # Useful as a lightweight summary for search indexing or RAG metadata.
        chunk['metadata']['key_phrases'] = analysis.get('key_phrases', [])

    # ------------------------------------------------------------------
    # Stage 2: Local regex extraction (fast, free, deterministic)
    # ------------------------------------------------------------------
    # Runs regardless of API success — these are always reliable and zero-cost.
    # Re-formats raw regex groups back into readable strings e.g. "$5.5M".
    monetary = PATTERNS['monetary_values'].findall(text)
    chunk['metadata']['monetary_values'] = [
        f"${amt}{sfx}" if sfx else f"${amt}"
        for amt, sfx in monetary
    ]

    STATS['chunks_processed'] += 1
    return chunk


# ===========================================================================
# Pipeline Orchestration
# ===========================================================================

def run_pipeline(
    input_file: str,
    api_key: Optional[str],
    output_dir: Optional[str] = None,
    **kwargs,
):
    """
    Orchestrates the full enrichment pipeline end-to-end:
      1. Initialise the OpenAI client
      2. Load chunks from the input JSON file
      3. Enrich each chunk sequentially
      4. Write the enriched output next to the input file (or to --output_dir)
      5. Print final stats to stdout

    Args:
        input_file : path to input JSON — must contain a top-level "chunks" list
        api_key    : optional OpenAI API key (falls back to env var if None)
        output_dir : optional output directory override; defaults to input file's
                     own directory so outputs stay co-located with their source
        **kwargs   : forwarded to enrich_chunk / analyze_chunk (e.g. model=...)
    """
    client = init_openai_client(api_key)
    if not client:
        # Client failed to initialise — error already logged inside init function
        return

    # Resolve to absolute path upfront so that input_path.parent is always
    # the true directory of the file, regardless of how the path was passed
    # (relative, with .., symlink, etc.)
    input_path = Path(input_file).resolve()

    with open(input_path, 'r') as f:
        data = json.load(f)

    chunks = data.get('chunks', [])
    logger.info(f"Processing {len(chunks)} chunks via OpenAI...")

    # Process chunks one at a time (sequential).
    # For large datasets, this can be parallelised with ThreadPoolExecutor —
    # each call is I/O-bound, so threading (not multiprocessing) is appropriate.
    enriched_chunks = [enrich_chunk(c, client, **kwargs) for c in chunks]

    # ------------------------------------------------------------------
    # Output path resolution
    # ------------------------------------------------------------------
    # Priority: explicit --output_dir flag > same directory as input file.
    # Using input_path.parent as the default ensures outputs are always
    # co-located with their source data — no mystery files in the CWD.
    out_dir = Path(output_dir).resolve() if output_dir else input_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)  # create output dir if it doesn't exist

    output_path = out_dir / (input_path.stem + "_enriched_openai.json")
    with open(output_path, 'w') as f:
        # stats embedded directly in the output file for full auditability —
        # no need to cross-reference separate log files to know what ran.
        json.dump({'chunks': enriched_chunks, 'stats': STATS}, f, indent=2)

    logger.info(f"Done. Saved to {output_path}")

    # Print stats to stdout as JSON so the caller can pipe/parse them
    # e.g.:  python enrich_pipeline_openai.py chunks.json | jq '.pii_replacements'
    print(json.dumps(STATS, indent=2))


# ===========================================================================
# CLI Entry Point
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="OpenAI-powered chunk enrichment: PII redaction, NER, key phrases"
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
        '--output_dir',
        default=None,
        help="Directory to write enriched output (default: same directory as input file)",
    )
    args = parser.parse_args()

    run_pipeline(args.input_file, args.api_key, output_dir=args.output_dir, model=args.model)