"""
===============================================================================
openai_embeddings.py  -  OpenAI Embedding Pipeline  v2
===============================================================================

Author  : Prudhvi  |  Thoughtworks
Stage   : 4 of 5  (Extract -> Chunk -> Enrich -> Embed -> Store)

-------------------------------------------------------------------------------
WHAT THIS MODULE DOES
-------------------------------------------------------------------------------

Takes the output of the enrichment pipeline (Stage 3) and adds a dense
vector embedding to each chunk using OpenAI's text-embedding-3-* models.

-------------------------------------------------------------------------------
MODELS
-------------------------------------------------------------------------------

  text-embedding-3-small (default)
    - 1536 dimensions
    - $0.020 per 1M tokens
    - Cost-efficient, good quality

  text-embedding-3-large
    - 3072 dimensions
    - $0.130 per 1M tokens
    - Best available quality

-------------------------------------------------------------------------------
INPUT FORMAT  (Stage 3 output — two accepted shapes)
-------------------------------------------------------------------------------

  Shape A — wrapped dict (ray_tasks.py wraps in top-level key):
  {
    "chunks": [
      { "content": "...", "metadata": { ... } },
      ...
    ]
  }

  Shape B — bare list (save_chunks_to_file writes list directly):
  [
    { "content": "...", "metadata": { ... } },
    ...
  ]

  load_chunks() handles both shapes automatically.

-------------------------------------------------------------------------------
OUTPUT FORMAT
-------------------------------------------------------------------------------

  {
    "metadata": {
      "model": "text-embedding-3-small",
      "dimensions": 1536,
      "total_chunks": 120,
      "embedded_chunks": 118,
      "skipped_chunks": 2,
      "generated_at": "...",
      "cost_tracking": { ... }
    },
    "chunks": [
      {
        "content": "...",
        "metadata": { ... },
        "embedding": [...floats...],        <- None for chunks with empty content
        "embedding_metadata": {
          "model": "...",
          "dimensions": 1536,
          "generated_at": "..."
        }
      },
      ...
    ]
  }

-------------------------------------------------------------------------------
TEXT FIELD PRIORITY
-------------------------------------------------------------------------------

  content_sanitised  ->  content

  content_sanitised: PII-redacted text from Stage 3 (preferred for external VDB).
  content:           raw original text (fallback when no redaction was done).

  For offloaded chunks (type="table_offloaded" / "image_offloaded"):
    content = ai_description written by Stage 1 — embedded as-is.
    No special handling needed; the field name is the same.

-------------------------------------------------------------------------------
EMPTY CONTENT HANDLING  (fix for silent data loss)
-------------------------------------------------------------------------------

  Chunks with empty content are NOT dropped from output.
  They are passed through with embedding=None and a skip reason in
  embedding_metadata. This preserves full chunk count across the pipeline:

    Stage 3 writes N chunks  ->  Stage 4 outputs N chunks  ->  Stage 5 sees N chunks

  Stage 5 (pinecone_upload.py) must check embedding is not None before upsert:
    if chunk.get('embedding') is None:
        logger.warning("Skipping upsert for %s — no embedding", chunk_id)
        continue

-------------------------------------------------------------------------------
SYNC CLIENT  (intentional — not a bug)
-------------------------------------------------------------------------------

  Uses sync OpenAI() not AsyncOpenAI().
  Embeddings are batched synchronously with tqdm progress and tenacity retry.
  AsyncOpenAI is needed only by Stage 3 (enrich_pipeline_openai.py) which
  runs concurrent per-chunk LLM calls inside Ray async workers.
  Batched synchronous embedding does not benefit from async — tenacity's
  exponential backoff would conflict with asyncio's event loop.

-------------------------------------------------------------------------------
DEPENDENCIES
-------------------------------------------------------------------------------

  pip install openai tenacity tqdm
  export OPENAI_API_KEY=sk-...

-------------------------------------------------------------------------------
USAGE
-------------------------------------------------------------------------------

  python openai_embeddings.py chunks_enriched.json
  python openai_embeddings.py chunks_enriched.json --model text-embedding-3-large
  python openai_embeddings.py chunks_enriched.json --batch-size 200

-------------------------------------------------------------------------------
CHANGELOG
-------------------------------------------------------------------------------

v2
  FIX 1 - Empty chunk silent data loss:
    Chunks with empty content are passed through with embedding=None instead
    of being silently dropped. Stage 5 must check embedding is not None.
  FIX 2 - load_chunks handles both dict and bare-list input shapes.
    data.get('chunks', []) returned [] when Stage 3 wrote a bare list.
    Now handles both: dict with 'chunks' key OR raw list.
  FIX 3 - generate_embeddings explicit keyword params with defaults.
    Positional-only params caused ambiguity when called from ray_tasks.py
    with keyword arguments. All params now have explicit types and defaults.

v1
  Original release.
"""

import json
import os
import sys
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

from core.encoding import write_json_utf8

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MODEL      = 'text-embedding-3-small'
DEFAULT_DIMENSIONS = 1536
DEFAULT_BATCH_SIZE = 100    # OpenAI allows up to 2048 texts per call

# Pricing per 1M tokens (as of early 2025)
MODEL_PRICING = {
    'text-embedding-3-small': 0.020,
    'text-embedding-3-large': 0.130,
}


# ===========================================================================
# Client Initialisation
# ===========================================================================

def init_openai_client(api_key: Optional[str] = None) -> OpenAI:
    """
    Create and return a synchronous OpenAI client.

    Sync OpenAI() is correct here — see module docstring for rationale.
    AsyncOpenAI is only required by Stage 3 (enrich_pipeline_openai.py).

    API key resolution order:
      1. Explicit api_key argument — used by ray_tasks.py to pass the
         pre-parsed key from config.OPENAI_API_KEY. config._parse_secret()
         unwraps the ECS Secrets Manager JSON wrapper {"OPENAI_API_KEY": "sk-..."}
         before passing the plain string here, preventing 401 errors.
      2. OPENAI_API_KEY environment variable — fallback for local CLI use.

    Raises:
        SystemExit if no key is found by either method.
    """
    resolved_key = api_key or os.getenv('OPENAI_API_KEY')
    if not resolved_key:
        logger.error("OPENAI_API_KEY not found.")
        logger.error("Pass it explicitly or run: export OPENAI_API_KEY='sk-...'")
        sys.exit(1)

    client = OpenAI(api_key=resolved_key)
    logger.info("OpenAI client initialised (sync)")
    return client


# ===========================================================================
# Data Loading
# ===========================================================================

def load_chunks(input_file: str) -> List[Dict]:
    """
    Load the chunks list from a Stage 3 output JSON file.

    FIX 2: Handles both output shapes from ray_tasks.py / save_chunks_to_file():

      Shape A — wrapped dict (ray_tasks.py wraps output):
        { "chunks": [...], "metadata": {...} }
        -> data['chunks']

      Shape B — bare list (save_chunks_to_file writes list directly):
        [ {...}, {...}, ... ]
        -> data itself

    The old code used data.get('chunks', []) which silently returned an
    empty list when Stage 3 wrote a bare list — embedding nothing.

    Args:
        input_file : path to the enriched chunks JSON file

    Returns:
        List of chunk dicts, each with at minimum a 'content' key.
    """
    logger.info("Loading chunks from: %s", input_file)

    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # FIX 2: handle both wrapped dict and bare list
    if isinstance(data, list):
        chunks = data
        logger.debug("load_chunks: input is bare list (%d chunks)", len(chunks))
    elif isinstance(data, dict):
        chunks = data.get('chunks', [])
        if not chunks:
            logger.warning(
                "load_chunks: dict input has no 'chunks' key or empty list — "
                "check Stage 3 output format."
            )
        logger.debug("load_chunks: input is wrapped dict (%d chunks)", len(chunks))
    else:
        logger.error(
            "load_chunks: unexpected top-level type %s — expected list or dict",
            type(data).__name__,
        )
        chunks = []

    logger.info("Loaded %d chunks", len(chunks))
    return chunks


# ===========================================================================
# Embedding API Call (with retry)
# ===========================================================================

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60),
)
def call_embeddings_api(
    client: OpenAI,
    texts: List[str],
    model: str,
    dimensions: int,
) -> Tuple[List[List[float]], int]:
    """
    Call the OpenAI Embeddings API for a single batch of texts.

    RETRY STRATEGY  (@retry from tenacity):
      - Up to 3 attempts
      - Exponential backoff: 4s -> 8s -> 16s (capped at 60s)
      - Handles transient 429 rate-limit and 5xx server errors
      - If all 3 attempts fail, exception propagates to generate_embeddings()
        which logs and re-raises — pipeline crashes cleanly rather than
        writing a partial output file.

    DIMENSIONS PARAMETER:
      Only supported by text-embedding-3-* models.
      text-embedding-ada-002 (legacy) does NOT support it — passing it causes
      HTTP 400 Bad Request. kwargs built conditionally to handle both.

    WHY RETURN TOKEN COUNT:
      Token count comes from the API response — the only accurate measure
      for cost tracking. Estimating locally (e.g. len(text)/4) is unreliable
      for multilingual or short texts.

    Args:
        client     : authenticated OpenAI client (sync)
        texts      : list of non-empty strings to embed (max 2048 per call)
        model      : embedding model name
        dimensions : number of dimensions to return

    Returns:
        Tuple of (list of embedding vectors, total tokens used in this call).
    """
    kwargs: Dict = {"model": model, "input": texts}
    if "text-embedding-3" in model:
        kwargs["dimensions"] = dimensions
    # ada-002: fixed 1536 dims, dimensions param not accepted

    response = client.embeddings.create(**kwargs)

    # API returns embeddings in input order — safe to zip directly
    embeddings  = [item.embedding for item in response.data]
    tokens_used = response.usage.total_tokens

    return embeddings, tokens_used


# ===========================================================================
# Embedding Generation
# ===========================================================================

def generate_embeddings(
    chunks: List[Dict],
    client: OpenAI,
    model: str = DEFAULT_MODEL,
    dimensions: int = DEFAULT_DIMENSIONS,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Tuple[List[Dict], int]:
    """
    Embed every chunk's text field in batches and attach the result.

    FIX 1 — NO SILENT DATA LOSS:
      Chunks with empty content are NOT dropped from the output list.
      They are passed through with embedding=None so Stage 5 sees the same
      total chunk count as Stage 3 produced. An explicit skip reason is
      written to embedding_metadata for audit/debugging.

      Stage 5 contract:
        if chunk.get('embedding') is None:
            logger.warning("Skipping upsert for %s — no embedding", chunk_id)
            continue

      When does this happen?
        - Large table / image chunks where Stage 1's AI description call failed.
          content = "AI description unavailable: ..." — treated as empty after strip.
        - Rarely: genuinely empty boundary markers that slipped through Stage 2.

    FIX 3 — EXPLICIT KEYWORD PARAMS:
      All parameters have explicit types and defaults so ray_tasks.py can
      call this with keyword args without ambiguity.

    TEXT FIELD PRIORITY:
      content_sanitised (PII-redacted, from Stage 3) > content (raw original).
      For offloaded chunks (table_offloaded / image_offloaded):
        content = ai_description — embedded as-is, no special handling needed.

    Args:
        chunks     : list of chunk dicts from load_chunks()
        client     : authenticated sync OpenAI client
        model      : embedding model name
        dimensions : embedding vector dimensions
        batch_size : number of texts per API call

    Returns:
        Tuple of (all chunks with embedding or None, total tokens used).
    """
    logger.info(
        "Embedding %d chunks | model=%s | dimensions=%d | batch_size=%d",
        len(chunks), model, dimensions, batch_size,
    )

    enriched_chunks: List[Dict] = []
    total_tokens                = 0
    total_skipped               = 0
    generated_at                = datetime.now().isoformat()

    for i in tqdm(range(0, len(chunks), batch_size), desc="Embedding batches"):
        batch       = chunks[i:i + batch_size]
        batch_index = i // batch_size + 1

        # ── Split batch into valid (non-empty) and skipped (empty) ────────
        # content_sanitised preferred — contains PII-redacted text from Stage 3.
        # content is fallback — raw text, or ai_description for offloaded chunks.
        texts_and_chunks = [
            (chunk.get('content_sanitised') or chunk.get('content', ''), chunk)
            for chunk in batch
        ]

        valid:   List[Tuple[str, Dict]] = []
        skipped: List[Dict]             = []

        for text, chunk in texts_and_chunks:
            # Treat "AI description unavailable: ..." as empty —
            # Stage 1 writes this placeholder when the OpenAI vision call fails.
            # Embedding a failure message produces a misleading vector.
            is_empty = (
                not text
                or not text.strip()
                or text.strip().startswith("AI description unavailable")
            )
            if is_empty:
                skipped.append(chunk)
            else:
                valid.append((text, chunk))

        # FIX 1: pass skipped chunks through with embedding=None
        # Do NOT drop them — Stage 5 must see the same total count as Stage 3.
        if skipped:
            logger.warning(
                "Batch %d: %d chunk(s) have empty/unavailable content — "
                "passing through with embedding=None",
                batch_index, len(skipped),
            )
            for chunk in skipped:
                skipped_chunk = chunk.copy()
                skipped_chunk['embedding'] = None
                skipped_chunk['embedding_metadata'] = {
                    'model':         model,
                    'dimensions':    dimensions,
                    'generated_at':  generated_at,
                    'skipped':       True,
                    'skipped_reason': 'empty_or_unavailable_content',
                }
                enriched_chunks.append(skipped_chunk)
                total_skipped += 1

        if not valid:
            logger.warning(
                "Batch %d: no valid chunks to embed — skipping API call.",
                batch_index,
            )
            continue

        texts        = [t for t, _ in valid]
        valid_chunks = [c for _, c in valid]

        try:
            embeddings, tokens = call_embeddings_api(client, texts, model, dimensions)
            total_tokens += tokens

            for chunk, embedding in zip(valid_chunks, embeddings):
                enriched = chunk.copy()
                enriched['embedding'] = embedding
                enriched['embedding_metadata'] = {
                    'model':        model,
                    'dimensions':   dimensions,
                    'generated_at': generated_at,
                    'skipped':      False,
                }
                enriched_chunks.append(enriched)

            # Small throttle between batches — lightweight rate-limit guard.
            # Increase for high-volume jobs (10k+ chunks) or lower-tier API keys.
            time.sleep(0.1)

        except Exception as exc:
            # All 3 tenacity retries exhausted — log batch index and re-raise.
            # Pipeline crashes cleanly rather than writing a partial output file.
            logger.error("Batch %d failed after all retries: %s", batch_index, exc)
            raise

    embedded_count = len(enriched_chunks) - total_skipped
    logger.info(
        "Embeddings complete | total=%d | embedded=%d | skipped=%d | tokens=%s",
        len(enriched_chunks), embedded_count, total_skipped, f"{total_tokens:,}",
    )
    return enriched_chunks, total_tokens


# ===========================================================================
# Cost Calculation
# ===========================================================================

def calculate_cost(model: str, total_tokens: int) -> Dict:
    """
    Compute the actual API cost from tokens consumed.

    Returns a dict embedded in the output metadata so cost is always
    co-located with the data — no need to grep log files.

    Args:
        model        : embedding model name (determines price per token)
        total_tokens : total tokens billed by the API across all batches

    Returns:
        Dict with token count, unit price, and total USD cost.
    """
    price_per_million = MODEL_PRICING.get(model, MODEL_PRICING[DEFAULT_MODEL])
    cost_usd          = (total_tokens / 1_000_000) * price_per_million

    return {
        'total_tokens':               total_tokens,
        'price_per_million_tokens':   price_per_million,
        'total_cost_usd':             round(cost_usd, 4),
    }


# ===========================================================================
# Output
# ===========================================================================

def save_results(
    chunks: List[Dict],
    input_file: str,
    model: str,
    dimensions: int,
    total_tokens: int,
) -> str:
    """
    Write embedded chunks to a JSON file in the same directory as the input.

    Output filename convention:
      <input_stem>_embeddings.json
      e.g. chunks_enriched.json -> chunks_enriched_embeddings.json

    Metadata block includes:
      - total_chunks:    all chunks (including skipped)
      - embedded_chunks: chunks with real embedding vectors
      - skipped_chunks:  chunks with embedding=None
    This makes it easy to audit chunk loss across stages.

    Args:
        chunks       : all chunks from generate_embeddings() (embedded + skipped)
        input_file   : original input file path (drives output directory)
        model        : model used (for metadata block)
        dimensions   : embedding dimensions (for metadata block)
        total_tokens : tokens billed by the API (for cost tracking)

    Returns:
        Absolute path to the written output file.
    """
    input_path  = Path(input_file).resolve()
    output_path = input_path.parent / f"{input_path.stem}_embeddings.json"

    cost_info      = calculate_cost(model, total_tokens)
    embedded_count = sum(1 for c in chunks if c.get('embedding') is not None)
    skipped_count  = len(chunks) - embedded_count

    output_data = {
        'metadata': {
            'model':           model,
            'dimensions':      dimensions,
            'total_chunks':    len(chunks),
            'embedded_chunks': embedded_count,
            'skipped_chunks':  skipped_count,
            'generated_at':    datetime.now().isoformat(),
            'cost_tracking':   cost_info,
        },
        'chunks': chunks,
    }

    # with open(output_path, 'w', encoding='utf-8') as f:
    #     json.dump(output_data, f, indent=2, ensure_ascii=False)
    logger.info("Fix applied")
    write_json_utf8(output_path, output_data)

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("Saved to: %s (%.2f MB)", output_path, file_size_mb)
    logger.info(
        "Cost: $%.4f USD (%s tokens) | embedded=%d skipped=%d",
        cost_info['total_cost_usd'], f"{cost_info['total_tokens']:,}",
        embedded_count, skipped_count,
    )

    return str(output_path)


# ===========================================================================
# Pipeline Orchestration
# ===========================================================================

def run_pipeline(
    input_file: str,
    model: str = DEFAULT_MODEL,
    dimensions: int = DEFAULT_DIMENSIONS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    api_key: Optional[str] = None,
) -> str:
    """
    Orchestrate the full embedding pipeline: init -> load -> embed -> save.

    Called by ray_tasks.py Stage 4:
      output_file = run_pipeline(
          input_file=enriched_chunks_path,
          model=config.EMBEDDING_MODEL,
          dimensions=config.EMBEDDING_DIMENSIONS,
          batch_size=config.EMBEDDING_BATCH_SIZE,
          api_key=config.OPENAI_API_KEY,
      )

    Args:
        input_file : path to the Stage 3 enriched chunks JSON file
        model      : OpenAI embedding model name
        dimensions : embedding vector dimensions
        batch_size : number of texts per API call
        api_key    : OpenAI API key (pre-parsed by config._parse_secret())

    Returns:
        Absolute path to the written embeddings output file.
    """
    start = datetime.now()
    logger.info("Starting OpenAI embedding pipeline...")

    # 1. Init
    client = init_openai_client(api_key=api_key)

    # 2. Load — handles both wrapped dict and bare list from Stage 3
    chunks = load_chunks(input_file)
    if not chunks:
        logger.error("No chunks loaded from %s — aborting.", input_file)
        sys.exit(1)

    # 3. Embed — skipped chunks passed through with embedding=None
    enriched_chunks, total_tokens = generate_embeddings(
        chunks=chunks,
        client=client,
        model=model,
        dimensions=dimensions,
        batch_size=batch_size,
    )

    # 4. Save
    output_file = save_results(
        chunks=enriched_chunks,
        input_file=input_file,
        model=model,
        dimensions=dimensions,
        total_tokens=total_tokens,
    )

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(
        "Done in %.1fs | %.3fs per chunk | output: %s",
        elapsed, elapsed / max(len(chunks), 1), output_file,
    )

    return output_file


# ===========================================================================
# CLI
# ===========================================================================

# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(
#         description="Generate OpenAI embeddings for enriched chunks  (Stage 4)",
#         formatter_class=argparse.RawDescriptionHelpFormatter,
#         epilog="""
# Examples:
#   python openai_embeddings.py data/chunks_enriched.json
#   python openai_embeddings.py data/chunks_enriched.json --model text-embedding-3-large
#   python openai_embeddings.py data/chunks_enriched.json --dimensions 3072 --batch-size 200
#
# Cost reference:
#   text-embedding-3-small : $0.020 / 1M tokens  (1536 dims default)
#   text-embedding-3-large : $0.130 / 1M tokens  (3072 dims default)
#
# Stage 5 contract for embedding=None chunks:
#   if chunk.get('embedding') is None:
#       logger.warning("Skipping upsert — no embedding")
#       continue
#         """,
#     )
#     parser.add_argument(
#         'input_file',
#         help="Path to enriched chunks JSON (Stage 3 output)",
#     )
#     parser.add_argument(
#         '--model',
#         default=DEFAULT_MODEL,
#         choices=list(MODEL_PRICING.keys()),
#         help=f"Embedding model (default: {DEFAULT_MODEL})",
#     )
#     parser.add_argument(
#         '--dimensions',
#         type=int,
#         default=DEFAULT_DIMENSIONS,
#         help=f"Embedding dimensions (default: {DEFAULT_DIMENSIONS})",
#     )
#     parser.add_argument(
#         '--batch-size',
#         type=int,
#         default=DEFAULT_BATCH_SIZE,
#         help=f"Texts per API call (default: {DEFAULT_BATCH_SIZE}, max: 2048)",
#     )
#
#     args = parser.parse_args()
#
#     if not Path(args.input_file).exists():
#         print(f"ERROR: Input file not found: {args.input_file}")
#         sys.exit(1)
#
#     price = MODEL_PRICING.get(args.model, MODEL_PRICING[DEFAULT_MODEL])
#     print(f"\nModel      : {args.model}")
#     print(f"Dimensions : {args.dimensions}")
#     print(f"Pricing    : ${price:.3f} / 1M tokens")
#     print(f"Input      : {args.input_file}\n")
#
#     # Uncomment to add cost confirmation for interactive use:
#     # confirm = input("Proceed? (yes/no): ").strip().lower()
#     # if confirm != 'yes':
#     #     print("Cancelled.")
#     #     sys.exit(0)
#
#     run_pipeline(
#         input_file=args.input_file,
#         model=args.model,
#         dimensions=args.dimensions,
#         batch_size=args.batch_size,
#     )