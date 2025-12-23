"""
DynamoDB Complete Operations - Production-Ready Python Program
================================================================

This module provides comprehensive DynamoDB operations including:
1. Table Creation with LSI and GSI
2. Insert Data (Single and Batch)
3. Retrieve Data (GetItem, Query, Scan)
4. Update Data (with conditional updates)
5. Delete Data (Single and Batch)
6. Advanced Operations (Transactions, TTL, Streams)

Author: Data Engineering Best Practices
Date: December 2024
"""

import boto3
import json
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError


class DynamoDBManager:
    """
    Comprehensive DynamoDB Manager for all table operations.
    
    Features:
    - Table lifecycle management
    - CRUD operations
    - Batch operations
    - Query and Scan with pagination
    - Transaction support
    - Index management
    """
    
    def __init__(self, region_name: str = 'us-east-1', endpoint_url: Optional[str] = None):
        """
        Initialize DynamoDB client and resource.
        
        Args:
            region_name: AWS region (default: us-east-1)
            endpoint_url: Custom endpoint for local DynamoDB (optional)
        """
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        
        # Initialize boto3 clients
        if endpoint_url:
            # For local DynamoDB
            self.dynamodb = boto3.resource(
                'dynamodb',
                region_name=region_name,
                endpoint_url=endpoint_url
            )
            self.client = boto3.client(
                'dynamodb',
                region_name=region_name,
                endpoint_url=endpoint_url
            )
        else:
            # For AWS DynamoDB
            self.dynamodb = boto3.resource('dynamodb', region_name=region_name)
            self.client = boto3.client('dynamodb', region_name=region_name)
    
    # ==================== TABLE MANAGEMENT ====================
    
    def create_table_with_indexes(
        self,
        table_name: str,
        partition_key: str,
        partition_key_type: str = 'S',
        sort_key: Optional[str] = None,
        sort_key_type: str = 'S',
        billing_mode: str = 'PAY_PER_REQUEST',
        read_capacity: int = 5,
        write_capacity: int = 5,
        global_secondary_indexes: Optional[List[Dict]] = None,
        local_secondary_indexes: Optional[List[Dict]] = None,
        stream_enabled: bool = False,
        ttl_attribute: Optional[str] = None
    ) -> bool:
        """
        Create DynamoDB table with optional GSI, LSI, Streams, and TTL.
        
        Args:
            table_name: Name of the table
            partition_key: Partition key attribute name
            partition_key_type: Type (S=String, N=Number, B=Binary)
            sort_key: Optional sort key attribute name
            sort_key_type: Sort key type
            billing_mode: 'PAY_PER_REQUEST' or 'PROVISIONED'
            read_capacity: RCU if PROVISIONED mode
            write_capacity: WCU if PROVISIONED mode
            global_secondary_indexes: List of GSI configurations
            local_secondary_indexes: List of LSI configurations
            stream_enabled: Enable DynamoDB Streams
            ttl_attribute: Attribute name for TTL
            
        Returns:
            bool: True if successful
            
        Example:
            manager.create_table_with_indexes(
                table_name='Users',
                partition_key='UserID',
                sort_key='Timestamp',
                billing_mode='PAY_PER_REQUEST',
                global_secondary_indexes=[{
                    'IndexName': 'EmailIndex',
                    'PartitionKey': 'Email',
                    'PartitionKeyType': 'S',
                    'ProjectionType': 'ALL'
                }]
            )
        """
        try:
            # Build key schema
            key_schema = [
                {'AttributeName': partition_key, 'KeyType': 'HASH'}
            ]
            
            attribute_definitions = [
                {'AttributeName': partition_key, 'AttributeType': partition_key_type}
            ]
            
            if sort_key:
                key_schema.append({'AttributeName': sort_key, 'KeyType': 'RANGE'})
                attribute_definitions.append({'AttributeName': sort_key, 'AttributeType': sort_key_type})
            
            # Prepare table parameters
            table_params = {
                'TableName': table_name,
                'KeySchema': key_schema,
                'AttributeDefinitions': attribute_definitions
            }
            
            # Billing mode
            if billing_mode == 'PROVISIONED':
                table_params['BillingMode'] = 'PROVISIONED'
                table_params['ProvisionedThroughput'] = {
                    'ReadCapacityUnits': read_capacity,
                    'WriteCapacityUnits': write_capacity
                }
            else:
                table_params['BillingMode'] = 'PAY_PER_REQUEST'
            
            # Add Global Secondary Indexes
            if global_secondary_indexes:
                gsi_list = []
                for gsi in global_secondary_indexes:
                    gsi_schema = {
                        'IndexName': gsi['IndexName'],
                        'KeySchema': [
                            {'AttributeName': gsi['PartitionKey'], 'KeyType': 'HASH'}
                        ],
                        'Projection': {'ProjectionType': gsi.get('ProjectionType', 'ALL')}
                    }
                    
                    # Add attribute definition if not already present
                    if not any(attr['AttributeName'] == gsi['PartitionKey'] for attr in attribute_definitions):
                        attribute_definitions.append({
                            'AttributeName': gsi['PartitionKey'],
                            'AttributeType': gsi.get('PartitionKeyType', 'S')
                        })
                    
                    # Add sort key if specified
                    if 'SortKey' in gsi:
                        gsi_schema['KeySchema'].append({
                            'AttributeName': gsi['SortKey'],
                            'KeyType': 'RANGE'
                        })
                        if not any(attr['AttributeName'] == gsi['SortKey'] for attr in attribute_definitions):
                            attribute_definitions.append({
                                'AttributeName': gsi['SortKey'],
                                'AttributeType': gsi.get('SortKeyType', 'S')
                            })
                    
                    # Add provisioned throughput if PROVISIONED mode
                    if billing_mode == 'PROVISIONED':
                        gsi_schema['ProvisionedThroughput'] = {
                            'ReadCapacityUnits': gsi.get('ReadCapacity', 5),
                            'WriteCapacityUnits': gsi.get('WriteCapacity', 5)
                        }
                    
                    gsi_list.append(gsi_schema)
                
                table_params['GlobalSecondaryIndexes'] = gsi_list
            
            # Add Local Secondary Indexes
            if local_secondary_indexes:
                lsi_list = []
                for lsi in local_secondary_indexes:
                    lsi_schema = {
                        'IndexName': lsi['IndexName'],
                        'KeySchema': [
                            {'AttributeName': partition_key, 'KeyType': 'HASH'},
                            {'AttributeName': lsi['SortKey'], 'KeyType': 'RANGE'}
                        ],
                        'Projection': {'ProjectionType': lsi.get('ProjectionType', 'ALL')}
                    }
                    
                    # Add attribute definition if not already present
                    if not any(attr['AttributeName'] == lsi['SortKey'] for attr in attribute_definitions):
                        attribute_definitions.append({
                            'AttributeName': lsi['SortKey'],
                            'AttributeType': lsi.get('SortKeyType', 'S')
                        })
                    
                    lsi_list.append(lsi_schema)
                
                table_params['LocalSecondaryIndexes'] = lsi_list
            
            # Enable DynamoDB Streams
            if stream_enabled:
                table_params['StreamSpecification'] = {
                    'StreamEnabled': True,
                    'StreamViewType': 'NEW_AND_OLD_IMAGES'  # Can be KEYS_ONLY, NEW_IMAGE, OLD_IMAGE, NEW_AND_OLD_IMAGES
                }
            
            # Create table
            table = self.dynamodb.create_table(**table_params)
            
            # Wait for table to be created
            print(f"Creating table {table_name}...")
            table.wait_until_exists()
            print(f"✓ Table {table_name} created successfully!")
            
            # Enable TTL if specified
            if ttl_attribute:
                self.enable_ttl(table_name, ttl_attribute)
            
            # Print table info
            self.describe_table(table_name)
            
            return True
            
        except ClientError as e:
            print(f"✗ Error creating table: {e.response['Error']['Message']}")
            return False
    
    def describe_table(self, table_name: str) -> None:
        """Print detailed table information."""
        try:
            response = self.client.describe_table(TableName=table_name)
            table = response['Table']
            
            print(f"\n{'='*60}")
            print(f"Table: {table['TableName']}")
            print(f"Status: {table['TableStatus']}")
            print(f"Item Count: {table.get('ItemCount', 0)}")
            print(f"Size (bytes): {table.get('TableSizeBytes', 0)}")
            print(f"Billing Mode: {table.get('BillingModeSummary', {}).get('BillingMode', 'PROVISIONED')}")
            
            if 'GlobalSecondaryIndexes' in table:
                print(f"\nGlobal Secondary Indexes: {len(table['GlobalSecondaryIndexes'])}")
                for gsi in table['GlobalSecondaryIndexes']:
                    print(f"  - {gsi['IndexName']} ({gsi['IndexStatus']})")
            
            if 'LocalSecondaryIndexes' in table:
                print(f"\nLocal Secondary Indexes: {len(table['LocalSecondaryIndexes'])}")
                for lsi in table['LocalSecondaryIndexes']:
                    print(f"  - {lsi['IndexName']}")
            
            print(f"{'='*60}\n")
            
        except ClientError as e:
            print(f"✗ Error describing table: {e.response['Error']['Message']}")
    
    def delete_table(self, table_name: str) -> bool:
        """Delete a DynamoDB table."""
        try:
            table = self.dynamodb.Table(table_name)
            table.delete()
            print(f"Deleting table {table_name}...")
            table.wait_until_not_exists()
            print(f"✓ Table {table_name} deleted successfully!")
            return True
        except ClientError as e:
            print(f"✗ Error deleting table: {e.response['Error']['Message']}")
            return False
    
    # ==================== INSERT OPERATIONS ====================
    
    def insert_item(self, table_name: str, item: Dict[str, Any]) -> bool:
        """
        Insert a single item into DynamoDB table.
        
        Args:
            table_name: Name of the table
            item: Dictionary representing the item
            
        Returns:
            bool: True if successful
            
        Example:
            manager.insert_item('Users', {
                'UserID': 'user123',
                'Name': 'John Doe',
                'Email': 'john@example.com',
                'Age': 30
            })
        """
        try:
            table = self.dynamodb.Table(table_name)
            
            # Convert float to Decimal for DynamoDB
            item = self._convert_floats_to_decimal(item)
            
            table.put_item(Item=item)
            print(f"✓ Item inserted successfully!")
            return True
            
        except ClientError as e:
            print(f"✗ Error inserting item: {e.response['Error']['Message']}")
            return False
    
    def batch_insert_items(self, table_name: str, items: List[Dict[str, Any]]) -> bool:
        """
        Batch insert multiple items (up to 25 per batch).
        
        Args:
            table_name: Name of the table
            items: List of items to insert
            
        Returns:
            bool: True if all successful
            
        Example:
            items = [
                {'UserID': 'user1', 'Name': 'Alice'},
                {'UserID': 'user2', 'Name': 'Bob'},
                # ... up to 25 items
            ]
            manager.batch_insert_items('Users', items)
        """
        try:
            table = self.dynamodb.Table(table_name)
            
            # Process in batches of 25 (DynamoDB limit)
            batch_size = 25
            total_items = len(items)
            
            for i in range(0, total_items, batch_size):
                batch = items[i:i + batch_size]
                
                with table.batch_writer() as writer:
                    for item in batch:
                        item = self._convert_floats_to_decimal(item)
                        writer.put_item(Item=item)
                
                print(f"✓ Batch {i//batch_size + 1}: Inserted {len(batch)} items")
            
            print(f"✓ Total {total_items} items inserted successfully!")
            return True
            
        except ClientError as e:
            print(f"✗ Error in batch insert: {e.response['Error']['Message']}")
            return False
    
    # ==================== RETRIEVE OPERATIONS ====================
    
    def get_item(
        self,
        table_name: str,
        key: Dict[str, Any],
        consistent_read: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single item by primary key.
        
        Args:
            table_name: Name of the table
            key: Primary key (partition key and sort key if applicable)
            consistent_read: Use strongly consistent read (default: False)
            
        Returns:
            Item dictionary or None if not found
            
        Example:
            item = manager.get_item('Users', {'UserID': 'user123'})
            item = manager.get_item('Orders', {
                'UserID': 'user123',
                'OrderTimestamp': '2024-12-01T10:30:00Z'
            })
        """
        try:
            table = self.dynamodb.Table(table_name)
            
            response = table.get_item(
                Key=key,
                ConsistentRead=consistent_read
            )
            
            item = response.get('Item')
            if item:
                print(f"✓ Item found!")
                return self._convert_decimals_to_float(item)
            else:
                print(f"✗ Item not found")
                return None
                
        except ClientError as e:
            print(f"✗ Error retrieving item: {e.response['Error']['Message']}")
            return None
    
    def query_items(
        self,
        table_name: str,
        key_condition_expression: Any,
        filter_expression: Optional[Any] = None,
        index_name: Optional[str] = None,
        limit: Optional[int] = None,
        scan_forward: bool = True,
        consistent_read: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Query items using partition key and optional sort key condition.
        
        Args:
            table_name: Name of the table
            key_condition_expression: Key condition (e.g., Key('UserID').eq('user123'))
            filter_expression: Optional filter after query
            index_name: GSI or LSI name (optional)
            limit: Maximum items to return
            scan_forward: True for ascending, False for descending
            consistent_read: Strongly consistent read (not available for GSI)
            
        Returns:
            List of items
            
        Example:
            # Query all orders for a user
            items = manager.query_items(
                'Orders',
                Key('UserID').eq('user123')
            )
            
            # Query with sort key condition
            items = manager.query_items(
                'Orders',
                Key('UserID').eq('user123') & Key('OrderTimestamp').begins_with('2024-12')
            )
            
            # Query with filter
            items = manager.query_items(
                'Orders',
                Key('UserID').eq('user123'),
                filter_expression=Attr('TotalAmount').gt(100)
            )
            
            # Query using GSI
            items = manager.query_items(
                'Products',
                Key('Category').eq('Electronics'),
                index_name='CategoryIndex'
            )
        """
        try:
            table = self.dynamodb.Table(table_name)
            
            query_params = {
                'KeyConditionExpression': key_condition_expression,
                'ScanIndexForward': scan_forward
            }
            
            if filter_expression:
                query_params['FilterExpression'] = filter_expression
            
            if index_name:
                query_params['IndexName'] = index_name
            
            if limit:
                query_params['Limit'] = limit
            
            if consistent_read and not index_name:
                query_params['ConsistentRead'] = consistent_read
            
            # Handle pagination
            items = []
            while True:
                response = table.query(**query_params)
                items.extend(response['Items'])
                
                if 'LastEvaluatedKey' not in response:
                    break
                
                query_params['ExclusiveStartKey'] = response['LastEvaluatedKey']
            
            print(f"✓ Query returned {len(items)} items")
            return [self._convert_decimals_to_float(item) for item in items]
            
        except ClientError as e:
            print(f"✗ Error querying items: {e.response['Error']['Message']}")
            return []
    
    def scan_table(
        self,
        table_name: str,
        filter_expression: Optional[Any] = None,
        index_name: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Scan entire table (expensive operation - use sparingly).
        
        Args:
            table_name: Name of the table
            filter_expression: Optional filter condition
            index_name: GSI or LSI name (optional)
            limit: Maximum items to return
            
        Returns:
            List of items
            
        Example:
            # Scan with filter
            items = manager.scan_table(
                'Products',
                filter_expression=Attr('Price').lt(50) & Attr('InStock').eq(True)
            )
        """
        try:
            table = self.dynamodb.Table(table_name)
            
            scan_params = {}
            
            if filter_expression:
                scan_params['FilterExpression'] = filter_expression
            
            if index_name:
                scan_params['IndexName'] = index_name
            
            if limit:
                scan_params['Limit'] = limit
            
            # Handle pagination
            items = []
            while True:
                response = table.scan(**scan_params)
                items.extend(response['Items'])
                
                if 'LastEvaluatedKey' not in response:
                    break
                
                scan_params['ExclusiveStartKey'] = response['LastEvaluatedKey']
            
            print(f"✓ Scan returned {len(items)} items")
            return [self._convert_decimals_to_float(item) for item in items]
            
        except ClientError as e:
            print(f"✗ Error scanning table: {e.response['Error']['Message']}")
            return []
    
    # ==================== UPDATE OPERATIONS ====================
    
    def update_item(
        self,
        table_name: str,
        key: Dict[str, Any],
        update_expression: str,
        expression_values: Dict[str, Any],
        condition_expression: Optional[str] = None,
        condition_values: Optional[Dict[str, Any]] = None,
        return_values: str = 'ALL_NEW'
    ) -> Optional[Dict[str, Any]]:
        """
        Update an item with conditional updates support.

        Args:
            table_name: Name of the table
            key: Primary key
            update_expression: Update expression (e.g., "SET Age = :val")
            expression_values: Values for expression (e.g., {':val': 31})
            condition_expression: Optional condition (e.g., "attribute_exists(UserID)")
            condition_values: Additional values for condition expression (e.g., {':expected': 5})
            return_values: What to return (NONE, ALL_OLD, UPDATED_OLD, ALL_NEW, UPDATED_NEW)

        Returns:
            Updated item or None if condition fails

        Example:
            # Simple update
            manager.update_item(
                'Users',
                {'UserID': 'user123'},
                'SET Age = :age, LastLogin = :login',
                {':age': 31, ':login': '2024-12-20T10:00:00Z'}
            )

            # Conditional update (optimistic locking)
            manager.update_item(
                'Users',
                {'UserID': 'user123'},
                'SET Balance = Balance + :amount, Version = Version + :inc',
                {':amount': 100, ':inc': 1},
                condition_expression='Version = :expected',
                condition_values={':expected': 5}
            )
        """
        try:
            table = self.dynamodb.Table(table_name)

            # Convert floats to Decimal
            expression_values = self._convert_floats_to_decimal(expression_values)

            # Merge condition values with expression values if provided
            if condition_values:
                condition_values = self._convert_floats_to_decimal(condition_values)
                expression_values.update(condition_values)

            update_params = {
                'Key': key,
                'UpdateExpression': update_expression,
                'ExpressionAttributeValues': expression_values,
                'ReturnValues': return_values
            }

            if condition_expression:
                update_params['ConditionExpression'] = condition_expression

            response = table.update_item(**update_params)

            print(f"✓ Item updated successfully!")

            if 'Attributes' in response:
                return self._convert_decimals_to_float(response['Attributes'])
            return None

        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                print(f"✗ Conditional update failed - condition not met")
            else:
                print(f"✗ Error updating item: {e.response['Error']['Message']}")
            return None

    # ==================== DELETE OPERATIONS ====================

    def delete_item(
        self,
        table_name: str,
        key: Dict[str, Any],
        condition_expression: Optional[str] = None
    ) -> bool:
        """
        Delete a single item.

        Args:
            table_name: Name of the table
            key: Primary key
            condition_expression: Optional condition for delete

        Returns:
            bool: True if successful

        Example:
            manager.delete_item('Users', {'UserID': 'user123'})
        """
        try:
            table = self.dynamodb.Table(table_name)

            delete_params = {'Key': key}

            if condition_expression:
                delete_params['ConditionExpression'] = condition_expression

            table.delete_item(**delete_params)
            print(f"✓ Item deleted successfully!")
            return True

        except ClientError as e:
            print(f"✗ Error deleting item: {e.response['Error']['Message']}")
            return False

    def batch_delete_items(self, table_name: str, keys: List[Dict[str, Any]]) -> bool:
        """
        Batch delete multiple items.

        Args:
            table_name: Name of the table
            keys: List of primary keys

        Returns:
            bool: True if all successful

        Example:
            keys = [
                {'UserID': 'user1'},
                {'UserID': 'user2'},
                {'UserID': 'user3'}
            ]
            manager.batch_delete_items('Users', keys)
        """
        try:
            table = self.dynamodb.Table(table_name)

            batch_size = 25
            total_keys = len(keys)

            for i in range(0, total_keys, batch_size):
                batch = keys[i:i + batch_size]

                with table.batch_writer() as writer:
                    for key in batch:
                        writer.delete_item(Key=key)

                print(f"✓ Batch {i//batch_size + 1}: Deleted {len(batch)} items")

            print(f"✓ Total {total_keys} items deleted successfully!")
            return True

        except ClientError as e:
            print(f"✗ Error in batch delete: {e.response['Error']['Message']}")
            return False

    # ==================== ADVANCED OPERATIONS ====================

    def transact_write_items(self, transact_items: List[Dict[str, Any]]) -> bool:
        """
        Execute a transaction with multiple write operations.

        Args:
            transact_items: List of transaction items (Put, Update, Delete, ConditionCheck)

        Returns:
            bool: True if transaction succeeds

        Example:
            transact_items = [
                {
                    'Put': {
                        'TableName': 'Users',
                        'Item': {'UserID': 'user123', 'Name': 'John'}
                    }
                },
                {
                    'Update': {
                        'TableName': 'Accounts',
                        'Key': {'AccountID': 'acc123'},
                        'UpdateExpression': 'SET Balance = Balance - :amount',
                        'ExpressionAttributeValues': {':amount': 100}
                    }
                }
            ]
            manager.transact_write_items(transact_items)
        """
        try:
            self.client.transact_write_items(TransactItems=transact_items)
            print(f"✓ Transaction completed successfully!")
            return True

        except ClientError as e:
            if e.response['Error']['Code'] == 'TransactionCanceledException':
                print(f"✗ Transaction cancelled: {e.response['Error']['Message']}")
            else:
                print(f"✗ Transaction error: {e.response['Error']['Message']}")
            return False

    def enable_ttl(self, table_name: str, ttl_attribute: str) -> bool:
        """
        Enable Time To Live (TTL) on a table.

        Args:
            table_name: Name of the table
            ttl_attribute: Attribute name containing expiration timestamp

        Returns:
            bool: True if successful

        Example:
            # Items will be automatically deleted after TTL expires
            manager.enable_ttl('Sessions', 'ExpirationTime')

            # When inserting items, add TTL attribute:
            item = {
                'SessionID': 'sess123',
                'Data': 'some data',
                'ExpirationTime': int(time.time()) + 3600  # Expires in 1 hour
            }
        """
        try:
            self.client.update_time_to_live(
                TableName=table_name,
                TimeToLiveSpecification={
                    'Enabled': True,
                    'AttributeName': ttl_attribute
                }
            )
            print(f"✓ TTL enabled on {table_name} with attribute {ttl_attribute}")
            return True

        except ClientError as e:
            print(f"✗ Error enabling TTL: {e.response['Error']['Message']}")
            return False

    # ==================== HELPER METHODS ====================

    def _convert_floats_to_decimal(self, obj: Any) -> Any:
        """Convert floats to Decimal for DynamoDB compatibility."""
        if isinstance(obj, float):
            return Decimal(str(obj))
        elif isinstance(obj, dict):
            return {k: self._convert_floats_to_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_floats_to_decimal(item) for item in obj]
        return obj

    def _convert_decimals_to_float(self, obj: Any) -> Any:
        """Convert Decimal back to float for easier handling."""
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: self._convert_decimals_to_float(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_decimals_to_float(item) for item in obj]
        return obj

    def print_items(self, items: List[Dict[str, Any]], limit: int = 10) -> None:
        """Pretty print items."""
        print(f"\n{'='*80}")
        print(f"Showing {min(len(items), limit)} of {len(items)} items:")
        print(f"{'='*80}")

        for i, item in enumerate(items[:limit], 1):
            print(f"\nItem {i}:")
            print(json.dumps(item, indent=2, default=str))

        if len(items) > limit:
            print(f"\n... and {len(items) - limit} more items")

        print(f"{'='*80}\n")


# ==================== EXAMPLE USAGE ====================

def main():
    """
    Demonstration of all DynamoDB operations.
    """

    # Initialize manager (use endpoint_url for local DynamoDB)
    manager = DynamoDBManager(region_name='us-east-1')
    # For local: manager = DynamoDBManager(region_name='us-east-1', endpoint_url='http://localhost:8000')

    print("\n" + "="*80)
    print("DynamoDB Operations Demo")
    print("="*80 + "\n")

    # ========== 1. CREATE TABLE WITH INDEXES ==========
    print("\n>>> 1. Creating Table with GSI and LSI...")

    manager.create_table_with_indexes(
        table_name='Products',
        partition_key='ProductID',
        partition_key_type='S',
        sort_key='Category',
        sort_key_type='S',
        billing_mode='PAY_PER_REQUEST',
        global_secondary_indexes=[
            {
                'IndexName': 'CategoryPriceIndex',
                'PartitionKey': 'Category',
                'PartitionKeyType': 'S',
                'SortKey': 'Price',
                'SortKeyType': 'N',
                'ProjectionType': 'ALL'
            },
            {
                'IndexName': 'BrandIndex',
                'PartitionKey': 'Brand',
                'PartitionKeyType': 'S',
                'ProjectionType': 'ALL'
            }
        ],
        local_secondary_indexes=[
            {
                'IndexName': 'ProductRatingIndex',
                'SortKey': 'Rating',
                'SortKeyType': 'N',
                'ProjectionType': 'ALL'
            }
        ],
        stream_enabled=True,
        ttl_attribute='ExpirationTime'
    )

    # Wait for table to be ready
    time.sleep(5)

    # ========== 2. INSERT SINGLE ITEM ==========
    print("\n>>> 2. Inserting Single Item...")

    manager.insert_item('Products', {
        'ProductID': 'PROD-001',
        'Category': 'Electronics',
        'Name': 'Wireless Headphones',
        'Brand': 'AudioTech',
        'Price': 299.99,
        'Rating': 4.5,
        'InStock': True,
        'Tags': ['wireless', 'bluetooth', 'noise-cancelling'],
        'Specifications': {
            'BatteryLife': '30 hours',
            'Weight': '250g',
            'Color': 'Black'
        }
    })

    # ========== 3. BATCH INSERT ITEMS ==========
    print("\n>>> 3. Batch Inserting Items...")

    products = [
        {
            'ProductID': 'PROD-002',
            'Category': 'Books',
            'Name': 'Python Programming',
            'Brand': 'TechPublishers',
            'Price': 39.99,
            'Rating': 4.8,
            'InStock': True,
            'Tags': ['programming', 'python', 'education']
        },
        {
            'ProductID': 'PROD-003',
            'Category': 'Electronics',
            'Name': 'Smart Watch',
            'Brand': 'TechGadgets',
            'Price': 199.99,
            'Rating': 4.3,
            'InStock': True,
            'Tags': ['smartwatch', 'fitness', 'wearable']
        },
        {
            'ProductID': 'PROD-004',
            'Category': 'Clothing',
            'Name': 'Running Shoes',
            'Brand': 'SportWear',
            'Price': 89.99,
            'Rating': 4.6,
            'InStock': False,
            'Tags': ['shoes', 'running', 'sports']
        },
        {
            'ProductID': 'PROD-005',
            'Category': 'Electronics',
            'Name': 'Laptop Stand',
            'Brand': 'OfficeEssentials',
            'Price': 49.99,
            'Rating': 4.4,
            'InStock': True,
            'Tags': ['office', 'ergonomic', 'laptop']
        }
    ]

    manager.batch_insert_items('Products', products)

    # ========== 4. GET ITEM ==========
    print("\n>>> 4. Getting Single Item...")

    item = manager.get_item('Products', {
        'ProductID': 'PROD-001',
        'Category': 'Electronics'
    })

    if item:
        manager.print_items([item], limit=1)

    # ========== 5. QUERY WITH PARTITION KEY ==========
    print("\n>>> 5. Querying Items by Category (GSI)...")

    electronics = manager.query_items(
        'Products',
        Key('Category').eq('Electronics'),
        index_name='CategoryPriceIndex'
    )

    manager.print_items(electronics)

    # ========== 6. QUERY WITH SORT KEY CONDITION ==========
    print("\n>>> 6. Querying Electronics with Price < 200...")

    affordable_electronics = manager.query_items(
        'Products',
        key_condition_expression=Key('Category').eq('Electronics') & Key('Price').lt(Decimal('200')),
        index_name='CategoryPriceIndex'
    )

    manager.print_items(affordable_electronics)

    # ========== 7. QUERY WITH FILTER ==========
    print("\n>>> 7. Querying In-Stock Electronics...")

    in_stock_electronics = manager.query_items(
        'Products',
        key_condition_expression = Key('Category').eq('Electronics'),
        filter_expression=Attr('InStock').eq(True),
        index_name='CategoryPriceIndex'
    )

    manager.print_items(in_stock_electronics)

    # ========== 8. SCAN WITH FILTER ==========
    print("\n>>> 8. Scanning for Highly Rated Products (Rating >= 4.5)...")

    high_rated = manager.scan_table(
        'Products',
        filter_expression=Attr('Rating').gte(Decimal('4.5'))
    )

    manager.print_items(high_rated)

    # ========== 9. UPDATE ITEM ==========
    print("\n>>> 9. Updating Item...")

    updated_item = manager.update_item(
        'Products',
        {'ProductID': 'PROD-001', 'Category': 'Electronics'},
        'SET Price = :price, Rating = :rating, LastUpdated = :timestamp',
        {
            ':price': Decimal('279.99'),
            ':rating': Decimal('4.7'),
            ':timestamp': datetime.now().isoformat()
        }
    )

    if updated_item:
        manager.print_items([updated_item], limit=1)

    # ========== 10. CONDITIONAL UPDATE ==========
    print("\n>>> 10. Conditional Update (Stock Management)...")

    # This will succeed only if InStock is True
    result = manager.update_item(
        'Products',
        {'ProductID': 'PROD-003', 'Category': 'Electronics'},
        'SET InStock = :false',
        {':false': False},
        condition_expression='InStock = :true',
        condition_values={':true': True}
    )

    # ========== 11. TRANSACTION EXAMPLE ==========
    print("\n>>> 11. Transaction Example (Transfer operation)...")

    # Example: Transfer stock from one product to another
    transact_items = [
        {
            'Update': {
                'TableName': 'Products',
                'Key': {'ProductID': {'S': 'PROD-001'}, 'Category': {'S': 'Electronics'}},
                'UpdateExpression': 'SET Price = Price - :discount',
                'ExpressionAttributeValues': {':discount': {'N': '20'}}
            }
        },
        {
            'Update': {
                'TableName': 'Products',
                'Key': {'ProductID': {'S': 'PROD-005'}, 'Category': {'S': 'Electronics'}},
                'UpdateExpression': 'SET Price = Price + :increase',
                'ExpressionAttributeValues': {':increase': {'N': '10'}}
            }
        }
    ]

    manager.transact_write_items(transact_items)

    # ========== 12. DELETE ITEM ==========
    print("\n>>> 12. Deleting Single Item...")

    manager.delete_item('Products', {
        'ProductID': 'PROD-004',
        'Category': 'Clothing'
    })

    # ========== 13. VERIFY FINAL STATE ==========
    print("\n>>> 13. Final Scan - All Remaining Products...")

    all_products = manager.scan_table('Products')
    manager.print_items(all_products)

    # ========== 14. CLEANUP (Optional) ==========
    # Uncomment to delete the table
    # print("\n>>> 14. Cleaning Up - Deleting Table...")
    # manager.delete_table('Products')

    print("\n" + "="*80)
    print("Demo Complete!")
    print("="*80 + "\n")


if __name__ == '__main__':
    main()