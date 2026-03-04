"""
orchestration/dynamodb.py — DynamoDB Control & Audit Table Operations

Provides three operations used by the orchestrator polling loop:
  1. query_pending_documents() — GSI query for PENDING docs, oldest-first
  2. claim_document()          — Atomic PENDING → IN_PROGRESS conditional update
  3. update_document_status()  — General status transitions + audit trail

Moved from: ray_orchestrator.py (DynamoDB operations section)

Why separate from orchestrator.py?
  - Testable in isolation (mock boto3.resource, no Ray dependency)
  - Reusable by retry jobs, admin scripts, monitoring dashboards
  - Single responsibility: DynamoDB access patterns in one place

Author: Prudhvi | Thoughtworks
"""

import logging
import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timedelta, timezone
from typing import List, Dict

from boto3.dynamodb.conditions import Key, Attr

from core.config import config

logger = logging.getLogger(__name__)


# ============================================================================
# DYNAMODB OPERATIONS
# ============================================================================

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
