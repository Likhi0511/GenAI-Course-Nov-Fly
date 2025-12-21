"""
================================================================================
Lambda Function: CSV Parser (Container-based)
================================================================================

WHAT DOES THIS LAMBDA DO?
------------------------
This Lambda processes CSV files uploaded by vendors into S3.
Each CSV row represents a product.

For every uploaded CSV file, this Lambda:
1. Identifies which vendor uploaded the file
2. Verifies the vendor exists and is active (via RDS)
3. Tracks the upload in an audit table (upload_history)
4. Parses each CSV row into a structured format
5. Inserts each row into DynamoDB with status = 'pending_validation'
6. Publishes CloudWatch metrics for observability

IMPORTANT DESIGN PRINCIPLE
--------------------------
This Lambda ONLY ingests data.
It does NOT validate product correctness.

Why?
- Separation of concerns
- Easier scaling
- Clear ownership of responsibilities

Downstream validation is handled by:
DynamoDB Streams → Validator Lambda

================================================================================
"""

# =============================================================================
# 1️⃣ STANDARD PYTHON LIBRARIES
# =============================================================================
# These are built into Python and require no installation.

import json              # Used for request/response payloads
import csv               # Parses CSV files
import os                # Reads environment variables
import io                # Treats strings as file-like objects
from datetime import datetime
from decimal import Decimal  # Required by DynamoDB (no float support)

# =============================================================================
# 2️⃣ AWS + THIRD-PARTY LIBRARIES
# =============================================================================

import boto3
from botocore.exceptions import ClientError

import psycopg2
from psycopg2.extras import RealDictCursor

from aws_secretsmanager_caching import SecretCache, SecretCacheConfig


# =============================================================================
# 3️⃣ ENVIRONMENT VARIABLES (CONFIGURATION)
# =============================================================================
# Environment variables allow the same code to run in DEV / QA / PROD
# without changing source code.

DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE', 'UploadRecords')
RDS_SECRET_NAME = os.environ.get('RDS_SECRET_NAME', 'ecommerce/rds/credentials')
REGION = os.environ.get('AWS_REGION', 'us-east-1')


# =============================================================================
# 4️⃣ AWS CLIENTS (CREATED ONCE PER CONTAINER)
# =============================================================================
# These objects are created outside lambda_handler so they are reused
# across warm Lambda invocations (better performance).

s3_client = boto3.client('s3', region_name=REGION)
dynamodb = boto3.resource('dynamodb', region_name=REGION)
cloudwatch = boto3.client('cloudwatch', region_name=REGION)
secretsmanager = boto3.client('secretsmanager', region_name=REGION)


# =============================================================================
# 5️⃣ SECRETS MANAGER CACHE
# =============================================================================
# Secrets Manager calls are:
# - slow
# - expensive
# - rate-limited
#
# This cache ensures:
# - secret is fetched once per container
# - reused across Lambda invocations
# - automatically refreshed if rotated

cache_config = SecretCacheConfig()
cache = SecretCache(config=cache_config, client=secretsmanager)


# =============================================================================
# 6️⃣ SECRETS MANAGER INTEGRATION
# =============================================================================

def get_rds_credentials():
    """
    Retrieve PostgreSQL credentials securely from AWS Secrets Manager.

    STUDENT NOTE:
    -------------
    NEVER store database passwords in:
    - code
    - environment variables
    - config files

    Secrets Manager + IAM is the correct approach.

    RETURNS
    -------
    dict
        {
            host,
            port,
            dbname,
            username,
            password
        }
    """
    try:
        # Either returns cached value OR fetches from Secrets Manager
        secret_string = cache.get_secret_string(RDS_SECRET_NAME)
        secret = json.loads(secret_string)

        # Logging only SAFE metadata (never log passwords)
        print("✓ RDS credentials retrieved")
        print(f"  Host: {secret.get('host')}")
        print(f"  Database: {secret.get('dbname')}")

        return secret

    except ClientError as e:
        # Explicit error logging helps in production debugging
        error_code = e.response['Error']['Code']
        print(f"✗ Secrets Manager error [{error_code}]")
        raise


def get_db_connection():
    """
    Create a PostgreSQL connection using psycopg2.

    WHY NO CONNECTION POOL?
    ----------------------
    Lambda executions are short-lived.
    Opening and closing connections is acceptable here.

    For high scale:
    - Add RDS Proxy
    - OR Step Functions fan-out control
    """
    creds = get_rds_credentials()

    return psycopg2.connect(
        host=creds.get('host'),
        port=creds.get('port', 5432),
        database=creds.get('dbname'),
        user=creds.get('username'),
        password=creds.get('password'),
        connect_timeout=5
    )


# =============================================================================
# 7️⃣ DATA TYPE CONVERSION HELPERS
# =============================================================================

def convert_to_decimal(value):
    """
    Convert string → Decimal.

    WHY?
    ----
    DynamoDB does NOT support float.
    Decimal is mandatory.

    Examples:
    "12.5" → Decimal("12.5")
    ""     → None
    """
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def convert_to_int(value):
    """
    Convert numeric string → int safely.
    """
    if value in (None, ''):
        return None
    try:
        return int(float(value))
    except Exception:
        return None


# =============================================================================
# 8️⃣ CSV NORMALIZATION LOGIC
# =============================================================================

def parse_csv_row(row, row_number):
    """
    Convert ONE CSV row into structured product data.

    STUDENT INSIGHT:
    ----------------
    This function acts as a *schema firewall*.
    Raw CSV never leaks beyond this boundary.

    If CSV format changes → ONLY update this function.
    """
    return {
        'vendor_product_id': row.get('vendor_product_id', ''),
        'product_name': row.get('product_name', ''),
        'category': row.get('category', ''),
        'subcategory': row.get('subcategory', ''),
        'description': row.get('description', ''),
        'sku': row.get('sku', ''),
        'brand': row.get('brand', ''),
        'price': convert_to_decimal(row.get('price')),
        'compare_at_price': convert_to_decimal(row.get('compare_at_price')),
        'stock_quantity': convert_to_int(row.get('stock_quantity')),
        'unit': row.get('unit', 'piece'),
        'weight_kg': convert_to_decimal(row.get('weight_kg')),
        'dimensions_cm': row.get('dimensions_cm', ''),
        'image_url': row.get('image_url', '')
    }


def extract_vendor_id_from_filename(filename):
    """
    Extract vendor_id from filename.

    EXPECTED FORMAT:
    ----------------
    VEND001_YYYYMMDD_HHMMSS.csv

    Why filename-based identity?
    ----------------------------
    - Simple
    - No need to trust CSV content
    - Easy traceability
    """
    try:
        return filename.split('_')[0]
    except Exception:
        return None


# =============================================================================
# 9️⃣ BUSINESS RULES (RDS CHECKS)
# =============================================================================

def verify_vendor_exists(vendor_id):
    """
    Business Gate #1

    A vendor:
    - MUST exist
    - MUST be active

    Otherwise upload is rejected early.
    """
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute(
            "SELECT vendor_id, status FROM vendors WHERE vendor_id = %s",
            (vendor_id,)
        )

        vendor = cursor.fetchone()

        if not vendor:
            print(f"✗ Vendor {vendor_id} not found")
            return False

        if vendor['status'] != 'active':
            print(f"✗ Vendor {vendor_id} inactive")
            return False

        print(f"✓ Vendor {vendor_id} verified")
        return True

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# =============================================================================
# 🔟 UPLOAD HISTORY (AUDIT TRAIL IN RDS)
# =============================================================================

def create_upload_history_record(upload_id, vendor_id, file_name, s3_key):
    """
    Create initial audit record for this upload.

    WHY THIS MATTERS:
    -----------------
    - Retry handling
    - Compliance
    - Data reconciliation
    - Operational dashboards
    """
    conn = cursor = None
    try:
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
            'processing',
            datetime.utcnow(),
            datetime.utcnow()
        ))

        conn.commit()
        print(f"✓ Upload history created")

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def update_upload_history_counts(upload_id, total_records):
    """
    Update upload_history once CSV parsing is complete.
    """
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE upload_history
            SET total_records = %s
            WHERE upload_id = %s
        """, (total_records, upload_id))

        conn.commit()
        print("✓ Upload history updated")

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# =============================================================================
# 1️⃣1️⃣ DYNAMODB INGESTION
# =============================================================================

def batch_insert_dynamodb_records(records):
    """
    Insert records into DynamoDB efficiently.

    DynamoDB LIMIT:
    ---------------
    Max 25 items per batch write.
    """
    table = dynamodb.Table(DYNAMODB_TABLE)
    successful = failed = 0

    for i in range(0, len(records), 25):
        with table.batch_writer() as writer:
            for record in records[i:i + 25]:
                try:
                    writer.put_item(Item=record)
                    successful += 1
                except Exception:
                    failed += 1

    return successful, failed


# =============================================================================
# 1️⃣2️⃣ CLOUDWATCH METRICS
# =============================================================================

def publish_metrics(upload_id, total, success, failed, duration):
    """
    Publish metrics for monitoring & alerting.
    """
    cloudwatch.put_metric_data(
        Namespace='EcommerceProductOnboarding',
        MetricData=[
            {'MetricName': 'CSVRecordsProcessed', 'Value': total},
            {'MetricName': 'CSVRecordsSuccessful', 'Value': success},
            {'MetricName': 'CSVProcessingTime', 'Value': duration}
        ]
    )


# =============================================================================
# 1️⃣3️⃣ MAIN LAMBDA HANDLER
# =============================================================================

def lambda_handler(event, context):
    """
    Orchestrates the entire CSV ingestion pipeline.
    """

    start_time = datetime.utcnow()

    try:
        # Step 1: Read S3 event
        s3_info = event['Records'][0]['s3']
        bucket = s3_info['bucket']['name']
        key = s3_info['object']['key']
        filename = key.split('/')[-1]

        # Step 2: Generate upload_id
        timestamp = filename.replace('.csv', '').split('_', 1)[1]
        upload_id = f"UPLOAD_{timestamp}"

        # Step 3: Vendor validation
        vendor_id = extract_vendor_id_from_filename(filename)
        if not verify_vendor_exists(vendor_id):
            raise ValueError("Vendor validation failed")

        # Step 4: Audit record
        create_upload_history_record(upload_id, vendor_id, filename, key)

        # Step 5: Download CSV
        csv_content = s3_client.get_object(
            Bucket=bucket,
            Key=key
        )['Body'].read().decode('utf-8')

        # Step 6: Parse CSV
        reader = csv.DictReader(io.StringIO(csv_content))
        records = []

        for i, row in enumerate(reader, 1):
            records.append({
                'upload_id': upload_id,
                'record_id': f"REC_{i:05d}",
                'vendor_id': vendor_id,
                'row_number': i,
                'product_data': parse_csv_row(row, i),
                'status': 'pending_validation',
                'error_reason': None,
                'error_details': None,
                'processed_at': None,
                'created_at': datetime.utcnow().isoformat()
            })

        # Step 7: DynamoDB insert
        success, failed = batch_insert_dynamodb_records(records)

        # Step 8: Update audit record
        update_upload_history_counts(upload_id, len(records))

        # Step 9: Metrics
        duration = (datetime.utcnow() - start_time).total_seconds()
        publish_metrics(upload_id, len(records), success, failed, duration)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'upload_id': upload_id,
                'vendor_id': vendor_id,
                'total_records': len(records),
                'successful_records': success,
                'failed_records': failed,
                'processing_time_seconds': duration
            })
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'message': 'CSV parsing failed'
            })
        }