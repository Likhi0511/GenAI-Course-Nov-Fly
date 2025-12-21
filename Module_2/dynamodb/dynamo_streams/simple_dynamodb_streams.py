"""
Simple DynamoDB Streams Processor
==================================

This is a simple, straightforward implementation for processing DynamoDB Streams.
No classes, no complexity - just functions that work.

Use Case: Process stream events from the Products table and log all changes.

Author: Educational Examples
Date: December 2024
"""

import json
import boto3
from decimal import Decimal
from datetime import datetime


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def deserialize_dynamodb_json(dynamodb_json):
    """
    Convert DynamoDB JSON format to regular Python dict.
    
    DynamoDB uses format like {'S': 'value'}, {'N': '123'}, etc.
    This converts it to normal Python types.
    
    Example:
        Input:  {'Name': {'S': 'John'}, 'Age': {'N': '30'}}
        Output: {'Name': 'John', 'Age': 30}
    """
    if not dynamodb_json:
        return {}
    
    result = {}
    for key, value in dynamodb_json.items():
        result[key] = deserialize_attribute(value)
    return result


def deserialize_attribute(attribute):
    """
    Convert a single DynamoDB attribute to Python type.
    
    Type mapping:
    - S  → string
    - N  → number (Decimal)
    - BOOL → boolean
    - NULL → None
    - M  → dict
    - L  → list
    - SS → set of strings
    - NS → set of numbers
    """
    if 'S' in attribute:
        return attribute['S']
    elif 'N' in attribute:
        return Decimal(attribute['N'])
    elif 'BOOL' in attribute:
        return attribute['BOOL']
    elif 'NULL' in attribute:
        return None
    elif 'M' in attribute:
        # Recursively convert map
        return {k: deserialize_attribute(v) for k, v in attribute['M'].items()}
    elif 'L' in attribute:
        # Recursively convert list
        return [deserialize_attribute(item) for item in attribute['L']]
    elif 'SS' in attribute:
        return set(attribute['SS'])
    elif 'NS' in attribute:
        return set(Decimal(n) for n in attribute['NS'])
    else:
        return attribute


def log_event(event_type, item_keys, old_data=None, new_data=None):
    """
    Log stream event details.
    
    Args:
        event_type: INSERT, MODIFY, or REMOVE
        item_keys: Primary key of the item
        old_data: Item before change (for MODIFY/REMOVE)
        new_data: Item after change (for INSERT/MODIFY)
    """
    print("\n" + "="*80)
    print(f"EVENT: {event_type}")
    print("="*80)
    print(f"Keys: {json.dumps(item_keys, indent=2, default=str)}")
    
    if old_data:
        print(f"\nOLD DATA:")
        print(json.dumps(old_data, indent=2, default=str))
    
    if new_data:
        print(f"\nNEW DATA:")
        print(json.dumps(new_data, indent=2, default=str))
    
    print("="*80)


def calculate_changes(old_data, new_data):
    """
    Find what fields changed between old and new data.
    
    Returns:
        dict: Changed fields with old and new values
    """
    if not old_data or not new_data:
        return {}
    
    changes = {}
    
    # Check for changed or new fields
    for key, new_value in new_data.items():
        old_value = old_data.get(key)
        if old_value != new_value:
            changes[key] = {
                'old': old_value,
                'new': new_value
            }
    
    # Check for removed fields
    for key in old_data:
        if key not in new_data:
            changes[key] = {
                'old': old_data[key],
                'new': None
            }
    
    return changes


# =============================================================================
# STREAM PROCESSING FUNCTIONS
# =============================================================================

def process_insert_event(record):
    """
    Handle INSERT events - new item added to table.
    
    Args:
        record: Stream record from DynamoDB
    """
    # Get the keys
    keys = deserialize_dynamodb_json(record['dynamodb']['Keys'])
    
    # Get the new item data
    new_item = deserialize_dynamodb_json(record['dynamodb']['NewImage'])
    
    # Log the event
    log_event('INSERT', keys, new_data=new_item)
    
    # Your custom logic here
    # Example: Send notification, update analytics, etc.
    print(f"✓ New product added: {new_item.get('Name', 'Unknown')}")


def process_modify_event(record):
    """
    Handle MODIFY events - item updated in table.
    
    Args:
        record: Stream record from DynamoDB
    """
    # Get the keys
    keys = deserialize_dynamodb_json(record['dynamodb']['Keys'])
    
    # Get old and new data
    old_item = deserialize_dynamodb_json(record['dynamodb'].get('OldImage', {}))
    new_item = deserialize_dynamodb_json(record['dynamodb'].get('NewImage', {}))
    
    # Calculate what changed
    changes = calculate_changes(old_item, new_item)
    
    # Log the event
    log_event('MODIFY', keys, old_data=old_item, new_data=new_item)
    
    # Print what changed
    if changes:
        print("\nCHANGES:")
        for field, values in changes.items():
            print(f"  {field}: {values['old']} → {values['new']}")
    
    # Your custom logic here
    # Example: Update search index, invalidate cache, etc.
    print(f"✓ Product modified: {new_item.get('Name', 'Unknown')}")


def process_remove_event(record):
    """
    Handle REMOVE events - item deleted from table.
    
    Args:
        record: Stream record from DynamoDB
    """
    # Get the keys
    keys = deserialize_dynamodb_json(record['dynamodb']['Keys'])
    
    # Get the deleted item data
    old_item = deserialize_dynamodb_json(record['dynamodb'].get('OldImage', {}))
    
    # Log the event
    log_event('REMOVE', keys, old_data=old_item)
    
    # Your custom logic here
    # Example: Archive data, cleanup resources, etc.
    print(f"✓ Product deleted: {old_item.get('Name', 'Unknown')}")


def process_stream_record(record):
    """
    Process a single stream record based on event type.
    
    Args:
        record: Individual stream record from Lambda event
    """
    event_name = record['eventName']
    
    if event_name == 'INSERT':
        process_insert_event(record)
    elif event_name == 'MODIFY':
        process_modify_event(record)
    elif event_name == 'REMOVE':
        process_remove_event(record)
    else:
        print(f"Unknown event type: {event_name}")


# =============================================================================
# LAMBDA HANDLER
# =============================================================================

def lambda_handler(event, context):
    """
    Main Lambda function - processes DynamoDB Stream events.
    
    This function is called by AWS Lambda when stream events occur.
    
    Args:
        event: Contains 'Records' array with stream events
        context: Lambda context (function info, timeout, etc.)
    
    Returns:
        dict: Processing results
    """
    print(f"\n{'='*80}")
    print(f"Processing DynamoDB Stream Events")
    print(f"Received {len(event['Records'])} records")
    print(f"{'='*80}\n")
    
    successful = 0
    failed = 0
    
    # Process each record
    for record in event['Records']:
        try:
            # Process the record
            process_stream_record(record)
            successful += 1
            
        except Exception as e:
            # Log error but continue processing other records
            print(f"\n✗ ERROR processing record: {str(e)}")
            print(f"Record: {json.dumps(record, indent=2, default=str)}")
            failed += 1
    
    # Print summary
    print(f"\n{'='*80}")
    print(f"SUMMARY:")
    print(f"  Total: {len(event['Records'])}")
    print(f"  Successful: {successful}")
    print(f"  Failed: {failed}")
    print(f"{'='*80}\n")
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'processed': successful,
            'failed': failed
        })
    }


# # =============================================================================
# # EXAMPLE USE CASES
# # =============================================================================
#
# def example_analytics_processor(event, context):
#     """
#     Example: Real-time analytics for product changes.
#     Updates a daily sales summary when products are modified.
#     """
#     dynamodb = boto3.resource('dynamodb')
#     analytics_table = dynamodb.Table('ProductAnalytics')
#
#     for record in event['Records']:
#         if record['eventName'] == 'MODIFY':
#             # Get product data
#             new_item = deserialize_dynamodb_json(record['dynamodb']['NewImage'])
#             old_item = deserialize_dynamodb_json(record['dynamodb']['OldImage'])
#
#             # Check if price changed
#             old_price = old_item.get('Price')
#             new_price = new_item.get('Price')
#
#             if old_price != new_price:
#                 # Update analytics
#                 today = datetime.utcnow().strftime('%Y-%m-%d')
#                 product_id = new_item['ProductID']
#
#                 analytics_table.update_item(
#                     Key={'Date': today, 'ProductID': product_id},
#                     UpdateExpression='SET PriceChanges = PriceChanges + :inc, LastPrice = :price',
#                     ExpressionAttributeValues={
#                         ':inc': 1,
#                         ':price': new_price
#                     }
#                 )
#
#                 print(f"✓ Analytics updated: {product_id} price changed from {old_price} to {new_price}")
#
#     return {'statusCode': 200}
#
#
# def example_replication_processor(event, context):
#     """
#     Example: Replicate data to another region.
#     Copies all changes to a backup table in different region.
#     """
#     dynamodb_backup = boto3.resource('dynamodb', region_name='us-west-2')
#     backup_table = dynamodb_backup.Table('Products-Backup')
#
#     for record in event['Records']:
#         event_name = record['eventName']
#         keys = deserialize_dynamodb_json(record['dynamodb']['Keys'])
#
#         if event_name == 'INSERT' or event_name == 'MODIFY':
#             # Replicate insert/update
#             new_item = deserialize_dynamodb_json(record['dynamodb']['NewImage'])
#             backup_table.put_item(Item=new_item)
#             print(f"✓ Replicated {event_name}: {keys}")
#
#         elif event_name == 'REMOVE':
#             # Replicate delete
#             backup_table.delete_item(Key=keys)
#             print(f"✓ Replicated REMOVE: {keys}")
#
#     return {'statusCode': 200}
#
#
# def example_audit_logger(event, context):
#     """
#     Example: Create audit trail of all changes.
#     Logs every change to an audit table for compliance.
#     """
#     dynamodb = boto3.resource('dynamodb')
#     audit_table = dynamodb.Table('AuditLog')
#
#     for record in event['Records']:
#         # Create audit entry
#         audit_entry = {
#             'AuditID': record['eventID'],
#             'Timestamp': datetime.utcnow().isoformat(),
#             'EventType': record['eventName'],
#             'TableName': 'Products',
#             'Keys': deserialize_dynamodb_json(record['dynamodb']['Keys'])
#         }
#
#         # Add old/new data based on event type
#         if 'OldImage' in record['dynamodb']:
#             audit_entry['OldData'] = deserialize_dynamodb_json(record['dynamodb']['OldImage'])
#
#         if 'NewImage' in record['dynamodb']:
#             audit_entry['NewData'] = deserialize_dynamodb_json(record['dynamodb']['NewImage'])
#
#         # Save audit entry
#         audit_table.put_item(Item=audit_entry)
#         print(f"✓ Audit logged: {audit_entry['AuditID']}")
#
#     return {'statusCode': 200}
#
#
# # =============================================================================
# # LOCAL TESTING
# # =============================================================================
#
# if __name__ == '__main__':
#     """
#     Test the stream processor locally with sample data.
#     """
#
#     # Sample stream event (what Lambda receives)
#     test_event = {
#         'Records': [
#             {
#                 'eventID': '1',
#                 'eventName': 'INSERT',
#                 'eventSource': 'aws:dynamodb',
#                 'awsRegion': 'us-east-1',
#                 'dynamodb': {
#                     'Keys': {
#                         'ProductID': {'S': 'PROD-001'},
#                         'Category': {'S': 'Electronics'}
#                     },
#                     'NewImage': {
#                         'ProductID': {'S': 'PROD-001'},
#                         'Category': {'S': 'Electronics'},
#                         'Name': {'S': 'Wireless Headphones'},
#                         'Brand': {'S': 'AudioTech'},
#                         'Price': {'N': '299.99'},
#                         'Rating': {'N': '4.5'},
#                         'InStock': {'BOOL': True}
#                     },
#                     'SequenceNumber': '111',
#                     'SizeBytes': 100,
#                     'StreamViewType': 'NEW_AND_OLD_IMAGES'
#                 }
#             },
#             {
#                 'eventID': '2',
#                 'eventName': 'MODIFY',
#                 'eventSource': 'aws:dynamodb',
#                 'awsRegion': 'us-east-1',
#                 'dynamodb': {
#                     'Keys': {
#                         'ProductID': {'S': 'PROD-001'},
#                         'Category': {'S': 'Electronics'}
#                     },
#                     'OldImage': {
#                         'ProductID': {'S': 'PROD-001'},
#                         'Category': {'S': 'Electronics'},
#                         'Name': {'S': 'Wireless Headphones'},
#                         'Price': {'N': '299.99'},
#                         'Rating': {'N': '4.5'}
#                     },
#                     'NewImage': {
#                         'ProductID': {'S': 'PROD-001'},
#                         'Category': {'S': 'Electronics'},
#                         'Name': {'S': 'Wireless Headphones'},
#                         'Price': {'N': '279.99'},
#                         'Rating': {'N': '4.7'}
#                     },
#                     'SequenceNumber': '222',
#                     'SizeBytes': 120,
#                     'StreamViewType': 'NEW_AND_OLD_IMAGES'
#                 }
#             },
#             {
#                 'eventID': '3',
#                 'eventName': 'REMOVE',
#                 'eventSource': 'aws:dynamodb',
#                 'awsRegion': 'us-east-1',
#                 'dynamodb': {
#                     'Keys': {
#                         'ProductID': {'S': 'PROD-002'},
#                         'Category': {'S': 'Books'}
#                     },
#                     'OldImage': {
#                         'ProductID': {'S': 'PROD-002'},
#                         'Category': {'S': 'Books'},
#                         'Name': {'S': 'Python Programming'},
#                         'Price': {'N': '39.99'}
#                     },
#                     'SequenceNumber': '333',
#                     'SizeBytes': 80,
#                     'StreamViewType': 'NEW_AND_OLD_IMAGES'
#                 }
#             }
#         ]
#     }
#
#     # Mock context
#     class MockContext:
#         function_name = 'test-stream-processor'
#         memory_limit_in_mb = 128
#
#     # Test the processor
#     print("Testing DynamoDB Stream Processor...")
#     print("="*80)
#
#     result = lambda_handler(test_event, MockContext())
#
#     print("\nTest Complete!")
#     print(f"Result: {json.dumps(result, indent=2)}")
