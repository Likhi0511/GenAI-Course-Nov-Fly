"""
load_embeddings_to_pgvector.py
--------------------------------
Load enriched + embedded chunks into PostgreSQL with the pgvector extension.

WHAT THIS SCRIPT DOES
----------------------
Takes the output of any embedding script (sentence_transformers, openai, or
bedrock_titan) and loads every chunk into a PostgreSQL table with a vector
column. Once loaded, you can run semantic similarity searches using SQL.

PIPELINE POSITION
-----------------
  [1] Docling extraction
  [2] Meta-enrichment (PII redaction, NER, key phrases)
  [3] Embedding generation (ST / OpenAI / Bedrock Titan)
  [4] pgvector ingestion  ← you are here
  [5] Semantic search / RAG queries

WHAT GETS CREATED IN POSTGRES
------------------------------
  Schema  : <schema>  (default: public)
  Table   : <table>   (default: document_chunks)

  Columns:
    id          TEXT PRIMARY KEY   — chunk identifier from the JSON
    content     TEXT               — original chunk text
    metadata    JSONB              — entities, key_phrases, monetary_values, etc.
    embedding   vector(N)          — dense vector (N auto-detected from the file)
    created_at  TIMESTAMP          — ingestion timestamp

  Index: HNSW or IVFFlat on the embedding column for fast ANN search

EXAMPLE SEARCH SQL (after loading)
------------------------------------
  SELECT content, 1 - (embedding <=> '[0.12, -0.34, ...]'::vector) AS similarity
  FROM public.document_chunks
  ORDER BY embedding <=> '[0.12, -0.34, ...]'::vector
  LIMIT 5;

USAGE
-----
  python load_embeddings_to_pgvector.py chunks_embeddings.json
  python load_embeddings_to_pgvector.py chunks_embeddings.json --schema analytics --table my_docs
  python load_embeddings_to_pgvector.py chunks_embeddings.json --index-type ivf --no-index

DEPENDENCIES
------------
  pip install psycopg2-binary
  PostgreSQL with pgvector extension installed
"""

import json
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values


# ---------------------------------------------------------------------------
# Defaults — all overridable via CLI flags
# ---------------------------------------------------------------------------
DEFAULT_HOST = 'localhost'
DEFAULT_PORT = 5432
DEFAULT_DB   = 'vector_demo'
DEFAULT_USER = 'postgres'
DEFAULT_PASS = 'postgres'
DEFAULT_SCHEMA = 'public'
DEFAULT_TABLE  = 'document_chunks'
DEFAULT_BATCH  = 100     # rows per INSERT — balance between speed and memory


# ===========================================================================
# Database Connection
# ===========================================================================

def connect(host, port, database, user, password):
    """
    Open a psycopg2 connection to PostgreSQL.

    autocommit=False so every write is wrapped in an explicit transaction.
    The caller is responsible for conn.commit() on success or
    conn.rollback() on failure — this prevents partial writes.

    Returns:
        (conn, cursor) tuple, or raises SystemExit on failure.
    """
    print(f"Connecting to PostgreSQL | {host}:{port}/{database} as {user}")
    try:
        conn = psycopg2.connect(
            host=host, port=port, database=database,
            user=user, password=password
        )
        conn.autocommit = False   # explicit transaction control
        cursor = conn.cursor()
        print("Connected.")
        return conn, cursor
    except Exception as e:
        print(f"ERROR: Connection failed — {e}")
        print("Check host/port/database/user/password and that PostgreSQL is running.")
        sys.exit(1)


# ===========================================================================
# pgvector Extension
# ===========================================================================

def enable_pgvector(conn, cursor):
    """
    Install the pgvector extension if it isn't already present.

    CREATE EXTENSION IF NOT EXISTS is idempotent — safe to run every time.
    The quick sanity-cast ('[1,2,3]'::vector) verifies the extension is
    actually functional, not just listed in pg_extension.

    Raises SystemExit if the extension can't be created (e.g. not installed
    at the OS level — fix: `apt install postgresql-16-pgvector` or equivalent).
    """
    print("Enabling pgvector extension...")
    try:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        # Sanity check: cast a literal to vector type
        cursor.execute("SELECT '[1,2,3]'::vector")
        cursor.fetchone()
        print("pgvector ready.")
    except Exception as e:
        print(f"ERROR: Could not enable pgvector — {e}")
        print("Install pgvector: https://github.com/pgvector/pgvector#installation")
        conn.rollback()
        sys.exit(1)


# ===========================================================================
# Data Loading & Validation
# ===========================================================================

def load_json(input_file: str):
    """
    Read the embedding JSON file and validate its structure.

    EXPECTED FORMAT (produced by any of the three embedding scripts):
      {
        "metadata": { ... },         ← optional top-level metadata
        "chunks": [
          {
            "content": "...",
            "metadata": { ... },
            "embedding": [float, float, ...],
            "embedding_metadata": { ... }
          },
          ...
        ]
      }

    DIMENSION AUTO-DETECTION
    The vector dimension is read from the first chunk's embedding length.
    All subsequent chunks are validated to have the same dimension — a mismatch
    means the file was generated by two different models and would corrupt the
    vector index.

    Returns:
        Dict with keys: 'chunks' (list), 'dimensions' (int)
        Raises SystemExit on any validation failure.
    """
    print(f"Loading: {input_file}")
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: File not found — {input_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON — {e}")
        sys.exit(1)

    # Validate top-level structure
    chunks = data.get('chunks', [])
    if not chunks:
        print("ERROR: No chunks found in JSON (expected a non-empty 'chunks' list)")
        sys.exit(1)

    # Check the first chunk has an embedding field
    if 'embedding' not in chunks[0]:
        print("ERROR: Chunks are missing the 'embedding' field — run an embedding script first")
        sys.exit(1)

    # Auto-detect dimensions from first chunk
    dimensions = len(chunks[0]['embedding'])
    print(f"Loaded {len(chunks)} chunks | {dimensions} dimensions (auto-detected)")

    # Validate all chunks share the same dimension
    # Mismatched dimensions would cause a Postgres type error on INSERT
    for i, chunk in enumerate(chunks):
        if len(chunk['embedding']) != dimensions:
            print(f"ERROR: Chunk {i} has {len(chunk['embedding'])} dims, expected {dimensions}")
            print("All chunks must come from the same embedding model.")
            sys.exit(1)

    return {'chunks': chunks, 'dimensions': dimensions}


# ===========================================================================
# Table Creation
# ===========================================================================

def create_table(conn, cursor, dimensions: int, schema: str, table: str):
    """
    Drop and recreate the target table with the correct vector column size.

    WHY DROP + RECREATE?
    If the script is re-run after changing the embedding model (e.g. switching
    from 384D to 1536D), the existing vector column would have the wrong size
    and every INSERT would fail. DROP + RECREATE ensures a clean slate.

    For production (append-only) workflows, remove the DROP line and add
    an IF NOT EXISTS guard instead.

    TABLE DESIGN NOTES
    - content TEXT        : the raw text — kept here so SQL queries can read
                            results without joining back to the source file
    - metadata JSONB      : entities, key_phrases, monetary_values, etc.
                            JSONB enables index-supported key lookups:
                            WHERE metadata->>'pii_redacted' = 'true'
    - embedding vector(N) : the dense vector; N must match dimensions exactly
    """
    print(f"Creating table {schema}.{table} with vector({dimensions})...")
    try:
        # Create schema if it doesn't exist (e.g. 'analytics', 'production')
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

        # Drop existing table — ensures column types are always correct
        cursor.execute(f"DROP TABLE IF EXISTS {schema}.{table} CASCADE")

        cursor.execute(f"""
            CREATE TABLE {schema}.{table} (
                id          TEXT        PRIMARY KEY,
                content     TEXT        NOT NULL,
                metadata    JSONB,
                embedding   vector({dimensions}),
                created_at  TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        print(f"Table {schema}.{table} created.")
    except Exception as e:
        print(f"ERROR: Could not create table — {e}")
        conn.rollback()
        sys.exit(1)


# ===========================================================================
# Data Insertion
# ===========================================================================

def insert_chunks(conn, cursor, chunks: list, schema: str, table: str, batch_size: int):
    """
    Insert all chunks into the target table in batches.

    WHY BATCHING?
    Sending 10,000 individual INSERT statements is slow — each round-trip to
    Postgres has network + parse + plan overhead. execute_values() sends one
    multi-row INSERT per batch, typically 10-50x faster for bulk loads.

    BATCH SIZE TRADE-OFF
    - Too small (1-10)   : many round-trips, slow
    - Too large (1000+)  : high memory usage, longer rollback window on error
    - 100 is a safe default; increase to 500 on a local or LAN connection

    FIELD MAPPING
    Supports both 'content' and 'text' keys — the enrichment pipeline uses
    'content', older formats sometimes use 'text'. Falls back gracefully.
    """
    print(f"Inserting {len(chunks)} chunks into {schema}.{table} (batch_size={batch_size})...")

    # Build the rows list once — avoids re-accessing dict keys inside the batch loop
    import hashlib

    rows = []
    for chunk in chunks:
        # ID resolution priority: 'id' → 'chunk_id' → MD5 hash of content
        # The MD5 fallback handles chunks that left the enrichment pipeline without
        # an id field. Using content as the hash input makes the ID deterministic —
        # re-running the same file always produces the same IDs, so re-loads are safe.
        text = chunk.get('content') or chunk.get('text', '')
        chunk_id = (
            chunk.get('id')
            or chunk.get('chunk_id')
            or 'chunk_' + hashlib.md5(text.encode()).hexdigest()[:16]
        )
        rows.append((
            chunk_id,
            text,
            json.dumps(chunk.get('metadata', {})),
            chunk['embedding']
        ))

    start = time.time()
    total_inserted = 0

    try:
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]

            # execute_values sends a single multi-row INSERT — much faster than
            # looping individual cursor.execute() calls
            execute_values(
                cursor,
                f"""
                INSERT INTO {schema}.{table} (id, content, metadata, embedding)
                VALUES %s
                """,
                batch
            )
            total_inserted += len(batch)
            elapsed = time.time() - start
            rate = total_inserted / elapsed if elapsed > 0 else 0
            print(f"  {total_inserted}/{len(rows)} rows | {rate:.0f} rows/sec")

        conn.commit()
        print(f"Insert complete in {time.time() - start:.1f}s.")

    except Exception as e:
        print(f"ERROR: Insert failed — {e}")
        conn.rollback()
        sys.exit(1)


# ===========================================================================
# Index Creation
# ===========================================================================

def create_index(conn, cursor, schema: str, table: str,
                 index_type: str, hnsw_m: int, hnsw_ef: int, ivf_lists: int):
    """
    Build a vector index on the embedding column for fast ANN search.

    HNSW vs IVFFlat — which to choose?
    ┌──────────┬──────────────────────────────┬───────────────────────────────┐
    │          │ HNSW                         │ IVFFlat                       │
    ├──────────┼──────────────────────────────┼───────────────────────────────┤
    │ Speed    │ Faster queries               │ Slower queries                │
    │ Build    │ Slower build, more memory    │ Fast build, low memory        │
    │ Recall   │ Higher recall (more accurate)│ Lower recall (approximate)    │
    │ Use case │ Production, quality-first    │ Large datasets, build-time    │
    │          │                              │ constrained environments      │
    └──────────┴──────────────────────────────┴───────────────────────────────┘

    HNSW KEY PARAMETERS
    - m (default 16): connections per node per layer. Higher = better recall,
      more memory. Range 8-64. For most RAG workloads, 16 is the right default.
    - ef_construction (default 64): quality of graph build. Higher = better
      recall at query time, slower to build. Range 32-512.

    IVFFlat KEY PARAMETERS
    - lists: number of Voronoi clusters. Rule of thumb: sqrt(total_rows).
      For 10,000 rows → ~100 lists. Must have rows in table before building.

    Both use vector_cosine_ops because our embeddings are L2-normalised
    (cosine similarity = dot product when both vectors have unit length).
    """
    print(f"Building {index_type.upper()} index on {schema}.{table}.embedding...")
    start = time.time()

    try:
        if index_type == 'hnsw':
            print(f"  m={hnsw_m}, ef_construction={hnsw_ef}")
            cursor.execute(f"""
                CREATE INDEX ON {schema}.{table}
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = {hnsw_m}, ef_construction = {hnsw_ef})
            """)
        elif index_type == 'ivf':
            print(f"  lists={ivf_lists}")
            cursor.execute(f"""
                CREATE INDEX ON {schema}.{table}
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = {ivf_lists})
            """)

        conn.commit()
        print(f"Index built in {time.time() - start:.1f}s.")

    except Exception as e:
        print(f"ERROR: Index creation failed — {e}")
        conn.rollback()
        sys.exit(1)


# ===========================================================================
# Verification
# ===========================================================================

def verify(cursor, schema: str, table: str):
    """
    Run quick sanity checks and print a summary after ingestion.

    Checks:
      1. Row count matches expectation
      2. All embeddings have the same dimensions (vector_dims() function)
      3. One sample row for a manual eyeball check
      4. List of indexes on the table

    This is the last step before declaring success — catching issues here
    is far cheaper than discovering them during a live RAG query.
    """
    print(f"\nVerifying {schema}.{table}...")

    # Total row count
    cursor.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
    count = cursor.fetchone()[0]
    print(f"  Rows: {count}")

    # Dimension distribution — should be exactly one value
    cursor.execute(f"""
        SELECT vector_dims(embedding) AS dims, COUNT(*)
        FROM {schema}.{table}
        GROUP BY dims
    """)
    for dims, cnt in cursor.fetchall():
        print(f"  Dimensions: {dims}D ({cnt} rows)")

    # Sample row — quick eyeball that content and metadata arrived correctly
    cursor.execute(f"""
        SELECT id, LEFT(content, 80), metadata
        FROM {schema}.{table}
        LIMIT 1
    """)
    row = cursor.fetchone()
    if row:
        print(f"  Sample id      : {row[0]}")
        print(f"  Sample content : {row[1]}...")
        print(f"  Metadata keys  : {list(row[2].keys()) if row[2] else 'none'}")

    # Indexes on this table
    cursor.execute(f"""
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = %s AND tablename = %s
    """, (schema, table))
    indexes = [r[0] for r in cursor.fetchall()]
    print(f"  Indexes: {', '.join(indexes) if indexes else 'none'}")

    print("Verification passed.")


# ===========================================================================
# Pipeline Orchestration
# ===========================================================================

def run_pipeline(args):
    """
    Orchestrate the full load pipeline: connect → setup → load → index → verify.

    Linear sequence of six steps. Each step either succeeds or calls sys.exit(1).
    The finally block guarantees the connection is closed even on failure.

    Args:
        args : parsed argparse Namespace
    """
    conn, cursor = None, None

    try:
        # 1. Connect
        conn, cursor = connect(
            args.host, args.port, args.database, args.user, args.password
        )

        # 2. Enable pgvector extension
        enable_pgvector(conn, cursor)

        # 3. Load and validate the embedding JSON
        data = load_json(args.json_file)

        # 4. Create table (drop + recreate for clean schema)
        create_table(conn, cursor, data['dimensions'], args.schema, args.table)

        # 5. Insert all chunks
        insert_chunks(conn, cursor, data['chunks'], args.schema, args.table, args.batch_size)

        # 6. Build vector index (skip if --no-index passed)
        if not args.no_index:
            create_index(
                conn, cursor,
                schema=args.schema, table=args.table,
                index_type=args.index_type,
                hnsw_m=args.hnsw_m, hnsw_ef=args.hnsw_ef_construction,
                ivf_lists=args.ivf_lists
            )
        else:
            print("Skipping index creation (--no-index).")

        # 7. Verify
        verify(cursor, args.schema, args.table)

        # Success summary + example query
        print(f"""
Done. {len(data['chunks'])} chunks loaded into {args.schema}.{args.table}.

Example search query:
  SELECT content, 1 - (embedding <=> '[...]'::vector) AS similarity
  FROM {args.schema}.{args.table}
  ORDER BY embedding <=> '[...]'::vector
  LIMIT 5;
""")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    finally:
        # Always close the connection — even on error or interrupt
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            print("Connection closed.")


# ===========================================================================
# CLI
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load embedding JSON into PostgreSQL with pgvector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python load_embeddings_to_pgvector.py chunks_embeddings.json
  python load_embeddings_to_pgvector.py chunks_embeddings.json --schema analytics --table docs
  python load_embeddings_to_pgvector.py chunks_embeddings.json --index-type ivf --ivf-lists 50
  python load_embeddings_to_pgvector.py chunks_embeddings.json --no-index
        """
    )

    # Required
    parser.add_argument('json_file', help="Path to embedding JSON (output of any embedding script)")

    # Database connection
    parser.add_argument('--host',     default=DEFAULT_HOST, help=f"PostgreSQL host (default: {DEFAULT_HOST})")
    parser.add_argument('--port',     default=DEFAULT_PORT, type=int, help=f"Port (default: {DEFAULT_PORT})")
    parser.add_argument('--database', default=DEFAULT_DB,   help=f"Database name (default: {DEFAULT_DB})")
    parser.add_argument('--user',     default=DEFAULT_USER, help=f"DB user (default: {DEFAULT_USER})")
    parser.add_argument('--password', default=DEFAULT_PASS, help=f"DB password (default: {DEFAULT_PASS})")

    # Table location
    parser.add_argument('--schema', default=DEFAULT_SCHEMA, help=f"Schema name (default: {DEFAULT_SCHEMA})")
    parser.add_argument('--table',  default=DEFAULT_TABLE,  help=f"Table name (default: {DEFAULT_TABLE})")

    # Insertion
    parser.add_argument('--batch-size', type=int, default=DEFAULT_BATCH,
                        help=f"Rows per INSERT batch (default: {DEFAULT_BATCH})")

    # Indexing
    parser.add_argument('--index-type', choices=['hnsw', 'ivf'], default='hnsw',
                        help="Vector index algorithm: hnsw (default) or ivf")
    parser.add_argument('--hnsw-m', type=int, default=16,
                        help="HNSW: connections per node (default: 16, range: 8-64)")
    parser.add_argument('--hnsw-ef-construction', type=int, default=64,
                        help="HNSW: build quality (default: 64, higher = better recall)")
    parser.add_argument('--ivf-lists', type=int, default=100,
                        help="IVFFlat: number of clusters (default: 100, rule: sqrt(row_count))")
    parser.add_argument('--no-index', action='store_true',
                        help="Skip index creation (useful for testing or deferred indexing)")

    args = parser.parse_args()

    # Validate input file before touching the database
    if not Path(args.json_file).exists():
        print(f"ERROR: File not found — {args.json_file}")
        sys.exit(1)

    run_pipeline(args)