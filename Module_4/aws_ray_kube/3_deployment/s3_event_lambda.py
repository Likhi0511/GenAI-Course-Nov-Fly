"""
s3_event_lambda.py

AWS Lambda Function - S3 Event Handler
The ENTRY POINT of our RAG pipeline!

================================================================================
                          WHAT THIS LAMBDA DOES
================================================================================

This Lambda function is the "doorbell" of our document processing pipeline.
When someone uploads a PDF to S3, this function:

1. Gets notified by S3 (automatic trigger)
2. Creates a tracking record in DynamoDB
3. Tells the pipeline "New document ready for processing!"

Think of it like a restaurant:
- Customer orders food (user uploads PDF)
- Waiter writes order ticket (Lambda creates DynamoDB record)
- Kitchen starts cooking (Ray pipeline processes document)

┌─────────────────────────────────────────────────────────────────┐
│                        EVENT FLOW                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  User uploads PDF                                               │
│         │                                                        │
│         ▼                                                        │
│  ┌───────────────┐                                              │
│  │  S3 Bucket    │  PDF stored in s3://bucket/input/file.pdf   │
│  └───────┬───────┘                                              │
│          │                                                       │
│          │ (S3 triggers event)                                  │
│          │                                                       │
│          ▼                                                       │
│  ┌───────────────┐                                              │
│  │ THIS LAMBDA   │  Creates DynamoDB records                   │
│  └───────┬───────┘                                              │
│          │                                                       │
│          ├─────────────────┐                                    │
│          │                 │                                    │
│          ▼                 ▼                                    │
│  ┌─────────────┐   ┌─────────────┐                            │
│  │ Control     │   │ Audit       │  Track document status      │
│  │ Table       │   │ Table       │                             │
│  └─────────────┘   └─────────────┘                            │
│          │                                                       │
│          ▼                                                       │
│  Ray Orchestrator polls Control Table                          │
│          │                                                       │
│          ▼                                                       │
│  Pipeline starts processing!                                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

Why Lambda?
✓ Serverless (no servers to manage)
✓ Auto-scaling (handles any upload volume)
✓ Pay-per-use (only charged when files upload)
✓ S3 integration (automatic trigger)
✓ Fast (millisecond response times)

Cost: ~$0.0000002 per invocation (basically free!)
Execution time: ~100-200ms per file

Deployment:
1. Package this file with boto3
2. Create Lambda function in AWS Console
3. Set up S3 event trigger for PUT events on input/ prefix
4. Configure IAM role with DynamoDB and S3 permissions

Author: Prudhvi
Organization: Thoughtworks
"""

import json
import boto3  # AWS SDK for Python
from datetime import datetime
import uuid  # For generating unique IDs
import os


# ============================================================================
# INITIALIZE AWS CLIENTS
# ============================================================================
# These clients let us interact with AWS services
# They're initialized ONCE at container startup (efficient!)
# ============================================================================

# DynamoDB client - for storing document metadata
# DynamoDB is like a super-fast spreadsheet in the cloud
dynamodb = boto3.resource('dynamodb')

# S3 client - for interacting with S3 buckets
# We use this to get file metadata (size, etc.)
s3 = boto3.client('s3')

# ============================================================================
# GET CONFIGURATION FROM ENVIRONMENT VARIABLES
# ============================================================================
# Lambda gets config from environment variables (set in AWS Console)
# This makes it easy to use different tables for dev/staging/production
#
# Example:
# - Development: 'dev-document-processing-control'
# - Production:  'prod-document-processing-control'
# ============================================================================

# Control table - tracks document processing status
# This is the "source of truth" for what stage each document is in
CONTROL_TABLE_NAME = os.environ.get('CONTROL_TABLE_NAME', 'document_processing_control')

# Audit table - tracks all events for compliance/debugging
# This is the "history book" - never deleted, only appended to
AUDIT_TABLE_NAME = os.environ.get('AUDIT_TABLE_NAME', 'document_processing_audit')

# Get references to the actual DynamoDB tables
control_table = dynamodb.Table(CONTROL_TABLE_NAME)
audit_table = dynamodb.Table(AUDIT_TABLE_NAME)


def lambda_handler(event, context):
    """
    Main Lambda handler - this is what AWS calls when S3 triggers the function.

    This function is the ENTRY POINT to the entire pipeline!

    What happens here:
    1. Parse S3 event (extract bucket name, file key, file size)
    2. Validate the file (is it a PDF in the right folder?)
    3. Generate unique document ID
    4. Create control record (tells orchestrator to process this)
    5. Create audit record (tracks that we received the file)

    Think of this as the "intake clerk" at a hospital:
    - Patient arrives (PDF uploaded)
    - Clerk checks ID (validates file)
    - Clerk creates medical record (control record)
    - Clerk logs arrival time (audit record)
    - Patient sent to triage (orchestrator picks up for processing)

    Args:
        event: S3 event containing object details
            Example structure:
            {
                "Records": [
                    {
                        "eventVersion": "2.1",
                        "eventSource": "aws:s3",
                        "eventName": "ObjectCreated:Put",
                        "s3": {
                            "bucket": {
                                "name": "ray-ingestion-prudhvi-2026"
                            },
                            "object": {
                                "key": "input/NCT04368728_Remdesivir_COVID.pdf",
                                "size": 2457600  # bytes
                            }
                        }
                    }
                ]
            }

        context: Lambda context (runtime information)
            Contains:
            - function_name
            - memory_limit_in_mb
            - request_id
            - log_group_name
            (We don't use this, but AWS always provides it)

    Returns:
        Response with status code and message
        {
            'statusCode': 200,  # or 207 for partial success
            'body': JSON string with results
        }

    How S3 Triggers This:
    1. User uploads file to s3://bucket/input/file.pdf
    2. S3 checks event notification rules: "Trigger Lambda on PUT in input/"
    3. S3 creates event JSON and calls Lambda
    4. Lambda executes this function
    5. All happens in < 1 second!
    """

    # ========================================================================
    # LOG THE INCOMING EVENT
    # ========================================================================
    # Always log the event for debugging!
    # This helps us troubleshoot issues:
    # - What file triggered this?
    # - When did it happen?
    # - What was the exact event structure?
    #
    # These logs go to CloudWatch Logs automatically
    # ========================================================================
    print(f"Received event: {json.dumps(event)}")

    # Counters for success/failure tracking
    processed_count = 0  # How many files we successfully processed
    errors = []          # List of any errors that occurred

    # ========================================================================
    # PROCESS EACH RECORD IN THE EVENT
    # ========================================================================
    # S3 can send multiple records in one event (batch processing)
    # Example: User uploads 5 files → 1 Lambda invocation with 5 records
    #
    # Why batch? More efficient!
    # Instead of: 5 Lambda invocations × $0.0000002 = $0.000001
    # We get:     1 Lambda invocation × $0.0000002 = $0.0000002
    # ========================================================================
    for record in event['Records']:
        try:
            # ================================================================
            # STEP 1: EXTRACT S3 EVENT DETAILS
            # ================================================================
            # Parse the S3 event to get file information
            # The event structure is nested JSON, so we dig down:
            # event → Records → [0] → s3 → bucket/object → name/key/size
            # ================================================================

            bucket = record['s3']['bucket']['name']  # e.g., "ray-ingestion-prudhvi-2026"
            key = record['s3']['object']['key']      # e.g., "input/NCT04368728.pdf"
            size = record['s3']['object']['size']    # e.g., 2457600 (bytes)

            print(f"Processing S3 object: s3://{bucket}/{key} ({size} bytes)")

            # ================================================================
            # STEP 2: VALIDATE THE FILE
            # ================================================================
            # We only want to process:
            # ✓ Files in the input/ folder (not other folders)
            # ✓ PDF files (not .txt, .jpg, etc.)
            #
            # Why validate?
            # - Prevents processing wrong files
            # - Avoids wasting pipeline resources
            # - Gives clear feedback (via logs)
            #
            # Example valid file:   input/trial.pdf ✓
            # Example invalid file: processed/trial.pdf ✗ (wrong folder)
            # Example invalid file: input/data.csv ✗ (not a PDF)
            # ================================================================

            # Check 1: Must be in input/ folder
            if not key.startswith('input/'):
                print(f"Skipping - not in input/ prefix: {key}")
                continue  # Skip to next record

            # Check 2: Must be a PDF file
            if not key.lower().endswith('.pdf'):
                print(f"Skipping - not a PDF: {key}")
                continue  # Skip to next record

            # ================================================================
            # STEP 3: GENERATE UNIQUE DOCUMENT ID
            # ================================================================
            # Create a unique ID for this document
            # Format: doc_YYYYMMDD_HHMMSS_RANDOM
            # Example: doc_20240222_143025_a1b2c3d4
            #
            # Why this format?
            # - Sortable by upload time (timestamp first)
            # - Human-readable (can see date/time)
            # - Collision-proof (random suffix)
            # - Short enough for logging
            #
            # Components:
            # - doc_: Prefix to identify as document ID
            # - 20240222: Date (YYYYMMDD)
            # - 143025: Time (HHMMSS)
            # - a1b2c3d4: Random 8-char hex (from UUID)
            # ================================================================

            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')  # e.g., "20240222_143025"
            unique_id = uuid.uuid4().hex[:8]  # e.g., "a1b2c3d4" (first 8 chars of random UUID)
            document_id = f"doc_{timestamp}_{unique_id}"  # e.g., "doc_20240222_143025_a1b2c3d4"

            # ================================================================
            # STEP 4: CREATE CONTROL RECORD
            # ================================================================
            # This is the MASTER RECORD for this document
            # The Ray orchestrator polls this table to find work
            #
            # Structure:
            # {
            #   "document_id": "doc_...",           # Primary key (unique)
            #   "processing_version": "v1",         # Sort key (for schema changes)
            #   "status": "PENDING",                # Current overall status
            #   "current_stage": "extraction",      # Which stage is next?
            #   "stage_status": {...},              # Status of each stage
            #   "retry_count": 0,                   # How many retries attempted?
            #   "max_retries": 3,                   # Stop after 3 failures
            #   "ttl": 1234567890                   # Auto-delete after 90 days
            # }
            #
            # Why processing_version?
            # If we change the pipeline (add stages, change logic), we can:
            # - Keep old records as "v1"
            # - Process new ones as "v2"
            # - No data migration needed!
            # ================================================================

            current_time = datetime.utcnow().isoformat() + 'Z'  # e.g., "2024-02-22T14:30:25Z"

            control_item = {
                # ============================================================
                # PRIMARY KEYS
                # ============================================================
                'document_id': document_id,           # Partition key (unique ID)
                'processing_version': 'v1',           # Sort key (schema version)

                # ============================================================
                # SOURCE INFORMATION
                # ============================================================
                'source_s3_key': key,                 # Where is the PDF?
                'source_bucket': bucket,              # Which bucket?
                'file_size_bytes': size,              # How big is it?
                'upload_timestamp': current_time,     # When was it uploaded?

                # ============================================================
                # PROCESSING STATUS
                # ============================================================
                # Overall status can be:
                # - PENDING: Waiting to start
                # - IN_PROGRESS: Currently being processed
                # - COMPLETED: All stages finished successfully
                # - FAILED: One or more stages failed
                'status': 'PENDING',

                # Which stage should process next?
                # - extraction
                # - chunking
                # - enrichment
                # - embedding
                # - loading
                'current_stage': 'extraction',

                # ============================================================
                # TIMESTAMPS
                # ============================================================
                'created_at': current_time,           # When record created
                'updated_at': current_time,           # When last updated

                # ============================================================
                # STAGE-BY-STAGE STATUS
                # ============================================================
                # Track each stage independently
                # This lets us:
                # - Know exactly where we are in the pipeline
                # - Restart from a specific stage if needed
                # - Monitor progress (dashboard: "Stage 3/5 complete")
                #
                # Each stage can be:
                # - PENDING: Not started yet
                # - IN_PROGRESS: Currently running
                # - COMPLETED: Finished successfully
                # - FAILED: Hit an error
                # ============================================================
                'stage_status': {
                    'extraction': {'status': 'PENDING'},
                    'chunking': {'status': 'PENDING'},
                    'enrichment': {'status': 'PENDING'},
                    'embedding': {'status': 'PENDING'},
                    'loading': {'status': 'PENDING'}
                },

                # ============================================================
                # RETRY LOGIC
                # ============================================================
                # If a stage fails, we can retry it
                # - retry_count: How many times we've tried
                # - max_retries: Stop after this many attempts
                #
                # Example flow:
                # Try 1: Stage 3 fails → retry_count = 1
                # Try 2: Stage 3 fails → retry_count = 2
                # Try 3: Stage 3 fails → retry_count = 3 (max!)
                # Give up: Mark document as FAILED
                #
                # Why retry? Transient errors are common:
                # - Network hiccup to OpenAI API
                # - Temporary Pinecone rate limit
                # - S3 eventual consistency
                # ============================================================
                'retry_count': 0,        # Start at 0 retries
                'max_retries': 3,        # Allow up to 3 retries

                # ============================================================
                # TIME-TO-LIVE (TTL)
                # ============================================================
                # Auto-delete this record after 90 days
                # Why?
                # - Keeps DynamoDB table small (better performance)
                # - Reduces storage costs
                # - Compliance (don't keep data forever)
                #
                # Formula: current time + 90 days (in seconds)
                # Example:
                # - Current: 1708610425 (Feb 22, 2024)
                # - TTL: 1708610425 + (90 × 24 × 3600) = 1716386425
                # - Delete on: May 22, 2024 ✓
                #
                # DynamoDB automatically deletes items when TTL expires
                # ============================================================
                'ttl': int(datetime.utcnow().timestamp()) + (90 * 24 * 3600)
            }

            # Write to DynamoDB control table
            # This is an atomic operation - either succeeds completely or fails
            control_table.put_item(Item=control_item)
            print(f"Created control record: {document_id}")

            # ================================================================
            # STEP 5: CREATE AUDIT RECORD
            # ================================================================
            # This is a HISTORY LOG entry
            # Every significant event gets logged here for:
            # - Compliance (who did what when?)
            # - Debugging (trace document journey)
            # - Analytics (how long did each stage take?)
            #
            # Audit vs Control:
            # - Control: Current state (1 record per document)
            # - Audit: Event history (many records per document)
            #
            # Example audit trail for one document:
            # 1. DOCUMENT_RECEIVED (now)
            # 2. STAGE_STARTED (extraction)
            # 3. STAGE_COMPLETED (extraction)
            # 4. STAGE_STARTED (chunking)
            # ... etc
            # ================================================================

            audit_item = {
                # ============================================================
                # PRIMARY KEYS
                # ============================================================
                'document_id': document_id,           # Partition key (which document?)
                'timestamp': current_time,            # Sort key (when did this happen?)

                # ============================================================
                # EVENT INFORMATION
                # ============================================================
                # Event types:
                # - DOCUMENT_RECEIVED: PDF uploaded (this event!)
                # - STAGE_STARTED: Beginning a pipeline stage
                # - STAGE_COMPLETED: Finished a pipeline stage
                # - STAGE_FAILED: Error in a pipeline stage
                # - RETRY_ATTEMPTED: Retrying after failure
                # - PIPELINE_COMPLETED: All stages finished
                'event_type': 'DOCUMENT_RECEIVED',

                # Which stage? (or 'ingestion' for upload)
                'stage': 'ingestion',

                # What's the status?
                'status': 'PENDING',

                # Which version of the pipeline?
                'processing_version': 'v1',

                # ============================================================
                # METADATA
                # ============================================================
                # Additional context about this event
                # This is flexible - different events can have different metadata
                'metadata': {
                    'source': 's3_event',             # How was this triggered?
                    'file_size': size,                # File size in bytes
                    'bucket': bucket,                 # Which S3 bucket?
                    'key': key                        # Exact S3 key
                },

                # ============================================================
                # TIME-TO-LIVE (TTL)
                # ============================================================
                # Keep audit records longer (180 days vs 90 for control)
                # Why longer?
                # - Compliance requirements (may need 6-month history)
                # - Investigation (look back at old failures)
                # - Cost: Audit table is smaller per-record
                # ============================================================
                'ttl': int(datetime.utcnow().timestamp()) + (180 * 24 * 3600)
            }

            # Write to DynamoDB audit table
            audit_table.put_item(Item=audit_item)
            print(f"Created audit record: {document_id}")

            # Success! Increment counter
            processed_count += 1

        except Exception as e:
            # ================================================================
            # ERROR HANDLING
            # ================================================================
            # Something went wrong processing this file!
            #
            # Common errors:
            # - DynamoDB throttling (too many writes)
            # - Malformed S3 event (missing fields)
            # - Permission error (can't write to DynamoDB)
            # - Network error (AWS API temporarily down)
            #
            # What we do:
            # 1. Log the error (for debugging)
            # 2. Add to errors list (for response)
            # 3. Continue processing other files (don't fail entire batch)
            #
            # Why continue?
            # If user uploads 10 files and 1 has an issue:
            # - Bad: Stop processing, 0 files succeed
            # - Good: Process 9 successfully, report 1 error
            # ================================================================
            error_msg = f"Error processing {key}: {str(e)}"
            print(error_msg)
            errors.append(error_msg)

    # ========================================================================
    # PREPARE RESPONSE
    # ========================================================================
    # Lambda must return a response to AWS
    #
    # Status codes:
    # - 200: All good! Everything processed successfully
    # - 207: Multi-Status (partial success - some succeeded, some failed)
    # - 500: Complete failure (would trigger retry)
    #
    # Why return 200 even with errors?
    # - We handled the errors gracefully
    # - Successful files were processed
    # - We don't want Lambda to retry (it would duplicate records!)
    # ========================================================================
    response = {
        'statusCode': 200 if not errors else 207,  # 207 = partial success
        'body': json.dumps({
            'message': 'Processing initiated',     # Human-readable message
            'processed': processed_count,          # How many succeeded?
            'errors': errors                       # What went wrong?
        })
    }

    print(f"Lambda execution complete. Processed: {processed_count}, Errors: {len(errors)}")

    return response


# ============================================================================
# LOCAL TESTING
# ============================================================================
# This section lets you test the Lambda function on your laptop!
#
# Why local testing?
# ✓ Faster than deploying to AWS every time
# ✓ Free (no Lambda invocation costs)
# ✓ Easy debugging (use Python debugger)
# ✓ No AWS dependencies (mock the event)
#
# How to test:
# 1. Set environment variables:
#    export CONTROL_TABLE_NAME='test-control'
#    export AUDIT_TABLE_NAME='test-audit'
#
# 2. Make sure you have AWS credentials configured:
#    aws configure
#
# 3. Run the script:
#    python s3_event_lambda.py
#
# 4. It will process the test event below
# ============================================================================

if __name__ == "__main__":
    # ========================================================================
    # SAMPLE S3 EVENT FOR TESTING
    # ========================================================================
    # This mimics what S3 would send to Lambda
    # Structure is identical to real S3 events
    #
    # To test different scenarios, modify:
    # - bucket name (test different buckets)
    # - key (test different folders, file types)
    # - size (test large files)
    # ========================================================================
    test_event = {
        "Records": [
            {
                "s3": {
                    "bucket": {
                        "name": "your-document-pipeline"  # Change to your bucket
                    },
                    "object": {
                        "key": "input/2025/01/31/test_document.pdf",  # Test file
                        "size": 2457600  # ~2.4 MB
                    }
                }
            }
        ]
    }

    # Run the Lambda handler with test event
    result = lambda_handler(test_event, None)

    # Pretty-print the result
    print(json.dumps(result, indent=2))


# ============================================================================
# SUMMARY FOR STUDENTS
# ============================================================================
#
# This Lambda function is the ENTRY POINT to the RAG pipeline!
#
# Flow:
# 1. User uploads PDF to S3
# 2. S3 triggers this Lambda
# 3. Lambda creates DynamoDB records
# 4. Ray orchestrator polls DynamoDB
# 5. Pipeline starts processing
#
# Key Concepts:
# ✓ Event-driven architecture (S3 → Lambda)
# ✓ Serverless computing (no servers to manage)
# ✓ Database design (control vs audit tables)
# ✓ Error handling (graceful degradation)
# ✓ Idempotency (safe to run multiple times)
#
# Important DynamoDB Patterns:
# 1. Control Table: Current state (1 record per document)
# 2. Audit Table: Event history (many records per document)
# 3. TTL: Auto-delete old records
# 4. Composite keys: (document_id, processing_version)
#
# Why This Design?
# ✓ Decoupled: Lambda doesn't know about Ray pipeline
# ✓ Scalable: Can handle 1 or 1000 uploads
# ✓ Reliable: Errors don't stop the whole batch
# ✓ Observable: Audit trail for every document
# ✓ Cost-effective: Pay only when files upload
#
# Questions for Students:
# 1. What happens if the same file is uploaded twice?
#    → Creates 2 different document IDs (different timestamps)
# 2. What if DynamoDB is temporarily down?
#    → Lambda fails, S3 retries (exponential backoff)
# 3. Why not process the PDF in Lambda?
#    → Lambda has 15-min limit, PDF processing takes longer
# 4. Could we skip DynamoDB and process directly?
#    → Yes, but we'd lose status tracking and retry logic
# 5. What if we want to reprocess a document?
#    → Upload it again, gets new document_id, processes fresh
#
# Next Steps:
# - Deploy this Lambda to AWS
# - Set up S3 event notification
# - Upload a test PDF
# - Check DynamoDB tables
# - Watch Ray orchestrator pick it up!
#
# ============================================================================