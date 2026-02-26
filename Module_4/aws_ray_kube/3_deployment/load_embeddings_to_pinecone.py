"""
load_embeddings_to_pinecone.py
---------------------------------
Loads a JSON file of embeddings (produced by openai_embeddings.py or
sentence_transformers_embeddings.py) into a Pinecone serverless index.

WHAT THIS SCRIPT DOES
----------------------
1. Reads the JSON embedding file produced by the embedding pipeline
2. Initialises a Pinecone client with your API key
3. Creates a serverless index if it doesn't exist (or reuses an existing one)
4. Converts chunks into Pinecone's {id, values, metadata} vector format
5. Upserts vectors in batches, then verifies the count

PIPELINE POSITION
-----------------
  [1] Docling extraction
  [2] Meta-enrichment (enrich_pipeline_openai.py)
  [3] Embedding generation (openai_embeddings.py → text-embedding-3-small, 1536 dims)
  [4] Pinecone ingestion  ← you are here
  [5] Semantic search (search_pinecone.py)

PINECONE vs PGVECTOR
---------------------
  pgvector  — runs inside your own PostgreSQL; free, self-hosted, no size limit
  Pinecone  — managed cloud service; free tier (2GB / 1 index), no infra to manage

  Both store vectors and search by cosine distance.
  The main difference is operational: Pinecone has no server to run or tune,
  but pgvector gives you SQL joins and full control over your data.

UPSERT vs INSERT
----------------
Pinecone uses "upsert" not "insert" — if a vector ID already exists, it is
overwritten. This means re-running this script on the same file is safe: it
refreshes existing vectors and adds any new ones. No duplicate-key errors.

METADATA LIMITS
---------------
Pinecone enforces a 40KB limit per vector's metadata. We keep text under 10KB
and select specific fields from the enrichment metadata. Arbitrary-depth nested
objects are not supported — metadata must be flat key-value pairs.

USAGE
-----
  export PINECONE_API_KEY=pc-...
  python load_embeddings_to_pinecone.py embeddings.json
  python load_embeddings_to_pinecone.py embeddings.json --index-name financial-docs
  python load_embeddings_to_pinecone.py embeddings.json --namespace q4-reports --batch-size 50

DEPENDENCIES
------------
  pip install pinecone-client
"""

import os
import sys
import time
import json
import hashlib
import argparse
from pathlib import Path

from pinecone import Pinecone, ServerlessSpec


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_INDEX_NAME = 'embeddings-index'
DEFAULT_METRIC     = 'cosine'       # best for normalised text embeddings
DEFAULT_CLOUD      = 'aws'
DEFAULT_REGION     = 'us-east-1'   # Pinecone free tier lives here
DEFAULT_BATCH_SIZE = 100            # Pinecone recommends 100–200 per upsert
METADATA_TEXT_LIMIT = 10_000       # chars — well under Pinecone's 40KB per-vector limit


# ===========================================================================
# Pinecone Client
# ===========================================================================

def init_pinecone(api_key: str = None) -> Pinecone:
    """
    Initialise the Pinecone client.

    API key resolution order:
      1. --api-key CLI argument
      2. PINECONE_API_KEY environment variable

    Get your key from: https://app.pinecone.io/

    Returns:
        Pinecone client, or sys.exit(1) if no key found.
    """
    key = api_key or os.getenv('PINECONE_API_KEY')
    if not key:
        print("ERROR: Pinecone API key required.")
        print("  export PINECONE_API_KEY=pc-...  or  --api-key pc-...")
        print("  Get your key at: https://app.pinecone.io/")
        sys.exit(1)
    client = Pinecone(api_key=key)
    print("Pinecone client initialised.")
    return client


# ===========================================================================
# JSON Loading
# ===========================================================================

def load_json(path: str, override_dims: int = None) -> dict:
    """
    Read and validate the embedding JSON file.

    Expected structure (produced by openai_embeddings.py):
      {
        "chunks": [
          {
            "id": "...",               ← optional; MD5 fallback applied below
            "content": "...",          ← chunk text
            "embedding": [0.1, ...],   ← list of floats (required)
            "metadata": { ... }        ← enrichment metadata (optional)
          },
          ...
        ]
      }

    DIMENSION AUTO-DETECTION
    ------------------------
    We read the length of the first chunk's embedding vector and use that as
    the index dimension. This ensures the index is created with the right size
    without requiring the user to remember or pass the dimension manually.
    Use --dimensions only if you need to override (rare).

    Args:
        path          : path to the JSON file
        override_dims : if set, use this dimension count instead of auto-detecting

    Returns:
        Dict with 'chunks', 'dimensions', and raw 'stats'.
    """
    print(f"Loading: {path}")
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: File not found — {path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON — {e}")
        sys.exit(1)

    chunks = data.get('chunks', [])
    if not chunks:
        print("ERROR: 'chunks' key missing or empty.")
        sys.exit(1)

    if 'embedding' not in chunks[0]:
        print("ERROR: First chunk has no 'embedding' field.")
        sys.exit(1)

    dims = override_dims or len(chunks[0]['embedding'])
    print(f"Loaded {len(chunks)} chunks | {dims} dimensions (auto-detected)")
    return {'chunks': chunks, 'dimensions': dims, 'stats': data.get('stats', {})}


# ===========================================================================
# Index Setup
# ===========================================================================

def create_or_get_index(pc: Pinecone, index_name: str, dimensions: int,
                         metric: str, cloud: str, region: str):
    """
    Return a ready Pinecone index — create it if it doesn't exist.

    SERVERLESS vs POD-BASED
    -----------------------
    Pinecone offers two index types:
      Serverless  — scales automatically, pay per query; free tier available
      Pod-based   — dedicated infrastructure, predictable latency

    We default to Serverless (ServerlessSpec) because it's simpler, cheaper
    for small datasets, and the free tier supports one serverless index.

    IDEMPOTENT CREATION
    -------------------
    We check existing indexes first. If one with the same name already exists:
      - Same dimension: reuse it (upsert will refresh vectors)
      - Different dimension: fail with a clear message — you can't change
        dimensions on an existing index without recreating it

    READINESS WAIT
    --------------
    Pinecone index creation is asynchronous. We poll describe_index() until
    status.ready == True before returning. Typically takes 5–30 seconds.

    Args:
        pc         : initialised Pinecone client
        index_name : name of the index to create or reuse
        dimensions : vector dimension count (must match embedding model output)
        metric     : distance metric — 'cosine' for text embeddings
        cloud      : cloud provider ('aws', 'gcp', 'azure')
        region     : cloud region (must be supported by free tier for aws)

    Returns:
        Pinecone Index object, ready for upsert.
    """
    existing = [idx['name'] for idx in pc.list_indexes()]

    if index_name in existing:
        info = pc.describe_index(index_name)
        existing_dims = info['dimension']

        if existing_dims != dimensions:
            print(f"ERROR: Index '{index_name}' exists with {existing_dims} dims "
                  f"but file has {dimensions} dims.")
            print(f"  Fix: use --index-name a-new-name  OR  delete the index in the Pinecone console.")
            sys.exit(1)

        index = pc.Index(index_name)
        stats = index.describe_index_stats()
        print(f"Reusing index '{index_name}' | {stats['total_vector_count']} vectors already present")
        return index

    # Create new index
    print(f"Creating index '{index_name}' | {dimensions} dims | {metric} | {cloud}/{region}...")
    pc.create_index(
        name=index_name,
        dimension=dimensions,
        metric=metric,
        spec=ServerlessSpec(cloud=cloud, region=region)
    )

    # Poll until ready — creation is asynchronous
    print("Waiting for index to become ready...", end='', flush=True)
    while True:
        status = pc.describe_index(index_name).get('status', {})
        if status.get('ready', False):
            break
        print('.', end='', flush=True)
        time.sleep(1)
    print(" ready.")

    return pc.Index(index_name)


# ===========================================================================
# Vector Preparation
# ===========================================================================

def prepare_vectors(chunks: list, namespace: str = None) -> list:
    """
    Convert chunk dicts into Pinecone's upsert format.

    PINECONE VECTOR FORMAT
    ----------------------
    Each vector must be:
      {
        "id":       str,            ← unique string ID
        "values":   list[float],    ← the embedding
        "metadata": dict            ← flat key-value pairs only
      }

    Nested dicts and lists of objects are not supported in Pinecone metadata.
    We flatten the enrichment metadata into scalar fields.

    ID FALLBACK
    -----------
    If a chunk has no 'id' or 'chunk_id', we generate a deterministic ID
    from the MD5 hash of the content text. This matches the fallback used in
    load_embeddings_to_pgvector.py — same input always produces the same ID,
    so upserts remain idempotent.

    METADATA FIELDS INCLUDED
    ------------------------
    We include a curated subset of the enrichment metadata:
      text        — truncated chunk content (for display in search results)
      source      — document filename or path
      page        — page number (int)
      breadcrumbs — section heading path
      key_phrases — comma-joined list (Pinecone requires scalar, not list)
      char_count  — length of original chunk text
      pii_redacted — whether PII was scrubbed

    We deliberately omit:
      embedding  — already stored as 'values', no need to duplicate in metadata
      entities   — nested dict, not supported
      monetary_values — redundant with content text

    Args:
        chunks    : list of chunk dicts from the JSON file
        namespace : informational only (used in log line); not embedded in vector

    Returns:
        List of vector dicts ready for pc.Index.upsert().
    """
    print(f"Preparing {len(chunks)} vectors{' for namespace: ' + namespace if namespace else ''}...")

    vectors = []
    skipped = 0

    for chunk in chunks:
        # --- ID resolution ---
        text = chunk.get('content') or chunk.get('content_only') or chunk.get('text', '')
        chunk_id = (
            chunk.get('id')
            or chunk.get('chunk_id')
            or 'chunk_' + hashlib.md5(text.encode()).hexdigest()[:16]
        )

        # --- Embedding ---
        embedding = chunk.get('embedding')
        if not embedding:
            print(f"  SKIP {chunk_id}: no embedding field")
            skipped += 1
            continue

        # --- Metadata (flat scalars only) ---
        meta = chunk.get('metadata') or {}
        vector_meta = {}

        # Text content — truncated to stay under 40KB Pinecone metadata limit
        if text:
            vector_meta['text'] = text[:METADATA_TEXT_LIMIT]

        # Source document provenance
        if 'source'       in meta: vector_meta['source']       = str(meta['source'])
        if 'page_number'  in meta: vector_meta['page']         = int(meta['page_number'])
        if 'breadcrumbs'  in meta: vector_meta['breadcrumbs']  = str(meta['breadcrumbs'])
        if 'char_count'   in meta: vector_meta['char_count']   = int(meta['char_count'])
        if 'pii_redacted' in meta: vector_meta['pii_redacted'] = bool(meta['pii_redacted'])

        # key_phrases: list → comma-joined string (Pinecone requires scalar metadata)
        if 'key_phrases' in meta:
            vector_meta['key_phrases'] = ', '.join(meta['key_phrases'][:10])

        # num_atomic_chunks: useful for scoring chunk density
        if 'num_atomic_chunks' in meta:
            vector_meta['num_atomic_chunks'] = int(meta['num_atomic_chunks'])

        vectors.append({
            "id":       chunk_id,
            "values":   embedding,
            "metadata": vector_meta
        })

    print(f"Prepared {len(vectors)} vectors | {skipped} skipped (no embedding)")
    return vectors


# ===========================================================================
# Upsert
# ===========================================================================

def upsert_vectors(index, vectors: list, namespace: str = None,
                   batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """
    Upsert vectors into Pinecone in batches.

    WHY UPSERT (not insert)?
    ------------------------
    Pinecone only supports upsert — if a vector ID already exists, it is
    overwritten with the new values. This makes the script fully idempotent:
    running it twice on the same file is safe and has the same outcome as
    running it once. No duplicate-key errors, no manual deduplication needed.

    WHY BATCH?
    ----------
    The Pinecone SDK's upsert() has a payload size limit. Batching at 100
    vectors (the recommended default) keeps each request well under the limit
    and makes progress visible. For high-throughput scenarios, increase to 200.

    NAMESPACE
    ---------
    Namespaces are logical partitions within an index. Vectors in different
    namespaces are isolated — a query in namespace "q1-reports" never touches
    "q2-reports". Use namespaces to organise documents without creating
    separate indexes (which would each consume your index quota).

    Args:
        index      : Pinecone Index object from create_or_get_index()
        vectors    : list of {id, values, metadata} dicts
        namespace  : target namespace (empty string = default namespace)
        batch_size : vectors per upsert call

    Returns:
        Total vectors upserted.
    """
    total    = len(vectors)
    uploaded = 0
    start    = time.time()

    for i in range(0, total, batch_size):
        batch = vectors[i : i + batch_size]
        index.upsert(vectors=batch, namespace=namespace or "")
        uploaded += len(batch)
        elapsed = time.time() - start
        rate    = uploaded / elapsed if elapsed > 0 else 0
        print(f"  Upserted {uploaded}/{total} | {rate:.0f} vectors/s")

    elapsed = time.time() - start
    print(f"Done. {total} vectors in {elapsed:.1f}s ({total/elapsed:.0f} vectors/s avg)")
    return uploaded


# ===========================================================================
# Verification
# ===========================================================================

def verify(index, expected: int, namespace: str = None):
    """
    Check that the index contains the expected number of vectors.

    ASYNC STATS NOTE
    ----------------
    Pinecone updates index statistics asynchronously — describe_index_stats()
    may lag by a few seconds after a large upsert. If the count doesn't match
    immediately, this is usually a timing issue rather than data loss.
    We print a soft warning rather than failing, since the data is almost
    certainly there.

    Args:
        index    : Pinecone Index object
        expected : number of vectors we upserted
        namespace: namespace to check (None = check total)
    """
    stats = index.describe_index_stats()

    if namespace:
        actual = stats.get('namespaces', {}).get(namespace, {}).get('vector_count', 0)
        print(f"Namespace '{namespace}': {actual} vectors (expected {expected})")
    else:
        actual = stats['total_vector_count']
        print(f"Total vectors in index: {actual} (expected {expected})")

    if actual == expected:
        print("Verification passed.")
    else:
        print(f"WARNING: Count mismatch — Pinecone stats update asynchronously, "
              f"wait a few seconds and recheck.")

    print(f"Index dimensions: {stats['dimension']}")

    if stats.get('namespaces'):
        for ns, ns_data in stats['namespaces'].items():
            label = ns if ns else '(default)'
            print(f"  namespace {label}: {ns_data.get('vector_count', 0)} vectors")


# ===========================================================================
# Pipeline Orchestration
# ===========================================================================

def run_pipeline(args):
    """
    Orchestrate the full load pipeline:
      init client → load file → create/get index → prepare → upsert → verify
    """
    # 1. Pinecone client
    pc = init_pinecone(args.api_key)

    # 2. Load JSON
    data = load_json(args.json_file, args.dimensions)

    # 3. Create or reuse index
    index = create_or_get_index(
        pc, args.index_name, data['dimensions'],
        args.metric, args.cloud, args.region
    )

    # 4. Prepare vectors
    vectors = prepare_vectors(data['chunks'], args.namespace)
    if not vectors:
        print("ERROR: No vectors prepared — check your JSON file.")
        sys.exit(1)

    # 5. Upsert
    upsert_vectors(index, vectors, args.namespace, args.batch_size)

    # 6. Verify (give Pinecone a moment to update stats)
    time.sleep(2)
    verify(index, len(vectors), args.namespace)

    print(f"\nDone. {len(vectors)} vectors loaded into '{args.index_name}'.")
    print(f"Console: https://app.pinecone.io/")


# ===========================================================================
# CLI
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load JSON embeddings into a Pinecone serverless index",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  export PINECONE_API_KEY=pc-...

  python load_embeddings_to_pinecone.py embeddings.json
  python load_embeddings_to_pinecone.py embeddings.json --index-name financial-docs
  python load_embeddings_to_pinecone.py embeddings.json --namespace q4-reports
  python load_embeddings_to_pinecone.py embeddings.json --dimensions 384 --metric cosine
  python load_embeddings_to_pinecone.py embeddings.json --cloud gcp --region us-central1
        """
    )

    parser.add_argument('json_file', help='Path to JSON file with embeddings')
    parser.add_argument('--api-key',    default=None, help="Pinecone API key (default: PINECONE_API_KEY env var)")
    parser.add_argument('--index-name', default=DEFAULT_INDEX_NAME, help=f"Index name (default: {DEFAULT_INDEX_NAME})")
    parser.add_argument('--namespace',  default=None, help="Namespace for logical partitioning (optional)")
    parser.add_argument('--dimensions', type=int, default=None,
                        help="Vector dimensions — auto-detected from first chunk if not set")
    parser.add_argument('--metric', default=DEFAULT_METRIC,
                        choices=['cosine', 'euclidean', 'dotproduct'],
                        help=f"Distance metric (default: {DEFAULT_METRIC})")
    parser.add_argument('--cloud',  default=DEFAULT_CLOUD,
                        choices=['aws', 'gcp', 'azure'],
                        help=f"Cloud provider (default: {DEFAULT_CLOUD})")
    parser.add_argument('--region', default=DEFAULT_REGION,
                        help=f"Cloud region (default: {DEFAULT_REGION})")
    parser.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"Vectors per upsert batch (default: {DEFAULT_BATCH_SIZE})")

    run_pipeline(parser.parse_args())