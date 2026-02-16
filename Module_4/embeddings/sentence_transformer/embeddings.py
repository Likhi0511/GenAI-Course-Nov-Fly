"""
sentence_transformers_embeddings.py
-------------------------------------
Generate local embeddings for enriched chunks using Sentence Transformers.

WHAT THIS SCRIPT DOES
----------------------
Takes the output of the meta-enrichment pipeline (a JSON file with a 'chunks'
list) and adds a dense vector embedding to each chunk's 'content' field.

Embeddings are generated locally — no API key, no cost, no network calls
after the one-time model download (~80MB).

MODEL: all-MiniLM-L6-v2
  - 384 dimensions
  - Fast inference, good quality for semantic search and RAG
  - L2-normalised → cosine similarity = dot product (cheaper at query time)

INPUT FORMAT (from meta-enrichment pipeline)
  {
    "chunks": [
      { "content": "...", "metadata": { ... } },
      ...
    ]
  }

OUTPUT FORMAT (same structure, embedding added to each chunk)
  {
    "metadata": { "model": ..., "dimensions": 384, ... },
    "chunks": [
      { "content": "...", "metadata": { ... }, "embedding": [...384 floats...], "embedding_metadata": { ... } },
      ...
    ]
  }

USAGE
-----
  python sentence_transformers_embeddings.py chunks_enriched.json
  python sentence_transformers_embeddings.py chunks_enriched.json --batch-size 64
  python sentence_transformers_embeddings.py chunks_enriched.json --model all-mpnet-base-v2

OUTPUT FILE
-----------
  Written to the same directory as the input file:
  e.g. data/chunks_enriched.json  →  data/chunks_enriched_embeddings.json

DEPENDENCIES
------------
  pip install sentence-transformers tqdm
"""

import json
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict

from sentence_transformers import SentenceTransformer
from tqdm import tqdm


# ---------------------------------------------------------------------------
# Logging — simple timestamp + level format, consistent with the rest of
# the pipeline family (enrich_pipeline_*.py)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MODEL = 'all-MiniLM-L6-v2'   # 384-dim, fast, 80MB — good default for RAG
DEFAULT_BATCH_SIZE = 32               # safe default; increase to 64-128 on GPU


# ===========================================================================
# Data Loading
# ===========================================================================

def load_chunks(input_file: str) -> List[Dict]:
    """
    Load the chunks list from the meta-enrichment output JSON.

    Expects the file to have a top-level "chunks" key — the same format
    produced by enrich_pipeline_bedrock.py / enrich_pipeline_openai.py.

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
# Embedding Generation
# ===========================================================================

def generate_embeddings(chunks: List[Dict], model_name: str, batch_size: int) -> List[Dict]:
    """
    Load the Sentence Transformers model and embed every chunk's 'content' field.

    WHY 'content' (not 'content_sanitised')?
    The raw 'content' field is used by default because embeddings should
    capture the full semantic signal of the text. If your downstream use case
    requires privacy-safe embeddings (e.g. storing in an external vector DB),
    swap to 'content_sanitised' — it falls back to 'content' if not present.

    NORMALISATION
    normalize_embeddings=True applies L2 normalisation so cosine similarity
    between two vectors equals their dot product. This makes ANN index queries
    (pgvector, FAISS, Pinecone) faster and the scores directly comparable.

    Args:
        chunks     : list of chunk dicts from load_chunks()
        model_name : Sentence Transformers model name/path
        batch_size : number of texts encoded per forward pass

    Returns:
        Same list with 'embedding' and 'embedding_metadata' added to each chunk.
    """
    logger.info(f"Loading model: {model_name} (first run downloads ~80MB)...")
    model = SentenceTransformer(model_name)
    dimensions = model.get_sentence_embedding_dimension()
    logger.info(f"Model ready | dimensions={dimensions}")

    # Extract the text to embed from each chunk.
    # Falls back to 'content_sanitised' → 'content' → empty string in priority order.
    # Using content_sanitised when available is safer for privacy-sensitive pipelines;
    # falling back to content ensures no chunk is silently skipped if not redacted.
    texts = [
        chunk.get('content_sanitised') or chunk.get('content', '')
        for chunk in chunks
    ]

    logger.info(f"Embedding {len(texts)} chunks in batches of {batch_size}...")

    # encode() handles batching internally; show_progress_bar gives a tqdm bar
    # normalize_embeddings=True → L2 norm → cosine sim == dot product at query time
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True
    )

    # Attach embedding + lightweight metadata to each chunk (in-place copy)
    enriched_chunks = []
    generated_at = datetime.now().isoformat()   # single timestamp for the whole batch

    for chunk, embedding in zip(chunks, embeddings):
        enriched = chunk.copy()

        # The embedding itself — converted from numpy float32 to plain Python list
        # so json.dump() can serialise it without a custom encoder
        enriched['embedding'] = embedding.tolist()

        # Provenance metadata so consumers know which model/config produced this vector.
        # Useful when mixing embeddings from different models in the same vector store.
        enriched['embedding_metadata'] = {
            'model': model_name,
            'dimensions': dimensions,
            'normalized': True,
            'generated_at': generated_at
        }
        enriched_chunks.append(enriched)

    logger.info(f"Embeddings generated for {len(enriched_chunks)} chunks")
    return enriched_chunks, dimensions


# ===========================================================================
# Output
# ===========================================================================

def save_results(chunks: List[Dict], input_file: str, model_name: str, dimensions: int) -> str:
    """
    Write the embedded chunks to a JSON file in the same directory as the input.

    Output filename convention:
      <input_stem>_embeddings.json
      e.g.  chunks_enriched_bedrock.json  →  chunks_enriched_bedrock_embeddings.json

    The top-level 'metadata' block records the run configuration for
    auditability — what model, when it ran, how many chunks — without
    needing to grep log files.

    Args:
        chunks     : enriched chunks list (with embeddings)
        input_file : original input file path (drives output location)
        model_name : model used (for metadata block)
        dimensions : embedding dimensions (for metadata block)

    Returns:
        Absolute path to the written output file as a string.
    """
    input_path = Path(input_file).resolve()

    # Output sits next to the input file — consistent with the rest of the pipeline
    output_path = input_path.parent / f"{input_path.stem}_embeddings.json"

    output_data = {
        'metadata': {
            'model': model_name,
            'dimensions': dimensions,
            'total_chunks': len(chunks),
            'normalized': True,
            'generated_at': datetime.now().isoformat()
        },
        'chunks': chunks
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(f"Saved to: {output_path} ({file_size_mb:.2f} MB)")

    return str(output_path)


# ===========================================================================
# Pipeline Orchestration
# ===========================================================================

def run_pipeline(input_file: str, model_name: str, batch_size: int):
    """
    Orchestrate the full embedding pipeline: load → embed → save.

    Kept deliberately simple — three function calls in sequence.
    All complexity lives in the individual functions above.

    Args:
        input_file : path to the meta-enrichment output JSON
        model_name : Sentence Transformers model to use
        batch_size : batch size for encoding
    """
    start = datetime.now()
    logger.info("Starting embedding pipeline...")

    # 1. Load
    chunks = load_chunks(input_file)

    # 2. Embed
    enriched_chunks, dimensions = generate_embeddings(chunks, model_name, batch_size)

    # 3. Save
    output_file = save_results(enriched_chunks, input_file, model_name, dimensions)

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"Done in {elapsed:.1f}s | {elapsed/len(chunks):.3f}s per chunk")
    logger.info(f"Output: {output_file}")

    return output_file


# ===========================================================================
# CLI
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate local Sentence Transformer embeddings for enriched chunks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sentence_transformers_embeddings.py data/chunks_enriched.json
  python sentence_transformers_embeddings.py data/chunks_enriched.json --batch-size 64
  python sentence_transformers_embeddings.py data/chunks_enriched.json --model all-mpnet-base-v2
        """
    )
    parser.add_argument(
        'input_file',
        help="Path to enriched chunks JSON (output of meta-enrichment pipeline)"
    )
    parser.add_argument(
        '--model',
        default=DEFAULT_MODEL,
        help=f"Sentence Transformers model name (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Encoding batch size (default: {DEFAULT_BATCH_SIZE}, increase on GPU)"
    )

    args = parser.parse_args()

    # Validate input file exists before doing anything
    if not Path(args.input_file).exists():
        print(f"ERROR: Input file not found: {args.input_file}")
        sys.exit(1)

    run_pipeline(args.input_file, args.model, args.batch_size)