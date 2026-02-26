"""
ray_orchestrator.py

Main Ray Pipeline Orchestrator — ECS Production Ready
Coordinates all 5 pipeline stages and manages document processing flow.

================================================================================
                            ARCHITECTURE
================================================================================

The orchestrator is a POLLING LOOP that runs forever:

┌─────────────────────────────────────────────────────────┐
│                   ORCHESTRATOR LOOP                      │
│                                                          │
│  1. Query DynamoDB GSI for PENDING documents            │
│  2. For each document:                                  │
│     - Atomically claim it (PENDING → IN_PROGRESS)       │
│       using a conditional DynamoDB update               │
│     - Run all 5 Ray stages in sequence                  │
│     - Mark COMPLETED or FAILED                          │
│  3. Sleep with interrupt-awareness (short loop)         │
│  4. Repeat until shutdown signal                        │
│                                                          │
└─────────────────────────────────────────────────────────┘

PIPELINE STAGES (sequential; each stage feeds its S3 key to the next):
  Stage 1: extract_pdf              → PDF → Markdown pages with boundary markers
  Stage 2: chunk_document           → Pages → Semantic chunks JSON
  Stage 3: enrich_chunks            → Chunks → Enriched JSON (PII + NER + phrases)
  Stage 4: generate_embeddings_task → Enriched → Vectors JSON (1536-dim embeddings)
  Stage 5: load_vectors             → Vectors → Pinecone (document now searchable!)

================================================================================
                        ECS-SPECIFIC CONSIDERATIONS
================================================================================

1. IAM / Credentials
   - boto3 auto-discovers credentials from the ECS metadata endpoint.
   - Do NOT set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in env vars.
   - The ECS Task Role must allow:
       s3:GetObject, s3:PutObject, s3:HeadBucket, s3:ListBucket
       dynamodb:Query, dynamodb:UpdateItem, dynamodb:PutItem, dynamodb:DescribeTable
       secretsmanager:GetSecretValue   (if config reads from Secrets Manager)

2. SIGTERM / Graceful Shutdown
   - ECS sends SIGTERM → waits stopTimeout (default 30s) → sends SIGKILL.
   - time.sleep(POLLING_INTERVAL) is NOT interruptible — if POLLING_INTERVAL
     is 60s the container is killed before the signal handler can exit cleanly.
   - FIX: sleep in 1-second chunks, checking shutdown_requested each iteration.
   - Also check shutdown_requested between every ray.get() call so a
     long-running pipeline can be interrupted mid-stage.

3. Ray Address
   - In ECS, orchestrator and Ray head node run in separate tasks.
   - RAY_ADDRESS must be the private IP or service-discovery DNS of the
     Ray head task — NOT "localhost" or "auto".
   - Example: RAY_ADDRESS = "ray://ray-head.internal:10001"

4. /tmp Storage (ECS Fargate)
   - ECS Fargate default ephemeral storage = 20 GB.
   - Large PDFs + Docling output can easily exceed this under concurrent load.
   - FIX: Set ephemeralStorage.sizeInGiB in the ECS task definition (up to 200 GB).
   - The finally: cleanup_document_workspace() calls in ray_tasks.py are critical
     for reclaiming space after each document.

5. Multi-Instance Race Condition
   - If two orchestrator ECS tasks run simultaneously (rolling deploy, HA),
     both can query the same PENDING document and process it twice.
   - FIX: Use a DynamoDB conditional update to atomically claim a document.
     Only succeeds if status is still PENDING at write time.
     If it fails with ConditionalCheckFailedException, another instance already
     claimed it — skip it silently.

6. Blocking ray.get() vs SIGTERM
   - ray.get() is blocking. Five sequential ray.get() calls per document means
     the orchestrator cannot respond to SIGTERM while a document is in-flight.
   - FIX: Check shutdown_requested between every stage so the pipeline aborts
     gracefully mid-document if a shutdown signal arrives.

Author: Prudhvi
Organization: Thoughtworks
"""

import ray
import time
import signal
import sys
import logging
import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from boto3.dynamodb.conditions import Key, Attr

from config import config  # Central config — reads env vars / Secrets Manager

# NOTE: ray_tasks are imported INSIDE process_document() after ray.init() runs.
# Importing at module level would deserialise @ray.remote decorators before Ray
# is ready, causing serialisation errors.

# ============================================================================
# LOGGING SETUP
# ============================================================================
# Configure once at module load — all loggers inherit this format.
# LOG_LEVEL is driven by env var via config so it can change per environment
# without a code change (e.g. DEBUG in dev, WARNING in prod).
# ============================================================================

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

# Suppress noisy low-level AWS SDK logs — we only want our own application logs
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ============================================================================
# GLOBAL SHUTDOWN FLAG
# ============================================================================
# Set to True by the signal handler; checked inside the main polling loop
# and between every ray.get() call.
# A module-level bool is the standard Python pattern for signal → loop
# coordination because signal handlers cannot use threading primitives.
# ============================================================================

shutdown_requested = False


# ============================================================================
# SIGNAL HANDLERS
# ============================================================================

def signal_handler(signum, frame):
    """
    Handle SIGTERM (ECS stop) and SIGINT (Ctrl+C) for graceful shutdown.

    ECS stop sequence:
      1. ECS sends SIGTERM to PID 1 in the container
      2. Waits stopTimeout seconds (default 30s, configurable up to 120s)
      3. Sends SIGKILL if process hasn't exited yet

    This handler sets shutdown_requested=True so the main loop and each
    ray.get() check-point can exit cleanly before the SIGKILL arrives.

    IMPORTANT: The main sleep must be interruptible (1-second chunks) and
    ray.get() calls must be guarded — otherwise the 30s window is wasted.
    """
    global shutdown_requested

    logger.info("=" * 70)
    logger.info(f"SHUTDOWN SIGNAL RECEIVED: signal {signum}")
    logger.info("Setting shutdown flag — will exit at next safe checkpoint")
    logger.info("=" * 70)

    shutdown_requested = True  # Main loop and stage loop check this flag


def interruptible_sleep(seconds: int):
    """
    Sleep for `seconds` total, but wake every 1 second to check for shutdown.

    Why not time.sleep(POLLING_INTERVAL)?
    If POLLING_INTERVAL = 60s and ECS stopTimeout = 30s, the container is
    killed mid-sleep before we can exit cleanly — losing audit trail updates
    and potentially leaving documents stuck in IN_PROGRESS forever.

    This function guarantees the orchestrator responds to SIGTERM within ~1 second.
    """
    for _ in range(seconds):
        if shutdown_requested:
            return  # Exit immediately if shutdown was requested during sleep
        time.sleep(1)


# ============================================================================
# DYNAMODB OPERATIONS
# ============================================================================

MAX_RETRY_ATTEMPTS = 3          # Documents failing more than this stay FAILED permanently
RETRY_AFTER_MINUTES = 10       # Wait 10 minutes before retrying a FAILED document


def retry_failed_documents():
    """
    Reset recently-failed documents back to PENDING so they are retried.

    Only resets documents that:
      1. Have status = FAILED
      2. Have retry_count < MAX_RETRY_ATTEMPTS (prevents infinite retry loops)
      3. Failed within the last RETRY_AFTER_MINUTES minutes

    Transient failures (network blips, API timeouts, brief OOM) are retried.
    Permanent failures (corrupt PDF, invalid config) stop after MAX_RETRY_ATTEMPTS.
    """
    try:
        dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
        table    = dynamodb.Table(config.DYNAMODB_CONTROL_TABLE)

        # Query the GSI for FAILED documents
        response = table.query(
            IndexName="status-updated-index",
            KeyConditionExpression=Key("status").eq("FAILED"),
            Limit=50,
        )

        items = response.get("Items", [])
        if not items:
            return

        now = datetime.now(tz=__import__('datetime').timezone.utc)
        retry_cutoff = now - timedelta(minutes=RETRY_AFTER_MINUTES)
        reset_count = 0

        for item in items:
            retry_count = int(item.get("retry_count", 0))
            if retry_count >= MAX_RETRY_ATTEMPTS:
                continue  # Exhausted retries — leave permanently FAILED

            # Parse the updated_at timestamp
            updated_str = item.get("updated_at", "")
            try:
                updated_at = datetime.fromisoformat(updated_str.rstrip("Z")).replace(
                    tzinfo=__import__('datetime').timezone.utc
                )
            except (ValueError, AttributeError):
                continue

            if updated_at > retry_cutoff:
                continue  # Failed too recently — wait before retrying

            # Reset to PENDING with incremented retry_count
            try:
                timestamp = datetime.now(tz=__import__('datetime').timezone.utc).isoformat()
                table.update_item(
                    Key={
                        "document_id"       : item["document_id"],
                        "processing_version": item["processing_version"],
                    },
                    UpdateExpression=(
                        "SET #status = :pending, updated_at = :ts, "
                        "retry_count = :rc, current_stage = :stage, #msg = :msg"
                    ),
                    ConditionExpression=Attr("status").eq("FAILED"),
                    ExpressionAttributeNames={"#status": "status", "#msg": "message"},
                    ExpressionAttributeValues={
                        ":pending": "PENDING",
                        ":ts"     : timestamp,
                        ":rc"     : retry_count + 1,
                        ":stage"  : "RETRY_QUEUED",
                        ":msg"    : f"Auto-retry attempt {retry_count + 1} of {MAX_RETRY_ATTEMPTS}",
                    },
                )
                reset_count += 1
                logger.info(
                    f"  ↻ Queued retry {retry_count + 1}/{MAX_RETRY_ATTEMPTS} "                    f"for {item['document_id']}"
                )
            except ClientError as e:
                if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    logger.error(f"Error resetting {item['document_id']}: {e}")

        if reset_count:
            logger.info(f"✓ Reset {reset_count} failed documents to PENDING for retry")

    except Exception as e:
        logger.error(f"✗ Error in retry_failed_documents: {e}", exc_info=True)


def query_pending_documents() -> List[Dict]:
    """
    Query the DynamoDB GSI for documents in PENDING status, oldest-first (FIFO).

    Uses the 'status-updated-index' GSI:
      - HASH key:  status      → filters to 'PENDING' only
      - RANGE key: updated_at  → ScanIndexForward=True gives oldest first

    FIFO ordering ensures documents are processed in submission order — fair
    and prevents newer documents from jumping ahead of older ones.

    Returns:
        List of document dicts (up to MAX_DOCUMENTS_PER_POLL).
        Returns empty list on any error — orchestrator retries next poll.
    """
    try:
        # boto3.resource provides a higher-level ORM-style interface;
        # cleaner than boto3.client for simple query / get / put operations.
        dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
        table    = dynamodb.Table(config.DYNAMODB_CONTROL_TABLE)

        response = table.query(
            IndexName="status-updated-index",
            KeyConditionExpression=Key("status").eq("PENDING"),
            Limit=config.MAX_DOCUMENTS_PER_POLL,  # Cap to avoid overwhelming the Ray cluster
            ScanIndexForward=True,                 # True = ascending by updated_at = oldest first
        )

        documents = response.get("Items", [])

        if documents:
            logger.info(f"✓ Found {len(documents)} pending documents")
            # Log first 3 at DEBUG level — noisy in production, useful in development
            for i, doc in enumerate(documents[:3]):
                logger.debug(
                    f"  [{i+1}] {doc['document_id']} "
                    f"(created {doc.get('created_at', 'unknown')})"
                )
            if len(documents) > 3:
                logger.debug(f"  ... and {len(documents) - 3} more")

        return documents

    except Exception as e:
        # Swallow the exception — a DynamoDB hiccup must not crash the orchestrator.
        # The GSI may have a brief outage; the next poll cycle will likely succeed.
        logger.error(f"✗ Error querying DynamoDB: {e}", exc_info=True)
        logger.error("  Returning empty list — will retry next poll")
        return []


def claim_document(document_id: str, processing_version: str) -> bool:
    """
    Atomically transition a document from PENDING → IN_PROGRESS using a
    DynamoDB conditional update.

    WHY THIS MATTERS (ECS multi-instance race condition):
    Without this, two orchestrator instances can both see the same PENDING
    document, both call process_document(), and both submit it to Ray.
    Result: double processing, duplicate Pinecone vectors, double API costs.

    HOW IT WORKS:
    DynamoDB's ConditionExpression makes the update atomic server-side:
      - If status = 'PENDING' at write time → update succeeds → we own the doc
      - If status ≠ 'PENDING' → ConditionalCheckFailedException → another
        instance already claimed it → we skip it safely

    This is the standard "optimistic locking" pattern for distributed systems.

    Args:
        document_id        : Document to claim
        processing_version : Pipeline version key (part of the DynamoDB primary key)

    Returns:
        True  if we successfully claimed the document
        False if another instance already claimed it (or any other error)
    """
    try:
        dynamodb      = boto3.resource("dynamodb", region_name=config.AWS_REGION)
        control_table = dynamodb.Table(config.DYNAMODB_CONTROL_TABLE)
        audit_table   = dynamodb.Table(config.DYNAMODB_AUDIT_TABLE)
        timestamp     = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        # Conditional update: only proceeds if status is still 'PENDING'.
        # If another instance claimed it first, this raises ConditionalCheckFailedException.
        control_table.update_item(
            Key={
                "document_id"       : document_id,
                "processing_version": processing_version,
            },
            UpdateExpression=(
                "SET #status = :in_progress, "
                "updated_at = :ts, "
                "current_stage = :stage, "
                "#msg = :msg"
            ),
            ConditionExpression=Attr("status").eq("PENDING"),  # The atomic guard
            ExpressionAttributeNames={
                "#status": "status",  # 'status' is a DynamoDB reserved word
                "#msg"   : "message",
            },
            ExpressionAttributeValues={
                ":in_progress": "IN_PROGRESS",
                ":ts"         : timestamp,
                ":stage"      : "SUBMITTED",
                ":msg"        : "Orchestrator claimed document",
            },
        )

        # Append an audit record for the claim event
        audit_table.put_item(
            Item={
                "document_id": document_id,
                "timestamp"  : timestamp,
                "event_type" : "STATUS_CHANGE",
                "status"     : "IN_PROGRESS",
                "message"    : "Orchestrator claimed document",
                "metadata"   : {
                    "processing_version": processing_version,
                    "current_stage"     : "SUBMITTED",
                },
                # TTL: auto-delete audit records after 180 days
                "ttl": int((datetime.now(tz=timezone.utc) + timedelta(days=180)).timestamp()),
            }
        )

        logger.debug(f"✓ Claimed document: {document_id}")
        return True  # We own this document — safe to process

    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Another orchestrator instance beat us to it — this is expected
            # in multi-instance deployments. Skip silently, not an error.
            logger.info(f"  Document {document_id} already claimed by another instance — skipping")
        else:
            # Unexpected DynamoDB error — log it but don't crash
            logger.error(f"✗ Error claiming document {document_id}: {e}", exc_info=True)
        return False  # We do NOT own this document — do not process


def update_document_status(
    document_id: str,
    status: str,
    processing_version: str = None,
    message: str = "",
    current_stage: str = None,
):
    """
    Update document status in both the Control table and the Audit table.

    Why two tables?
      Control table (1 record per document):
        - Stores the latest known state — fast O(1) single-key lookups
        - Used by: orchestrator, monitoring dashboards, retry jobs
      Audit table (append-only, many records per document):
        - Full immutable history of every status transition
        - Used by: compliance reviews, incident debugging, SLA reporting

    Note: claim_document() handles the PENDING → IN_PROGRESS transition
    with a conditional update. This function handles all other transitions
    (IN_PROGRESS → COMPLETED, IN_PROGRESS → FAILED, stage updates).

    Errors are logged but not raised — a failed status update is non-fatal;
    the pipeline processing continues and the next update may succeed.

    Args:
        document_id        : Unique document identifier
        status             : New status ('IN_PROGRESS' | 'COMPLETED' | 'FAILED')
        processing_version : Pipeline version — defaults to config.PROCESSING_VERSION
        message            : Human-readable description of the transition
        current_stage      : Which stage is active (e.g. 'STAGE_2_CHUNKING')
    """
    if processing_version is None:
        processing_version = config.PROCESSING_VERSION

    try:
        dynamodb      = boto3.resource("dynamodb", region_name=config.AWS_REGION)
        control_table = dynamodb.Table(config.DYNAMODB_CONTROL_TABLE)
        audit_table   = dynamodb.Table(config.DYNAMODB_AUDIT_TABLE)

        # ISO 8601 with explicit 'Z' suffix → unambiguous UTC timestamp
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        # Build UpdateExpression dynamically — only include optional fields
        # when values are actually provided to keep records clean.
        update_expr = "SET #status = :status, updated_at = :ts"
        expr_names  = {"#status": "status"}  # Alias because 'status' is reserved
        expr_values = {":status": status, ":ts": timestamp}

        if message:
            update_expr += ", #msg = :msg"
            expr_names["#msg"] = "message"
            expr_values[":msg"] = message

        if current_stage:
            update_expr += ", current_stage = :stage"
            expr_values[":stage"] = current_stage

        # Unconditional update — claim_document() already owns the document
        control_table.update_item(
            Key={
                "document_id"       : document_id,
                "processing_version": processing_version,
            },
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )

        logger.debug(f"✓ Updated control record: {document_id} → {status}")

        # Append an audit record — put_item always inserts because timestamp
        # is part of the sort key, making every status change a unique record.
        audit_table.put_item(
            Item={
                "document_id": document_id,
                "timestamp"  : timestamp,
                "event_type" : "STATUS_CHANGE",
                "status"     : status,
                "message"    : message or f"Status changed to {status}",
                "metadata"   : {
                    "processing_version": processing_version,
                    "current_stage"     : current_stage or "unknown",
                },
                "ttl": int((datetime.now(tz=timezone.utc) + timedelta(days=180)).timestamp()),
            }
        )

        logger.debug(f"✓ Created audit record for {document_id}")

    except Exception as e:
        # Non-fatal — log and continue. A DynamoDB write failure should not
        # stop document processing; the pipeline result matters more.
        logger.error(f"✗ Error updating document status: {e}", exc_info=True)
        logger.error(f"  Document: {document_id}, Status: {status}")


# ============================================================================
# DOCUMENT PROCESSING — FULL 5-STAGE PIPELINE
# ============================================================================

def process_document(document: Dict):
    """
    Drive a single document through all 5 Ray pipeline stages sequentially.

    Each stage is submitted to a Ray worker via .remote(), then ray.get()
    blocks until that worker finishes and returns its result dict.
    The output S3 key from each stage is passed as input to the next stage.

    Shutdown-awareness:
      shutdown_requested is checked between every stage. If ECS sends SIGTERM
      while a document is in-flight, the pipeline aborts after the current
      stage completes (within ~60s worst case) rather than being killed mid-write.

    Race condition prevention:
      claim_document() uses a DynamoDB conditional update to atomically take
      ownership. If it returns False, another orchestrator instance already
      claimed this document — we skip it without processing.

    Args:
        document : DynamoDB record dict. Required keys:
                   document_id, s3_bucket, s3_key, processing_version
    """
    # Import here (not at module level) — @ray.remote decorators must be
    # registered after ray.init() is called on the driver process.
    from ray_tasks import (
        extract_pdf,
        chunk_document,
        enrich_chunks,
        generate_embeddings_task,
        load_vectors,
    )

    document_id        = document["document_id"]
    s3_bucket          = document["s3_bucket"]
    s3_key             = document["s3_key"]
    processing_version = document.get("processing_version", config.PROCESSING_VERSION)

    logger.info("=" * 70)
    logger.info(f"PROCESSING DOCUMENT: {document_id}")
    logger.info(f"  S3 Location: s3://{s3_bucket}/{s3_key}")
    logger.info(f"  Version    : {processing_version}")
    logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Atomically claim the document before touching it
    # ------------------------------------------------------------------
    # If this returns False, another orchestrator instance already claimed it.
    # Skipping prevents double processing and duplicate Pinecone vectors.
    if not claim_document(document_id, processing_version):
        logger.info(f"  Skipping {document_id} — already claimed by another instance")
        return

    try:
        # ------------------------------------------------------------------
        # STAGE 1: PDF EXTRACTION
        # ------------------------------------------------------------------
        logger.info(f"[{document_id}] Stage 1/5: PDF Extraction")
        update_document_status(
            document_id, "IN_PROGRESS",
            processing_version=processing_version,
            current_stage="STAGE_1_EXTRACTION",
        )

        # .remote() submits the task to a Ray worker (non-blocking).
        # ray.get() blocks HERE until the worker returns the result dict.
        # We must block sequentially — each stage needs the previous stage's
        # output S3 key before it can start.
        stage1 = ray.get(extract_pdf.remote(document_id, s3_bucket, s3_key))

        # Check shutdown flag between stages — allows clean mid-pipeline abort
        # if ECS sends SIGTERM while we're waiting for a long stage.
        if shutdown_requested:
            raise Exception("Shutdown requested — aborting pipeline after Stage 1")

        if stage1["status"] != "COMPLETED":
            raise Exception(f"Stage 1 failed: {stage1.get('error', 'unknown error')}")

        extracted_prefix = stage1["output_s3_key"]  # Passed to Stage 2 as input
        logger.info(
            f"[{document_id}] Stage 1 done — "
            f"{stage1['metadata']['pages_extracted']} pages, "
            f"{stage1['metadata']['images_extracted']} images extracted"
        )

        # ------------------------------------------------------------------
        # STAGE 2: SEMANTIC CHUNKING
        # ------------------------------------------------------------------
        logger.info(f"[{document_id}] Stage 2/5: Semantic Chunking")
        update_document_status(
            document_id, "IN_PROGRESS",
            processing_version=processing_version,
            current_stage="STAGE_2_CHUNKING",
        )

        stage2 = ray.get(chunk_document.remote(document_id, extracted_prefix))

        if shutdown_requested:
            raise Exception("Shutdown requested — aborting pipeline after Stage 2")

        if stage2["status"] != "COMPLETED":
            raise Exception(f"Stage 2 failed: {stage2.get('error', 'unknown error')}")

        chunks_key = stage2["output_s3_key"]  # S3 key of the chunks JSON for Stage 3
        logger.info(
            f"[{document_id}] Stage 2 done — "
            f"{stage2['metadata']['total_chunks']} semantic chunks created"
        )

        # ------------------------------------------------------------------
        # STAGE 3: METADATA ENRICHMENT
        # ------------------------------------------------------------------
        logger.info(f"[{document_id}] Stage 3/5: Metadata Enrichment")
        update_document_status(
            document_id, "IN_PROGRESS",
            processing_version=processing_version,
            current_stage="STAGE_3_ENRICHMENT",
        )

        stage3 = ray.get(enrich_chunks.remote(document_id, chunks_key))

        if shutdown_requested:
            raise Exception("Shutdown requested — aborting pipeline after Stage 3")

        if stage3["status"] != "COMPLETED":
            raise Exception(f"Stage 3 failed: {stage3.get('error', 'unknown error')}")

        enriched_key = stage3["output_s3_key"]  # S3 key of the enriched JSON for Stage 4
        logger.info(
            f"[{document_id}] Stage 3 done — "
            f"{stage3['metadata']['chunks_enriched']} chunks enriched, "
            f"{stage3['metadata']['pii_redacted_count']} with PII redacted"
        )

        # ------------------------------------------------------------------
        # STAGE 4: EMBEDDING GENERATION
        # ------------------------------------------------------------------
        logger.info(f"[{document_id}] Stage 4/5: Embedding Generation")
        update_document_status(
            document_id, "IN_PROGRESS",
            processing_version=processing_version,
            current_stage="STAGE_4_EMBEDDING",
        )

        stage4 = ray.get(generate_embeddings_task.remote(document_id, enriched_key))

        if shutdown_requested:
            raise Exception("Shutdown requested — aborting pipeline after Stage 4")

        if stage4["status"] != "COMPLETED":
            raise Exception(f"Stage 4 failed: {stage4.get('error', 'unknown error')}")

        embeddings_key = stage4["output_s3_key"]  # S3 key of the embeddings JSON for Stage 5
        logger.info(
            f"[{document_id}] Stage 4 done — "
            f"{stage4['metadata']['embeddings_generated']} embeddings, "
            f"cost=${stage4['metadata']['openai_cost_usd']:.6f}"
        )

        # ------------------------------------------------------------------
        # STAGE 5: VECTOR LOADING
        # ------------------------------------------------------------------
        logger.info(f"[{document_id}] Stage 5/5: Vector Loading")
        update_document_status(
            document_id, "IN_PROGRESS",
            processing_version=processing_version,
            current_stage="STAGE_5_LOADING",
        )

        stage5 = ray.get(load_vectors.remote(document_id, embeddings_key))

        if stage5["status"] != "COMPLETED":
            raise Exception(f"Stage 5 failed: {stage5.get('error', 'unknown error')}")

        logger.info(
            f"[{document_id}] Stage 5 done — "
            f"{stage5['metadata']['vectors_uploaded']} vectors in Pinecone"
        )

        # ------------------------------------------------------------------
        # ALL STAGES COMPLETE
        # ------------------------------------------------------------------
        update_document_status(
            document_id=document_id,
            processing_version=processing_version,
            status="COMPLETED",
            message="All 5 stages completed successfully",
            current_stage="STAGE_5_COMPLETE",
        )

        logger.info(f"✓ Pipeline complete for {document_id}")

    except Exception as e:
        # Any stage failure or shutdown abort lands here.
        # Mark FAILED so this document is not picked up again on the next poll
        # (unless a separate retry job re-sets its status to PENDING).
        logger.error(f"✗ Pipeline failed for {document_id}: {e}", exc_info=True)
        update_document_status(
            document_id=document_id,
            processing_version=processing_version,
            status="FAILED",
            message=f"Pipeline error: {str(e)}",
            current_stage="FAILED",
        )


# ============================================================================
# CONNECTION TESTING
# ============================================================================

def test_connections() -> bool:
    """
    Verify S3 and DynamoDB are reachable before starting the polling loop.

    Fail-fast principle: surface misconfiguration at startup rather than
    discovering it 10 minutes into processing the first document.

    Tests:
      1. S3 bucket exists and our Task Role has s3:HeadBucket permission
      2. DynamoDB control table exists (validates Task Role has dynamodb:DescribeTable)
      3. DynamoDB audit table exists

    Does NOT test OpenAI or Pinecone — those would cost money and require
    index setup. They fail loudly at the stage level if misconfigured.

    Returns True if all pass, False if any fail.
    """
    logger.info("=" * 70)
    logger.info("TESTING AWS CONNECTIONS")
    logger.info("=" * 70)

    try:
        # head_bucket checks existence + IAM permissions without listing any data (fast)
        # If the Task Role is missing s3:HeadBucket, this raises a ClientError here
        # rather than failing silently mid-pipeline.
        s3 = boto3.client("s3", region_name=config.AWS_REGION)
        s3.head_bucket(Bucket=config.S3_BUCKET)
        logger.info(f"✓ S3 bucket accessible: {config.S3_BUCKET}")

        dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)

        # Accessing .table_status forces a DescribeTable API call.
        # Raises ResourceNotFoundException immediately if the table name is wrong.
        table  = dynamodb.Table(config.DYNAMODB_CONTROL_TABLE)
        status = table.table_status
        logger.info(f"✓ DynamoDB control table: {config.DYNAMODB_CONTROL_TABLE} ({status})")

        table  = dynamodb.Table(config.DYNAMODB_AUDIT_TABLE)
        status = table.table_status
        logger.info(f"✓ DynamoDB audit table:   {config.DYNAMODB_AUDIT_TABLE} ({status})")

        logger.info("✅ ALL CONNECTION TESTS PASSED")
        logger.info("=" * 70 + "\n")
        return True

    except Exception as e:
        logger.error("❌ CONNECTION TEST FAILED")
        logger.error(f"Error: {e}", exc_info=True)
        logger.info("=" * 70 + "\n")
        return False


# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================

def main():
    """
    Entry point — runs the polling loop until a shutdown signal is received.

    Startup sequence:
      1. Register SIGTERM / SIGINT handlers for graceful shutdown
      2. Print and validate configuration (exits on invalid config)
      3. Initialise Ray cluster connection (exits on failure)
      4. Test AWS connectivity (exits on failure)
      5. Poll → process → interruptible_sleep loop (runs forever)
      6. Graceful shutdown: Ray cleanup + sys.exit(0)

    ECS Task Role requirement:
      boto3 automatically picks up credentials from the ECS metadata endpoint
      (169.254.170.2). Do NOT set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
      env vars — the Task Role is the correct credential mechanism for ECS.

    ECS ephemeral storage:
      Set ephemeralStorage.sizeInGiB in the task definition.
      Recommended minimum: 50 GB for large PDF workloads.
      Maximum: 200 GB on Fargate.

    RAY_ADDRESS:
      Must point to the Ray head node's private IP or service-discovery DNS.
      Example: "ray://ray-head.internal:10001"
      Do NOT use "localhost" or "auto" — the head node runs in a separate ECS task.

    Exit codes:
      0 — Normal shutdown (SIGTERM / SIGINT received)
      1 — Startup failure (invalid config, Ray unreachable, AWS unreachable)
    """
    global shutdown_requested

    # Register OS signal handlers.
    # SIGTERM = ECS stop signal (sent before SIGKILL after stopTimeout)
    # SIGINT  = Ctrl+C during local development
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Startup banner — visible in ECS / CloudWatch logs at every container start
    logger.info("")
    logger.info("=" * 70)
    logger.info("RAY DOCUMENT PROCESSING ORCHESTRATOR")
    logger.info(f"Started at: {datetime.now(tz=timezone.utc).isoformat()}Z")
    logger.info("=" * 70 + "\n")

    # Validate all required config fields are present.
    # Exits with code 1 immediately if anything is missing — fail fast.
    config.print_config()
    if not config.validate():
        logger.error("❌ Configuration validation failed — check environment variables")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Initialise Ray
    # -----------------------------------------------------------------------
    # RAY_ADDRESS must be the private IP or service-discovery DNS of the
    # Ray head node ECS task — NOT "localhost".
    # Example: "ray://ray-head.internal:10001"
    logger.info("=" * 70)
    logger.info("INITIALISING RAY")
    logger.info("=" * 70)

    try:
        # Determine the correct Ray address:
        #
        # Head node  → CloudFormation sets RAY_ADDRESS=""  (empty string)
        #              We pass "auto" so ray.init() connects to the local cluster
        #              that `ray start --head` already started on 127.0.0.1:6379.
        #              Passing None would start a NEW cluster (fails — port in use).
        #              Passing ""  raises "Invalid address format: "
        #
        # Worker node → CloudFormation sets RAY_ADDRESS="ray-head.local:6379"
        #               We pass it directly so the worker joins the head cluster.
        raw_addr = config.RAY_ADDRESS.strip() if config.RAY_ADDRESS else ""
        ray_addr = "auto" if not raw_addr else raw_addr

        ray.init(
            address=ray_addr,        # "auto" on head node, "ray-head.local:6379" on workers
            namespace=config.RAY_NAMESPACE,  # Isolates this app's tasks from other Ray apps
            logging_level=config.LOG_LEVEL,  # Propagate log level to Ray internals
        )

        logger.info("✓ Ray initialised successfully")
        logger.info(f"  Address  : {config.RAY_ADDRESS}")
        logger.info(f"  Namespace: {config.RAY_NAMESPACE}")
        # Note: Ray Dashboard (port 8265) runs on the head node, not this container.
        # Access it via the Ray head node's address, not localhost.

        # Log cluster resources for capacity planning and debugging
        resources = ray.cluster_resources()
        logger.info(f"  CPUs  : {resources.get('CPU', 0)}")
        logger.info(
            f"  Memory: {resources.get('memory', 0) / 1024 / 1024 / 1024:.2f} GB"
        )
        logger.info(f"  Nodes : {len(ray.nodes())}")
        logger.info("=" * 70 + "\n")

    except Exception as e:
        logger.error("❌ RAY INITIALISATION FAILED")
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Test AWS connectivity
    # -----------------------------------------------------------------------
    if not test_connections():
        logger.error("❌ AWS connection tests failed — shutting down Ray")
        ray.shutdown()
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Start the polling loop
    # -----------------------------------------------------------------------
    logger.info("=" * 70)
    logger.info("STARTING POLLING LOOP")
    logger.info(f"  Polling interval  : {config.POLLING_INTERVAL}s")
    logger.info(f"  Max docs per poll : {config.MAX_DOCUMENTS_PER_POLL}")
    logger.info(f"  Processing version: {config.PROCESSING_VERSION}")
    logger.info("=" * 70 + "\n")

    # Running counters — logged after every poll cycle for operational visibility
    poll_count      = 0
    total_processed = 0
    total_errors    = 0

    while not shutdown_requested:
        try:
            poll_count += 1
            logger.info(f"\n{'=' * 70}")
            logger.info(f"POLL #{poll_count} — {datetime.now(tz=timezone.utc).isoformat()}Z")
            logger.info(f"{'=' * 70}")

            # Reset recently-failed documents for retry (up to MAX_RETRY_ATTEMPTS)
            retry_failed_documents()

            pending_documents = query_pending_documents()

            if not pending_documents:
                logger.info("No pending documents found")
            else:
                logger.info(f"Found {len(pending_documents)} documents to process")

                for doc in pending_documents:
                    # Check flag before each document — allows fast shutdown
                    # even when processing a large batch.
                    if shutdown_requested:
                        logger.info("Shutdown requested — stopping mid-batch cleanly")
                        break

                    try:
                        process_document(doc)
                        total_processed += 1
                    except Exception as doc_err:
                        # process_document() catches its own errors internally and marks
                        # the doc FAILED, but if something truly unexpected escapes, count it.
                        total_errors += 1
                        logger.error(f"❌ Unexpected error processing {doc.get('document_id', '?')}: {doc_err}", exc_info=True)

                logger.info(f"Processed {len(pending_documents)} documents this poll")

            # Log running stats after every poll
            logger.info(
                f"\nStatistics — "
                f"polls: {poll_count}, "
                f"processed: {total_processed}, "
                f"errors: {total_errors}, "
                f"avg: {total_processed / poll_count:.2f}/poll"
            )

            # Sleep with interrupt-awareness — wakes every 1s to check shutdown flag.
            # This ensures ECS SIGTERM → clean exit within ~1s, well inside the
            # default 30s stopTimeout window.
            if not shutdown_requested:
                logger.info(f"Sleeping {config.POLLING_INTERVAL}s (interruptible)...")
                interruptible_sleep(config.POLLING_INTERVAL)

        except KeyboardInterrupt:
            # Ctrl+C arrives as KeyboardInterrupt before the signal handler runs.
            # Catching it here gives a clean log message.
            logger.info("KEYBOARD INTERRUPT — shutting down gracefully")
            break

        except Exception as e:
            # Catch-all guard — the orchestrator must NEVER crash on any error.
            # Log, increment counter, back off briefly, then continue.
            total_errors += 1
            logger.error(f"❌ MAIN LOOP ERROR #{total_errors}: {e}", exc_info=True)
            logger.error("Continuing — will retry next poll cycle")
            # Back off 10s before retrying to avoid hammering a failing service
            interruptible_sleep(10)

    # -----------------------------------------------------------------------
    # Graceful Shutdown
    # -----------------------------------------------------------------------
    logger.info("\n" + "=" * 70)
    logger.info("SHUTTING DOWN ORCHESTRATOR")
    logger.info(f"  Shutdown time : {datetime.now(tz=timezone.utc).isoformat()}Z")
    logger.info(f"  Total polls   : {poll_count}")
    logger.info(f"  Processed     : {total_processed}")
    logger.info(f"  Errors        : {total_errors}")
    logger.info("=" * 70)

    try:
        ray.shutdown()  # Cleanly disconnect from the Ray cluster
        logger.info("✓ Ray shutdown complete")
    except Exception as e:
        logger.error(f"✗ Error during Ray shutdown: {e}")

    logger.info("ORCHESTRATOR STOPPED\n")
    sys.exit(0)  # Code 0 = expected shutdown (ECS marks the task as STOPPED, not FAILED)


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    main()