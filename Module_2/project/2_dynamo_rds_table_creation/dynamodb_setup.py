"""
DynamoDB Table Creation Script
===============================

Creates the UploadRecords table for tracking product upload processing.

Purpose:
- Fast ingestion of CSV records during parsing
- Real-time status tracking
- DynamoDB Streams to trigger validation Lambda
- Audit trail of all upload attempts

Table Design:
- Partition Key: upload_id (groups all records from same upload)
- Sort Key: record_id (individual product within upload)
- GSI 1: VendorIndex (query by vendor)
- GSI 2: StatusIndex (query by processing status)
- Streams: Enabled (triggers validation Lambda)
"""

import boto3
import json
from botocore.exceptions import ClientError


def create_upload_records_table(
    table_name='UploadRecords',
    region='us-east-1',
    billing_mode='PAY_PER_REQUEST'
):
    """
    Create DynamoDB UploadRecords table with indexes and streams.
    
    Args:
        table_name: Name of the table (default: UploadRecords)
        region: AWS region (default: us-east-1)
        billing_mode: PAY_PER_REQUEST or PROVISIONED
    
    Returns:
        bool: True if successful
    """
    
    # Initialize DynamoDB client
    dynamodb = boto3.client('dynamodb', region_name=region)
    
    print("\n" + "="*80)
    print(f"Creating DynamoDB Table: {table_name}")
    print("="*80 + "\n")
    
    # Table configuration
    table_config = {
        'TableName': table_name,
        
        # ========================================
        # PRIMARY KEY SCHEMA
        # ========================================
        # Partition Key: upload_id (groups records from same CSV file)
        # Sort Key: record_id (individual product record)
        'KeySchema': [
            {
                'AttributeName': 'upload_id',
                'KeyType': 'HASH'  # Partition key
            },
            {
                'AttributeName': 'record_id',
                'KeyType': 'RANGE'  # Sort key
            }
        ],
        
        # ========================================
        # ATTRIBUTE DEFINITIONS
        # ========================================
        # Only define attributes used in keys or indexes
        'AttributeDefinitions': [
            {
                'AttributeName': 'upload_id',
                'AttributeType': 'S'  # String
            },
            {
                'AttributeName': 'record_id',
                'AttributeType': 'S'  # String
            },
            {
                'AttributeName': 'vendor_id',
                'AttributeType': 'S'  # String
            },
            {
                'AttributeName': 'status',
                'AttributeType': 'S'  # String
            }
        ],
        
        # ========================================
        # GLOBAL SECONDARY INDEXES (GSI)
        # ========================================
        'GlobalSecondaryIndexes': [
            
            # GSI 1: VendorIndex
            # Purpose: Query all uploads for a specific vendor
            # Use case: Vendor dashboard, vendor analytics
            {
                'IndexName': 'VendorIndex',
                'KeySchema': [
                    {
                        'AttributeName': 'vendor_id',
                        'KeyType': 'HASH'
                    },
                    {
                        'AttributeName': 'upload_id',
                        'KeyType': 'RANGE'
                    }
                ],
                'Projection': {
                    'ProjectionType': 'ALL'  # Include all attributes
                }
            },
            
            # GSI 2: StatusIndex
            # Purpose: Query records by processing status
            # Use case: Monitor validation progress, find pending records
            {
                'IndexName': 'StatusIndex',
                'KeySchema': [
                    {
                        'AttributeName': 'upload_id',
                        'KeyType': 'HASH'
                    },
                    {
                        'AttributeName': 'status',
                        'KeyType': 'RANGE'
                    }
                ],
                'Projection': {
                    'ProjectionType': 'ALL'
                }
            }
        ],
        
        # ========================================
        # BILLING MODE
        # ========================================
        'BillingMode': billing_mode,
        
        # ========================================
        # DYNAMODB STREAMS
        # ========================================
        # CRITICAL: Enables event-driven validation workflow
        # When new record inserted → Stream event → Validation Lambda triggered
        'StreamSpecification': {
            'StreamEnabled': True,
            'StreamViewType': 'NEW_IMAGE'  # Only need new data for validation
            # Options: KEYS_ONLY, NEW_IMAGE, OLD_IMAGE, NEW_AND_OLD_IMAGES
        },
        
        # ========================================
        # TAGS
        # ========================================
        'Tags': [
            {
                'Key': 'Project',
                'Value': 'EcommerceProductOnboarding'
            },
            {
                'Key': 'Environment',
                'Value': 'Development'
            },
            {
                'Key': 'Purpose',
                'Value': 'UploadProcessingTracker'
            }
        ]
    }
    
    try:
        # Create the table
        print("Creating table with configuration:")
        print(json.dumps(table_config, indent=2, default=str))
        print()
        
        response = dynamodb.create_table(**table_config)
        
        print(f"✓ Table creation initiated: {table_name}")
        print(f"  Status: {response['TableDescription']['TableStatus']}")
        print(f"  ARN: {response['TableDescription']['TableArn']}")
        
        # Wait for table to be active
        print(f"\nWaiting for table to become ACTIVE...")
        waiter = dynamodb.get_waiter('table_exists')
        waiter.wait(TableName=table_name)
        
        # Get final table details
        response = dynamodb.describe_table(TableName=table_name)
        table_desc = response['Table']
        
        print(f"\n✓ Table {table_name} is now ACTIVE!")
        print(f"\nTable Details:")
        print(f"  Table Name: {table_desc['TableName']}")
        print(f"  Table Status: {table_desc['TableStatus']}")
        print(f"  Item Count: {table_desc.get('ItemCount', 0)}")
        print(f"  Table Size: {table_desc.get('TableSizeBytes', 0)} bytes")
        print(f"  Billing Mode: {table_desc.get('BillingModeSummary', {}).get('BillingMode', 'PROVISIONED')}")
        
        # Stream information
        if 'LatestStreamArn' in table_desc:
            print(f"\nDynamoDB Stream:")
            print(f"  Stream ARN: {table_desc['LatestStreamArn']}")
            print(f"  Stream Enabled: {table_desc['StreamSpecification']['StreamEnabled']}")
            print(f"  Stream View Type: {table_desc['StreamSpecification']['StreamViewType']}")
        
        # Indexes
        if 'GlobalSecondaryIndexes' in table_desc:
            print(f"\nGlobal Secondary Indexes:")
            for gsi in table_desc['GlobalSecondaryIndexes']:
                print(f"  - {gsi['IndexName']} ({gsi['IndexStatus']})")
        
        print("\n" + "="*80)
        print("Table created successfully!")
        print("="*80 + "\n")
        
        return True
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceInUseException':
            print(f"✗ Table {table_name} already exists!")
            return False
        else:
            print(f"✗ Error creating table: {e.response['Error']['Message']}")
            return False


def delete_table(table_name='UploadRecords', region='us-east-1'):
    """Delete DynamoDB table (use with caution!)"""
    
    dynamodb = boto3.client('dynamodb', region_name=region)
    
    try:
        print(f"\nDeleting table: {table_name}...")
        dynamodb.delete_table(TableName=table_name)
        
        print(f"Waiting for table to be deleted...")
        waiter = dynamodb.get_waiter('table_not_exists')
        waiter.wait(TableName=table_name)
        
        print(f"✓ Table {table_name} deleted successfully!")
        return True
        
    except ClientError as e:
        print(f"✗ Error deleting table: {e.response['Error']['Message']}")
        return False


def insert_sample_record(table_name='UploadRecords', region='us-east-1'):
    """Insert a sample record for testing"""
    
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)
    
    from datetime import datetime
    from decimal import Decimal
    
    sample_record = {
        'upload_id': 'UPLOAD_20241221_103045',
        'record_id': 'REC_001',
        'vendor_id': 'VEND001',
        'row_number': 1,
        'product_data': {
            'vendor_product_id': 'PROD0001',
            'product_name': 'Wireless Mouse - Model 651',
            'category': 'Computer Accessories',
            'sku': 'CA-VEND001-0001',
            'brand': 'TechGear',
            'price': Decimal('19.99'),
            'stock_quantity': 150
        },
        'status': 'pending_validation',
        'error_reason': None,
        'error_details': None,
        'processed_at': None,
        'created_at': datetime.utcnow().isoformat()
    }
    
    try:
        table.put_item(Item=sample_record)
        print(f"\n✓ Sample record inserted successfully!")
        print(f"  Upload ID: {sample_record['upload_id']}")
        print(f"  Record ID: {sample_record['record_id']}")
        return True
    except Exception as e:
        print(f"\n✗ Error inserting sample record: {str(e)}")
        return False


def query_examples(table_name='UploadRecords', region='us-east-1'):
    """Show example queries for the table"""
    
    print("\n" + "="*80)
    print("Example Query Patterns")
    print("="*80 + "\n")
    
    print("1. Get all records for a specific upload:")
    print("""
    from boto3.dynamodb.conditions import Key
    
    response = table.query(
        KeyConditionExpression=Key('upload_id').eq('UPLOAD_20241221_103045')
    )
    """)
    
    print("\n2. Get records by status within an upload:")
    print("""
    response = table.query(
        IndexName='StatusIndex',
        KeyConditionExpression=Key('upload_id').eq('UPLOAD_20241221_103045') & 
                               Key('status').eq('error')
    )
    """)
    
    print("\n3. Get all uploads for a vendor:")
    print("""
    response = table.query(
        IndexName='VendorIndex',
        KeyConditionExpression=Key('vendor_id').eq('VEND001')
    )
    """)
    
    print("\n4. Get a specific record:")
    print("""
    response = table.get_item(
        Key={
            'upload_id': 'UPLOAD_20241221_103045',
            'record_id': 'REC_001'
        }
    )
    """)


# ============================================================================
# ITEM STRUCTURE DOCUMENTATION
# ============================================================================

ITEM_STRUCTURE = """
# DynamoDB Item Structure
# =======================

{
    # Primary Key
    'upload_id': 'UPLOAD_20241221_103045',      # Partition Key
    'record_id': 'REC_001',                     # Sort Key
    
    # Vendor Information
    'vendor_id': 'VEND001',                     # GSI: VendorIndex
    
    # Row Information
    'row_number': 1,                            # CSV row number
    
    # Product Data (as received from CSV)
    'product_data': {
        'vendor_product_id': 'PROD0001',
        'product_name': 'Wireless Mouse',
        'category': 'Electronics',
        'subcategory': '',
        'description': 'Ergonomic wireless mouse...',
        'sku': 'CA-VEND001-0001',
        'brand': 'TechGear',
        'price': Decimal('29.99'),
        'compare_at_price': Decimal('39.99'),
        'stock_quantity': 150,
        'unit': 'piece',
        'weight_kg': Decimal('0.25'),
        'dimensions_cm': '12x8x4',
        'image_url': 'https://...'
    },
    
    # Processing Status
    'status': 'pending_validation',             # GSI: StatusIndex
                                                # Values: 
                                                #   - pending_validation
                                                #   - validated
                                                #   - error
    
    # Error Information (if status = 'error')
    'error_reason': 'INVALID_PRICE',            # Error type
    'error_details': 'Price must be > 0',       # Detailed message
    
    # Timestamps
    'created_at': '2024-12-21T10:30:45Z',      # When record created
    'processed_at': '2024-12-21T10:30:47Z',    # When validation completed
    
    # TTL (Optional - for auto-cleanup after 30 days)
    'ttl': 1735747845                           # Unix timestamp
}

# Status Flow:
# 1. CSV Parser creates record with status='pending_validation'
# 2. DynamoDB Stream triggers Validation Lambda
# 3. Validator updates status to 'validated' or 'error'
#    - If validated: Insert into RDS Products
#    - If error: Send to SQS error queue
"""


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == '__main__':
    import sys
    
    print("\n" + "="*80)
    print("DynamoDB Table Setup")
    print("="*80)
    
    # Configuration
    TABLE_NAME = 'UploadRecords'
    REGION = 'us-east-1'
    
    print("\nOptions:")
    print("1. Create table")
    print("2. Delete table")
    print("3. Insert sample record")
    print("4. Show query examples")
    print("5. Show item structure")
    
    if len(sys.argv) > 1:
        choice = sys.argv[1]
    else:
        choice = input("\nEnter choice (1-5): ")
    
    if choice == '1':
        create_upload_records_table(TABLE_NAME, REGION)
    
    elif choice == '2':
        confirm = input(f"Are you sure you want to delete {TABLE_NAME}? (yes/no): ")
        if confirm.lower() == 'yes':
            delete_table(TABLE_NAME, REGION)
    
    elif choice == '3':
        insert_sample_record(TABLE_NAME, REGION)
    
    elif choice == '4':
        query_examples(TABLE_NAME, REGION)
    
    elif choice == '5':
        print(ITEM_STRUCTURE)
    
    else:
        print("\nInvalid choice. Run with argument 1-5 or no argument for interactive mode.")
        print("\nExamples:")
        print("  python dynamodb_setup.py 1    # Create table")
        print("  python dynamodb_setup.py 4    # Show query examples")
