"""
ray_tasks.py

Ray Remote Functions for Document Processing Pipeline
Each function represents one stage in the pipeline.

================================================================================
                    THE 5-STAGE RAG PIPELINE EXPLAINED
================================================================================

Think of this file as the "assembly line workers" in our document factory.
Each @ray.remote function is a specialized worker that does ONE job:

┌─────────────────────────────────────────────────────────────────────────┐
│                        DOCUMENT PROCESSING FLOW                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  PDF (S3) → [Stage 1] → [Stage 2] → [Stage 3] → [Stage 4] → [Stage 5] → Pinecone  │
│               ↓            ↓           ↓           ↓           ↓                   │
│             Extract      Chunk      Enrich      Embed        Load                  │
│             Text         Text       Metadata    Vectors      to DB                 │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘

Stage 1 – extract_pdf              → Extract text/tables/images from PDF
Stage 2 – chunk_document           → Split into semantic chunks (~1500 chars)
Stage 3 – enrich_chunks            → Add PII redaction, entities, key phrases
Stage 4 – generate_embeddings_task → Convert text to 1536-dim vectors
Stage 5 – load_vectors             → Upsert vectors into Pinecone

Why @ray.remote functions instead of classes?
✓ Simpler  — no __init__, no self, no shared state to worry about
✓ Stateless — every call is isolated, safe to retry independently
✓ Testable  — call like a regular function in unit tests
✓ Explicit  — resource requirements are clear on the decorator

Author: Prudhvi
Organization: Thoughtworks
"""

import ray
import json
import time
import logging
from typing import Dict
from datetime import datetime

# ---------------------------------------------------------------------------
# STAGE-SPECIFIC IMPORTS
# ---------------------------------------------------------------------------

# Stage 1 — Docling (IBM) gives us high-quality PDF extraction:
#   - Preserves table structure as markdown
#   - Extracts images and sends them to GPT-4o for text descriptions
#   - Wraps each element in HTML boundary markers for precise chunking later
from docling_bounded_extractor import process_pdf as bounded_process_pdf
from openai import OpenAI as _OpenAI  # Used by Docling to describe images/tables

# Stage 2 — Boundary-aware chunker that:
#   - Respects document structure (never splits mid-paragraph or mid-table)
#   - Groups atomic elements into semantic chunks (~1500 chars target)
#   - Returns clean, consistently structured output dicts
from comprehensive_chunker import (
    chunk_directory,           # Parse .md files → per-element atomic chunks
    create_semantic_chunks,    # Group atomic chunks into ~1500-char semantic units
    format_chunks_for_output,  # Strip internal IDs, ensure consistent output shape
)

# Stage 3 — Single GPT-4o-mini call per chunk handles three tasks at once:
#   - PII detection + redaction  (emails, phone numbers, SSNs → [REDACTED])
#   - Named Entity Recognition   (people, orgs, medications, locations)
#   - Key phrase extraction       (important terms for better search recall)
from enrich_pipeline_openai import enrich_chunk, init_openai_client

# Stage 4 — OpenAI embeddings with built-in safeguards:
#   - Exponential-backoff retry for 429 rate-limit errors
#   - Batch processing to minimise API round-trips
#   - Token tracking so we know the exact dollar cost per document
from openai_embeddings import (
    init_openai_client as init_embedding_client,  # Aliased to avoid name collision with Stage 3
    load_chunks as load_embedding_chunks,          # Reads enriched JSON → list of chunk dicts
    generate_embeddings,                           # Calls API, attaches vectors to chunks
    save_results as save_embedding_results,        # Writes output JSON with cost metadata
)

# Stage 5 — Pinecone vector storage:
#   - Auto dimension detection   (reads first embedding, no manual config)
#   - Namespace support           (logical partitioning for multi-tenant use)
#   - Idempotent upsert           (same content → same MD5 ID → safe to re-run)
#   - Post-upload verification    (warns if count mismatches — expected due to async stats)
from load_embeddings_to_pinecone import (
    init_pinecone,
    load_json as pinecone_load_json,   # Reads JSON + detects embedding dimensions
    create_or_get_index,               # Creates index if missing, connects if it exists
    prepare_vectors,                   # Flattens nested metadata, generates IDs
    upsert_vectors,                    # Uploads in configurable batch sizes
    verify as pinecone_verify,         # Queries index stats to confirm upload succeeded
)

# Shared helpers used across all stages
from config import config   # Central config — reads from env vars / Secrets Manager
from utils import S3Helper, LocalFileManager, format_duration
#   S3Helper         — upload_file / download_file / upload_directory / download_directory
#   LocalFileManager — create_document_workspace(doc_id) → tmp Path; cleanup_document_workspace(doc_id)
#   format_duration  — converts float seconds → human-readable "1m 23s"

logger = logging.getLogger(__name__)


# ============================================================================
# STAGE 1: PDF EXTRACTION
# ============================================================================
# Purpose : Convert a raw PDF into per-page markdown files with boundary markers.
#
# Input   : PDF file at s3://<bucket>/<s3_key>
# Output  : Folder at s3://<bucket>/extracted/<doc_id>/
#             pages/page_1.md … page_N.md   ← text with <!-- BOUNDARY --> markers
#             figures/fig_p1_0.png …         ← extracted images
#             metadata.json                 ← page count, image count, etc.
#
# Why boundary markers?
#   Without: "...paragraph ends.TABLE| data |TABLE.Next paragraph..."
#   With:    "...paragraph ends.<!-- BOUNDARY_START:TABLE -->| data |<!-- BOUNDARY_END:TABLE -->..."
#   Stage 2 can then extract tables as complete, indivisible atomic units.
#
# Cost : ~$0.01–$0.05 per document  (GPT-4o image/table descriptions)
# Time : ~30–60 seconds per document
# ============================================================================

@ray.remote(
    num_cpus=config.EXTRACTION_NUM_CPUS,
    memory=config.EXTRACTION_MEMORY_MB * 1024 * 1024,  # Ray expects bytes; config stores MB
)
def extract_pdf(document_id: str, s3_bucket: str, s3_key: str) -> Dict:
    """
    Download a PDF from S3, extract structured text via Docling + GPT-4o,
    and upload the result back to S3.

    Args:
        document_id : Unique identifier  e.g. "doc_20240222_123456_a1b2c3d4"
        s3_bucket   : Source bucket      e.g. "ray-ingestion-prudhvi-2026"
        s3_key      : Source object key  e.g. "input/NCT04368728_Remdesivir_COVID.pdf"

    Returns:
        On success:
            {
                'status'          : 'COMPLETED',
                'output_s3_key'   : 'extracted/doc_id',      ← S3 prefix, not a file
                'duration_seconds': 45,
                'metadata': {
                    'pages_extracted' : 25,
                    'images_extracted': 5,   ← each image consumed one GPT-4o call
                    'tables_extracted': 12
                }
            }
        On failure:
            { 'status': 'FAILED', 'error': '<message>', 'duration_seconds': N }
    """
    start_time = time.time()
    log = logging.getLogger(__name__)

    # Initialise helpers inside the function — not at module level.
    # Ray runs each @ray.remote call in a separate worker process, so
    # module-level objects created on the driver would NOT be available here.
    s3_helper     = S3Helper(bucket=config.S3_BUCKET, region=config.AWS_REGION)
    file_manager  = LocalFileManager()
    openai_client = _OpenAI(api_key=config.OPENAI_API_KEY)  # Used by Docling for image descriptions

    # Create an isolated temp workspace: /tmp/workspaces/<doc_id>/
    # Each document gets its own folder so concurrent workers don't collide.
    workspace         = file_manager.create_document_workspace(document_id)
    local_pdf         = workspace / "input.pdf"              # Downloaded PDF lands here
    local_output_base = workspace / "extracted_docs_bounded" # Docling writes output here
    local_output_base.mkdir(parents=True, exist_ok=True)

    try:
        log.info(f"Starting PDF extraction for {document_id}")

        # ------------------------------------------------------------------
        # STEP 1: Download PDF from S3 to local disk
        # ------------------------------------------------------------------
        # Docling requires a local file path — it cannot stream directly from S3.
        if not s3_helper.download_file(s3_key, str(local_pdf)):
            raise Exception(f"Failed to download PDF from s3://{s3_bucket}/{s3_key}")

        # ------------------------------------------------------------------
        # STEP 2: Run Docling extraction (with GPT-4o image/table descriptions)
        # ------------------------------------------------------------------
        # bounded_process_pdf does three things internally:
        #   a) Parses PDF structure: pages, paragraphs, tables, figures
        #   b) Sends images and complex tables to GPT-4o for text descriptions
        #   c) Wraps every element in <!-- BOUNDARY_START:TYPE --> HTML comment markers
        # Returns a metadata dict with per-page breakdown (page count, images, tables).
        log.info("Running bounded Docling extraction...")
        metadata = bounded_process_pdf(
            pdf_path=local_pdf,
            output_base_dir=local_output_base,
            openai_client=openai_client,
        )

        # Docling writes its output under <output_base>/<pdf_stem>/
        # e.g.  extracted_docs_bounded/NCT04368728_Remdesivir_COVID/
        actual_output = local_output_base / local_pdf.stem
        if not actual_output.exists():
            raise Exception("No extraction output directory found")

        # ------------------------------------------------------------------
        # STEP 3: Upload extracted folder to S3
        # ------------------------------------------------------------------
        # upload_directory walks the local folder recursively and mirrors
        # every file under the target S3 prefix, preserving the sub-structure:
        #   pages/, figures/, metadata.json
        s3_output_prefix = f"{config.S3_EXTRACTED_PREFIX}/{document_id}"
        if not s3_helper.upload_directory(str(actual_output), s3_output_prefix):
            raise Exception("Failed to upload extraction results to S3")

        # ------------------------------------------------------------------
        # STEP 4: Compute metrics for monitoring and cost tracking
        # ------------------------------------------------------------------
        duration     = time.time() - start_time
        pages        = metadata.get("pages", [])
        # Count images and tables across all pages — each image = 1 GPT-4o call (~$0.01)
        total_images = sum(len(p.get("images", [])) for p in pages)
        total_tables = sum(len(p.get("tables", [])) for p in pages)

        result = {
            "status"          : "COMPLETED",
            "output_s3_key"   : s3_output_prefix,  # Stage 2 uses this as its input prefix
            "duration_seconds": int(duration),
            "metadata"        : {
                "pages_extracted" : len(pages),
                "images_extracted": total_images,
                "tables_extracted": total_tables,
            },
        }

        log.info(f"Extraction completed for {document_id} in {format_duration(duration)}")
        return result

    except Exception as e:
        # Return a FAILED dict rather than raising — the orchestrator decides
        # whether to retry or permanently mark the document as failed.
        log.error(f"Extraction failed for {document_id}: {e}")
        return {
            "status"          : "FAILED",
            "error"           : str(e),
            "duration_seconds": int(time.time() - start_time),
        }

    finally:
        # Always clean up temp files — even if an exception was raised above.
        # Without this, the worker's disk fills up after processing many documents.
        file_manager.cleanup_document_workspace(document_id)


# ============================================================================
# STAGE 2: SEMANTIC CHUNKING
# ============================================================================
# Purpose : Split per-page markdown into optimally-sized semantic chunks.
#
# Input   : Markdown pages with boundary markers from Stage 1
#             s3://<bucket>/extracted/<doc_id>/pages/page_N.md
# Output  : Single JSON at s3://<bucket>/chunks/<doc_id>_chunks.json
#
# Why chunk at all?
#   - LLMs have context limits; we need pieces small enough to fit in a prompt
#   - Smaller chunks → higher precision in vector search results
#   - Semantic boundaries → each chunk is a complete thought, never mid-sentence
#
# Target sizes (from config):
#   CHUNK_TARGET_SIZE = 1500 chars  (sweet spot for most LLMs)
#   CHUNK_MIN_SIZE    =  500 chars  (avoid tiny, low-signal chunks)
#   CHUNK_MAX_SIZE    = 3000 chars  (hard ceiling to keep search precise)
#
# Cost : FREE — pure CPU, zero API calls
# Time : ~5–10 seconds per document
# ============================================================================

@ray.remote(
    num_cpus=config.CHUNKING_NUM_CPUS,
    memory=config.CHUNKING_MEMORY_MB * 1024 * 1024,
)
def chunk_document(document_id: str, extracted_s3_prefix: str) -> Dict:
    """
    Download Stage-1 output, extract semantic chunks, and upload to S3.

    Args:
        document_id         : Document identifier
        extracted_s3_prefix : S3 prefix from Stage 1 (e.g. "extracted/doc_id")

    Returns:
        On success:
            {
                'status'          : 'COMPLETED',
                'output_s3_key'   : 'chunks/doc_id_chunks.json',
                'duration_seconds': 7,
                'metadata': {
                    'total_chunks'           : 35,  ← final semantic chunks produced
                    'atomic_chunks_extracted': 87   ← raw elements before grouping
                }
            }
        On failure:
            { 'status': 'FAILED', 'error': '<message>', 'duration_seconds': N }
    """
    start_time = time.time()
    log = logging.getLogger(__name__)

    s3_helper    = S3Helper(bucket=config.S3_BUCKET, region=config.AWS_REGION)
    file_manager = LocalFileManager()

    workspace       = file_manager.create_document_workspace(document_id)
    local_pages_dir = workspace / "pages"       # Downloaded .md files land here
    output_file     = workspace / "chunks.json" # Assembled output before S3 upload

    try:
        log.info(f"Starting chunking for {document_id}")

        # ------------------------------------------------------------------
        # STEP 1: Download extracted pages from S3
        # ------------------------------------------------------------------
        # Pull all page_N.md files that Stage 1 produced.
        # These contain text wrapped in <!-- BOUNDARY_START/END:TYPE --> markers
        # that tell the chunker exactly where each element begins and ends.
        pages_prefix = f"{extracted_s3_prefix}/pages/"
        if not s3_helper.download_directory(pages_prefix, str(local_pages_dir)):
            raise Exception(
                f"Failed to download pages from s3://{config.S3_BUCKET}/{pages_prefix}"
            )

        # ------------------------------------------------------------------
        # STEP 2: Extract atomic chunks from boundary markers
        # ------------------------------------------------------------------
        # chunk_directory parses every .md file and extracts one atomic chunk
        # per boundary-delimited element (one paragraph, one table, one heading, etc.).
        # Returns: { "page_1.md": [chunk_dict, ...], "page_2.md": [...], ... }
        log.info("Extracting atomic chunks from boundary markers...")
        raw_results = chunk_directory(local_pages_dir)

        # Flatten the per-file dict into a single ordered list.
        # Preserving order is critical — chunks must stay in document-reading sequence.
        atomic_chunks = []
        for file_chunks in raw_results.values():
            atomic_chunks.extend(file_chunks)

        if not atomic_chunks:
            raise Exception("No atomic chunks extracted from pages")

        # ------------------------------------------------------------------
        # STEP 3: Group atomic chunks into semantic chunks
        # ------------------------------------------------------------------
        # Algorithm:
        #   1. Accumulate atomic chunks into a "current" semantic chunk
        #   2. When current size > TARGET_SIZE AND next element would push
        #      it over MAX_SIZE → flush current chunk and start a new one
        #   3. Never split mid-element (boundary markers prevent this)
        # Result: every chunk is a complete thought — no dangling sentences.
        log.info(f"Grouping {len(atomic_chunks)} atomic chunks into semantic chunks...")
        semantic_chunks = create_semantic_chunks(
            atomic_chunks,
            target_size=config.CHUNK_TARGET_SIZE,  # Aim for ~1500 chars
            min_size=config.CHUNK_MIN_SIZE,         # Never emit a chunk smaller than 500 chars
            max_size=config.CHUNK_MAX_SIZE,         # Hard ceiling at 3000 chars
        )

        # ------------------------------------------------------------------
        # STEP 4: Format chunks for downstream stages
        # ------------------------------------------------------------------
        # format_chunks_for_output strips internal working IDs and ensures
        # every chunk dict has a consistent structure that Stage 3 expects.
        clean_chunks = format_chunks_for_output(semantic_chunks, keep_ids=False)

        # ------------------------------------------------------------------
        # STEP 5: Write output JSON
        # ------------------------------------------------------------------
        # Wrap chunks in a metadata envelope so any downstream stage can
        # answer: "which document? how many chunks? when was this chunked?"
        output_data = {
            "metadata": {
                "document_id"    : document_id,
                "total_chunks"   : len(clean_chunks),
                "chunked_at"     : datetime.utcnow().isoformat() + "Z",
                "chunking_config": {              # Stored for reproducibility / debugging
                    "target_size": config.CHUNK_TARGET_SIZE,
                    "min_size"   : config.CHUNK_MIN_SIZE,
                    "max_size"   : config.CHUNK_MAX_SIZE,
                },
            },
            "chunks": clean_chunks,
        }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        # ------------------------------------------------------------------
        # STEP 6: Upload to S3
        # ------------------------------------------------------------------
        s3_output_key = f"{config.S3_CHUNKS_PREFIX}/{document_id}_chunks.json"
        if not s3_helper.upload_file(str(output_file), s3_output_key):
            raise Exception("Failed to upload chunks to S3")

        duration = time.time() - start_time
        result = {
            "status"          : "COMPLETED",
            "output_s3_key"   : s3_output_key,  # Stage 3 uses this as its input
            "duration_seconds": int(duration),
            "metadata"        : {
                "total_chunks"           : len(clean_chunks),
                "atomic_chunks_extracted": len(atomic_chunks),  # Useful for debugging chunking ratios
            },
        }

        log.info(f"Chunking completed for {document_id} in {format_duration(duration)}")
        return result

    except Exception as e:
        log.error(f"Chunking failed for {document_id}: {e}")
        return {
            "status"          : "FAILED",
            "error"           : str(e),
            "duration_seconds": int(time.time() - start_time),
        }

    finally:
        file_manager.cleanup_document_workspace(document_id)


# ============================================================================
# STAGE 3: METADATA ENRICHMENT
# ============================================================================
# Purpose : Add intelligence to each chunk — PII redaction, NER, key phrases.
#
# Input   : Chunks JSON from Stage 2
# Output  : Enriched chunks JSON at s3://<bucket>/enriched/<doc_id>_enriched.json
#
# Per-chunk enrichment (single GPT-4o-mini call handles all three tasks):
#   1. PII detection + redaction → chunk["content_sanitised"]  (safe to embed)
#   2. Named Entity Recognition  → chunk["metadata"]["entities"]
#   3. Key phrase extraction      → chunk["metadata"]["key_phrases"]
#   Plus: local regex for monetary values ($500, £1000) — free, no API needed.
#
# Why GPT-4o-mini over AWS Comprehend?
#   ✓ One call covers PII + NER + phrases  (Comprehend needs 3 separate calls)
#   ✓ Better accuracy on medical / scientific terminology
#   ✓ Cheaper at low–medium volume: $0.15/1M tokens vs Comprehend unit pricing
#
# Cost : ~$0.001–$0.002 per chunk
# Time : ~20–30 seconds for 35 chunks
# ============================================================================

@ray.remote(
    num_cpus=config.ENRICHMENT_NUM_CPUS,
    memory=config.ENRICHMENT_MEMORY_MB * 1024 * 1024,
)
def enrich_chunks(document_id: str, chunks_s3_key: str) -> Dict:
    """
    Enrich each chunk with PII redaction, NER, and key phrases via GPT-4o-mini.

    Args:
        document_id   : Document identifier
        chunks_s3_key : S3 key from Stage 2 (e.g. "chunks/doc_id_chunks.json")

    Returns:
        On success:
            {
                'status'          : 'COMPLETED',
                'output_s3_key'   : 'enriched/doc_id_enriched.json',
                'duration_seconds': 25,
                'metadata': {
                    'chunks_enriched'   : 35,
                    'pii_redacted_count': 12  ← chunks that contained PII
                }
            }
        On failure:
            { 'status': 'FAILED', 'error': '<message>', 'duration_seconds': N }
    """
    start_time = time.time()
    log = logging.getLogger(__name__)

    # init_openai_client wraps OpenAI() with any project-level defaults from config
    openai_client = init_openai_client(api_key=config.OPENAI_API_KEY)
    s3_helper     = S3Helper(bucket=config.S3_BUCKET, region=config.AWS_REGION)
    file_manager  = LocalFileManager()

    workspace      = file_manager.create_document_workspace(document_id)
    local_chunks   = workspace / "chunks.json"   # Input from Stage 2
    local_enriched = workspace / "enriched.json" # Output written here before S3 upload

    try:
        log.info(f"Starting enrichment for {document_id}")

        # ------------------------------------------------------------------
        # STEP 1: Download chunks JSON from S3
        # ------------------------------------------------------------------
        if not s3_helper.download_file(chunks_s3_key, str(local_chunks)):
            raise Exception(
                f"Failed to download chunks from s3://{config.S3_BUCKET}/{chunks_s3_key}"
            )

        with open(local_chunks, "r", encoding="utf-8") as f:
            data = json.load(f)

        chunks = data.get("chunks", [])
        if not chunks:
            raise Exception("Chunks file is empty or malformed")

        # ------------------------------------------------------------------
        # STEP 2: Enrich every chunk via GPT-4o-mini
        # ------------------------------------------------------------------
        # enrich_chunk makes ONE API call per chunk that:
        #   a) Detects + redacts PII     → result in chunk["content_sanitised"]
        #   b) Extracts named entities   → chunk["metadata"]["entities"]
        #   c) Extracts key phrases      → chunk["metadata"]["key_phrases"]
        #   d) Extracts monetary values  → chunk["metadata"]["monetary_values"] (local regex, free)
        #
        # IMPORTANT: Stage 4 embeds content_sanitised, not original content.
        # This ensures PII never reaches Pinecone vector metadata.
        log.info(f"Enriching {len(chunks)} chunks via gpt-4o-mini...")
        enriched_chunks = [
            enrich_chunk(chunk, openai_client, model="gpt-4o-mini")
            for chunk in chunks
        ]

        # ------------------------------------------------------------------
        # STEP 3: Save enriched data to disk
        # ------------------------------------------------------------------
        # Pass through the original metadata envelope unchanged so downstream
        # stages still have access to document_id, total_chunks, chunking config, etc.
        enriched_data = {
            "metadata": data.get("metadata", {}),
            "chunks"  : enriched_chunks,
        }
        with open(local_enriched, "w", encoding="utf-8") as f:
            json.dump(enriched_data, f, indent=2, ensure_ascii=False)

        # ------------------------------------------------------------------
        # STEP 4: Upload enriched JSON to S3
        # ------------------------------------------------------------------
        s3_output_key = f"{config.S3_ENRICHED_PREFIX}/{document_id}_enriched.json"
        if not s3_helper.upload_file(str(local_enriched), s3_output_key):
            raise Exception("Failed to upload enriched chunks to S3")

        # ------------------------------------------------------------------
        # STEP 5: Compute PII metric for privacy / compliance auditing
        # ------------------------------------------------------------------
        duration  = time.time() - start_time
        # Count chunks where enrich_chunk flagged at least one PII redaction.
        # Surfacing this in the result helps monitor privacy protection coverage.
        pii_count = sum(
            1 for c in enriched_chunks
            if c.get("metadata", {}).get("pii_redacted", False)
        )

        result = {
            "status"          : "COMPLETED",
            "output_s3_key"   : s3_output_key,  # Stage 4 uses this as its input
            "duration_seconds": int(duration),
            "metadata"        : {
                "chunks_enriched"   : len(enriched_chunks),
                "pii_redacted_count": pii_count,
            },
        }

        log.info(f"Enrichment completed for {document_id} in {format_duration(duration)}")
        return result

    except Exception as e:
        log.error(f"Enrichment failed for {document_id}: {e}")
        return {
            "status"          : "FAILED",
            "error"           : str(e),
            "duration_seconds": int(time.time() - start_time),
        }

    finally:
        file_manager.cleanup_document_workspace(document_id)


# ============================================================================
# STAGE 4: EMBEDDING GENERATION
# ============================================================================
# Purpose : Convert each chunk's sanitised text into a dense vector.
#
# Input   : Enriched chunks JSON from Stage 3
# Output  : Embeddings JSON at s3://<bucket>/embeddings/<doc_id>_embeddings.json
#           Each chunk gains an "embedding": [float, ...] field (1536 dimensions)
#
# Model   : text-embedding-ada-002
#   - 1536 dimensions  (Pinecone's industry-standard default)
#   - Cost: $0.0001 per 1K tokens  (~$0.003–$0.01 per typical 35-chunk document)
#   - Best price/performance for RAG as of 2024
#
# Built-in safeguards inside generate_embeddings():
#   - Exponential-backoff retry on 429 rate-limit errors  (4s → 16s → 64s)
#   - Batch processing  (default 100 chunks/batch; reduces API round-trips)
#   - Token counting    (returned alongside chunks for precise cost accounting)
#
# Cost : ~$0.003–$0.01 per document
# Time : ~15–25 seconds for 35 chunks
# ============================================================================

@ray.remote(
    num_cpus=config.EMBEDDING_NUM_CPUS,
    memory=config.EMBEDDING_MEMORY_MB * 1024 * 1024,
)
def generate_embeddings_task(document_id: str, enriched_s3_key: str) -> Dict:
    """
    Generate OpenAI embeddings for enriched chunks and upload to S3.

    Args:
        document_id      : Document identifier
        enriched_s3_key  : S3 key from Stage 3 (e.g. "enriched/doc_id_enriched.json")

    Returns:
        On success:
            {
                'status'          : 'COMPLETED',
                'output_s3_key'   : 'embeddings/doc_id_embeddings.json',
                'duration_seconds': 22,
                'metadata': {
                    'tokens_processed'    : 8543,
                    'openai_cost_usd'     : 0.0008543,  ← actual spend logged for cost control
                    'embeddings_generated': 35
                }
            }
        On failure:
            { 'status': 'FAILED', 'error': '<message>', 'duration_seconds': N }
    """
    start_time = time.time()
    log = logging.getLogger(__name__)

    # init_embedding_client returns an OpenAI client configured for the embeddings API.
    # Aliased on import to avoid collision with Stage 3's init_openai_client.
    client       = init_embedding_client()
    s3_helper    = S3Helper(bucket=config.S3_BUCKET, region=config.AWS_REGION)
    file_manager = LocalFileManager()

    workspace      = file_manager.create_document_workspace(document_id)
    local_enriched = workspace / "enriched.json"  # Input from Stage 3

    try:
        log.info(f"Starting embedding generation for {document_id}")

        # ------------------------------------------------------------------
        # STEP 1: Download enriched chunks from S3
        # ------------------------------------------------------------------
        if not s3_helper.download_file(enriched_s3_key, str(local_enriched)):
            raise Exception(
                f"Failed to download enriched chunks from "
                f"s3://{config.S3_BUCKET}/{enriched_s3_key}"
            )

        # ------------------------------------------------------------------
        # STEP 2: Parse JSON → list of chunk dicts
        # ------------------------------------------------------------------
        # load_embedding_chunks reads the JSON file and returns just the
        # "chunks" array, stripping the outer metadata envelope.
        chunks = load_embedding_chunks(str(local_enriched))

        # ------------------------------------------------------------------
        # STEP 3: Generate embeddings in batches
        # ------------------------------------------------------------------
        # generate_embeddings:
        #   - Groups chunks into batches of EMBEDDING_BATCH_SIZE
        #   - Calls OpenAI API for each batch (with retry on rate limits)
        #   - Attaches each 1536-dim vector to its chunk as chunk["embedding"]
        #   - Returns (enriched_chunks_with_embeddings, total_tokens_used)
        log.info(f"Embedding {len(chunks)} chunks | model={config.OPENAI_MODEL}")
        enriched_chunks, total_tokens = generate_embeddings(
            chunks=chunks,
            client=client,
            model=config.OPENAI_MODEL,           # "text-embedding-ada-002"
            dimensions=config.OPENAI_DIMENSIONS,  # 1536
            batch_size=config.EMBEDDING_BATCH_SIZE,  # 100 chunks per API call
        )

        # ------------------------------------------------------------------
        # STEP 4: Save results with cost metadata
        # ------------------------------------------------------------------
        # save_embedding_results:
        #   - Calculates $ cost from token count (rate: $0.0001 / 1K tokens)
        #   - Adds a "cost_tracking" block to the metadata envelope
        #   - Writes everything to a JSON file and returns its path
        output_path = save_embedding_results(
            chunks=enriched_chunks,
            input_file=str(local_enriched),    # Used to copy the original metadata envelope
            model=config.OPENAI_MODEL,
            dimensions=config.OPENAI_DIMENSIONS,
            total_tokens=total_tokens,
        )

        # ------------------------------------------------------------------
        # STEP 5: Upload to S3
        # ------------------------------------------------------------------
        s3_output_key = (
            f"{config.S3_EMBEDDINGS_PREFIX}/{document_id}_embeddings.json"
        )
        if not s3_helper.upload_file(output_path, s3_output_key):
            raise Exception("Failed to upload embeddings to S3")

        # ------------------------------------------------------------------
        # STEP 6: Re-read saved file to surface cost_tracking in the result
        # ------------------------------------------------------------------
        # save_embedding_results computes the precise cost inside the file;
        # reading it back is the cleanest way to retrieve that value.
        with open(output_path, "r") as f:
            saved_data = json.load(f)
        cost_info = saved_data.get("metadata", {}).get("cost_tracking", {})

        duration = time.time() - start_time
        result = {
            "status"          : "COMPLETED",
            "output_s3_key"   : s3_output_key,  # Stage 5 uses this as its input
            "duration_seconds": int(duration),
            "metadata"        : {
                # Prefer cost_tracking values — more precise than raw total_tokens
                "tokens_processed"    : cost_info.get("total_tokens", total_tokens),
                "openai_cost_usd"     : cost_info.get("total_cost_usd", 0.0),
                "embeddings_generated": len(enriched_chunks),
            },
        }

        log.info(f"Embedding completed for {document_id} in {format_duration(duration)}")
        return result

    except Exception as e:
        log.error(f"Embedding failed for {document_id}: {e}")
        return {
            "status"          : "FAILED",
            "error"           : str(e),
            "duration_seconds": int(time.time() - start_time),
        }

    finally:
        file_manager.cleanup_document_workspace(document_id)


# ============================================================================
# STAGE 5: VECTOR LOADING
# ============================================================================
# Purpose : Upsert all vectors into Pinecone, making the document searchable.
#
# Input   : Embeddings JSON from Stage 4
# Output  : Vectors live in Pinecone — no S3 output (Pinecone IS the output)
#
# Key behaviours:
#   - Auto-detects vector dimensions from the first embedding  (no manual config)
#   - Creates the index if it doesn't exist; connects if it does
#   - Deterministic MD5 IDs → same document re-run = same IDs = idempotent upsert
#   - Flattens nested metadata to flat key-value pairs  (Pinecone requirement)
#   - Uploads in configurable batches  (default 100 vectors per batch)
#   - Post-upload verification  (count check; mismatch warnings are normal due to async stats)
#
# Cost : Pinecone free tier covers 1M vectors / 1 pod
# Time : ~10–15 seconds for 35 vectors
# ============================================================================

@ray.remote(
    num_cpus=config.LOADING_NUM_CPUS,
    memory=config.LOADING_MEMORY_MB * 1024 * 1024,
)
def load_vectors(document_id: str, embeddings_s3_key: str) -> Dict:
    """
    Download embeddings from S3 and upsert into Pinecone.

    Args:
        document_id       : Document identifier
        embeddings_s3_key : S3 key from Stage 4 (e.g. "embeddings/doc_id_embeddings.json")

    Returns:
        On success:
            {
                'status'          : 'COMPLETED',
                'duration_seconds': 12,
                'metadata': {
                    'vectors_uploaded'  : 35,
                    'pinecone_index'    : 'clinical-trials-index',
                    'pinecone_namespace': 'clinical-trials',
                    'dimensions'        : 1536
                }
            }
        On failure:
            { 'status': 'FAILED', 'error': '<message>', 'duration_seconds': N }
    """
    start_time = time.time()
    log = logging.getLogger(__name__)

    # init_pinecone returns an authenticated Pinecone client
    pc           = init_pinecone(api_key=config.PINECONE_API_KEY)
    s3_helper    = S3Helper(bucket=config.S3_BUCKET, region=config.AWS_REGION)
    file_manager = LocalFileManager()

    workspace        = file_manager.create_document_workspace(document_id)
    local_embeddings = workspace / "embeddings.json"  # Input from Stage 4

    try:
        log.info(f"Starting vector loading for {document_id}")

        # ------------------------------------------------------------------
        # STEP 1: Download embeddings JSON from S3
        # ------------------------------------------------------------------
        if not s3_helper.download_file(embeddings_s3_key, str(local_embeddings)):
            raise Exception(
                f"Failed to download embeddings from "
                f"s3://{config.S3_BUCKET}/{embeddings_s3_key}"
            )

        # ------------------------------------------------------------------
        # STEP 2: Load JSON and auto-detect vector dimensions
        # ------------------------------------------------------------------
        # pinecone_load_json reads the file, inspects len(chunks[0]["embedding"]),
        # and returns: { "chunks": [...], "dimensions": 1536 }
        # Auto-detection means changing the embedding model auto-adjusts the index.
        data = pinecone_load_json(str(local_embeddings))

        # ------------------------------------------------------------------
        # STEP 3: Create or connect to the Pinecone index
        # ------------------------------------------------------------------
        # create_or_get_index behaviour:
        #   - Index missing  → creates it with cosine metric + waits for READY (~60s)
        #   - Index exists   → verifies dimensions match, then returns connection
        # Keeping cloud + region the same as S3/ECS minimises cross-region data transfer costs.
        index = create_or_get_index(
            pc=pc,
            index_name=config.PINECONE_INDEX,
            dimensions=data["dimensions"],  # Auto-detected above
            metric=config.PINECONE_METRIC,  # "cosine" — best metric for text similarity
            cloud="aws",
            region=config.AWS_REGION,       # Same region as S3 and ECS
        )

        # ------------------------------------------------------------------
        # STEP 4: Prepare vectors for Pinecone's required format
        # ------------------------------------------------------------------
        # prepare_vectors transforms each chunk into:
        #   { "id": "<md5_hash>", "values": [...1536 floats...], "metadata": { flat k-v } }
        #
        # Metadata flattening is required — Pinecone only accepts scalar values:
        #   Before: { "key_phrases": ["trial", "efficacy"] }
        #   After : { "key_phrases": "trial, efficacy" }
        vectors = prepare_vectors(data["chunks"], namespace=config.PINECONE_NAMESPACE)
        if not vectors:
            raise Exception("No vectors prepared from embeddings file")

        # ------------------------------------------------------------------
        # STEP 5: Upsert vectors in batches
        # ------------------------------------------------------------------
        # "Upsert" = update if ID already exists, insert if it doesn't.
        # Because IDs are MD5 hashes of content, re-running the pipeline for
        # the same document is safe — no duplicates will be created.
        log.info(
            f"Upserting {len(vectors)} vectors | "
            f"index={config.PINECONE_INDEX} "
            f"namespace={config.PINECONE_NAMESPACE}"
        )
        upsert_vectors(
            index=index,
            vectors=vectors,
            namespace=config.PINECONE_NAMESPACE,
            batch_size=config.PINECONE_BATCH_SIZE,  # 100 vectors per batch by default
        )

        # ------------------------------------------------------------------
        # STEP 6: Verify the upload
        # ------------------------------------------------------------------
        # Brief sleep because Pinecone's index stats are eventually consistent:
        # vectors are immediately queryable but the reported count takes a few
        # seconds to update. A count mismatch at this point is usually just lag.
        time.sleep(2)
        pinecone_verify(index, len(vectors), config.PINECONE_NAMESPACE)

        duration = time.time() - start_time
        result = {
            "status"          : "COMPLETED",
            "duration_seconds": int(duration),
            "metadata"        : {
                "vectors_uploaded"  : len(vectors),
                "pinecone_index"    : config.PINECONE_INDEX,
                "pinecone_namespace": config.PINECONE_NAMESPACE,
                "dimensions"        : data["dimensions"],
            },
        }

        log.info(f"Vector loading completed for {document_id} in {format_duration(duration)}")
        return result

    except Exception as e:
        log.error(f"Vector loading failed for {document_id}: {e}")
        return {
            "status"          : "FAILED",
            "error"           : str(e),
            "duration_seconds": int(time.time() - start_time),
        }

    finally:
        file_manager.cleanup_document_workspace(document_id)