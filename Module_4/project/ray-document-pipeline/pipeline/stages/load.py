"""
===============================================================================
load_embeddings_to_pinecone.py  -  Pinecone Vector Ingestion  v3
===============================================================================

Author  : Prudhvi  |  Thoughtworks
Stage   : 5 of 5  (Extract -> Chunk -> Enrich -> Embed -> Store)

-------------------------------------------------------------------------------
WHAT THIS MODULE DOES
-------------------------------------------------------------------------------

1. Reads the JSON embedding file produced by openai_embeddings.py (Stage 4)
2. Initialises a Pinecone client
3. Creates a serverless index if it doesn't exist (or reuses an existing one)
4. Converts chunks into Pinecone's {id, values, metadata} vector format
5. Upserts vectors in batches, then verifies the count

-------------------------------------------------------------------------------
TWO-PASS RETRIEVAL CONTRACT  (critical metadata fields)
-------------------------------------------------------------------------------

The query layer uses two Pinecone metadata fields to decide whether to trigger
a second-pass S3 fetch for large tables and images:

  type    — 'table_offloaded' | 'image_offloaded' | absent (normal text)
  s3_uri  — 's3://bucket/doc/tables/p3_table_1.md' | absent

Query layer pattern:
  for match in results.matches:
      if match.metadata.get('type') == 'table_offloaded':
          raw_table = fetch_from_s3(s3_client, match.metadata['s3_uri'])
          # pass description + raw table to LLM for precise numeric answers

  v1 BUG: both fields were missing from vector_meta — two-pass retrieval was
  silently broken. All large tables returned only the AI description.

-------------------------------------------------------------------------------
EMBEDDING=NONE HANDLING  (Stage 4 contract)
-------------------------------------------------------------------------------

Stage 4 (openai_embeddings.py) passes chunks with empty content through with
embedding=None rather than dropping them (silent data loss fix).

This stage skips upsert for those chunks — they have no vector to store.
The skip is logged with the correct reason rather than "no embedding field".

  v1 BUG: log message said "no embedding field" even when the field was
  present with an intentional None value from Stage 4.

-------------------------------------------------------------------------------
PIPELINE POSITION
-------------------------------------------------------------------------------

  [1] Docling extraction        (docling_bounded_extractor.py)
  [2] Semantic chunking         (comprehensive_chunker.py)
  [3] Enrichment                (enrich_pipeline_openai.py)
  [4] Embedding generation      (openai_embeddings.py)
  [5] Pinecone ingestion        <- you are here
  [6] Semantic search / RAG     (query layer)

-------------------------------------------------------------------------------
PINECONE vs PGVECTOR
-------------------------------------------------------------------------------

  pgvector  — runs inside PostgreSQL; free, self-hosted, SQL joins
  Pinecone  — managed cloud; free tier (2GB / 1 index), no infra to manage

  Both store vectors and search by cosine distance.

-------------------------------------------------------------------------------
UPSERT vs INSERT
-------------------------------------------------------------------------------

Pinecone uses upsert — existing vector IDs are overwritten.
Re-running on the same file is safe and idempotent. No duplicate-key errors.

-------------------------------------------------------------------------------
METADATA LIMITS
-------------------------------------------------------------------------------

Pinecone enforces a 40KB limit per vector's metadata.
Text is capped at METADATA_TEXT_LIMIT (10KB) — well under the limit.
Metadata must be flat key-value pairs; nested objects are not supported.

-------------------------------------------------------------------------------
USAGE
-------------------------------------------------------------------------------

  export PINECONE_API_KEY=pc-...
  python load_embeddings_to_pinecone.py embeddings.json
  python load_embeddings_to_pinecone.py embeddings.json --index-name my-docs
  python load_embeddings_to_pinecone.py embeddings.json --namespace q4-reports

-------------------------------------------------------------------------------
DEPENDENCIES
-------------------------------------------------------------------------------

  pip install pinecone-client
  from utils import read_json_robust

-------------------------------------------------------------------------------
CHANGELOG
-------------------------------------------------------------------------------

v3
  FIX 6 - patch_urllib3_latin1() monkey-patches urllib3 to pre-encode string
           bodies as UTF-8 bytes. This is the ROOT CAUSE fix — urllib3 defaults
           to Latin-1 per HTTP/1.1 spec, which cannot represent U+0100+ chars.
           Environment-level fixes (PYTHONIOENCODING, LANG, sitecustomize.py)
           do NOT affect this code path.
  FIX 7 - sanitize_for_transport() replaces non-Latin-1 characters using
           unicodedata categories and names — fully generic, zero hardcoded
           character mappings. Defence-in-depth for SDK changes / gRPC paths.
  FIX 8 - sanitize_metadata() applies transport sanitisation to ALL string
           values in vector metadata, not just the text field.
  FIX 9 - Raw byte contamination handling (0xa3 invalid start byte) via
           UTF-8 round-trip with surrogate pass + replace error handler.

v2
  FIX 1 - load_json handles both wrapped dict and bare-list input shapes.
           data.get('chunks', []) returned [] for bare-list files.
  FIX 2 - load_json validates embedding value (not just key presence).
           chunks[0]['embedding'] could be None (Stage 4 intentional skip).
           Now counts real embeddings upfront and warns if zero.
  FIX 3 - s3_uri added to vector_meta in prepare_vectors().
           Two-pass retrieval was silently broken without it.
           Checks both chunk['s3_uri'] (Stage 2 level) and meta['s3_uri'].
  FIX 4 - type added to vector_meta in prepare_vectors().
           Query layer needs type='table_offloaded'/'image_offloaded' to
           decide when to trigger two-pass S3 retrieval.
  FIX 5 - verify() namespace lookup uses namespace or '' as key.
           namespace=None used as dict key always returned 0 vector count.

v1
  Original release.
"""

import os
import sys
import time
import json
import hashlib
import argparse
import logging
from pathlib import Path
from typing import Optional

from pinecone import Pinecone, ServerlessSpec
from core.encoding import (
    read_json_robust,
    patch_urllib3_latin1,
    sanitize_for_transport,
    sanitize_metadata,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_INDEX_NAME    = 'embeddings-index'
DEFAULT_METRIC        = 'cosine'        # best for normalised text embeddings
DEFAULT_CLOUD         = 'aws'
DEFAULT_REGION        = 'us-east-1'    # Pinecone free tier lives here
DEFAULT_BATCH_SIZE    = 100            # Pinecone recommends 100-200 per upsert
METADATA_TEXT_LIMIT   = 10_000        # chars — well under Pinecone's 40KB limit


# ===========================================================================
# Pinecone Client
# ===========================================================================

def init_pinecone(api_key: Optional[str] = None) -> Pinecone:
    """
    Initialise the Pinecone client.

    API key resolution order:
      1. --api-key CLI argument  (or explicit api_key= when called from ray_tasks.py)
      2. PINECONE_API_KEY environment variable

    Returns:
        Pinecone client, or sys.exit(1) if no key found.
    """
    key = api_key or os.getenv('PINECONE_API_KEY')
    if not key:
        print("ERROR: Pinecone API key required.")
        print("  export PINECONE_API_KEY=pc-...  or  --api-key pc-...")
        print("  Get your key at: https://app.pinecone.io/")
        sys.exit(1)

    # FIX: Patch urllib3 BEFORE creating the Pinecone client.
    # This ensures all HTTP requests use UTF-8 body encoding.
    patch_urllib3_latin1()

    client = Pinecone(api_key=key)
    print("Pinecone client initialised.")
    return client


# ===========================================================================
# JSON Loading
# ===========================================================================

def load_json(path: str, override_dims: int = None) -> dict:
    """
    Read and validate the embedding JSON file from Stage 4.

    FIX 1 — handles both input shapes:
      Shape A — wrapped dict (Stage 4 save_results always writes this):
        { "metadata": {...}, "chunks": [...] }
        -> data['chunks']

      Shape B — bare list (defensive; in case called with raw list file):
        [ {...}, {...}, ... ]
        -> data itself

    FIX 2 — validates embedding value, not just key presence:
      Stage 4 intentionally sets embedding=None for chunks with empty content.
      The old guard `if 'embedding' not in chunks[0]` would pass for these
      chunks since the key IS present (just with a None value).
      We now count chunks with real (non-None) embeddings upfront and warn
      clearly if none exist before creating the index or spending API quota.

    DIMENSION AUTO-DETECTION:
      Length of the first real (non-None) embedding vector.
      Use --dimensions only to override (rare).

    Args:
        path          : path to the Stage 4 output JSON file
        override_dims : if set, use this dimension count instead of auto-detecting

    Returns:
        Dict with 'chunks', 'dimensions', and raw 'stats'.
    """
    print(f"Loading: {path}")
    try:
        data = read_json_robust(path)
    except FileNotFoundError:
        print(f"ERROR: File not found — {path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON — {e}")
        sys.exit(1)

    # FIX 1: handle both wrapped dict and bare list
    if isinstance(data, list):
        chunks = data
    elif isinstance(data, dict):
        chunks = data.get('chunks', [])
    else:
        print(f"ERROR: Unexpected top-level type {type(data).__name__} — expected list or dict.")
        sys.exit(1)

    if not chunks:
        print("ERROR: No chunks found — 'chunks' key missing or empty list.")
        sys.exit(1)

    # FIX 2: count real embeddings — embedding=None chunks are intentional Stage 4 skips
    real_embeddings = [
        c for c in chunks
        if c.get('embedding') is not None and c.get('embedding') != []
    ]
    skipped_count = len(chunks) - len(real_embeddings)

    if not real_embeddings:
        print(
            f"ERROR: All {len(chunks)} chunks have embedding=None "
            f"(Stage 4 marked them all as skipped — check Stage 3/4 output)."
        )
        sys.exit(1)

    if skipped_count:
        print(
            f"  NOTE: {skipped_count} chunk(s) have embedding=None "
            f"(Stage 4 skips) — will not be upserted."
        )

    # Auto-detect dimensions from first real embedding
    dims = override_dims or len(real_embeddings[0]['embedding'])
    print(
        f"Loaded {len(chunks)} chunks total | "
        f"{len(real_embeddings)} with embeddings | "
        f"{skipped_count} skipped | "
        f"{dims} dimensions (auto-detected)"
    )
    return {'chunks': chunks, 'dimensions': dims, 'stats': data.get('stats', {})}


# ===========================================================================
# Index Setup
# ===========================================================================

def create_or_get_index(
    pc: Pinecone,
    index_name: str,
    dimensions: int,
    metric: str,
    cloud: str,
    region: str,
):
    """
    Return a ready Pinecone index — create it if it doesn't exist.

    SERVERLESS vs POD-BASED:
      Serverless  — scales automatically, pay per query; free tier available
      Pod-based   — dedicated infrastructure, predictable latency
    We default to Serverless (ServerlessSpec) — simpler and free-tier-eligible.

    IDEMPOTENT CREATION:
      Same name + same dims -> reuse (upsert refreshes vectors).
      Same name + different dims -> sys.exit(1) with clear message.
      Pinecone index dimensions cannot be changed after creation.

    READINESS POLL:
      Creation is asynchronous — we poll describe_index() until ready.
      Typically 5-30 seconds.

    Args:
        pc         : initialised Pinecone client
        index_name : name of the index to create or reuse
        dimensions : vector dimension count (must match embedding model)
        metric     : distance metric ('cosine' for text embeddings)
        cloud      : cloud provider ('aws', 'gcp', 'azure')
        region     : cloud region

    Returns:
        Pinecone Index object, ready for upsert.
    """
    existing = [idx['name'] for idx in pc.list_indexes()]

    if index_name in existing:
        info          = pc.describe_index(index_name)
        existing_dims = info['dimension']

        if existing_dims != dimensions:
            print(
                f"ERROR: Index '{index_name}' exists with {existing_dims} dims "
                f"but file has {dimensions} dims."
            )
            print(
                "  Fix: --index-name a-new-name  "
                "OR  delete the index in the Pinecone console."
            )
            sys.exit(1)

        index = pc.Index(index_name)
        stats = index.describe_index_stats()
        print(
            f"Reusing index '{index_name}' | "
            f"{stats['total_vector_count']} vectors already present"
        )
        return index

    # Create new index
    print(
        f"Creating index '{index_name}' | "
        f"{dimensions} dims | {metric} | {cloud}/{region}..."
    )
    pc.create_index(
        name=index_name,
        dimension=dimensions,
        metric=metric,
        spec=ServerlessSpec(cloud=cloud, region=region),
    )

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

    PINECONE VECTOR FORMAT:
      { "id": str, "values": list[float], "metadata": dict }
      Metadata must be flat key-value pairs — no nested objects or lists of dicts.

    ID FALLBACK:
      chunk['id'] -> chunk['chunk_id'] -> MD5 hash of content text.
      MD5 is deterministic — same content always produces the same ID,
      so repeated upserts remain idempotent.

    FIX 3 — s3_uri added to vector_meta:
      Stage 2 writes s3_uri directly on the chunk dict (not inside metadata):
        chunk['s3_uri'] = 's3://bucket/doc/tables/p3_table_1.md'
      Stage 4 passes it through unchanged.
      We check both chunk['s3_uri'] and chunk['metadata']['s3_uri'].
      Without this, the query layer cannot fetch raw Markdown for large tables
      (two-pass retrieval pattern is silently broken).

    FIX 4 — type added to vector_meta:
      Stage 3 writes chunk['metadata']['type'] = 'table_offloaded' or
      'image_offloaded' for offloaded assets.
      The query layer needs this to decide whether to trigger two-pass S3 fetch:
        if match.metadata.get('type') == 'table_offloaded':
            raw_table = fetch_from_s3(s3_client, match.metadata['s3_uri'])

    METADATA FIELDS INCLUDED:
      text            — truncated chunk content (shown in search results)
      type            — 'table_offloaded' / 'image_offloaded' / absent
      s3_uri          — S3 pointer for two-pass retrieval
      source          — document filename or path
      page            — page number (int)
      breadcrumbs     — section heading path (e.g. "Results > Efficacy")
      char_count      — original chunk text length
      pii_redacted    — whether PII was scrubbed by Stage 3
      key_phrases     — comma-joined top phrases from Stage 3
      num_atomic_chunks — number of Docling elements merged into this chunk

    METADATA FIELDS OMITTED:
      embedding       — stored as 'values', duplicating in metadata wastes space
      entities        — nested dict, not supported by Pinecone metadata
      monetary_values — redundant with content text

    NOTE on key_phrases:
      Stored as a comma-joined string for compatibility.
      Pinecone does support list values for $in filter queries — upgrade to
      list storage if metadata filtering on key_phrases is needed:
        filter={'key_phrases': {'$in': ['hazard ratio']}}

    Args:
        chunks    : list of chunk dicts from load_json()
        namespace : informational only; logged in output, not stored in vector

    Returns:
        List of {id, values, metadata} dicts ready for index.upsert().
    """
    print(
        f"Preparing vectors"
        f"{' for namespace: ' + namespace if namespace else ''}..."
    )

    vectors = []
    skipped = 0

    for chunk in chunks:
        # ── ID resolution ─────────────────────────────────────────────────
        text     = chunk.get('content') or chunk.get('content_only') or chunk.get('text', '')
        chunk_id = (
            chunk.get('id')
            or chunk.get('chunk_id')
            or 'chunk_' + hashlib.md5(text.encode()).hexdigest()[:16]
        )

        # ── Embedding ─────────────────────────────────────────────────────
        # embedding=None means Stage 4 intentionally skipped this chunk
        # (empty content — e.g. Stage 1 AI description failed for an asset).
        # Do NOT upsert — no vector to store.
        embedding = chunk.get('embedding')
        if embedding is None:
            print(
                f"  SKIP {chunk_id}: embedding=None "
                f"(Stage 4 marked as skipped — empty or unavailable content)"
            )
            skipped += 1
            continue
        if not embedding:
            # Empty list [] — should not happen normally, treat same as None
            print(f"  SKIP {chunk_id}: embedding is empty list")
            skipped += 1
            continue

        # ── Metadata (flat scalars only) ───────────────────────────────────
        meta        = chunk.get('metadata') or {}
        vector_meta = {}

        # Text content — truncated to stay under 40KB Pinecone metadata limit
        if text:
            vector_meta['text'] = sanitize_for_transport(text)[:METADATA_TEXT_LIMIT]

        # FIX 4: chunk type — query layer needs this to trigger two-pass retrieval
        # Stage 3 writes type='table_offloaded' / 'image_offloaded' in metadata.
        chunk_type = meta.get('type') or meta.get('chunk_type')
        if chunk_type:
            vector_meta['type'] = str(chunk_type)

        # FIX 3: s3_uri — essential for two-pass retrieval of large tables/images.
        # Stage 2 writes s3_uri at chunk level (not inside metadata dict).
        # Also check meta['s3_uri'] as defensive fallback.
        s3_uri = chunk.get('s3_uri') or meta.get('s3_uri')
        if s3_uri:
            vector_meta['s3_uri'] = str(s3_uri)

        # Source document provenance
        if 'source'       in meta: vector_meta['source']       = str(meta['source'])
        if 'page_number'  in meta: vector_meta['page']         = int(meta['page_number'])
        if 'breadcrumbs'  in meta: vector_meta['breadcrumbs']  = str(meta['breadcrumbs'])
        if 'char_count'   in meta: vector_meta['char_count']   = int(meta['char_count'])
        if 'pii_redacted' in meta: vector_meta['pii_redacted'] = bool(meta['pii_redacted'])

        # key_phrases: list -> comma-joined string (Pinecone requires scalar values)
        if 'key_phrases' in meta:
            kp = meta['key_phrases']
            if isinstance(kp, list):
                vector_meta['key_phrases'] = ', '.join(str(p) for p in kp[:10])
            elif isinstance(kp, str):
                vector_meta['key_phrases'] = kp

        # Chunk density — useful for scoring
        if 'num_atomic_chunks' in meta:
            vector_meta['num_atomic_chunks'] = int(meta['num_atomic_chunks'])

        # FIX: Sanitise ALL metadata strings as defence-in-depth.
        # Even with the urllib3 patch, this protects against SDK changes,
        # gRPC fallback paths, and raw byte contamination from upstream stages.
        vector_meta = sanitize_metadata(vector_meta)

        vectors.append({
            "id":       chunk_id,
            "values":   embedding,
            "metadata": vector_meta,
        })

    print(f"Prepared {len(vectors)} vectors | {skipped} skipped (embedding=None)")
    return vectors


# ===========================================================================
# Upsert
# ===========================================================================

def upsert_vectors(
    index,
    vectors: list,
    namespace: Optional[str] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """
    Upsert vectors into Pinecone in batches.

    WHY UPSERT?
      Pinecone only supports upsert. Existing vector IDs are overwritten.
      Re-running on the same file is fully idempotent — no deduplication needed.

    NAMESPACE:
      Logical partition within an index. Vectors in different namespaces are
      isolated — a query in 'q1-reports' never touches 'q2-reports'. Use
      namespaces to organise documents without consuming additional index quota.

    Args:
        index      : Pinecone Index object from create_or_get_index()
        vectors    : list of {id, values, metadata} dicts
        namespace  : target namespace (None or '' = default namespace)
        batch_size : vectors per upsert call (100-200 recommended)

    Returns:
        Total vectors upserted.
    """
    total    = len(vectors)
    uploaded = 0
    start    = time.time()

    for i in range(0, total, batch_size):
        batch     = vectors[i:i + batch_size]
        index.upsert(vectors=batch, namespace=namespace or "")
        uploaded += len(batch)
        elapsed   = time.time() - start
        rate      = uploaded / elapsed if elapsed > 0 else 0
        print(f"  Upserted {uploaded}/{total} | {rate:.0f} vectors/s")

    elapsed = time.time() - start
    print(f"Done. {total} vectors in {elapsed:.1f}s ({total/elapsed:.0f} vectors/s avg)")
    return uploaded


# ===========================================================================
# Verification
# ===========================================================================

def verify(index, expected: int, namespace: Optional[str] = None):
    """
    Check that the index contains the expected number of vectors.

    FIX 5 — namespace dict key uses namespace or '':
      Pinecone stats['namespaces'] keys the default namespace as '' (empty string).
      The old code used namespace directly as the dict key — when namespace=None
      this looked up key None which never matches, always returning count=0.

    ASYNC STATS NOTE:
      Pinecone updates index statistics asynchronously. describe_index_stats()
      may lag a few seconds after a large upsert. We print a soft warning rather
      than failing — the data is almost certainly present.

    Args:
        index     : Pinecone Index object
        expected  : number of vectors upserted (len(vectors) from prepare_vectors)
        namespace : namespace to check (None = check total index count)
    """
    stats = index.describe_index_stats()

    if namespace:
        # FIX 5: use namespace or '' — Pinecone keys the default namespace as ''
        actual = (
            stats.get('namespaces', {})
                 .get(namespace or '', {})
                 .get('vector_count', 0)
        )
        print(f"Namespace '{namespace}': {actual} vectors (expected {expected})")
    else:
        actual = stats['total_vector_count']
        print(f"Total vectors in index: {actual} (expected {expected})")

    if actual == expected:
        print("Verification passed.")
    else:
        print(
            f"WARNING: Count mismatch ({actual} vs {expected}) — "
            f"Pinecone stats update asynchronously, wait a few seconds and recheck."
        )

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
      init client -> load file -> create/get index -> prepare -> upsert -> verify

    Called by ray_tasks.py Stage 5 or directly via CLI.
    """
    # 1. Pinecone client
    pc = init_pinecone(getattr(args, 'api_key', None))

    # 2. Load JSON — handles both dict and bare-list input shapes
    data = load_json(args.json_file, getattr(args, 'dimensions', None))

    # 3. Create or reuse index
    index = create_or_get_index(
        pc, args.index_name, data['dimensions'],
        args.metric, args.cloud, args.region,
    )

    # 4. Prepare vectors — skips embedding=None, adds type + s3_uri
    vectors = prepare_vectors(data['chunks'], getattr(args, 'namespace', None))
    if not vectors:
        print(
            "ERROR: No vectors prepared — all chunks have embedding=None. "
            "Check Stage 3/4 pipeline output."
        )
        sys.exit(1)

    # 5. Upsert
    upsert_vectors(index, vectors, getattr(args, 'namespace', None), args.batch_size)

    # 6. Verify (give Pinecone a moment to update stats)
    time.sleep(2)
    verify(index, len(vectors), getattr(args, 'namespace', None))

    print(f"\nDone. {len(vectors)} vectors loaded into '{args.index_name}'.")
    print("Console: https://app.pinecone.io/")


# ===========================================================================
# CLI
# ===========================================================================

# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(
#         description="Load JSON embeddings into a Pinecone serverless index  (Stage 5)",
#         formatter_class=argparse.RawDescriptionHelpFormatter,
#         epilog="""
# Examples:
#   export PINECONE_API_KEY=pc-...
#
#   python load_embeddings_to_pinecone.py embeddings.json
#   python load_embeddings_to_pinecone.py embeddings.json --index-name my-docs
#   python load_embeddings_to_pinecone.py embeddings.json --namespace q4-reports
#   python load_embeddings_to_pinecone.py embeddings.json --cloud gcp --region us-central1
#   python load_embeddings_to_pinecone.py embeddings.json --dimensions 384 --batch-size 200
#
# Two-pass retrieval (query layer must implement):
#   for match in results.matches:
#       if match.metadata.get('type') == 'table_offloaded':
#           raw_table = fetch_from_s3(s3_client, match.metadata['s3_uri'])
#           # pass description + raw table to LLM
#         """,
#     )
#
#     parser.add_argument('json_file',     help="Path to JSON file with embeddings (Stage 4 output)")
#     parser.add_argument('--api-key',     default=None,
#                         help="Pinecone API key (default: PINECONE_API_KEY env var)")
#     parser.add_argument('--index-name',  default=DEFAULT_INDEX_NAME,
#                         help=f"Index name (default: {DEFAULT_INDEX_NAME})")
#     parser.add_argument('--namespace',   default=None,
#                         help="Namespace for logical partitioning (optional)")
#     parser.add_argument('--dimensions',  type=int, default=None,
#                         help="Vector dimensions — auto-detected from first chunk if not set")
#     parser.add_argument('--metric',      default=DEFAULT_METRIC,
#                         choices=['cosine', 'euclidean', 'dotproduct'],
#                         help=f"Distance metric (default: {DEFAULT_METRIC})")
#     parser.add_argument('--cloud',       default=DEFAULT_CLOUD,
#                         choices=['aws', 'gcp', 'azure'],
#                         help=f"Cloud provider (default: {DEFAULT_CLOUD})")
#     parser.add_argument('--region',      default=DEFAULT_REGION,
#                         help=f"Cloud region (default: {DEFAULT_REGION})")
#     parser.add_argument('--batch-size',  type=int, default=DEFAULT_BATCH_SIZE,
#                         help=f"Vectors per upsert batch (default: {DEFAULT_BATCH_SIZE})")
#
#     run_pipeline(parser.parse_args())