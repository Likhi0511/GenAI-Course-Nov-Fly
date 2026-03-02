"""
Ingest RAGBench HotpotQA corpus into Pinecone (with OpenAI embeddings)
----------------------------------------------------------------------
- Reads JSONL records from: ragbench_hotpotqa_exports/rag_corpus_hotpotqa_500.jsonl
- Optionally chunks long texts using RecursiveCharacterTextSplitter
- Embeds with OpenAI via langchain_openai (text-embedding-3-large by default)
- Upserts to Pinecone using langchain_pinecone.PineconeVectorStore

Env vars required:
  export OPENAI_API_KEY="sk-..."
  export PINECONE_API_KEY="pcn-..."
Optional tunables:
  INDEX_NAME, NAMESPACE, CHUNK_SIZE, CHUNK_OVERLAP, EMBEDDING_MODEL
"""

import os
import json
import logging
from pathlib import Path
from typing import Iterable, List, Dict

from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain.text_splitter import RecursiveCharacterTextSplitter
from pinecone import Pinecone, ServerlessSpec

# ---------------------- Logging ----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("pinecone_ingest")

# ---------------------- Config -----------------------
CORPUS_PATH = Path("ragbench_hotpotqa_exports/rag_corpus_hotpotqa_500.jsonl")

INDEX_NAME = os.getenv("PINECONE_INDEX", "hotpotqa-ragbench-mini")
NAMESPACE = os.getenv("PINECONE_NAMESPACE", "hotpotqa")  # keeps data scoped

# OpenAI embedding model (and inferred dimension)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
# Known dims: 3072 for text-embedding-3-large, 1536 for text-embedding-3-small
MODEL_DIMS = {"text-embedding-3-large": 3072, "text-embedding-3-small": 1536}
DIMENSION = MODEL_DIMS.get(EMBEDDING_MODEL, 3072)

# Chunking (keep modest for retrieval quality)
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "128"))

# ---------------------- Helpers ----------------------
def ensure_env():
    """Validate required environment variables exist."""
    missing = []
    if not os.getenv("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if not os.getenv("PINECONE_API_KEY"):
        missing.append("PINECONE_API_KEY")
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

def load_jsonl(path: Path) -> Iterable[Dict]:
    """Stream JSONL records lazily."""
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)

def chunk_records(records: Iterable[Dict]) -> List[Dict]:
    """
    For each JSON record:
      {"id": "...", "text": "...", "metadata": {...}}
    return possibly multiple chunked records with updated ids and metadata.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],  # gentle fallbacks
    )

    chunked = []
    for rec in records:
        base_id = rec["id"]
        text = rec["text"]
        meta = rec.get("metadata", {}) or {}

        if not isinstance(text, str) or not text.strip():
            continue

        parts = splitter.split_text(text)
        if not parts:
            continue

        if len(parts) == 1:
            chunked.append(
                {
                    "id": base_id,  # keep original id if single chunk
                    "text": parts[0],
                    "metadata": meta | {"chunk_index": 0, "chunk_count": 1},
                }
            )
        else:
            for i, p in enumerate(parts):
                chunked.append(
                    {
                        "id": f"{base_id}_c{i}",
                        "text": p,
                        "metadata": meta | {"chunk_index": i, "chunk_count": len(parts)},
                    }
                )
    return chunked

def batched(iterable: List, size: int) -> Iterable[List]:
    """Yield fixed-size batches from a list."""
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]

def ensure_index(pc: Pinecone, index_name: str, dimension: int):
    """Create Pinecone index if it doesn't exist (serverless spec)."""
    existing = {i.name for i in pc.list_indexes()}
    if index_name in existing:
        log.info(f"Index '{index_name}' already exists")
        return

    log.info(
        f"Creating Pinecone index '{index_name}' (dim={dimension}, metric='cosine', serverless AWS/us-east-1)..."
    )
    pc.create_index(
        name=index_name,
        dimension=dimension,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )
    log.info("Index creation requested. It may take a few seconds to become ready.")

# ---------------------- Main Flow ----------------------
def main():
    ensure_env()

    if not CORPUS_PATH.exists():
        raise FileNotFoundError(
            f"Corpus file not found at {CORPUS_PATH}. "
            "Run the export script first to generate JSONL."
        )

    # Init Pinecone (control plane)
    log.info("Initializing Pinecone client...")
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    ensure_index(pc, INDEX_NAME, DIMENSION)

    # Connect LangChain to the specific index
    log.info("Preparing embedding function (OpenAI)...")
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)

    # Load and chunk
    log.info(f"Loading records from: {CORPUS_PATH}")
    raw_records = list(load_jsonl(CORPUS_PATH))
    log.info(f"Loaded {len(raw_records)} records from JSONL.")

    log.info(f"Chunking with CHUNK_SIZE={CHUNK_SIZE}, CHUNK_OVERLAP={CHUNK_OVERLAP} ...")
    chunked_records = chunk_records(raw_records)
    log.info(f"After chunking → {len(chunked_records)} chunks total.")

    # Convert to LangChain Document objects on the fly to save memory
    from langchain.schema import Document
    def to_documents(recs: List[Dict]) -> List[Document]:
        return [
            Document(page_content=r["text"], metadata=r.get("metadata", {}) | {"_id": r["id"]})
            for r in recs
        ]

    # Upsert in batches
    log.info(
        f"Starting upsert into Pinecone index='{INDEX_NAME}', namespace='{NAMESPACE}' "
        f"using batches of {BATCH_SIZE} ..."
    )

    # Create (or connect) vector store; from_documents upserts immediately.
    # We’ll do it in batches to avoid large payloads/timeouts.
    total = 0
    for batch in batched(chunked_records, BATCH_SIZE):
        docs = to_documents(batch)
        # Use 'ids' to preserve our own ids (stored in metadata["_id"])
        ids = [d.metadata["_id"] for d in docs]
        PineconeVectorStore.from_documents(
            documents=docs,
            embedding=embeddings,
            index_name=INDEX_NAME,
            namespace=NAMESPACE,
            ids=ids,
        )
        total += len(batch)
        log.info(f"Upserted {total}/{len(chunked_records)} chunks...")

    log.info("Ingestion complete!")
    log.info(f"Index: {INDEX_NAME} | Namespace: {NAMESPACE}")
    log.info("You can now query the index using the same embedding model.")

if __name__ == "__main__":
    main()