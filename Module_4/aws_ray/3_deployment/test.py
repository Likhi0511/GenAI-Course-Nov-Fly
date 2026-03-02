import hashlib
import json
import os

from pinecone import Pinecone
METADATA_TEXT_LIMIT = 10_000

def prepare_vectors(chunk: list, namespace: str = None) -> list:
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

    vectors = []
    skipped = 0


    # --- ID resolution ---
    text = chunk.get('content') or chunk.get('content_only') or chunk.get('text', '')
    chunk_id = (
        chunk.get('id')
        or chunk.get('chunk_id')
        or 'chunk_' + hashlib.md5(text.encode()).hexdigest()[:16]
    )

    # --- Embedding ---
    embedding = chunk.get('embedding')

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

    return {
        "id":       chunk_id,
        "values":   embedding,
        "metadata": vector_meta
    }

with open("/Users/akellaprudhvi/mystuff/Course/GenAI-Course-Modules/Module_4/aws_ray/3_deployment/doc_NCT02014597_Scleroderma_Study_6_6413a934_embeddings.json",'r') as f:
    content = f.read()
    json_data = json.loads(content)
    key = os.getenv('PINECONE_API_KEY')
    client = Pinecone(api_key=key)
    index = client.Index("clinical-trials-index")
    for chunk in json_data['chunks']:
        print(chunk)
        try:
            index.upsert([prepare_vectors(chunk)])
        except Exception as e:
            raise e


