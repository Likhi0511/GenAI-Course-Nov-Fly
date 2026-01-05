"""
Lambda Function: Product Validator (Container-based)
====================================================

PURPOSE
-------
Validates product records ingested into DynamoDB via vendor CSV uploads.

FLOW
----
DynamoDB Stream (INSERT)
    → Validate product fields
    → If valid:
         - Mark record as validated in DynamoDB
         - (Optionally) Insert into RDS products table
    → If invalid:
         - Mark record as error in DynamoDB
         - Persist error in RDS
         - Send error payload to SQS

DESIGN PRINCIPLES
-----------------
- Separation of ingestion vs validation
- Idempotent processing
- Explicit error handling & traceability
- Production-grade logging with stack traces
"""

# =============================================================================
# STANDARD LIBRARIES
# =============================================================================

import json
import os
import logging
import traceback
from datetime import datetime
from decimal import Decimal

# =============================================================================
# AWS & THIRD-PARTY LIBRARIES
# =============================================================================

import boto3
from botocore.exceptions import ClientError
import psycopg2
from psycopg2.extras import RealDictCursor
from aws_secretsmanager_caching import SecretCache, SecretCacheConfig

# =============================================================================
# STRUCTURED LOGGING SETUP
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
# ENVIRONMENT VARIABLES
# =============================================================================

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "UploadRecords")
RDS_SECRET_NAME = os.environ.get("RDS_SECRET_NAME", "ecommerce/rds/credentials")
SQS_ERROR_QUEUE_URL = os.environ.get("SQS_ERROR_QUEUE_URL")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# =============================================================================
# AWS CLIENTS (REUSED ACROSS INVOCATIONS)
# =============================================================================

dynamodb = boto3.resource("dynamodb", region_name=REGION)
sqs_client = boto3.client("sqs", region_name=REGION)
cloudwatch = boto3.client("cloudwatch", region_name=REGION)
secretsmanager = boto3.client("secretsmanager", region_name=REGION)

# =============================================================================
# SECRETS MANAGER CACHE
# =============================================================================

cache = SecretCache(
    config=SecretCacheConfig(),
    client=secretsmanager
)

# =============================================================================
# DATABASE CONNECTION (GLOBAL FOR REUSE)
# =============================================================================

db_connection = None

# =============================================================================
# VALIDATION RULE DEFINITIONS
# =============================================================================

VALIDATION_RULES = {
    "required_fields": [
        "vendor_product_id",
        "product_name",
        "category",
        "sku",
        "price",
        "stock_quantity"
    ],
    "price": {"min": Decimal("0.01"), "max": Decimal("999999.99")},
    "stock": {"min": 0, "max": 1_000_000},
    "field_lengths": {
        "product_name": 200,
        "description": 2000,
        "sku": 100,
        "brand": 100,
        "vendor_product_id": 100
    }
}

# =============================================================================
# LOG CONTEXT BUILDER
# =============================================================================

def build_log_context(context=None, upload_id=None, record_id=None, vendor_id=None):
    """
    Build a structured logging context attached to every log entry.
    """
    return {
        "request_id": context.aws_request_id if context else None,
        "function": os.environ.get("AWS_LAMBDA_FUNCTION_NAME"),
        "upload_id": upload_id,
        "record_id": record_id,
        "vendor_id": vendor_id
    }

# =============================================================================
# SECRETS & DATABASE HELPERS
# =============================================================================

def get_rds_credentials():
    """
    Retrieve RDS credentials from AWS Secrets Manager.

    Uses caching to avoid repeated Secrets Manager API calls.

    Returns
    -------
    dict
        Dictionary containing host, port, dbname, username, password

    Raises
    ------
    Exception
        If secret retrieval fails
    """
    try:
        logger.info("RDS_SECRET_FETCH_STARTED")
        secret_string = cache.get_secret_string(RDS_SECRET_NAME)
        logger.info("RDS_SECRET_FETCH_SUCCEEDED")
        return json.loads(secret_string)
    except ClientError as e:
        logger.error(
            "RDS_SECRET_FETCH_FAILED",
            extra={
                "error_code": e.response.get("Error", {}).get("Code"),
                "error_message": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        raise
    except Exception as e:
        logger.error(
            "RDS_SECRET_PARSE_FAILED",
            extra={
                "exception_type": type(e).__name__,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        raise


def get_db_connection():
    """
    Get an active PostgreSQL connection.

    Reuses an existing connection if still alive.
    Recreates connection if stale or closed.

    Returns
    -------
    psycopg2.connection
        Active database connection
    """
    global db_connection

    # Attempt to reuse existing connection
    try:
        if db_connection and not db_connection.closed:
            with db_connection.cursor() as cur:
                cur.execute("SELECT 1")
            logger.debug("DB_CONNECTION_REUSED")
            return db_connection
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
        logger.warning(
            "DB_CONNECTION_STALE",
            extra={
                "exception_type": type(e).__name__,
                "error": str(e)
            }
        )
        db_connection = None
    except Exception as e:
        logger.warning(
            "DB_CONNECTION_CHECK_FAILED",
            extra={
                "exception_type": type(e).__name__,
                "error": str(e)
            }
        )
        db_connection = None

    # Create a new database connection
    try:
        logger.info("DB_CONNECTION_CREATE_STARTED")
        creds = get_rds_credentials()
        db_connection = psycopg2.connect(
            host=creds["host"],
            port=creds.get("port", 5432),
            database=creds.get("dbname", "ecommerce_platform"),
            user=creds["username"],
            password=creds["password"],
            connect_timeout=5
        )
        logger.info(
            "DB_CONNECTION_CREATE_SUCCEEDED",
            extra={"host": creds["host"], "database": creds.get("dbname")}
        )
        return db_connection
    except psycopg2.OperationalError as e:
        logger.critical(
            "DB_CONNECTION_FAILED",
            extra={
                "error_code": e.pgcode,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        raise
    except Exception as e:
        logger.critical(
            "DB_CONNECTION_UNEXPECTED_ERROR",
            extra={
                "exception_type": type(e).__name__,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        raise

# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_required_fields(product_data):
    """
    Ensure mandatory fields are present and non-empty.

    Returns
    -------
    (bool, str | None)
        Validation result and error message
    """
    try:
        missing = [
            field for field in VALIDATION_RULES["required_fields"]
            if not product_data.get(field)
        ]
        if missing:
            return False, f"Missing required fields: {', '.join(missing)}"
        return True, None
    except Exception as e:
        logger.error(
            "REQUIRED_FIELDS_VALIDATION_ERROR",
            extra={
                "exception_type": type(e).__name__,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        return False, f"Required fields validation error: {str(e)}"


def validate_price(price):
    """
    Validate price value and bounds.
    """
    try:
        if price is None or price == "":
            return False, "Price is required"

        price = Decimal(str(price))

        if price < VALIDATION_RULES["price"]["min"]:
            return False, f"Price below minimum allowed ({VALIDATION_RULES['price']['min']})"
        if price > VALIDATION_RULES["price"]["max"]:
            return False, f"Price exceeds maximum allowed ({VALIDATION_RULES['price']['max']})"

        return True, None
    except (ValueError, TypeError) as e:
        return False, f"Invalid price format: {str(e)}"
    except Exception as e:
        logger.error(
            "PRICE_VALIDATION_ERROR",
            extra={
                "price": price,
                "exception_type": type(e).__name__,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        return False, f"Price validation error: {str(e)}"


def validate_stock_quantity(stock):
    """
    Validate stock quantity bounds.
    """
    try:
        if stock is None or stock == "":
            return False, "Stock quantity is required"

        stock = int(stock)

        if stock < VALIDATION_RULES["stock"]["min"]:
            return False, "Stock cannot be negative"
        if stock > VALIDATION_RULES["stock"]["max"]:
            return False, f"Stock exceeds maximum allowed ({VALIDATION_RULES['stock']['max']})"

        return True, None
    except (ValueError, TypeError) as e:
        return False, f"Invalid stock format: {str(e)}"
    except Exception as e:
        logger.error(
            "STOCK_VALIDATION_ERROR",
            extra={
                "stock": stock,
                "exception_type": type(e).__name__,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        return False, f"Stock validation error: {str(e)}"


def validate_field_lengths(product_data):
    """
    Validate string field lengths against configured limits.
    """
    try:
        errors = []
        for field, max_len in VALIDATION_RULES["field_lengths"].items():
            value = product_data.get(field)
            if value and len(str(value)) > max_len:
                errors.append(f"{field} exceeds {max_len} characters")

        if errors:
            return False, "; ".join(errors)
        return True, None
    except Exception as e:
        logger.error(
            "FIELD_LENGTH_VALIDATION_ERROR",
            extra={
                "exception_type": type(e).__name__,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        return False, f"Field length validation error: {str(e)}"


def validate_category(category, log_ctx):
    """
    Ensure category exists and is active in reference table.
    """
    conn = cursor = None
    try:
        logger.debug(
            "CATEGORY_VALIDATION_STARTED",
            extra={**log_ctx, "category": category}
        )

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute(
            """
            SELECT 1
            FROM product_categories
            WHERE category_name = %s
              AND is_active = TRUE
            """,
            (category,)
        )

        result = cursor.fetchone()

        if result:
            logger.debug("CATEGORY_VALIDATION_SUCCEEDED", extra=log_ctx)
            return True, None
        else:
            logger.warning(
                "CATEGORY_VALIDATION_FAILED",
                extra={**log_ctx, "category": category, "reason": "not_found_or_inactive"}
            )
            return False, "Invalid or inactive category"

    except psycopg2.OperationalError as e:
        logger.error(
            "CATEGORY_VALIDATION_DB_ERROR",
            extra={
                **log_ctx,
                "category": category,
                "error_code": e.pgcode,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        return False, "Category validation database error"
    except Exception as e:
        logger.error(
            "CATEGORY_VALIDATION_ERROR",
            extra={
                **log_ctx,
                "category": category,
                "exception_type": type(e).__name__,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        return False, "Category validation error"
    finally:
        if cursor:
            cursor.close()


def validate_sku_uniqueness(sku, log_ctx):
    """
    Ensure SKU is globally unique across all vendors.
    """
    conn = cursor = None
    try:
        logger.debug(
            "SKU_UNIQUENESS_CHECK_STARTED",
            extra={**log_ctx, "sku": sku}
        )

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM products WHERE sku = %s", (sku,))
        result = cursor.fetchone()

        if result:
            logger.warning(
                "SKU_UNIQUENESS_CHECK_FAILED",
                extra={**log_ctx, "sku": sku, "reason": "duplicate_found"}
            )
            return False, "Duplicate SKU"
        else:
            logger.debug("SKU_UNIQUENESS_CHECK_SUCCEEDED", extra=log_ctx)
            return True, None

    except psycopg2.OperationalError as e:
        logger.error(
            "SKU_UNIQUENESS_CHECK_DB_ERROR",
            extra={
                **log_ctx,
                "sku": sku,
                "error_code": e.pgcode,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        return False, "SKU uniqueness check database error"
    except Exception as e:
        logger.error(
            "SKU_UNIQUENESS_CHECK_ERROR",
            extra={
                **log_ctx,
                "sku": sku,
                "exception_type": type(e).__name__,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        return False, "SKU uniqueness check failed"
    finally:
        if cursor:
            cursor.close()


def validate_vendor_product_id_uniqueness(vendor_product_id, vendor_id, log_ctx):
    """
    Ensure vendor_product_id is unique per vendor.
    """
    conn = cursor = None
    try:
        logger.debug(
            "VENDOR_PRODUCT_ID_UNIQUENESS_CHECK_STARTED",
            extra={**log_ctx, "vendor_product_id": vendor_product_id}
        )

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT 1
            FROM products
            WHERE vendor_id = %s
              AND vendor_product_id = %s
            """,
            (vendor_id, vendor_product_id)
        )

        result = cursor.fetchone()

        if result:
            logger.warning(
                "VENDOR_PRODUCT_ID_UNIQUENESS_CHECK_FAILED",
                extra={
                    **log_ctx,
                    "vendor_product_id": vendor_product_id,
                    "reason": "duplicate_found"
                }
            )
            return False, "Duplicate vendor product ID"
        else:
            logger.debug("VENDOR_PRODUCT_ID_UNIQUENESS_CHECK_SUCCEEDED", extra=log_ctx)
            return True, None

    except psycopg2.OperationalError as e:
        logger.error(
            "VENDOR_PRODUCT_ID_UNIQUENESS_CHECK_DB_ERROR",
            extra={
                **log_ctx,
                "vendor_product_id": vendor_product_id,
                "error_code": e.pgcode,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        return False, "Vendor product ID uniqueness check database error"
    except Exception as e:
        logger.error(
            "VENDOR_PRODUCT_ID_UNIQUENESS_CHECK_ERROR",
            extra={
                **log_ctx,
                "vendor_product_id": vendor_product_id,
                "exception_type": type(e).__name__,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        return False, "Vendor product ID uniqueness check failed"
    finally:
        if cursor:
            cursor.close()


def validate_product(product_data, vendor_id, log_ctx):
    """
    Run all validation checks sequentially.

    Short-circuits on first failure.

    Returns
    -------
    (bool, str | None, str | None)
        is_valid, error_type, error_message
    """
    try:
        logger.debug("PRODUCT_VALIDATION_STARTED", extra=log_ctx)

        validations = [
            (lambda d: validate_required_fields(d), "MISSING_REQUIRED_FIELDS"),
            (lambda d: validate_price(d.get("price")), "INVALID_PRICE"),
            (lambda d: validate_stock_quantity(d.get("stock_quantity")), "INVALID_STOCK"),
            (lambda d: validate_field_lengths(d), "FIELD_LENGTH_EXCEEDED"),
            (lambda d: validate_category(d.get("category"), log_ctx), "INVALID_CATEGORY"),
            (lambda d: validate_sku_uniqueness(d.get("sku"), log_ctx), "DUPLICATE_SKU"),
            (lambda d: validate_vendor_product_id_uniqueness(
                d.get("vendor_product_id"), vendor_id, log_ctx
            ), "DUPLICATE_VENDOR_PRODUCT_ID"),
        ]

        for fn, error_type in validations:
            is_valid, error_message = fn(product_data)
            if not is_valid:
                logger.info(
                    "PRODUCT_VALIDATION_FAILED",
                    extra={**log_ctx, "error_type": error_type, "error_message": error_message}
                )
                return False, error_type, error_message

        logger.debug("PRODUCT_VALIDATION_SUCCEEDED", extra=log_ctx)
        return True, None, None

    except Exception as e:
        logger.error(
            "PRODUCT_VALIDATION_UNEXPECTED_ERROR",
            extra={
                **log_ctx,
                "exception_type": type(e).__name__,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
        return False, "VALIDATION_ERROR", f"Unexpected validation error: {str(e)}"

# =============================================================================
# DYNAMODB & SQS OPERATIONS
# =============================================================================

def update_dynamodb_record_status(upload_id, record_id, status,
                                  error_reason=None, error_details=None, log_ctx=None):
    """
    Update validation status of a record in DynamoDB.
    """
    try:
        logger.debug(
            "DYNAMODB_UPDATE_STARTED",
            extra={**(log_ctx or {}), "status": status}
        )

        table = dynamodb.Table(DYNAMODB_TABLE)

        update_expr = "SET #s = :s, processed_at = :p"
        expr_vals = {
            ":s": status,
            ":p": datetime.utcnow().isoformat()
        }
        expr_names = {"#s": "status"}

        if error_reason:
            update_expr += ", error_reason = :r, error_details = :d"
            expr_vals.update({
                ":r": error_reason,
                ":d": error_details
            })

        table.update_item(
            Key={"upload_id": upload_id, "record_id": record_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_vals,
            ExpressionAttributeNames=expr_names
        )

        logger.debug(
            "DYNAMODB_UPDATE_SUCCEEDED",
            extra={**(log_ctx or {}), "status": status}
        )

    except ClientError as e:
        logger.error(
            "DYNAMODB_UPDATE_FAILED",
            extra={
                **(log_ctx or {}),
                "error_code": e.response.get("Error", {}).get("Code"),
                "error_message": str(e),
                "status": status,
                "stacktrace": traceback.format_exc()
            }
        )
    except Exception as e:
        logger.error(
            "DYNAMODB_UPDATE_UNEXPECTED_ERROR",
            extra={
                **(log_ctx or {}),
                "exception_type": type(e).__name__,
                "error": str(e),
                "status": status,
                "stacktrace": traceback.format_exc()
            }
        )


def send_error_to_sqs(message, log_ctx=None):
    """
    Send validation error payload to SQS for downstream handling.
    """
    try:
        logger.debug(
            "SQS_ERROR_SEND_STARTED",
            extra={**(log_ctx or {}), "queue_url": SQS_ERROR_QUEUE_URL}
        )

        response = sqs_client.send_message(
            QueueUrl=SQS_ERROR_QUEUE_URL,
            MessageBody=json.dumps(message, default=str)
        )

        logger.info(
            "SQS_ERROR_SEND_SUCCEEDED",
            extra={
                **(log_ctx or {}),
                "message_id": response.get("MessageId"),
                "queue_url": SQS_ERROR_QUEUE_URL
            }
        )

    except ClientError as e:
        logger.error(
            "SQS_ERROR_SEND_FAILED",
            extra={
                **(log_ctx or {}),
                "error_code": e.response.get("Error", {}).get("Code"),
                "error_message": str(e),
                "queue_url": SQS_ERROR_QUEUE_URL,
                "stacktrace": traceback.format_exc()
            }
        )
    except Exception as e:
        logger.error(
            "SQS_ERROR_SEND_UNEXPECTED_ERROR",
            extra={
                **(log_ctx or {}),
                "exception_type": type(e).__name__,
                "error": str(e),
                "queue_url": SQS_ERROR_QUEUE_URL,
                "stacktrace": traceback.format_exc()
            }
        )

# =============================================================================
# CLOUDWATCH METRICS
# =============================================================================

def publish_validation_metrics(total, valid, errors, duration, log_ctx):
    """
    Publish validation metrics to CloudWatch.
    """
    try:
        logger.debug("CLOUDWATCH_METRICS_PUBLISH_STARTED", extra=log_ctx)

        cloudwatch.put_metric_data(
            Namespace="EcommerceProductValidation",
            MetricData=[
                {"MetricName": "ProductsValidated", "Value": total, "Unit": "Count"},
                {"MetricName": "ProductsValid", "Value": valid, "Unit": "Count"},
                {"MetricName": "ProductsInvalid", "Value": errors, "Unit": "Count"},
                {"MetricName": "ValidationDuration", "Value": duration, "Unit": "Seconds"}
            ]
        )

        logger.info("CLOUDWATCH_METRICS_PUBLISH_SUCCEEDED", extra=log_ctx)

    except ClientError as e:
        logger.error(
            "CLOUDWATCH_METRICS_PUBLISH_FAILED",
            extra={
                **log_ctx,
                "error_code": e.response.get("Error", {}).get("Code"),
                "error_message": str(e),
                "stacktrace": traceback.format_exc()
            }
        )
    except Exception as e:
        logger.error(
            "CLOUDWATCH_METRICS_PUBLISH_UNEXPECTED_ERROR",
            extra={
                **log_ctx,
                "exception_type": type(e).__name__,
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
        )

# =============================================================================
# MAIN LAMBDA HANDLER
# =============================================================================

def lambda_handler(event, context):
    """
    Lambda entry point.

    Triggered by DynamoDB Streams INSERT events.
    """
    start_time = datetime.utcnow()
    log_ctx = build_log_context(context)

    logger.info(
        "PRODUCT_VALIDATOR_STARTED",
        extra={**log_ctx, "event_record_count": len(event.get("Records", []))}
    )

    total = valid = error = 0

    try:
        for record in event["Records"]:
            # Process only INSERT events
            if record["eventName"] != "INSERT":
                logger.debug(
                    "RECORD_SKIPPED",
                    extra={**log_ctx, "event_name": record["eventName"], "reason": "not_insert"}
                )
                continue

            total += 1

            try:
                image = record["dynamodb"]["NewImage"]

                # Extract primary identifiers
                upload_id = image["upload_id"]["S"]
                record_id = image["record_id"]["S"]
                vendor_id = image["vendor_id"]["S"]
                row_number = int(image["row_number"]["N"])

                # Update log context for this record
                record_log_ctx = build_log_context(
                    context, upload_id, record_id, vendor_id
                )
                record_log_ctx["row_number"] = row_number

                logger.debug("RECORD_PROCESSING_STARTED", extra=record_log_ctx)

                # Convert DynamoDB Map → Python dict
                product_data = {
                    k: (
                        v.get("S") if "S" in v else
                        Decimal(v["N"]) if "N" in v else
                        None
                    )
                    for k, v in image["product_data"]["M"].items()
                }

                # Validate product
                is_valid, error_type, error_message = validate_product(
                    product_data, vendor_id, record_log_ctx
                )

                if is_valid:
                    valid += 1
                    update_dynamodb_record_status(
                        upload_id, record_id, "validated", log_ctx=record_log_ctx
                    )
                    logger.info("PRODUCT_VALIDATED", extra=record_log_ctx)
                else:
                    error += 1
                    update_dynamodb_record_status(
                        upload_id, record_id, "error", error_type, error_message,
                        log_ctx=record_log_ctx
                    )
                    send_error_to_sqs({
                        "upload_id": upload_id,
                        "vendor_id": vendor_id,
                        "record_id": record_id,
                        "row_number": row_number,
                        "error_type": error_type,
                        "error_message": error_message,
                        "product_data": {k: str(v) for k, v in product_data.items()}
                    }, log_ctx=record_log_ctx)
                    logger.warning(
                        "PRODUCT_VALIDATION_FAILED",
                        extra={
                            **record_log_ctx,
                            "error_type": error_type,
                            "error_message": error_message
                        }
                    )

            except KeyError as e:
                error += 1
                logger.error(
                    "RECORD_PROCESSING_FAILED",
                    extra={
                        **log_ctx,
                        "exception_type": "KeyError",
                        "missing_field": str(e),
                        "error": "Required field missing in DynamoDB record",
                        "stacktrace": traceback.format_exc()
                    }
                )
            except Exception as e:
                error += 1
                logger.error(
                    "RECORD_PROCESSING_UNEXPECTED_ERROR",
                    extra={
                        **log_ctx,
                        "exception_type": type(e).__name__,
                        "error": str(e),
                        "stacktrace": traceback.format_exc()
                    }
                )

        duration = (datetime.utcnow() - start_time).total_seconds()

        # Publish metrics
        publish_validation_metrics(total, valid, error, duration, log_ctx)

        logger.info(
            "PRODUCT_VALIDATOR_COMPLETED",
            extra={
                **log_ctx,
                "total": total,
                "valid": valid,
                "errors": error,
                "duration_sec": duration
            }
        )

        return {
            "statusCode": 200,
            "body": json.dumps({
                "total_records": total,
                "valid_records": valid,
                "error_records": error,
                "processing_time_seconds": duration
            })
        }

    except Exception as e:
        duration = (datetime.utcnow() - start_time).total_seconds()

        logger.critical(
            "PRODUCT_VALIDATOR_FAILED",
            extra={
                **log_ctx,
                "exception_type": type(e).__name__,
                "error": str(e),
                "duration_sec": duration,
                "stacktrace": traceback.format_exc()
            }
        )

        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e),
                "message": "Validation failed",
                "total_processed": total,
                "valid_records": valid,
                "error_records": error
            })
        }