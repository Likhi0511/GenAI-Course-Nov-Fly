"""
bedrock_titan_embeddings.py
-----------------------------
Generate embeddings for enriched chunks using AWS Bedrock Titan Embeddings.

WHAT THIS SCRIPT DOES
----------------------
Takes the output of the meta-enrichment pipeline (a JSON file with a 'chunks'
list) and adds a dense vector embedding to each chunk using Amazon Titan
Embeddings V2 via the AWS Bedrock Runtime API.

WHY TITAN?
  - No model download — fully managed AWS service
  - 100+ language support out of the box
  - Very low cost: $0.0001 per 1K tokens
  - Fits naturally in AWS-native stacks (same IAM, same VPC)
  - Flexible dimensions: 256 / 512 / 1024

TITAN VS OPENAI EMBEDDINGS
  - Titan: one call per chunk (no batching in the API)
  - OpenAI: up to 2048 texts per call
  - Titan is slower at scale but cheaper and fully in-AWS

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
  python bedrock_titan_embeddings.py chunks_enriched.json
  python bedrock_titan_embeddings.py chunks_enriched.json --region us-west-2
  python bedrock_titan_embeddings.py chunks_enriched.json --dimensions 512

OUTPUT FILE
-----------
  Written to the same directory as the input file:
  e.g. data/chunks_enriched_bedrock.json  →  data/chunks_enriched_bedrock_embeddings_titan.json

AWS CREDENTIALS (resolved in this order)
  1. AWS CLI profile  (aws configure)
  2. Environment variables  (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
  3. IAM Instance Role / ECS Task Role

DEPENDENCIES
------------
  pip install boto3 tenacity tqdm
"""

import json
import sys
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple

import boto3
from botocore.exceptions import ClientError
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
DEFAULT_MODEL = 'amazon.titan-embed-text-v2:0'
DEFAULT_REGION = 'us-east-1'
DEFAULT_DIMENSIONS = 1024
VALID_DIMENSIONS = [256, 512, 1024]   # only values Titan V2 supports

# Titan pricing: $0.0001 per 1K tokens (as of early 2025)
# Bedrock doesn't return token counts, so we estimate from word count
PRICE_PER_1K_TOKENS = 0.0001


# ===========================================================================
# Client Initialization
# ===========================================================================

def init_bedrock_client(region: str = DEFAULT_REGION):
    """
    Create and return a Bedrock Runtime boto3 client.

    Authentication is resolved via the standard AWS credential chain:
      1. AWS CLI profile  (aws configure)
      2. Env vars         (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
      3. IAM Instance / ECS Task Role

    A quick credential check is run upfront so the script fails fast
    with a clear message rather than on the first API call mid-pipeline.

    Args:
        region : AWS region where Bedrock is available (default: us-east-1)

    Returns:
        boto3 bedrock-runtime client

    Raises:
        SystemExit if no credentials are found.
    """
    # Validate credentials exist before creating the client
    try:
        session = boto3.Session()
        creds = session.get_credentials()
        if not creds:
            raise ValueError("No credentials found")
    except Exception:
        logger.error("AWS credentials not found.")
        logger.error("Run 'aws configure', or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.")
        sys.exit(1)

    client = session.client('bedrock-runtime', region_name=region)
    logger.info(f"Bedrock client initialised | region={region}")
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
# Single-Chunk API Call (with retry)
# ===========================================================================

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60)
)
def call_titan_api(
    client,
    text: str,
    model_id: str,
    dimensions: int
) -> List[float]:
    """
    Call the Bedrock Titan Embeddings API for a single text string.

    WHY ONE TEXT AT A TIME?
    Unlike OpenAI which accepts up to 2048 texts per call, the Titan
    Embeddings API accepts exactly one inputText per request. Batching
    must be done at the loop level (see generate_embeddings).

    RETRY STRATEGY
    Decorated with @retry (tenacity):
      - Up to 3 attempts
      - Exponential backoff: 4s → 8s → 16s (capped at 60s)
    Handles transient throttling (ThrottlingException) and service errors
    without crashing the pipeline mid-run.

    NORMALISATION
    "normalize": True applies L2 normalisation inside the Titan model so
    cosine similarity equals dot product at query time — cheaper for ANN
    indexes like pgvector or FAISS.

    Args:
        client     : initialised bedrock-runtime boto3 client
        text       : single text string to embed
        model_id   : Bedrock model ID for Titan
        dimensions : 256, 512, or 1024

    Returns:
        Embedding vector as a list of floats.

    Raises:
        ClientError after all retries are exhausted — propagates to caller.
    """
    request_body = {
        "inputText": text,
        "dimensions": dimensions,
        "normalize": True      # L2 norm → cosine sim == dot product at query time
    }

    try:
        response = client.invoke_model(
            modelId=model_id,
            contentType='application/json',
            accept='application/json',
            body=json.dumps(request_body)
        )
        response_body = json.loads(response['body'].read())
        return response_body['embedding']

    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"Bedrock ClientError [{error_code}]: {e}")
        raise   # re-raise so tenacity can retry


# ===========================================================================
# Embedding Generation
# ===========================================================================

def generate_embeddings(
    chunks: List[Dict],
    client,
    model_id: str,
    dimensions: int
) -> Tuple[List[Dict], int]:
    """
    Embed every chunk's 'content' field one at a time (Titan API constraint).

    TEXT FIELD PRIORITY
    Uses content_sanitised → content fallback:
      - content_sanitised: PII-redacted text from the enrichment pipeline —
        preferred when storing vectors in an external vector DB.
      - content: raw original text — fallback if no redaction was applied.

    TOKEN ESTIMATION
    Bedrock Titan does not return a token count in its response. We estimate
    using word count (word_count ≈ token_count for English; slightly under for
    multilingual text). This gives a reasonable cost approximation.

    RATE LIMITING
    A 0.05s sleep between calls is a lightweight throttle suitable for the
    default Bedrock service quota. Increase to 0.1–0.5s if you hit
    ThrottlingException errors on large datasets.

    Args:
        chunks     : list of chunk dicts from load_chunks()
        client     : initialised bedrock-runtime client
        model_id   : Titan model ID
        dimensions : embedding dimensions (256, 512, or 1024)

    Returns:
        Tuple of (enriched chunks list with embeddings, estimated total tokens).
    """
    logger.info(f"Embedding {len(chunks)} chunks | model={model_id} | dims={dimensions}")
    logger.info("Note: Titan processes one text per call — no batching")

    enriched_chunks = []
    estimated_tokens = 0
    generated_at = datetime.now().isoformat()   # single timestamp for the whole run

    for chunk in tqdm(chunks, desc="Embedding chunks"):
        # Use redacted text when available for privacy-safe vector stores
        text = chunk.get('content_sanitised') or chunk.get('content', '')

        try:
            embedding = call_titan_api(client, text, model_id, dimensions)

            enriched = chunk.copy()

            # Embedding vector — plain Python list from the JSON response,
            # no numpy conversion needed
            enriched['embedding'] = embedding

            # Provenance metadata for consumers of the vector store
            enriched['embedding_metadata'] = {
                'model': model_id,
                'dimensions': dimensions,
                'normalized': True,
                'generated_at': generated_at
            }
            enriched_chunks.append(enriched)

            # Estimate tokens from word count (Bedrock doesn't return exact counts)
            estimated_tokens += len(text.split())

            # Small delay to stay within default Bedrock service quota
            time.sleep(0.05)

        except Exception as e:
            # All 3 retries exhausted — log the chunk ID and re-raise
            # so the pipeline exits cleanly rather than silently producing
            # a partial output file
            logger.error(f"Chunk '{chunk.get('id', 'unknown')}' failed after retries: {e}")
            raise

    logger.info(f"Embeddings generated | estimated_tokens={estimated_tokens:,}")
    return enriched_chunks, estimated_tokens


# ===========================================================================
# Cost Calculation
# ===========================================================================

def calculate_cost(estimated_tokens: int) -> Dict:
    """
    Estimate the Bedrock Titan API cost from the word-count token approximation.

    Because Bedrock doesn't return exact token counts, this is an estimate.
    It will be slightly low for multilingual or code-heavy text (tokenisers
    produce more tokens per word in those cases).

    Args:
        estimated_tokens : total word-count approximation across all chunks

    Returns:
        Dict with token estimate, unit price, and estimated USD cost.
    """
    cost_usd = (estimated_tokens / 1000) * PRICE_PER_1K_TOKENS

    return {
        'estimated_tokens': estimated_tokens,   # word-count approximation
        'price_per_1k_tokens': PRICE_PER_1K_TOKENS,
        'estimated_cost_usd': round(cost_usd, 6)
    }


# ===========================================================================
# Output
# ===========================================================================

def save_results(
    chunks: List[Dict],
    input_file: str,
    model_id: str,
    region: str,
    dimensions: int,
    estimated_tokens: int
) -> str:
    """
    Write the embedded chunks to a JSON file in the same directory as the input.

    Output filename convention:
      <input_stem>_embeddings_titan.json
      (suffix _titan distinguishes from OpenAI embeddings output)
      e.g.  chunks_enriched_bedrock.json  →  chunks_enriched_bedrock_embeddings_titan.json

    Args:
        chunks           : enriched chunks list (with embeddings)
        input_file       : original input file path (drives output location)
        model_id         : Titan model ID (for metadata block)
        region           : AWS region used (for metadata block)
        dimensions       : embedding dimensions (for metadata block)
        estimated_tokens : word-count token approximation (for cost tracking)

    Returns:
        Absolute path to the written output file as a string.
    """
    input_path = Path(input_file).resolve()
    output_path = input_path.parent / f"{input_path.stem}_embeddings_titan.json"

    cost_info = calculate_cost(estimated_tokens)

    output_data = {
        'metadata': {
            'model': model_id,
            'region': region,
            'dimensions': dimensions,
            'normalized': True,
            'total_chunks': len(chunks),
            'generated_at': datetime.now().isoformat(),
            'cost_tracking': cost_info    # estimated — Bedrock omits exact token counts
        },
        'chunks': chunks
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(f"Saved to: {output_path} ({file_size_mb:.2f} MB)")
    logger.info(f"Est. cost: ${cost_info['estimated_cost_usd']:.6f} USD "
                f"(~{cost_info['estimated_tokens']:,} tokens)")

    return str(output_path)


# ===========================================================================
# Pipeline Orchestration
# ===========================================================================

def run_pipeline(input_file: str, model_id: str, region: str, dimensions: int):
    """
    Orchestrate the full embedding pipeline: init → load → embed → save.

    Intentionally flat — four function calls in sequence.
    All complexity (retry logic, rate limiting, cost estimation) lives in
    the individual functions above.

    Args:
        input_file : path to the meta-enrichment output JSON
        model_id   : Titan model ID
        region     : AWS region for the Bedrock client
        dimensions : embedding dimensions (256, 512, or 1024)
    """
    start = datetime.now()
    logger.info("Starting Bedrock Titan embedding pipeline...")

    # 1. Init
    client = init_bedrock_client(region)

    # 2. Load
    chunks = load_chunks(input_file)

    # 3. Embed
    enriched_chunks, estimated_tokens = generate_embeddings(
        chunks, client, model_id, dimensions
    )

    # 4. Save
    output_file = save_results(
        enriched_chunks, input_file, model_id, region, dimensions, estimated_tokens
    )

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"Done in {elapsed:.1f}s | {elapsed / len(chunks):.3f}s per chunk")
    logger.info(f"Output: {output_file}")

    return output_file


# ===========================================================================
# CLI
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate AWS Bedrock Titan embeddings for enriched chunks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bedrock_titan_embeddings.py data/chunks_enriched.json
  python bedrock_titan_embeddings.py data/chunks_enriched.json --region us-west-2
  python bedrock_titan_embeddings.py data/chunks_enriched.json --dimensions 512

Cost reference:
  $0.0001 per 1K tokens — very low cost compared to OpenAI
  Typical 50-chunk document: ~$0.001-0.005
        """
    )
    parser.add_argument(
        'input_file',
        help="Path to enriched chunks JSON (output of meta-enrichment pipeline)"
    )
    parser.add_argument(
        '--model',
        default=DEFAULT_MODEL,
        help=f"Bedrock Titan model ID (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        '--region',
        default=DEFAULT_REGION,
        help=f"AWS region (default: {DEFAULT_REGION})"
    )
    parser.add_argument(
        '--dimensions',
        type=int,
        default=DEFAULT_DIMENSIONS,
        choices=VALID_DIMENSIONS,
        help=f"Embedding dimensions — {VALID_DIMENSIONS} (default: {DEFAULT_DIMENSIONS})"
    )

    args = parser.parse_args()

    # Validate input file before touching AWS
    if not Path(args.input_file).exists():
        print(f"ERROR: Input file not found: {args.input_file}")
        sys.exit(1)

    print(f"\nModel      : {args.model}")
    print(f"Region     : {args.region}")
    print(f"Dimensions : {args.dimensions}")
    print(f"Pricing    : ${PRICE_PER_1K_TOKENS} / 1K tokens")
    print(f"Input      : {args.input_file}\n")

    run_pipeline(args.input_file, args.model, args.region, args.dimensions)