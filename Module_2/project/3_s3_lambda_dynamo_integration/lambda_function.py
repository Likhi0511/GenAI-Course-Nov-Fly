"""
================================================================================
Lambda Function: CSV Parser (Container-based)
================================================================================

OVERVIEW
--------
This Lambda function ingests vendor-uploaded CSV files from Amazon S3 and
persists each row as a *pending-validation* record in Amazon DynamoDB.

The function performs **ingestion only** — all business validation,
deduplication, and enrichment are intentionally deferred to downstream
processors.

This design enables:
- High ingestion throughput
- Clear separation of concerns
- Independent scaling of ingestion vs validation
- Reliable replay and reconciliation

--------------------------------------------------------------------------------
TRIGGER
-------
S3 ObjectCreated events for vendor-uploaded CSV files.

Expected file naming convention:
    <VENDOR_ID>_<YYYYMMDD>_<HHMMSS>.csv

--------------------------------------------------------------------------------
ARCHITECTURE
------------
S3 (CSV Upload)
    → CSV Parser Lambda (this module)
        → RDS (vendor verification + upload audit)
        → DynamoDB (raw product records, status=pending_validation)
        → CloudWatch (metrics + logs)

--------------------------------------------------------------------------------
DESIGN GUARANTEES
-----------------
✔ Idempotent ingestion (upload_id-based)
✔ Schema firewall at CSV boundary
✔ Strong auditability (upload history table)
✔ Structured, request-scoped logging
✔ Metrics-driven observability

--------------------------------------------------------------------------------
NON-GOALS
---------
✖ Business validation
✖ Data enrichment
✖ Deduplication
✖ Product approval logic

These are handled downstream by dedicated processors.

================================================================================
"""

# =============================================================================
# 1️⃣ STANDARD LIBRARIES
# =============================================================================

import json
import csv
import os
import io
import logging
import traceback
from datetime import datetime
from decimal import Decimal

# =============================================================================
# 2️⃣ AWS + THIRD-PARTY LIBRARIES
# =============================================================================

import boto3
from botocore.exceptions import ClientError
import psycopg2
from psycopg2.extras import RealDictCursor
from aws_secretsmanager_caching import SecretCache, SecretCacheConfig

# =============================================================================
# 3️⃣ STRUCTURED LOGGING SETUP (CRITICAL FIX)
# =============================================================================

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


class JsonFormatter(logging.Formatter):
    """
    JSON log formatter that correctly serializes `extra` fields.

    This makes logs:
    - Queryable in CloudWatch Logs Insights
    - Compatible with OpenTelemetry / Datadog
    - Safe for Lambda
    """

    RESERVED_ATTRS = {
        "args", "asctime", "created", "exc_info", "exc_text",
        "filename", "funcName", "levelname", "levelno",
        "lineno", "module", "msecs", "msg", "name",
        "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName"
    }

    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach all custom fields passed via `extra`
        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS:
                try:
                    json.dumps(value)  # ensure serializable
                    log_record[key] = value
                except Exception:
                    log_record[key] = str(value)

        return json.dumps(log_record)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())

logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)
logger.handlers = [handler]
logger.propagate = False

# =============================================================================
# 4️⃣ ENVIRONMENT VARIABLES
# =============================================================================

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "UploadRecords")
RDS_SECRET_NAME = os.environ.get("RDS_SECRET_NAME", "ecommerce/rds/credentials")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# =============================================================================
# 5️⃣ AWS CLIENTS
# =============================================================================

s3_client = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
cloudwatch = boto3.client("cloudwatch", region_name=REGION)
secretsmanager = boto3.client("secretsmanager", region_name=REGION)

# =============================================================================
# 6️⃣ SECRETS MANAGER CACHE
# =============================================================================

cache = SecretCache(
    config=SecretCacheConfig(),
    client=secretsmanager
)

# =============================================================================
# 7️⃣ LOG CONTEXT BUILDER
# =============================================================================

def build_log_context(context=None, upload_id=None, vendor_id=None):
    """
    Build a structured logging context attached to every log entry.
    """
    return {
        "request_id": context.aws_request_id if context else None,
        "function": os.environ.get("AWS_LAMBDA_FUNCTION_NAME"),
        "upload_id": upload_id,
        "vendor_id": vendor_id
    }

# =============================================================================
# 8️⃣ RDS HELPERS
# =============================================================================

def get_rds_credentials():
    try:
        secret_string = cache.get_secret_string(RDS_SECRET_NAME)
        return json.loads(secret_string)
    except ClientError:
        logger.error(
            "RDS_SECRET_FETCH_FAILED",
            extra={"stacktrace": traceback.format_exc()}
        )
        raise


def get_db_connection():
    creds = get_rds_credentials()
    return psycopg2.connect(
        host=creds["host"],
        port=creds.get("port", 5432),
        database=creds["dbname"],
        user=creds["username"],
        password=creds["password"],
        connect_timeout=5
    )

# =============================================================================
# 9️⃣ TYPE CONVERSION
# =============================================================================

def convert_to_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def convert_to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except Exception:
        return None

# =============================================================================
# 🔟 CSV NORMALIZATION
# =============================================================================

def parse_csv_row(row, row_number):
    return {
        "vendor_product_id": row.get("vendor_product_id", ""),
        "product_name": row.get("product_name", ""),
        "category": row.get("category", ""),
        "subcategory": row.get("subcategory", ""),
        "description": row.get("description", ""),
        "sku": row.get("sku", ""),
        "brand": row.get("brand", ""),
        "price": convert_to_decimal(row.get("price")),
        "compare_at_price": convert_to_decimal(row.get("compare_at_price")),
        "stock_quantity": convert_to_int(row.get("stock_quantity")),
        "unit": row.get("unit", "piece"),
        "weight_kg": convert_to_decimal(row.get("weight_kg")),
        "dimensions_cm": row.get("dimensions_cm", ""),
        "image_url": row.get("image_url", "")
    }


def extract_vendor_id_from_filename(filename):
    try:
        return filename.split("_")[0]
    except Exception:
        return None

# =============================================================================
# 1️⃣1️⃣ BUSINESS RULES
# =============================================================================

def verify_vendor_exists(vendor_id, log_ctx):
    conn = cursor = None
    try:
        logger.info("VENDOR_VERIFICATION_STARTED", extra=log_ctx)

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute(
            "SELECT status FROM vendors WHERE vendor_id = %s",
            (vendor_id,)
        )
        vendor = cursor.fetchone()

        if not vendor or vendor["status"] != "active":
            logger.warning("VENDOR_INVALID", extra=log_ctx)
            return False

        logger.info("VENDOR_VERIFIED", extra=log_ctx)
        return True

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# =============================================================================
# 1️⃣2️⃣ UPLOAD HISTORY
# =============================================================================

def create_upload_history_record(upload_id, vendor_id, file_name, s3_key, log_ctx):
    conn = cursor = None
    try:
        logger.info("UPLOAD_HISTORY_CREATE_STARTED", extra=log_ctx)

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO upload_history (
                upload_id, vendor_id, file_name, s3_key,
                status, upload_timestamp, processing_started_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (upload_id) DO NOTHING
        """, (
            upload_id,
            vendor_id,
            file_name,
            s3_key,
            "processing",
            datetime.utcnow(),
            datetime.utcnow()
        ))

        conn.commit()
        logger.info("UPLOAD_HISTORY_CREATED", extra=log_ctx)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def update_upload_history_counts(upload_id, total_records, log_ctx):
    conn = cursor = None
    try:
        logger.info(
            "UPLOAD_HISTORY_UPDATE_STARTED",
            extra={**log_ctx, "total_records": total_records}
        )

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE upload_history
            SET total_records = %s
            WHERE upload_id = %s
        """, (total_records, upload_id))

        conn.commit()
        logger.info("UPLOAD_HISTORY_UPDATED", extra=log_ctx)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# =============================================================================
# 1️⃣3️⃣ DYNAMODB INGESTION
# =============================================================================

def batch_insert_dynamodb_records(records, log_ctx):
    table = dynamodb.Table(DYNAMODB_TABLE)
    successful = failed = 0

    logger.info(
        "DYNAMODB_BATCH_INSERT_STARTED",
        extra={**log_ctx, "total_records": len(records)}
    )

    for i in range(0, len(records), 25):
        with table.batch_writer() as writer:
            for record in records[i:i + 25]:
                try:
                    writer.put_item(Item=record)
                    successful += 1
                except Exception:
                    failed += 1
                    logger.error(
                        "DYNAMODB_INSERT_FAILED",
                        extra={
                            **log_ctx,
                            "record_id": record.get("record_id"),
                            "stacktrace": traceback.format_exc()
                        }
                    )

    logger.info(
        "DYNAMODB_BATCH_INSERT_COMPLETED",
        extra={**log_ctx, "successful": successful, "failed": failed}
    )

    return successful, failed

# =============================================================================
# 1️⃣4️⃣ METRICS
# =============================================================================

def publish_metrics(upload_id, total, success, failed, duration, log_ctx):
    cloudwatch.put_metric_data(
        Namespace="EcommerceProductOnboarding",
        MetricData=[
            {"MetricName": "CSVRecordsProcessed", "Value": total},
            {"MetricName": "CSVRecordsSuccessful", "Value": success},
            {"MetricName": "CSVProcessingTime", "Value": duration}
        ]
    )

    logger.info("CLOUDWATCH_METRICS_PUBLISHED", extra=log_ctx)

# =============================================================================
# 1️⃣5️⃣ LAMBDA HANDLER
# =============================================================================

def lambda_handler(event, context):
    start_time = datetime.utcnow()
    log_ctx = build_log_context(context)

    logger.info("CSV_INGESTION_STARTED", extra=log_ctx)

    try:
        s3_info = event["Records"][0]["s3"]
        bucket = s3_info["bucket"]["name"]
        key = s3_info["object"]["key"]
        filename = key.split("/")[-1]

        vendor_id = extract_vendor_id_from_filename(filename)
        timestamp = filename.replace(".csv", "").split("_", 1)[1]
        upload_id = f"UPLOAD_{timestamp}"

        log_ctx.update({
            "upload_id": upload_id,
            "vendor_id": vendor_id,
            "s3_bucket": bucket,
            "s3_key": key,
            "file_name": filename
        })

        if not verify_vendor_exists(vendor_id, log_ctx):
            raise ValueError("Vendor validation failed")

        create_upload_history_record(upload_id, vendor_id, filename, key, log_ctx)

        csv_content = s3_client.get_object(
            Bucket=bucket,
            Key=key
        )["Body"].read().decode("utf-8")

        reader = csv.DictReader(io.StringIO(csv_content))

        logger.info(
            "CSV_SCHEMA_DETECTED",
            extra={**log_ctx, "columns": reader.fieldnames}
        )

        records = []
        for i, row in enumerate(reader, 1):
            records.append({
                "upload_id": upload_id,
                "record_id": f"REC_{i:05d}",
                "vendor_id": vendor_id,
                "row_number": i,
                "product_data": parse_csv_row(row, i),
                "status": "pending_validation",
                "error_reason": None,
                "error_details": None,
                "processed_at": None,
                "created_at": datetime.utcnow().isoformat()
            })

        success, failed = batch_insert_dynamodb_records(records, log_ctx)
        update_upload_history_counts(upload_id, len(records), log_ctx)

        duration = (datetime.utcnow() - start_time).total_seconds()
        publish_metrics(upload_id, len(records), success, failed, duration, log_ctx)

        logger.info(
            "CSV_INGESTION_COMPLETED",
            extra={**log_ctx, "duration_sec": duration}
        )

        return {
            "statusCode": 200,
            "body": json.dumps({
                "upload_id": upload_id,
                "vendor_id": vendor_id,
                "total_records": len(records),
                "successful_records": success,
                "failed_records": failed,
                "processing_time_seconds": duration
            })
        }

    except Exception as e:
        logger.critical(
            "CSV_INGESTION_FAILED",
            extra={
                **log_ctx,
                "exception_type": type(e).__name__,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e),
                "message": "CSV parsing failed"
            })
        }