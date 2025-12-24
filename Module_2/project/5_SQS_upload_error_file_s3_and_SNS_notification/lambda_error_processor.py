"""
Lambda Function: Error Processor (Container-based)
===================================================

Trigger: SQS (product-validation-errors queue)
Process: Aggregate validation errors and create error report CSV
Output: 
  - Error CSV file uploaded to S3 (errors/ prefix)
  - Upload history updated with error file location
  - SNS notification triggered (if all errors processed)

Container Image Deployment:
- Dockerfile builds Python 3.11 with psycopg2
- Deployed to ECR
- Lambda pulls from ECR

Error CSV Format:
Row Number, Product ID, SKU, Product Name, Error Type, Error Message, Original Data

Secrets Manager Integration:
- RDS credentials stored in AWS Secrets Manager
- Retrieved and cached using aws-secretsmanager-caching

Environment Variables:
- RDS_SECRET_NAME: ecommerce/rds/credentials
- S3_BUCKET_NAME: ecommerce-product-uploads-{account-id}
- SNS_TOPIC_ARN: arn:aws:sns:us-east-1:123456789012:product-upload-notifications
- REGION: us-east-1

IAM Permissions Required:
- sqs:ReceiveMessage, sqs:DeleteMessage (read from error queue)
- s3:PutObject (upload error CSV)
- rds:* (connect to RDS)
- sns:Publish (trigger notification)
- secretsmanager:GetSecretValue (retrieve RDS credentials)
- logs:CreateLogGroup, logs:CreateLogStream, logs:PutLogEvents
- cloudwatch:PutMetricData
- ec2:CreateNetworkInterface, ec2:DescribeNetworkInterfaces, ec2:DeleteNetworkInterface (VPC)
"""

import json
import csv
import os
import io
from datetime import datetime
from decimal import Decimal
from collections import defaultdict
import boto3
from botocore.exceptions import ClientError
import psycopg2
from psycopg2.extras import RealDictCursor
from aws_secretsmanager_caching import SecretCache, SecretCacheConfig


# =============================================================================
# ENVIRONMENT VARIABLES
# =============================================================================

RDS_SECRET_NAME = os.environ.get('RDS_SECRET_NAME', 'ecommerce/rds/credentials')
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
REGION = os.environ.get('AWS_REGION', 'us-east-1')

# AWS Clients
s3_client = boto3.client('s3', region_name=REGION)
sns_client = boto3.client('sns', region_name=REGION)
cloudwatch = boto3.client('cloudwatch', region_name=REGION)
secretsmanager = boto3.client('secretsmanager', region_name=REGION)

# Secrets Manager Cache
cache_config = SecretCacheConfig()
cache = SecretCache(config=cache_config, client=secretsmanager)

# Database connection (reused across invocations)
db_connection = None


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
    
    Returns:
        psycopg2.connection: Database connection
    """
    global db_connection
    
    try:
        # Check if connection exists and is valid
        if db_connection is not None and not db_connection.closed:
            cursor = db_connection.cursor()
            cursor.execute('SELECT 1')
            cursor.close()
            return db_connection
    except:
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
# ERROR PROCESSING FUNCTIONS
# =============================================================================

def parse_sqs_message(message):
    """
    Parse SQS message to extract error details.
    
    Args:
        message: SQS message dictionary
    
    Returns:
        dict: Parsed error data
    """
    try:
        body = json.loads(message['Body'])
        
        return {
            'upload_id': body.get('upload_id'),
            'vendor_id': body.get('vendor_id'),
            'record_id': body.get('record_id'),
            'row_number': body.get('row_number'),
            'error_type': body.get('error_type'),
            'error_message': body.get('error_message'),
            'product_data': body.get('product_data', {}),
            'timestamp': body.get('timestamp'),
            'receipt_handle': message['ReceiptHandle']
        }
    except Exception as e:
        print(f"✗ Error parsing SQS message: {str(e)}")
        return None


def group_errors_by_upload(errors):
    """
    Group errors by upload_id.
    
    Args:
        errors: List of error dictionaries
    
    Returns:
        dict: Errors grouped by upload_id
    """
    grouped = defaultdict(list)
    
    for error in errors:
        if error:
            upload_id = error.get('upload_id')
            if upload_id:
                grouped[upload_id].append(error)
    
    return dict(grouped)


def create_error_csv(errors):
    """
    Create CSV content from error list.
    
    CSV Format:
    Row Number, Vendor Product ID, SKU, Product Name, Error Type, Error Message, Price, Stock Quantity
    
    Args:
        errors: List of error dictionaries
    
    Returns:
        str: CSV content
    """
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'Row Number',
        'Vendor Product ID',
        'SKU',
        'Product Name',
        'Category',
        'Error Type',
        'Error Message',
        'Price',
        'Stock Quantity',
        'Brand',
        'Description'
    ])
    
    # Sort errors by row number
    sorted_errors = sorted(errors, key=lambda x: x.get('row_number', 0))
    
    # Write error rows
    for error in sorted_errors:
        product_data = error.get('product_data', {})
        
        writer.writerow([
            error.get('row_number', ''),
            product_data.get('vendor_product_id', ''),
            product_data.get('sku', ''),
            product_data.get('product_name', ''),
            product_data.get('category', ''),
            error.get('error_type', ''),
            error.get('error_message', ''),
            str(product_data.get('price', '')),
            str(product_data.get('stock_quantity', '')),
            product_data.get('brand', ''),
            product_data.get('description', '')[:100] + '...' if product_data.get('description') else ''
        ])
    
    csv_content = output.getvalue()
    output.close()
    
    return csv_content


def upload_error_csv_to_s3(upload_id, vendor_id, csv_content):
    """
    Upload error CSV to S3.
    
    Args:
        upload_id: Upload identifier
        vendor_id: Vendor identifier
        csv_content: CSV file content
    
    Returns:
        str: S3 key of uploaded file or None
    """
    try:
        # Generate S3 key
        s3_key = f"errors/{vendor_id}/{upload_id}_errors.csv"
        
        # Upload to S3
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=csv_content.encode('utf-8'),
            ContentType='text/csv',
            Metadata={
                'upload_id': upload_id,
                'vendor_id': vendor_id,
                'generated_at': datetime.utcnow().isoformat()
            }
        )
        
        print(f"  ✓ Uploaded error CSV to S3: s3://{S3_BUCKET_NAME}/{s3_key}")
        
        return s3_key
        
    except Exception as e:
        print(f"  ✗ Failed to upload error CSV to S3: {str(e)}")
        return None


def update_upload_history_with_error_file(upload_id, error_file_s3_key):
    """
    Update upload history with error file location.
    
    Args:
        upload_id: Upload identifier
        error_file_s3_key: S3 key of error file
    
    Returns:
        bool: True if successful
    """
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE upload_history 
            SET error_file_s3_key = %s
            WHERE upload_id = %s
        """, (error_file_s3_key, upload_id))
        
        conn.commit()
        
        print(f"  ✓ Updated upload_history with error file location")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Failed to update upload_history: {str(e)}")
        if conn:
            conn.rollback()
        return False
    
    finally:
        if cursor:
            cursor.close()


def check_upload_completion(upload_id):
    """
    Check if all records for an upload have been processed.
    
    Args:
        upload_id: Upload identifier
    
    Returns:
        tuple: (is_complete, upload_info)
    """
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT 
                upload_id,
                vendor_id,
                file_name,
                total_records,
                valid_records,
                error_records,
                status,
                error_file_s3_key
            FROM upload_history
            WHERE upload_id = %s
        """, (upload_id,))
        
        upload_info = cursor.fetchone()
        
        if not upload_info:
            return False, None
        
        # Check if all records processed
        processed = upload_info['valid_records'] + upload_info['error_records']
        is_complete = (processed == upload_info['total_records'])
        
        return is_complete, dict(upload_info)
        
    except Exception as e:
        print(f"  ✗ Error checking upload completion: {str(e)}")
        return False, None
    
    finally:
        if cursor:
            cursor.close()


def get_vendor_email(vendor_id):
    """
    Get vendor email from RDS.
    
    Args:
        vendor_id: Vendor identifier
    
    Returns:
        str: Vendor email or None
    """
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT email, vendor_name
            FROM vendors
            WHERE vendor_id = %s
        """, (vendor_id,))
        
        vendor = cursor.fetchone()
        
        if vendor:
            return vendor['email'], vendor['vendor_name']
        
        return None, None
        
    except Exception as e:
        print(f"  ✗ Error getting vendor email: {str(e)}")
        return None, None
    
    finally:
        if cursor:
            cursor.close()


def trigger_sns_notification(upload_info, error_file_s3_key):
    """
    Trigger SNS notification for upload completion.
    
    Args:
        upload_info: Upload information dictionary
        error_file_s3_key: S3 key of error file
    
    Returns:
        bool: True if successful
    """
    if not SNS_TOPIC_ARN:
        print("  ⚠ Warning: SNS_TOPIC_ARN not configured")
        return False
    
    try:
        # Get vendor email
        vendor_email, vendor_name = get_vendor_email(upload_info['vendor_id'])
        
        # Calculate success rate
        total = upload_info['total_records']
        valid = upload_info['valid_records']
        errors = upload_info['error_records']
        success_rate = (valid / total * 100) if total > 0 else 0
        
        # Generate S3 presigned URL for error file
        error_file_url = None
        if error_file_s3_key:
            error_file_url = s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': S3_BUCKET_NAME,
                    'Key': error_file_s3_key
                },
                ExpiresIn=604800  # 7 days
            )
        
        # Create email subject
        subject = f"Product Upload Complete - {upload_info['file_name']} ({success_rate:.1f}% Success)"
        
        # Create email body
        message = f"""
Product Upload Validation Complete
===================================

Upload ID: {upload_info['upload_id']}
File Name: {upload_info['file_name']}
Vendor: {vendor_name} ({upload_info['vendor_id']})

Results:
--------
Total Products: {total}
Valid Products: {valid} ({success_rate:.1f}%)
Invalid Products: {errors} ({100-success_rate:.1f}%)

Status: {upload_info['status'].upper()}

"""
        
        if errors > 0 and error_file_url:
            message += f"""
Error Details:
--------------
An error report has been generated with details of the {errors} products that failed validation.

Download Error Report: {error_file_url}
(Link expires in 7 days)

Please review the error report and correct the issues before re-uploading.

"""
        
        message += f"""
What's Next:
------------
- Valid products ({valid}) are now live in the catalog
- Invalid products ({errors}) need to be corrected and re-uploaded

For support, please contact: support@example.com

---
This is an automated notification from the Product Onboarding System.
"""
        
        # Publish to SNS
        response = sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=message,
            MessageAttributes={
                'upload_id': {
                    'StringValue': upload_info['upload_id'],
                    'DataType': 'String'
                },
                'vendor_id': {
                    'StringValue': upload_info['vendor_id'],
                    'DataType': 'String'
                },
                'vendor_email': {
                    'StringValue': vendor_email if vendor_email else 'unknown',
                    'DataType': 'String'
                },
                'status': {
                    'StringValue': upload_info['status'],
                    'DataType': 'String'
                }
            }
        )
        
        print(f"  ✓ SNS notification triggered: {response['MessageId']}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Failed to trigger SNS notification: {str(e)}")
        return False


def publish_metrics(upload_id, error_count, processing_time):
    """
    Publish error processing metrics to CloudWatch.
    
    Args:
        upload_id: Upload identifier
        error_count: Number of errors processed
        processing_time: Processing duration in seconds
    """
    try:
        cloudwatch.put_metric_data(
            Namespace='EcommerceProductOnboarding',
            MetricData=[
                {
                    'MetricName': 'ErrorsProcessed',
                    'Value': error_count,
                    'Unit': 'Count',
                    'Timestamp': datetime.utcnow(),
                    'Dimensions': [
                        {'Name': 'UploadId', 'Value': upload_id}
                    ]
                },
                {
                    'MetricName': 'ErrorProcessingTime',
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
    
    Triggered by: SQS (product-validation-errors queue)
    
    Args:
        event: SQS event containing error messages
        context: Lambda context
    
    Returns:
        dict: Processing summary
    """
    
    start_time = datetime.utcnow()
    
    print("\n" + "="*80)
    print("Error Processor Lambda - Started (Container Image)")
    print("="*80)
    
    total_messages = 0
    errors_processed = 0
    failed_messages = []
    
    try:
        # =====================================================================
        # STEP 1: Parse SQS Messages
        # =====================================================================
        
        print(f"\n>>> Step 1: Parsing {len(event['Records'])} SQS messages...")
        
        errors = []
        receipt_handles = []
        
        for record in event['Records']:
            total_messages += 1
            
            error_data = parse_sqs_message(record)
            
            if error_data:
                errors.append(error_data)
                receipt_handles.append(error_data['receipt_handle'])
                errors_processed += 1
                print(f"  ✓ Parsed error: {error_data['upload_id']} - Row {error_data['row_number']}")
            else:
                failed_messages.append(record['ReceiptHandle'])
                print(f"  ✗ Failed to parse message")
        
        print(f"  Total parsed: {errors_processed}/{total_messages}")
        
        # =====================================================================
        # STEP 2: Group Errors by Upload
        # =====================================================================
        
        print(f"\n>>> Step 2: Grouping errors by upload_id...")
        
        grouped_errors = group_errors_by_upload(errors)
        
        print(f"  Unique uploads: {len(grouped_errors)}")
        for upload_id, upload_errors in grouped_errors.items():
            print(f"    {upload_id}: {len(upload_errors)} errors")
        
        # =====================================================================
        # STEP 3: Process Each Upload
        # =====================================================================
        
        print(f"\n>>> Step 3: Processing errors for each upload...")
        
        for upload_id, upload_errors in grouped_errors.items():
            print(f"\n  Processing upload: {upload_id}")
            print(f"    Errors: {len(upload_errors)}")
            
            # Get vendor_id from first error
            vendor_id = upload_errors[0]['vendor_id']
            
            # -----------------------------------------------------------------
            # Create Error CSV
            # -----------------------------------------------------------------
            
            print(f"    Creating error CSV...")
            csv_content = create_error_csv(upload_errors)
            print(f"      ✓ CSV created ({len(csv_content)} bytes)")
            
            # -----------------------------------------------------------------
            # Upload to S3
            # -----------------------------------------------------------------
            
            print(f"    Uploading to S3...")
            error_file_s3_key = upload_error_csv_to_s3(upload_id, vendor_id, csv_content)
            
            if error_file_s3_key:
                # Update upload history
                print(f"    Updating upload history...")
                update_upload_history_with_error_file(upload_id, error_file_s3_key)
            
            # -----------------------------------------------------------------
            # Check if Upload Complete
            # -----------------------------------------------------------------
            
            print(f"    Checking upload completion...")
            is_complete, upload_info = check_upload_completion(upload_id)
            
            if is_complete:
                print(f"      ✓ Upload complete!")
                print(f"        Total: {upload_info['total_records']}")
                print(f"        Valid: {upload_info['valid_records']}")
                print(f"        Errors: {upload_info['error_records']}")
                
                # Trigger SNS notification
                print(f"    Triggering SNS notification...")
                trigger_sns_notification(upload_info, error_file_s3_key)
            else:
                print(f"      Upload still processing...")
        
        # =====================================================================
        # STEP 4: Publish Metrics
        # =====================================================================
        
        print(f"\n>>> Step 4: Publishing metrics to CloudWatch...")
        
        end_time = datetime.utcnow()
        processing_time = (end_time - start_time).total_seconds()
        
        for upload_id in grouped_errors.keys():
            publish_metrics(upload_id, len(grouped_errors[upload_id]), processing_time)
        
        # =====================================================================
        # Summary
        # =====================================================================
        
        print("\n" + "="*80)
        print("ERROR PROCESSING SUMMARY")
        print("="*80)
        print(f"Total SQS Messages: {total_messages}")
        print(f"Errors Processed: {errors_processed}")
        print(f"Unique Uploads: {len(grouped_errors)}")
        print(f"Processing Time: {processing_time:.2f} seconds")
        print("="*80 + "\n")
        
        print("✓ Error Processor Lambda - Completed Successfully!")
        
        # Note: SQS messages are automatically deleted after successful processing
        # If Lambda returns success, SQS will delete the messages
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Error processing completed successfully',
                'total_messages': total_messages,
                'errors_processed': errors_processed,
                'unique_uploads': len(grouped_errors),
                'processing_time_seconds': processing_time
            })
        }
        
    except Exception as e:
        print(f"\n✗ ERROR: {str(e)}")
        print("="*80 + "\n")
        
        # Return error - SQS will retry failed messages
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'message': 'Error processing failed'
            })
        }


# For local testing
if __name__ == '__main__':
    # Mock SQS event
    test_event = {
        'Records': [
            {
                'messageId': '1',
                'receiptHandle': 'AQEBxxx...',
                'body': json.dumps({
                    'upload_id': 'UPLOAD_20241221_103045',
                    'vendor_id': 'VEND001',
                    'record_id': 'REC_00003',
                    'row_number': 3,
                    'error_type': 'INVALID_PRICE',
                    'error_message': 'Price must be at least 0.01',
                    'product_data': {
                        'vendor_product_id': 'PROD0003',
                        'product_name': 'Invalid Product',
                        'category': 'Electronics',
                        'sku': 'TEST-SKU-003',
                        'price': -10.00,
                        'stock_quantity': 100
                    },
                    'timestamp': '2024-12-21T10:31:15.789Z'
                }),
                'attributes': {
                    'ApproximateReceiveCount': '1',
                    'SentTimestamp': '1703152875789'
                }
            }
        ]
    }
    
    class MockContext:
        function_name = 'error-processor'
        memory_limit_in_mb = 256
    
    result = lambda_handler(test_event, MockContext())
    print("\nTest Result:")
    print(json.dumps(result, indent=2))
