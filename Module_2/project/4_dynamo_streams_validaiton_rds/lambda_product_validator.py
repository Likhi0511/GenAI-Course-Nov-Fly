"""
Lambda Function: Product Validator (Container-based)
====================================================

Trigger: DynamoDB Streams (when new records inserted into UploadRecords)
Process: Validate product data against business rules
Output: 
  - Valid products → Insert into RDS products table
  - Invalid products → Send to SQS error queue

Container Image Deployment:
- Dockerfile builds Python 3.11 with psycopg2
- Deployed to ECR
- Lambda pulls from ECR

Validation Rules:
1. Required Fields: vendor_product_id, product_name, category, sku, price, stock_quantity
2. Price: Must be > 0 and <= 999,999.99
3. Stock: Must be >= 0 and <= 1,000,000
4. Category: Must be in whitelist (from RDS product_categories table)
5. SKU: Must be unique across platform (check RDS products table)
6. Vendor Product ID: Must be unique per vendor
7. Field Lengths: product_name (200 chars), description (2000 chars), etc.

Secrets Manager Integration:
- RDS credentials stored in AWS Secrets Manager
- Retrieved and cached using aws-secretsmanager-caching

Environment Variables:
- DYNAMODB_TABLE: UploadRecords
- RDS_SECRET_NAME: ecommerce/rds/credentials
- SQS_ERROR_QUEUE_URL: https://sqs.us-east-1.amazonaws.com/123456789012/product-validation-errors
- REGION: us-east-1

IAM Permissions Required:
- dynamodb:GetItem, dynamodb:UpdateItem (read/update DynamoDB records)
- dynamodb:DescribeStream, dynamodb:GetRecords, dynamodb:GetShardIterator (read streams)
- rds:* (connect to RDS)
- sqs:SendMessage (send to error queue)
- secretsmanager:GetSecretValue (retrieve RDS credentials)
- logs:CreateLogGroup, logs:CreateLogStream, logs:PutLogEvents
- cloudwatch:PutMetricData
- ec2:CreateNetworkInterface, ec2:DescribeNetworkInterfaces, ec2:DeleteNetworkInterface (VPC)
"""

import json
import os
from datetime import datetime
from decimal import Decimal
import boto3
from botocore.exceptions import ClientError
import psycopg2
from psycopg2.extras import RealDictCursor
from aws_secretsmanager_caching import SecretCache, SecretCacheConfig


# =============================================================================
# ENVIRONMENT VARIABLES
# =============================================================================

DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE', 'UploadRecords')
RDS_SECRET_NAME = os.environ.get('RDS_SECRET_NAME', 'ecommerce/rds/credentials')
SQS_ERROR_QUEUE_URL = os.environ.get('SQS_ERROR_QUEUE_URL')
REGION = os.environ.get('AWS_REGION', 'us-east-1')

# AWS Clients
dynamodb = boto3.resource('dynamodb', region_name=REGION)
sqs_client = boto3.client('sqs', region_name=REGION)
cloudwatch = boto3.client('cloudwatch', region_name=REGION)
secretsmanager = boto3.client('secretsmanager', region_name=REGION)

# Secrets Manager Cache
cache_config = SecretCacheConfig()
cache = SecretCache(config=cache_config, client=secretsmanager)

# Database connection (reused across invocations)
db_connection = None


# =============================================================================
# VALIDATION RULES CONFIGURATION
# =============================================================================

VALIDATION_RULES = {
    'required_fields': [
        'vendor_product_id',
        'product_name',
        'category',
        'sku',
        'price',
        'stock_quantity'
    ],
    'price': {
        'min': Decimal('0.01'),
        'max': Decimal('999999.99')
    },
    'stock': {
        'min': 0,
        'max': 1000000
    },
    'field_lengths': {
        'product_name': 200,
        'description': 2000,
        'sku': 100,
        'brand': 100,
        'vendor_product_id': 100
    }
}


# =============================================================================
# SECRETS MANAGER & DATABASE CONNECTION
# =============================================================================

def get_rds_credentials():
    """
    Retrieve RDS credentials from AWS Secrets Manager.
    Uses caching to reduce API calls.
    
    Returns:
        dict: RDS connection parameters
    """
    try:
        secret_string = cache.get_secret_string(RDS_SECRET_NAME)
        secret = json.loads(secret_string)
        return secret
    except Exception as e:
        print(f"✗ Error retrieving secret: {str(e)}")
        raise


def get_db_connection():
    """
    Get or create PostgreSQL connection using connection pooling.
    Reuses connection across Lambda invocations for better performance.
    
    Returns:
        psycopg2.connection: Database connection
    """
    global db_connection
    
    try:
        # Check if connection exists and is valid
        if db_connection is not None and not db_connection.closed:
            # Test connection
            cursor = db_connection.cursor()
            cursor.execute('SELECT 1')
            cursor.close()
            return db_connection
    except:
        # Connection is dead, will create new one
        db_connection = None
    
    # Create new connection
    try:
        creds = get_rds_credentials()
        
        db_connection = psycopg2.connect(
            host=creds.get('host'),
            port=creds.get('port', 5432),
            database=creds.get('dbname'),
            user=creds.get('username'),
            password=creds.get('password'),
            connect_timeout=5
        )
        
        print("✓ Connected to RDS successfully")
        return db_connection
        
    except Exception as e:
        print(f"✗ Database connection error: {str(e)}")
        raise


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_required_fields(product_data):
    """
    Validate that all required fields are present and not empty.
    
    Args:
        product_data: Product data dictionary
    
    Returns:
        tuple: (is_valid, error_message)
    """
    missing_fields = []
    
    for field in VALIDATION_RULES['required_fields']:
        value = product_data.get(field)
        
        # Check if field is missing or empty
        if value is None or value == '':
            missing_fields.append(field)
    
    if missing_fields:
        return False, f"Missing required fields: {', '.join(missing_fields)}"
    
    return True, None


def validate_price(price):
    """
    Validate price is within acceptable range.
    
    Args:
        price: Decimal or None
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if price is None:
        return False, "Price is required"
    
    try:
        price = Decimal(str(price))
        
        if price < VALIDATION_RULES['price']['min']:
            return False, f"Price must be at least {VALIDATION_RULES['price']['min']}"
        
        if price > VALIDATION_RULES['price']['max']:
            return False, f"Price cannot exceed {VALIDATION_RULES['price']['max']}"
        
        return True, None
        
    except Exception as e:
        return False, f"Invalid price format: {str(e)}"


def validate_stock_quantity(stock):
    """
    Validate stock quantity is within acceptable range.
    
    Args:
        stock: Integer or None
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if stock is None:
        return False, "Stock quantity is required"
    
    try:
        stock = int(stock)
        
        if stock < VALIDATION_RULES['stock']['min']:
            return False, f"Stock quantity cannot be negative"
        
        if stock > VALIDATION_RULES['stock']['max']:
            return False, f"Stock quantity cannot exceed {VALIDATION_RULES['stock']['max']}"
        
        return True, None
        
    except Exception as e:
        return False, f"Invalid stock quantity format: {str(e)}"


def validate_category(category):
    """
    Validate category exists in allowed categories list.
    
    Args:
        category: Category name
    
    Returns:
        tuple: (is_valid, error_message)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT category_id 
            FROM product_categories 
            WHERE category_name = %s AND is_active = TRUE
        """, (category,))
        
        result = cursor.fetchone()
        cursor.close()
        
        if result:
            return True, None
        else:
            return False, f"Invalid category: {category}. Category not found in allowed list."
        
    except Exception as e:
        print(f"✗ Error validating category: {str(e)}")
        return False, f"Category validation error: {str(e)}"


def validate_sku_uniqueness(sku, vendor_id):
    """
    Validate SKU is unique across the platform.
    
    Args:
        sku: Stock keeping unit
        vendor_id: Vendor identifier
    
    Returns:
        tuple: (is_valid, error_message)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT product_id, vendor_id 
            FROM products 
            WHERE sku = %s
        """, (sku,))
        
        result = cursor.fetchone()
        cursor.close()
        
        if result:
            return False, f"Duplicate SKU: {sku} already exists (Product ID: {result['product_id']}, Vendor: {result['vendor_id']})"
        
        return True, None
        
    except Exception as e:
        print(f"✗ Error validating SKU uniqueness: {str(e)}")
        return False, f"SKU validation error: {str(e)}"


def validate_vendor_product_id_uniqueness(vendor_product_id, vendor_id):
    """
    Validate vendor_product_id is unique for this vendor.
    
    Args:
        vendor_product_id: Vendor's product identifier
        vendor_id: Vendor identifier
    
    Returns:
        tuple: (is_valid, error_message)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT product_id 
            FROM products 
            WHERE vendor_id = %s AND vendor_product_id = %s
        """, (vendor_id, vendor_product_id))
        
        result = cursor.fetchone()
        cursor.close()
        
        if result:
            return False, f"Duplicate vendor product ID: {vendor_product_id} already exists for vendor {vendor_id}"
        
        return True, None
        
    except Exception as e:
        print(f"✗ Error validating vendor product ID: {str(e)}")
        return False, f"Vendor product ID validation error: {str(e)}"


def validate_field_lengths(product_data):
    """
    Validate field lengths don't exceed maximum allowed.
    
    Args:
        product_data: Product data dictionary
    
    Returns:
        tuple: (is_valid, error_message)
    """
    errors = []
    
    for field, max_length in VALIDATION_RULES['field_lengths'].items():
        value = product_data.get(field, '')
        
        if value and len(str(value)) > max_length:
            errors.append(f"{field} exceeds maximum length of {max_length} characters")
    
    if errors:
        return False, "; ".join(errors)
    
    return True, None


def validate_product(product_data, vendor_id):
    """
    Run all validation rules on product data.
    
    Args:
        product_data: Product data dictionary
        vendor_id: Vendor identifier
    
    Returns:
        tuple: (is_valid, error_type, error_message)
    """
    
    # 1. Validate required fields
    is_valid, error = validate_required_fields(product_data)
    if not is_valid:
        return False, 'MISSING_REQUIRED_FIELDS', error
    
    # 2. Validate price
    is_valid, error = validate_price(product_data.get('price'))
    if not is_valid:
        return False, 'INVALID_PRICE', error
    
    # 3. Validate stock quantity
    is_valid, error = validate_stock_quantity(product_data.get('stock_quantity'))
    if not is_valid:
        return False, 'INVALID_STOCK_QUANTITY', error
    
    # 4. Validate field lengths
    is_valid, error = validate_field_lengths(product_data)
    if not is_valid:
        return False, 'FIELD_LENGTH_EXCEEDED', error
    
    # 5. Validate category
    is_valid, error = validate_category(product_data.get('category'))
    if not is_valid:
        return False, 'INVALID_CATEGORY', error
    
    # 6. Validate SKU uniqueness
    is_valid, error = validate_sku_uniqueness(product_data.get('sku'), vendor_id)
    if not is_valid:
        return False, 'DUPLICATE_SKU', error
    
    # 7. Validate vendor product ID uniqueness
    is_valid, error = validate_vendor_product_id_uniqueness(
        product_data.get('vendor_product_id'), 
        vendor_id
    )
    if not is_valid:
        return False, 'DUPLICATE_VENDOR_PRODUCT_ID', error
    
    # All validations passed!
    return True, None, None


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def insert_valid_product(upload_id, vendor_id, product_data):
    """
    Insert validated product into RDS products table.
    
    Args:
        upload_id: Upload identifier
        vendor_id: Vendor identifier
        product_data: Validated product data
    
    Returns:
        int: Inserted product_id or None
    """
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO products (
                vendor_id,
                vendor_product_id,
                product_name,
                category,
                subcategory,
                description,
                sku,
                brand,
                price,
                compare_at_price,
                stock_quantity,
                unit,
                weight_kg,
                dimensions_cm,
                image_url,
                upload_id,
                status
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING product_id
        """, (
            vendor_id,
            product_data.get('vendor_product_id'),
            product_data.get('product_name'),
            product_data.get('category'),
            product_data.get('subcategory'),
            product_data.get('description'),
            product_data.get('sku'),
            product_data.get('brand'),
            product_data.get('price'),
            product_data.get('compare_at_price'),
            product_data.get('stock_quantity'),
            product_data.get('unit', 'piece'),
            product_data.get('weight_kg'),
            product_data.get('dimensions_cm'),
            product_data.get('image_url'),
            upload_id,
            'active'
        ))
        
        product_id = cursor.fetchone()[0]
        conn.commit()
        
        print(f"  ✓ Inserted product to RDS: {product_data.get('sku')} (ID: {product_id})")
        
        return product_id
        
    except Exception as e:
        print(f"  ✗ Failed to insert product: {str(e)}")
        if conn:
            conn.rollback()
        return None
    
    finally:
        if cursor:
            cursor.close()


def insert_validation_error(upload_id, vendor_id, row_number, vendor_product_id, 
                           error_type, error_message, product_data):
    """
    Insert validation error into RDS validation_errors table.
    
    Args:
        upload_id: Upload identifier
        vendor_id: Vendor identifier
        row_number: Row number in CSV
        vendor_product_id: Vendor's product ID
        error_type: Error type code
        error_message: Detailed error message
        product_data: Original product data
    
    Returns:
        bool: True if successful
    """
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO validation_errors (
                upload_id,
                vendor_id,
                row_number,
                vendor_product_id,
                error_type,
                error_field,
                error_message,
                original_data
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            upload_id,
            vendor_id,
            row_number,
            vendor_product_id,
            error_type,
            None,  # error_field (could extract from error_type)
            error_message,
            json.dumps(product_data, default=str)
        ))
        
        conn.commit()
        
        return True
        
    except Exception as e:
        print(f"  ⚠ Warning: Failed to insert validation error: {str(e)}")
        if conn:
            conn.rollback()
        return False
    
    finally:
        if cursor:
            cursor.close()


def update_upload_history_counts(upload_id, valid_count=0, error_count=0):
    """
    Update upload history with validation counts.
    
    Args:
        upload_id: Upload identifier
        valid_count: Number of valid products
        error_count: Number of error products
    """
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE upload_history 
            SET 
                valid_records = valid_records + %s,
                error_records = error_records + %s,
                status = CASE 
                    WHEN (valid_records + %s + error_records + %s) = total_records 
                    THEN 
                        CASE 
                            WHEN error_records + %s > 0 THEN 'partial'
                            ELSE 'completed'
                        END
                    ELSE 'processing'
                END,
                processing_completed_at = CASE 
                    WHEN (valid_records + %s + error_records + %s) = total_records 
                    THEN CURRENT_TIMESTAMP
                    ELSE processing_completed_at
                END
            WHERE upload_id = %s
        """, (
            valid_count, error_count,
            valid_count, error_count,
            error_count,
            valid_count, error_count,
            upload_id
        ))
        
        conn.commit()
        
    except Exception as e:
        print(f"  ⚠ Warning: Failed to update upload history: {str(e)}")
        if conn:
            conn.rollback()
    
    finally:
        if cursor:
            cursor.close()


# =============================================================================
# DYNAMODB OPERATIONS
# =============================================================================

def update_dynamodb_record_status(upload_id, record_id, status, error_reason=None, error_details=None):
    """
    Update DynamoDB record with validation status.
    
    Args:
        upload_id: Upload identifier
        record_id: Record identifier
        status: New status ('validated' or 'error')
        error_reason: Error type (if status is 'error')
        error_details: Detailed error message (if status is 'error')
    
    Returns:
        bool: True if successful
    """
    try:
        table = dynamodb.Table(DYNAMODB_TABLE)
        
        update_expression = "SET #status = :status, processed_at = :processed_at"
        expression_values = {
            ':status': status,
            ':processed_at': datetime.utcnow().isoformat()
        }
        expression_names = {
            '#status': 'status'
        }
        
        if error_reason:
            update_expression += ", error_reason = :error_reason, error_details = :error_details"
            expression_values[':error_reason'] = error_reason
            expression_values[':error_details'] = error_details
        
        table.update_item(
            Key={
                'upload_id': upload_id,
                'record_id': record_id
            },
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values,
            ExpressionAttributeNames=expression_names
        )
        
        return True
        
    except Exception as e:
        print(f"  ⚠ Warning: Failed to update DynamoDB record: {str(e)}")
        return False


# =============================================================================
# SQS OPERATIONS
# =============================================================================

def send_error_to_sqs(upload_id, vendor_id, record_id, row_number, product_data, 
                     error_type, error_message):
    """
    Send error record to SQS for error aggregation.
    
    Args:
        upload_id: Upload identifier
        vendor_id: Vendor identifier
        record_id: Record identifier
        row_number: Row number in CSV
        product_data: Product data
        error_type: Error type
        error_message: Error message
    
    Returns:
        bool: True if successful
    """
    if not SQS_ERROR_QUEUE_URL:
        print("  ⚠ Warning: SQS_ERROR_QUEUE_URL not configured")
        return False
    
    try:
        message_body = {
            'upload_id': upload_id,
            'vendor_id': vendor_id,
            'record_id': record_id,
            'row_number': row_number,
            'error_type': error_type,
            'error_message': error_message,
            'product_data': product_data,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        sqs_client.send_message(
            QueueUrl=SQS_ERROR_QUEUE_URL,
            MessageBody=json.dumps(message_body, default=str),
            MessageAttributes={
                'upload_id': {
                    'StringValue': upload_id,
                    'DataType': 'String'
                },
                'vendor_id': {
                    'StringValue': vendor_id,
                    'DataType': 'String'
                },
                'error_type': {
                    'StringValue': error_type,
                    'DataType': 'String'
                }
            }
        )
        
        return True
        
    except Exception as e:
        print(f"  ⚠ Warning: Failed to send error to SQS: {str(e)}")
        return False


# =============================================================================
# CLOUDWATCH METRICS
# =============================================================================

def publish_metrics(upload_id, valid_count, error_count, processing_time):
    """
    Publish validation metrics to CloudWatch.
    
    Args:
        upload_id: Upload identifier
        valid_count: Number of valid products
        error_count: Number of error products
        processing_time: Processing duration in seconds
    """
    try:
        cloudwatch.put_metric_data(
            Namespace='EcommerceProductOnboarding',
            MetricData=[
                {
                    'MetricName': 'ProductsValidated',
                    'Value': valid_count,
                    'Unit': 'Count',
                    'Timestamp': datetime.utcnow(),
                    'Dimensions': [
                        {'Name': 'UploadId', 'Value': upload_id}
                    ]
                },
                {
                    'MetricName': 'ProductsRejected',
                    'Value': error_count,
                    'Unit': 'Count',
                    'Timestamp': datetime.utcnow(),
                    'Dimensions': [
                        {'Name': 'UploadId', 'Value': upload_id}
                    ]
                },
                {
                    'MetricName': 'ValidationProcessingTime',
                    'Value': processing_time,
                    'Unit': 'Seconds',
                    'Timestamp': datetime.utcnow(),
                    'Dimensions': [
                        {'Name': 'UploadId', 'Value': upload_id}
                    ]
                }
            ]
        )
        print(f"✓ Metrics published to CloudWatch")
    except Exception as e:
        print(f"⚠ Warning: Failed to publish metrics: {str(e)}")


# =============================================================================
# MAIN LAMBDA HANDLER
# =============================================================================

def lambda_handler(event, context):
    """
    Main Lambda handler function.
    
    Triggered by: DynamoDB Streams
    
    Args:
        event: DynamoDB Stream event containing records
        context: Lambda context
    
    Returns:
        dict: Validation summary
    """
    
    start_time = datetime.utcnow()
    
    print("\n" + "="*80)
    print("Product Validator Lambda - Started (Container Image)")
    print("="*80)
    
    total_records = 0
    valid_count = 0
    error_count = 0
    
    upload_ids = set()
    
    try:
        # =====================================================================
        # STEP 1: Process DynamoDB Stream Records
        # =====================================================================
        
        print(f"\n>>> Processing {len(event['Records'])} stream records...")
        
        for stream_record in event['Records']:
            total_records += 1
            
            # Only process INSERT events
            if stream_record['eventName'] != 'INSERT':
                print(f"  Skipping {stream_record['eventName']} event")
                continue
            
            # Extract new image from stream record
            new_image = stream_record['dynamodb']['NewImage']
            
            # Parse DynamoDB types to Python types
            upload_id = new_image['upload_id']['S']
            record_id = new_image['record_id']['S']
            vendor_id = new_image['vendor_id']['S']
            row_number = int(new_image['row_number']['N'])
            
            upload_ids.add(upload_id)
            
            # Extract product_data (Map type)
            product_data_raw = new_image['product_data']['M']
            
            # Convert DynamoDB Map to Python dict
            product_data = {}
            for key, value in product_data_raw.items():
                if 'S' in value:
                    product_data[key] = value['S']
                elif 'N' in value:
                    # Handle Decimal numbers
                    product_data[key] = Decimal(value['N'])
                elif 'NULL' in value:
                    product_data[key] = None
            
            print(f"\n  Record {record_id} (Row {row_number}): {product_data.get('sku', 'N/A')}")
            
            # =================================================================
            # STEP 2: Validate Product
            # =================================================================
            
            is_valid, error_type, error_message = validate_product(product_data, vendor_id)
            
            if is_valid:
                # =============================================================
                # STEP 3A: Valid Product - Insert to RDS
                # =============================================================
                
                product_id = insert_valid_product(upload_id, vendor_id, product_data)
                
                if product_id:
                    # Update DynamoDB record status
                    update_dynamodb_record_status(upload_id, record_id, 'validated')
                    valid_count += 1
                    print(f"    ✓ VALID - Inserted to RDS (Product ID: {product_id})")
                else:
                    # Insert failed (shouldn't happen after validation)
                    error_type = 'DATABASE_INSERT_FAILED'
                    error_message = 'Failed to insert valid product to database'
                    
                    # Update DynamoDB record status
                    update_dynamodb_record_status(
                        upload_id, record_id, 'error', error_type, error_message
                    )
                    
                    # Send to SQS error queue
                    send_error_to_sqs(
                        upload_id, vendor_id, record_id, row_number,
                        product_data, error_type, error_message
                    )
                    
                    # Insert error to RDS
                    insert_validation_error(
                        upload_id, vendor_id, row_number,
                        product_data.get('vendor_product_id'),
                        error_type, error_message, product_data
                    )
                    
                    error_count += 1
                    print(f"    ✗ ERROR - {error_type}: {error_message}")
            
            else:
                # =============================================================
                # STEP 3B: Invalid Product - Handle Error
                # =============================================================
                
                # Update DynamoDB record status
                update_dynamodb_record_status(
                    upload_id, record_id, 'error', error_type, error_message
                )
                
                # Send to SQS error queue
                send_error_to_sqs(
                    upload_id, vendor_id, record_id, row_number,
                    product_data, error_type, error_message
                )
                
                # Insert error to RDS validation_errors table
                insert_validation_error(
                    upload_id, vendor_id, row_number,
                    product_data.get('vendor_product_id'),
                    error_type, error_message, product_data
                )
                
                error_count += 1
                print(f"    ✗ INVALID - {error_type}: {error_message}")
        
        # =====================================================================
        # STEP 4: Update Upload History
        # =====================================================================
        
        print(f"\n>>> Updating upload history...")
        
        for upload_id in upload_ids:
            update_upload_history_counts(upload_id, valid_count, error_count)
        
        # =====================================================================
        # STEP 5: Publish Metrics
        # =====================================================================
        
        print(f"\n>>> Publishing metrics to CloudWatch...")
        
        end_time = datetime.utcnow()
        processing_time = (end_time - start_time).total_seconds()
        
        for upload_id in upload_ids:
            publish_metrics(upload_id, valid_count, error_count, processing_time)
        
        # =====================================================================
        # Summary
        # =====================================================================
        
        print("\n" + "="*80)
        print("VALIDATION SUMMARY")
        print("="*80)
        print(f"Upload IDs: {', '.join(upload_ids)}")
        print(f"Total Records Processed: {total_records}")
        print(f"Valid Products: {valid_count}")
        print(f"Invalid Products: {error_count}")
        print(f"Success Rate: {(valid_count/total_records*100):.1f}%" if total_records > 0 else "N/A")
        print(f"Processing Time: {processing_time:.2f} seconds")
        print("="*80 + "\n")
        
        print("✓ Product Validator Lambda - Completed Successfully!")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Validation completed successfully',
                'total_records': total_records,
                'valid_count': valid_count,
                'error_count': error_count,
                'processing_time_seconds': processing_time
            })
        }
        
    except Exception as e:
        print(f"\n✗ ERROR: {str(e)}")
        print("="*80 + "\n")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'message': 'Validation failed'
            })
        }