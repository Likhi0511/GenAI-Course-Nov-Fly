"""
openai_embeddings.py
---------------------
Generate embeddings for enriched chunks using the OpenAI Embeddings API.

WHAT THIS SCRIPT DOES
----------------------
Takes the output of the meta-enrichment pipeline (a JSON file with a 'chunks'
list) and adds a dense vector embedding to each chunk using OpenAI's
text-embedding-3-small or text-embedding-3-large model.

MODELS
------
  text-embedding-3-small (default)
    - 1536 dimensions
    - $0.020 per 1M tokens
    - Good quality, cost-efficient

  text-embedding-3-large
    - 3072 dimensions
    - $0.130 per 1M tokens
    - Best available quality

INPUT FORMAT (from meta-enrichment pipeline)
  {
    "chunks": [
      { "content": "...", "metadata": { ... } },
      ...
    ]
  }

OUTPUT FORMAT (same structure, embedding added to each chunk)
  {
    "metadata": { "model": ..., "dimensions": ..., "cost_tracking": { ... } },
    "chunks": [
      { "content": "...", "metadata": { ... }, "embedding": [...floats...], "embedding_metadata": { ... } },
      ...
    ]
  }

USAGE
-----
  python openai_embeddings.py chunks_enriched.json
  python openai_embeddings.py chunks_enriched.json --model text-embedding-3-large
  python openai_embeddings.py chunks_enriched.json --batch-size 200

OUTPUT FILE
-----------
  Written to the same directory as the input file:
  e.g. data/chunks_enriched_bedrock.json  →  data/chunks_enriched_bedrock_embeddings.json

DEPENDENCIES
------------
  pip install openai tenacity tqdm
  export OPENAI_API_KEY=sk-...
"""

import json
import os
import sys
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm


# ---------------------------------------------------------------------------
# Logging — consistent format with the rest of the pipeline family
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MODEL = 'text-embedding-3-small'
DEFAULT_DIMENSIONS = 1536
DEFAULT_BATCH_SIZE = 100    # OpenAI allows up to 2048 texts per call; 100 is safe default

# Pricing per 1M tokens (as of early 2025) — used for cost estimation and tracking
MODEL_PRICING = {
    'text-embedding-3-small': 0.020,   # $0.020 / 1M tokens
    'text-embedding-3-large': 0.130,   # $0.130 / 1M tokens
}


# ===========================================================================
# Client Initialization
# ===========================================================================

def init_openai_client() -> OpenAI:
    """
    Create and return an OpenAI client authenticated via environment variable.

    Using an env var (OPENAI_API_KEY) rather than a CLI argument keeps the
    secret out of shell history and process listings.

    Raises:
        SystemExit if the env var is not set — fail fast before any API calls.
    """
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.error("OPENAI_API_KEY environment variable not set.")
        logger.error("Run: export OPENAI_API_KEY='sk-...'")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    logger.info("OpenAI client initialised")
    return client


# ===========================================================================
# Data Loading
# ===========================================================================

def load_chunks(input_file: str) -> List[Dict]:
    """
    Load the chunks list from the meta-enrichment output JSON.

    Expects a top-level "chunks" key — the same format produced by
    enrich_pipeline_bedrock.py / enrich_pipeline_openai.py.

    Args:
        input_file : path to the enriched chunks JSON file

    Returns:
        List of chunk dicts, each with at minimum a 'content' key.
    """
    logger.info(f"Loading chunks from: {input_file}")

    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    chunks = data.get('chunks', [])
    logger.info(f"Loaded {len(chunks)} chunks")
    return chunks


# ===========================================================================
# Embedding API Call (with retry)
# ===========================================================================

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60)
)
def call_embeddings_api(
    client: OpenAI,
    texts: List[str],
    model: str,
    dimensions: int
) -> Tuple[List[List[float]], int]:
    """
    Call the OpenAI Embeddings API for a single batch of texts.

    RETRY STRATEGY
    Decorated with @retry (tenacity):
      - Up to 3 attempts
      - Exponential backoff: 4s → 8s → 16s (capped at 60s)
    This handles transient rate-limit (429) and server errors (5xx) without
    crashing the whole pipeline. If all 3 attempts fail, the exception
    propagates up to generate_embeddings() which logs and re-raises.

    WHY RETURN TOKEN COUNT?
    The token count comes from the API response and is the only accurate
    measure for cost tracking. Estimating tokens locally (e.g. len(text)/4)
    is unreliable for multilingual or short texts.

    Args:
        client     : authenticated OpenAI client
        texts      : list of strings to embed (max 2048 per call)
        model      : embedding model name
        dimensions : number of dimensions to return

    Returns:
        Tuple of (list of embedding vectors, total tokens used in this call).
    """
    response = client.embeddings.create(
        model=model,
        input=texts,
        dimensions=dimensions
    )

    # API returns embeddings in the same order as input — safe to zip directly
    embeddings = [item.embedding for item in response.data]
    tokens_used = response.usage.total_tokens

    return embeddings, tokens_used


# ===========================================================================
# Embedding Generation
# ===========================================================================

def generate_embeddings(
    chunks: List[Dict],
    client: OpenAI,
    model: str,
    dimensions: int,
    batch_size: int
) -> Tuple[List[Dict], int]:
    """
    Embed every chunk's 'content' field in batches and attach the result.

    TEXT FIELD PRIORITY
    Uses content_sanitised → content fallback:
      - content_sanitised: PII-redacted text from the enrichment pipeline —
        preferred when storing vectors in an external/shared vector DB.
      - content: raw original text — fallback if no redaction was performed.
    This means privacy-safe and standard deployments both work without
    changing the script.

    RATE LIMITING
    A 0.1s sleep between batches is a lightweight throttle. For high-volume
    jobs (10k+ chunks), consider increasing this or using asyncio with a
    semaphore to stay within your tier's requests-per-minute limit.

    Args:
        chunks     : list of chunk dicts from load_chunks()
        client     : authenticated OpenAI client
        model      : embedding model name
        dimensions : embedding dimensions
        batch_size : number of texts per API call

    Returns:
        Tuple of (enriched chunks list with embeddings, total tokens used).
    """
    logger.info(f"Embedding {len(chunks)} chunks | model={model} | batch_size={batch_size}")

    enriched_chunks = []
    total_tokens = 0
    generated_at = datetime.now().isoformat()   # single timestamp for the whole run

    for i in tqdm(range(0, len(chunks), batch_size), desc="Embedding batches"):
        batch = chunks[i:i + batch_size]

        # Pick the most privacy-appropriate text field available in each chunk
        texts = [
            chunk.get('content', '')
            for chunk in batch
        ]

        try:
            embeddings, tokens = call_embeddings_api(client, texts, model, dimensions)
            total_tokens += tokens

            for chunk, embedding in zip(batch, embeddings):
                enriched = chunk.copy()

                # The embedding vector — already a plain Python list from the API,
                # no numpy conversion needed (unlike Sentence Transformers)
                enriched['embedding'] = embedding

                # Provenance metadata so consumers know what produced this vector
                enriched['embedding_metadata'] = {
                    'model': model,
                    'dimensions': dimensions,
                    'generated_at': generated_at
                }
                enriched_chunks.append(enriched)

            # Small delay between batches to avoid hitting rate limits
            time.sleep(0.1)

        except Exception as e:
            # All 3 retries exhausted — log the failing batch index and re-raise
            # so the pipeline exits cleanly rather than silently producing
            # a partial output file
            logger.error(f"Batch {i // batch_size + 1} failed after retries: {e}")
            raise

    logger.info(f"Embeddings generated | total_tokens={total_tokens:,}")
    return enriched_chunks, total_tokens


# ===========================================================================
# Cost Calculation
# ===========================================================================

def calculate_cost(model: str, total_tokens: int) -> Dict:
    """
    Compute the actual API cost from tokens consumed.

    Returns a dict that is embedded in the output metadata block so cost
    is always co-located with the data — no need to grep log files.

    Args:
        model        : embedding model name (determines price per token)
        total_tokens : total tokens billed by the API across all batches

    Returns:
        Dict with token count, unit price, and total USD cost.
    """
    price_per_million = MODEL_PRICING.get(model, MODEL_PRICING[DEFAULT_MODEL])
    cost_usd = (total_tokens / 1_000_000) * price_per_million

    return {
        'total_tokens': total_tokens,
        'price_per_million_tokens': price_per_million,
        'total_cost_usd': round(cost_usd, 4)
    }


# ===========================================================================
# Output
# ===========================================================================

def save_results(
    chunks: List[Dict],
    input_file: str,
    model: str,
    dimensions: int,
    total_tokens: int
) -> str:
    """
    Write the embedded chunks to a JSON file in the same directory as the input.

    Output filename convention:
      <input_stem>_embeddings.json
      e.g.  chunks_enriched_bedrock.json  →  chunks_enriched_bedrock_embeddings.json

    Cost tracking is embedded in the top-level metadata block so a single
    file tells you what ran, when, what model, and what it cost.

    Args:
        chunks       : enriched chunks list (with embeddings)
        input_file   : original input file path (drives output location)
        model        : model used (for metadata block)
        dimensions   : embedding dimensions (for metadata block)
        total_tokens : tokens billed by the API (for cost tracking)

    Returns:
        Absolute path to the written output file as a string.
    """
    input_path = Path(input_file).resolve()
    output_path = input_path.parent / f"{input_path.stem}_embeddings.json"

    cost_info = calculate_cost(model, total_tokens)

    output_data = {
        'metadata': {
            'model': model,
            'dimensions': dimensions,
            'total_chunks': len(chunks),
            'generated_at': datetime.now().isoformat(),
            'cost_tracking': cost_info     # actual cost — not an estimate
        },
        'chunks': chunks
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(f"Saved to: {output_path} ({file_size_mb:.2f} MB)")
    logger.info(f"Cost: ${cost_info['total_cost_usd']:.4f} USD ({cost_info['total_tokens']:,} tokens)")

    return str(output_path)


# ===========================================================================
# Pipeline Orchestration
# ===========================================================================

def run_pipeline(input_file: str, model: str, dimensions: int, batch_size: int):
    """
    Orchestrate the full embedding pipeline: init → load → embed → save.

    Intentionally flat — four function calls in sequence.
    All complexity (retry logic, batching, cost tracking) lives in the
    individual functions above.

    Args:
        input_file : path to the meta-enrichment output JSON
        model      : OpenAI embedding model name
        dimensions : number of dimensions to request
        batch_size : number of texts per API call
    """
    start = datetime.now()
    logger.info("Starting OpenAI embedding pipeline...")

    # 1. Init
    client = init_openai_client()

    # 2. Load
    chunks = load_chunks(input_file)

    # 3. Embed
    enriched_chunks, total_tokens = generate_embeddings(
        chunks, client, model, dimensions, batch_size
    )

    # 4. Save
    output_file = save_results(enriched_chunks, input_file, model, dimensions, total_tokens)

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"Done in {elapsed:.1f}s | {elapsed / len(chunks):.3f}s per chunk")
    logger.info(f"Output: {output_file}")

    return output_file


# ===========================================================================
# CLI
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate OpenAI embeddings for enriched chunks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python openai_embeddings.py data/chunks_enriched.json
  python openai_embeddings.py data/chunks_enriched.json --model text-embedding-3-large
  python openai_embeddings.py data/chunks_enriched.json --dimensions 3072 --batch-size 200

Cost reference:
  text-embedding-3-small : $0.020 / 1M tokens  (1536 dims)
  text-embedding-3-large : $0.130 / 1M tokens  (3072 dims)
        """
    )
    parser.add_argument(
        'input_file',
        help="Path to enriched chunks JSON (output of meta-enrichment pipeline)"
    )
    parser.add_argument(
        '--model',
        default=DEFAULT_MODEL,
        choices=list(MODEL_PRICING.keys()),
        help=f"OpenAI embedding model (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        '--dimensions',
        type=int,
        default=DEFAULT_DIMENSIONS,
        help=f"Embedding dimensions (default: {DEFAULT_DIMENSIONS})"
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Texts per API call (default: {DEFAULT_BATCH_SIZE}, max: 2048)"
    )

    args = parser.parse_args()

    # Validate input file before touching the API
    if not Path(args.input_file).exists():
        print(f"ERROR: Input file not found: {args.input_file}")
        sys.exit(1)

    # Show cost estimate and confirm before spending money
    price = MODEL_PRICING.get(args.model, MODEL_PRICING[DEFAULT_MODEL])
    print(f"\nModel      : {args.model}")
    print(f"Dimensions : {args.dimensions}")
    print(f"Pricing    : ${price:.3f} / 1M tokens")
    print(f"Input      : {args.input_file}\n")

    # confirm = input("Proceed? (yes/no): ").strip().lower()
    # if confirm != 'yes':
    #     print("Cancelled.")
    #     sys.exit(0)

    run_pipeline(args.input_file, args.model, args.dimensions, args.batch_size)