"""
s3_event_lambda.py

AWS Lambda function triggered by S3 uploads
Creates control records in DynamoDB for new PDFs

Deployment:
1. Package this file with boto3
2. Create Lambda function in AWS Console
3. Set up S3 event trigger for PUT events on input/ prefix
4. Configure IAM role with DynamoDB and S3 permissions

Author: Prudhvi
Organization: Thoughtworks
"""

import json
import boto3
from datetime import datetime
import uuid
import os


# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')

# Get table names from environment variables
CONTROL_TABLE_NAME = os.environ.get('CONTROL_TABLE_NAME', 'document_processing_control')
AUDIT_TABLE_NAME = os.environ.get('AUDIT_TABLE_NAME', 'document_processing_audit')

control_table = dynamodb.Table(CONTROL_TABLE_NAME)
audit_table = dynamodb.Table(AUDIT_TABLE_NAME)


def lambda_handler(event, context):
    """
    Lambda handler triggered by S3 PUT events.
    
    Args:
        event: S3 event containing object details
        context: Lambda context
    
    Returns:
        Response with status code and message
    """
    
    print(f"Received event: {json.dumps(event)}")
    
    processed_count = 0
    errors = []
    
    for record in event['Records']:
        try:
            # Extract S3 event details
            bucket = record['s3']['bucket']['name']
            key = record['s3']['object']['key']
            size = record['s3']['object']['size']
            
            print(f"Processing S3 object: s3://{bucket}/{key} ({size} bytes)")
            
            # Only process PDFs in input/ prefix
            if not key.startswith('input/'):
                print(f"Skipping - not in input/ prefix: {key}")
                continue
            
            if not key.lower().endswith('.pdf'):
                print(f"Skipping - not a PDF: {key}")
                continue
            
            # Generate unique document ID
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            unique_id = uuid.uuid4().hex[:8]
            document_id = f"doc_{timestamp}_{unique_id}"
            
            # Create control record
            current_time = datetime.utcnow().isoformat() + 'Z'
            
            control_item = {
                'document_id': document_id,
                'processing_version': 'v1',
                'source_s3_key': key,
                'source_bucket': bucket,
                'file_size_bytes': size,
                'upload_timestamp': current_time,
                'status': 'PENDING',
                'current_stage': 'extraction',
                'created_at': current_time,
                'updated_at': current_time,
                'stage_status': {
                    'extraction': {'status': 'PENDING'},
                    'chunking': {'status': 'PENDING'},
                    'enrichment': {'status': 'PENDING'},
                    'embedding': {'status': 'PENDING'},
                    'loading': {'status': 'PENDING'}
                },
                'retry_count': 0,
                'max_retries': 3,
                'ttl': int(datetime.utcnow().timestamp()) + (90 * 24 * 3600)  # 90 days
            }
            
            control_table.put_item(Item=control_item)
            print(f"Created control record: {document_id}")
            
            # Create audit event
            audit_item = {
                'document_id': document_id,
                'timestamp': current_time,
                'event_type': 'DOCUMENT_RECEIVED',
                'stage': 'ingestion',
                'status': 'PENDING',
                'processing_version': 'v1',
                'metadata': {
                    'source': 's3_event',
                    'file_size': size,
                    'bucket': bucket,
                    'key': key
                },
                'ttl': int(datetime.utcnow().timestamp()) + (180 * 24 * 3600)  # 180 days
            }
            
            audit_table.put_item(Item=audit_item)
            print(f"Created audit record: {document_id}")
            
            processed_count += 1
            
        except Exception as e:
            error_msg = f"Error processing {key}: {str(e)}"
            print(error_msg)
            errors.append(error_msg)
    
    # Prepare response
    response = {
        'statusCode': 200 if not errors else 207,  # 207 = Multi-Status (partial success)
        'body': json.dumps({
            'message': 'Processing initiated',
            'processed': processed_count,
            'errors': errors
        })
    }
    
    print(f"Lambda execution complete. Processed: {processed_count}, Errors: {len(errors)}")
    
    return response


# For local testing
if __name__ == "__main__":
    # Sample S3 event for testing
    test_event = {
        "Records": [
            {
                "s3": {
                    "bucket": {
                        "name": "your-document-pipeline"
                    },
                    "object": {
                        "key": "input/2025/01/31/test_document.pdf",
                        "size": 2457600
                    }
                }
            }
        ]
    }
    
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))
