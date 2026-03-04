"""
stages — The 5-Stage RAG Document Processing Pipeline

Each module owns exactly one pipeline stage:

  Stage 1: extract.py  — Docling PDF → boundary-marked Markdown pages
  Stage 2: chunk.py    — Boundary-aware semantic chunking
  Stage 3: enrich.py   — PII redaction + NER + key phrases (GPT-4o-mini)
  Stage 4: embed.py    — OpenAI text-embedding-3-small vector generation
  Stage 5: load.py     — Pinecone upsert with transport-safe encoding

Pipeline flow:
  PDF (S3) → [extract] → [chunk] → [enrich] → [embed] → [load] → Pinecone

These modules are called by orchestration/tasks.py via @ray.remote wrappers.
They can also be called directly for testing or local development.

Import examples:
    from stages.extract import create_docling_converter, extract_document
    from stages.chunk   import chunk_directory, create_semantic_chunks
    from stages.enrich  import enrich_chunks_async
    from stages.embed   import generate_embeddings
    from stages.load    import init_pinecone, prepare_vectors, upsert_vectors

Author: Prudhvi | Thoughtworks
"""
