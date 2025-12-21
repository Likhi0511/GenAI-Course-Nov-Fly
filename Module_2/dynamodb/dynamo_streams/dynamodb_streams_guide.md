# DynamoDB Streams - Complete Guide

## Table of Contents
1. [What are DynamoDB Streams?](#what-are-dynamodb-streams)
2. [Architecture & How Streams Work](#architecture--how-streams-work)
3. [Stream View Types](#stream-view-types)
4. [Use Cases](#use-cases)
5. [Setting Up Streams](#setting-up-streams)
6. [Processing Stream Records](#processing-stream-records)
7. [Lambda Integration](#lambda-integration)
8. [Best Practices](#best-practices)
9. [Monitoring & Troubleshooting](#monitoring--troubleshooting)

---

## What are DynamoDB Streams?

DynamoDB Streams is a feature that captures a time-ordered sequence of item-level modifications in a DynamoDB table and stores this information in a log for up to 24 hours.

### Key Characteristics

| Feature | Description |
|---------|-------------|
| **Capture** | All INSERT, UPDATE, DELETE operations |
| **Ordering** | Guaranteed order within a partition key |
| **Retention** | 24 hours |
| **Near Real-time** | Millisecond latency |
| **Durability** | Stored across multiple AZs |
| **Exactly-once** | Each record appears exactly once in the stream |
| **Cost** | Pay per read request unit |

### When to Use Streams

✅ **Good Use Cases:**
- Real-time analytics and aggregations
- Data replication across regions or tables
- Triggering workflows on data changes
- Audit trails and change tracking
- Maintaining materialized views
- Cross-service data synchronization
- Event-driven architectures

❌ **Not Ideal For:**
- Long-term archival (use S3 exports instead)
- Complex transformations (consider ETL pipelines)
- High-latency acceptable scenarios (use scheduled jobs)

---

## Architecture & How Streams Work

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      DynamoDB Table                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Item 1   │  │ Item 2   │  │ Item 3   │  │ Item 4   │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│       ▼              ▼              ▼              ▼            │
│    INSERT         UPDATE         DELETE         UPDATE          │
└─────────────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DynamoDB Stream                              │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐               │
│  │  Shard 1   │  │  Shard 2   │  │  Shard 3   │               │
│  │ (Records)  │  │ (Records)  │  │ (Records)  │               │
│  └────────────┘  └────────────┘  └────────────┘               │
│       ▼                ▼                ▼                       │
│  Stream Records with 24-hour retention                         │
└─────────────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Stream Consumers                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Lambda 1 │  │ Lambda 2 │  │ Kinesis  │  │  Custom  │       │
│  │Analytics │  │Replicator│  │ Firehose │  │ Consumer │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

### Stream Record Structure

Each stream record contains:

```json
{
  "eventID": "1",
  "eventName": "INSERT | MODIFY | REMOVE",
  "eventVersion": "1.1",
  "eventSource": "aws:dynamodb",
  "awsRegion": "us-east-1",
  "dynamodb": {
    "ApproximateCreationDateTime": 1640000000,
    "Keys": {
      "ProductID": {"S": "PROD-001"}
    },
    "NewImage": {
      "ProductID": {"S": "PROD-001"},
      "Name": {"S": "Laptop"},
      "Price": {"N": "999"}
    },
    "OldImage": {
      "ProductID": {"S": "PROD-001"},
      "Name": {"S": "Laptop"},
      "Price": {"N": "899"}
    },
    "SequenceNumber": "111",
    "SizeBytes": 26,
    "StreamViewType": "NEW_AND_OLD_IMAGES"
  },
  "eventSourceARN": "arn:aws:dynamodb:us-east-1:123456789:table/Products/stream/2024-12-20T10:30:00.000"
}
```

### Sharding

- DynamoDB automatically manages shards
- Each shard processes records from specific partition keys
- Shards split/merge automatically based on throughput
- Records within a shard are ordered

---

## Stream View Types

When enabling streams, you must choose what data to capture:

### 1. KEYS_ONLY

**Captures:** Only the key attributes of the modified item

**Use Cases:**
- Triggering actions without needing old/new values
- Counting operations
- Simple notifications

**Example Record:**
```json
{
  "eventName": "MODIFY",
  "dynamodb": {
    "Keys": {
      "UserID": {"S": "user123"},
      "Timestamp": {"S": "2024-12-20T10:00:00Z"}
    }
  }
}
```

**Pros:**
- Smallest record size
- Lowest cost
- Fastest processing

**Cons:**
- No access to actual data
- Need to query table if data needed

---

### 2. NEW_IMAGE

**Captures:** Key attributes + entire item as it appears AFTER modification

**Use Cases:**
- Real-time data replication
- Maintaining read replicas
- Search index updates
- Cache invalidation

**Example Record:**
```json
{
  "eventName": "MODIFY",
  "dynamodb": {
    "Keys": {
      "UserID": {"S": "user123"}
    },
    "NewImage": {
      "UserID": {"S": "user123"},
      "Name": {"S": "John Doe"},
      "Email": {"S": "john@example.com"},
      "Age": {"N": "31"}
    }
  }
}
```

**Pros:**
- See current state after change
- No need to query table
- Sufficient for most replication

**Cons:**
- Can't see what changed
- Larger than KEYS_ONLY

---

### 3. OLD_IMAGE

**Captures:** Key attributes + entire item as it appeared BEFORE modification

**Use Cases:**
- Audit trails
- Rollback scenarios
- Tracking deleted items
- Historical data capture

**Example Record:**
```json
{
  "eventName": "MODIFY",
  "dynamodb": {
    "Keys": {
      "UserID": {"S": "user123"}
    },
    "OldImage": {
      "UserID": {"S": "user123"},
      "Name": {"S": "John Doe"},
      "Email": {"S": "john@example.com"},
      "Age": {"N": "30"}
    }
  }
}
```

**Pros:**
- Track deleted data
- Historical snapshots
- Undo operations

**Cons:**
- Can't see new state without table query
- Not useful for replication

---

### 4. NEW_AND_OLD_IMAGES (Recommended for Most Cases)

**Captures:** Key attributes + item BEFORE and AFTER modification

**Use Cases:**
- Change data capture (CDC)
- Detailed audit logs
- Delta processing
- Complex business logic

**Example Record:**
```json
{
  "eventName": "MODIFY",
  "dynamodb": {
    "Keys": {
      "UserID": {"S": "user123"}
    },
    "OldImage": {
      "UserID": {"S": "user123"},
      "Name": {"S": "John Doe"},
      "Email": {"S": "john@example.com"},
      "Age": {"N": "30"}
    },
    "NewImage": {
      "UserID": {"S": "user123"},
      "Name": {"S": "John Doe"},
      "Email": {"S": "john.updated@example.com"},
      "Age": {"N": "31"}
    }
  }
}
```

**Pros:**
- Complete change visibility
- Can calculate deltas
- Most flexible option
- Best for CDC patterns

**Cons:**
- Largest record size
- Highest cost
- More data to process

---

## Use Cases

### Use Case 1: Real-Time Analytics

**Scenario:** Track product purchases in real-time

```python
# Lambda function triggered by DynamoDB Stream
def lambda_handler(event, context):
    for record in event['Records']:
        if record['eventName'] == 'INSERT':
            # New order placed
            new_order = record['dynamodb']['NewImage']
            
            # Update analytics dashboard
            update_sales_dashboard(
                product_id=new_order['ProductID']['S'],
                quantity=int(new_order['Quantity']['N']),
                amount=float(new_order['Amount']['N'])
            )
            
            # Send to real-time analytics stream
            send_to_kinesis(new_order)
```

---

### Use Case 2: Cross-Region Replication

**Scenario:** Replicate data to another region for disaster recovery

```python
import boto3

dynamodb_target = boto3.resource('dynamodb', region_name='us-west-2')

def lambda_handler(event, context):
    target_table = dynamodb_target.Table('Products-Replica')
    
    for record in event['Records']:
        if record['eventName'] == 'INSERT':
            # Replicate insert
            item = deserialize_dynamodb_item(record['dynamodb']['NewImage'])
            target_table.put_item(Item=item)
            
        elif record['eventName'] == 'MODIFY':
            # Replicate update
            item = deserialize_dynamodb_item(record['dynamodb']['NewImage'])
            target_table.put_item(Item=item)
            
        elif record['eventName'] == 'REMOVE':
            # Replicate delete
            keys = deserialize_dynamodb_item(record['dynamodb']['Keys'])
            target_table.delete_item(Key=keys)
```

---

### Use Case 3: Audit Trail

**Scenario:** Track all changes for compliance

```python
def lambda_handler(event, context):
    audit_table = boto3.resource('dynamodb').Table('AuditLog')
    
    for record in event['Records']:
        audit_entry = {
            'AuditID': str(uuid.uuid4()),
            'Timestamp': datetime.utcnow().isoformat(),
            'EventName': record['eventName'],
            'TableName': record['eventSourceARN'].split('/')[-3],
            'Keys': record['dynamodb'].get('Keys'),
            'OldValues': record['dynamodb'].get('OldImage'),
            'NewValues': record['dynamodb'].get('NewImage'),
            'UserIdentity': record.get('userIdentity', {})
        }
        
        audit_table.put_item(Item=audit_entry)
```

---

### Use Case 4: Materialized Views

**Scenario:** Maintain denormalized view for fast queries

```python
def lambda_handler(event, context):
    """
    Update materialized view when orders change
    Maintains: order_count, total_spent per customer
    """
    customer_stats_table = boto3.resource('dynamodb').Table('CustomerStats')
    
    for record in event['Records']:
        keys = record['dynamodb']['Keys']
        customer_id = keys['CustomerID']['S']
        
        if record['eventName'] == 'INSERT':
            # New order - increment counts
            new_image = record['dynamodb']['NewImage']
            amount = Decimal(new_image['TotalAmount']['N'])
            
            customer_stats_table.update_item(
                Key={'CustomerID': customer_id},
                UpdateExpression='ADD OrderCount :inc, TotalSpent :amount',
                ExpressionAttributeValues={
                    ':inc': 1,
                    ':amount': amount
                }
            )
            
        elif record['eventName'] == 'REMOVE':
            # Order cancelled - decrement counts
            old_image = record['dynamodb']['OldImage']
            amount = Decimal(old_image['TotalAmount']['N'])
            
            customer_stats_table.update_item(
                Key={'CustomerID': customer_id},
                UpdateExpression='ADD OrderCount :dec, TotalSpent :neg_amount',
                ExpressionAttributeValues={
                    ':dec': -1,
                    ':neg_amount': -amount
                }
            )
```

---

### Use Case 5: ElasticSearch/OpenSearch Sync

**Scenario:** Keep search index synchronized

```python
from opensearchpy import OpenSearch

opensearch = OpenSearch(
    hosts=[{'host': 'search-domain.region.es.amazonaws.com', 'port': 443}],
    http_auth=('username', 'password'),
    use_ssl=True
)

def lambda_handler(event, context):
    for record in event['Records']:
        doc_id = record['dynamodb']['Keys']['ProductID']['S']
        
        if record['eventName'] in ['INSERT', 'MODIFY']:
            # Index or update document
            new_image = deserialize_dynamodb_item(record['dynamodb']['NewImage'])
            
            opensearch.index(
                index='products',
                id=doc_id,
                body=new_image
            )
            
        elif record['eventName'] == 'REMOVE':
            # Delete from index
            opensearch.delete(
                index='products',
                id=doc_id,
                ignore=[404]  # Ignore if already deleted
            )
```

---

## Setting Up Streams

### Method 1: AWS Console

1. Open DynamoDB Console
2. Select your table
3. Go to "Exports and streams" tab
4. Click "Enable" under DynamoDB stream details
5. Choose stream view type
6. Click "Enable stream"

### Method 2: AWS CLI

```bash
# Enable stream
aws dynamodb update-table \
    --table-name Products \
    --stream-specification \
        StreamEnabled=true,StreamViewType=NEW_AND_OLD_IMAGES

# Get stream ARN
aws dynamodb describe-table \
    --table-name Products \
    --query 'Table.LatestStreamArn'
```

### Method 3: Boto3 (Python)

```python
import boto3

dynamodb = boto3.client('dynamodb')

# Enable stream on existing table
response = dynamodb.update_table(
    TableName='Products',
    StreamSpecification={
        'StreamEnabled': True,
        'StreamViewType': 'NEW_AND_OLD_IMAGES'
    }
)

print(f"Stream ARN: {response['TableDescription']['LatestStreamArn']}")

# Create new table with stream enabled
response = dynamodb.create_table(
    TableName='Orders',
    KeySchema=[
        {'AttributeName': 'OrderID', 'KeyType': 'HASH'}
    ],
    AttributeDefinitions=[
        {'AttributeName': 'OrderID', 'AttributeType': 'S'}
    ],
    BillingMode='PAY_PER_REQUEST',
    StreamSpecification={
        'StreamEnabled': True,
        'StreamViewType': 'NEW_AND_OLD_IMAGES'
    }
)
```

### Method 4: CloudFormation

```yaml
Resources:
  ProductsTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: Products
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: ProductID
          AttributeType: S
      KeySchema:
        - AttributeName: ProductID
          KeyType: HASH
      StreamSpecification:
        StreamViewType: NEW_AND_OLD_IMAGES
      Tags:
        - Key: Environment
          Value: Production
```

### Method 5: Terraform

```hcl
resource "aws_dynamodb_table" "products" {
  name           = "Products"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "ProductID"

  attribute {
    name = "ProductID"
    type = "S"
  }

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  tags = {
    Environment = "Production"
  }
}
```

---

## Processing Stream Records

### Python Stream Processor Class

See the companion file `dynamodb_streams_processor.py` for the complete implementation.

### Key Processing Patterns

#### Pattern 1: Batch Processing

```python
def process_batch(records):
    """Process multiple records together for efficiency"""
    batch_items = []
    
    for record in records:
        if record['eventName'] == 'INSERT':
            item = deserialize_dynamodb_item(record['dynamodb']['NewImage'])
            batch_items.append(item)
    
    if batch_items:
        # Batch write to target system
        write_batch_to_target(batch_items)
```

#### Pattern 2: Delta Processing

```python
def process_delta(record):
    """Process only changed attributes"""
    if record['eventName'] != 'MODIFY':
        return
    
    old_image = record['dynamodb'].get('OldImage', {})
    new_image = record['dynamodb'].get('NewImage', {})
    
    changes = {}
    for key in new_image:
        if key not in old_image or old_image[key] != new_image[key]:
            changes[key] = {
                'old': deserialize_attribute(old_image.get(key)),
                'new': deserialize_attribute(new_image[key])
            }
    
    return changes
```

#### Pattern 3: Idempotent Processing

```python
def process_with_idempotency(record):
    """Ensure processing is idempotent"""
    event_id = record['eventID']
    
    # Check if already processed
    if is_processed(event_id):
        print(f"Skipping already processed event: {event_id}")
        return
    
    # Process the record
    result = process_record(record)
    
    # Mark as processed
    mark_processed(event_id, result)
    
    return result

def is_processed(event_id):
    """Check DynamoDB for processed event IDs"""
    processed_table = boto3.resource('dynamodb').Table('ProcessedEvents')
    response = processed_table.get_item(Key={'EventID': event_id})
    return 'Item' in response
```

---

## Lambda Integration

### Lambda Event Source Mapping

#### Create Event Source Mapping (CLI)

```bash
aws lambda create-event-source-mapping \
    --function-name ProcessDynamoDBStream \
    --event-source-arn arn:aws:dynamodb:us-east-1:123456789:table/Products/stream/2024-12-20 \
    --starting-position LATEST \
    --batch-size 100 \
    --maximum-batching-window-in-seconds 5 \
    --parallelization-factor 10 \
    --maximum-retry-attempts 3 \
    --maximum-record-age-in-seconds 604800 \
    --bisect-batch-on-function-error \
    --destination-config '{
        "OnFailure": {
            "Destination": "arn:aws:sqs:us-east-1:123456789:dlq-stream-failures"
        }
    }'
```

#### Lambda Function Example

```python
import json
from decimal import Decimal
from typing import List, Dict, Any

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Process DynamoDB Stream records
    
    Event structure:
    {
        'Records': [
            {
                'eventID': '1',
                'eventName': 'INSERT',
                'dynamodb': {...}
            }
        ]
    }
    """
    successful = 0
    failed = 0
    
    for record in event['Records']:
        try:
            process_record(record)
            successful += 1
        except Exception as e:
            print(f"Error processing record: {e}")
            failed += 1
            # Don't raise - process remaining records
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'processed': successful,
            'failed': failed
        })
    }

def process_record(record: Dict[str, Any]) -> None:
    """Process a single stream record"""
    event_name = record['eventName']
    
    if event_name == 'INSERT':
        handle_insert(record)
    elif event_name == 'MODIFY':
        handle_modify(record)
    elif event_name == 'REMOVE':
        handle_remove(record)

def handle_insert(record: Dict[str, Any]) -> None:
    """Handle INSERT event"""
    new_item = deserialize_dynamodb_item(record['dynamodb']['NewImage'])
    print(f"New item created: {new_item}")
    # Your business logic here

def handle_modify(record: Dict[str, Any]) -> None:
    """Handle MODIFY event"""
    old_item = deserialize_dynamodb_item(record['dynamodb']['OldImage'])
    new_item = deserialize_dynamodb_item(record['dynamodb']['NewImage'])
    print(f"Item updated from {old_item} to {new_item}")
    # Your business logic here

def handle_remove(record: Dict[str, Any]) -> None:
    """Handle REMOVE event"""
    old_item = deserialize_dynamodb_item(record['dynamodb']['OldImage'])
    print(f"Item deleted: {old_item}")
    # Your business logic here

def deserialize_dynamodb_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert DynamoDB JSON format to Python dict"""
    python_item = {}
    for key, value in item.items():
        python_item[key] = deserialize_attribute(value)
    return python_item

def deserialize_attribute(attr: Dict[str, Any]) -> Any:
    """Deserialize a single DynamoDB attribute"""
    if 'S' in attr:
        return attr['S']
    elif 'N' in attr:
        return Decimal(attr['N'])
    elif 'BOOL' in attr:
        return attr['BOOL']
    elif 'NULL' in attr:
        return None
    elif 'L' in attr:
        return [deserialize_attribute(item) for item in attr['L']]
    elif 'M' in attr:
        return {k: deserialize_attribute(v) for k, v in attr['M'].items()}
    elif 'SS' in attr:
        return set(attr['SS'])
    elif 'NS' in attr:
        return set(Decimal(n) for n in attr['NS'])
    else:
        return attr
```

### Lambda Configuration Best Practices

```python
# Lambda configuration (CloudFormation/SAM)
"""
FunctionConfiguration:
  Timeout: 300              # 5 minutes (max for stream processing)
  MemorySize: 1024          # Adjust based on processing complexity
  ReservedConcurrentExecutions: 10  # Limit concurrent executions
  Environment:
    Variables:
      TARGET_TABLE: ReplicaTable
      BATCH_SIZE: 100
      ENABLE_LOGGING: true
"""

# Event Source Mapping settings
"""
- BatchSize: 100                    # Process up to 100 records per invocation
- MaximumBatchingWindowInSeconds: 5 # Wait up to 5s to fill batch
- ParallelizationFactor: 10         # Process 10 shards concurrently
- MaximumRetryAttempts: 3           # Retry failed batches 3 times
- MaximumRecordAgeInSeconds: 604800 # Discard records older than 7 days
- BisectBatchOnFunctionError: true  # Split batch on error for retry
- DestinationConfig:                # Send failures to DLQ
    OnFailure:
      Destination: arn:aws:sqs:...:dlq
"""
```

---

## Best Practices

### 1. Idempotency

**Problem:** Stream records may be delivered more than once

**Solution:** Track processed event IDs

```python
def ensure_idempotency(event_id, operation):
    """Idempotent processing wrapper"""
    cache_table = boto3.resource('dynamodb').Table('ProcessingCache')
    
    # Check if already processed
    response = cache_table.get_item(Key={'EventID': event_id})
    
    if 'Item' in response:
        return response['Item']['Result']
    
    # Process and cache result
    result = operation()
    
    cache_table.put_item(
        Item={
            'EventID': event_id,
            'Result': result,
            'ProcessedAt': datetime.utcnow().isoformat(),
            'TTL': int(time.time()) + 86400  # Expire after 24 hours
        }
    )
    
    return result
```

### 2. Error Handling

```python
def robust_stream_processor(event, context):
    """Process with comprehensive error handling"""
    failures = []
    
    for record in event['Records']:
        try:
            # Validate record
            if not validate_record(record):
                raise ValueError("Invalid record format")
            
            # Process with timeout
            with timeout(seconds=30):
                process_record(record)
                
        except Exception as e:
            error_info = {
                'eventID': record['eventID'],
                'error': str(e),
                'record': record
            }
            failures.append(error_info)
            
            # Log to CloudWatch
            print(f"ERROR: {json.dumps(error_info)}")
            
            # Send to DLQ
            send_to_dlq(error_info)
    
    if failures:
        # Partial batch failure - return failed items for retry
        return {
            'batchItemFailures': [
                {'itemIdentifier': f['eventID']} for f in failures
            ]
        }
    
    return {'statusCode': 200}
```

### 3. Performance Optimization

```python
# Batch operations for efficiency
def optimized_processor(records):
    """Process records in batches"""
    
    # Group by operation type
    inserts = []
    updates = []
    deletes = []
    
    for record in records:
        if record['eventName'] == 'INSERT':
            inserts.append(record)
        elif record['eventName'] == 'MODIFY':
            updates.append(record)
        elif record['eventName'] == 'REMOVE':
            deletes.append(record)
    
    # Process each type in parallel
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(process_inserts, inserts),
            executor.submit(process_updates, updates),
            executor.submit(process_deletes, deletes)
        ]
        
        # Wait for completion
        for future in futures:
            future.result()
```

### 4. Monitoring

```python
import time
from aws_lambda_powertools import Metrics
from aws_lambda_powertools.metrics import MetricUnit

metrics = Metrics(namespace="DynamoDBStreams")

@metrics.log_metrics
def lambda_handler(event, context):
    start_time = time.time()
    
    record_count = len(event['Records'])
    metrics.add_metric(name="RecordsReceived", unit=MetricUnit.Count, value=record_count)
    
    processed = 0
    failed = 0
    
    for record in event['Records']:
        try:
            process_record(record)
            processed += 1
        except Exception as e:
            failed += 1
            metrics.add_metric(name="ProcessingErrors", unit=MetricUnit.Count, value=1)
    
    # Record metrics
    metrics.add_metric(name="RecordsProcessed", unit=MetricUnit.Count, value=processed)
    metrics.add_metric(name="RecordsFailed", unit=MetricUnit.Count, value=failed)
    
    duration = time.time() - start_time
    metrics.add_metric(name="ProcessingDuration", unit=MetricUnit.Seconds, value=duration)
    
    return {'statusCode': 200}
```

---

## Monitoring & Troubleshooting

### CloudWatch Metrics

Monitor these key metrics:

```python
# Custom CloudWatch metrics
cloudwatch = boto3.client('cloudwatch')

def publish_metrics(metric_data):
    cloudwatch.put_metric_data(
        Namespace='DynamoDBStreams/Processing',
        MetricData=[
            {
                'MetricName': 'RecordLag',
                'Value': calculate_lag(),
                'Unit': 'Seconds',
                'Timestamp': datetime.utcnow()
            },
            {
                'MetricName': 'BatchSize',
                'Value': len(current_batch),
                'Unit': 'Count'
            },
            {
                'MetricName': 'ProcessingRate',
                'Value': records_per_second,
                'Unit': 'Count/Second'
            }
        ]
    )
```

### Key Metrics to Monitor

1. **IteratorAge** - How far behind the processor is
2. **ProcessingLatency** - Time to process each batch
3. **ErrorRate** - Failed vs successful records
4. **Throttling** - DynamoDB read throttles on stream
5. **Lambda Errors** - Function errors and timeouts

### Troubleshooting Common Issues

#### Issue 1: High Iterator Age

**Symptom:** Processing falling behind
**Causes:**
- Insufficient Lambda concurrency
- Slow processing logic
- DynamoDB read throttling

**Solutions:**
```python
# Increase parallelization
aws lambda update-event-source-mapping \
    --uuid <mapping-id> \
    --parallelization-factor 20

# Optimize processing
def optimized_process(records):
    # Use batch operations
    # Reduce external API calls
    # Cache frequently accessed data
    pass
```

#### Issue 2: Duplicate Processing

**Symptom:** Same record processed multiple times
**Solution:** Implement idempotency (see best practices above)

#### Issue 3: Lambda Timeouts

**Symptom:** Timeout errors in CloudWatch
**Solutions:**
```python
# Reduce batch size
aws lambda update-event-source-mapping \
    --uuid <mapping-id> \
    --batch-size 50

# Increase timeout
aws lambda update-function-configuration \
    --function-name ProcessStream \
    --timeout 300
```

---

## Cost Considerations

### Pricing Components

1. **Stream Read Requests**
   - $0.02 per 100,000 read request units
   - Each GetRecords API call = 1 read request unit

2. **Lambda Invocations**
   - $0.20 per 1M requests
   - Plus compute time costs

3. **Data Transfer**
   - Free within same region
   - Standard rates for cross-region

### Cost Optimization Tips

```python
# 1. Batch processing
EventSourceMapping(
    BatchSize=100,  # Larger batches = fewer Lambda invocations
    MaximumBatchingWindowInSeconds=10  # Wait to fill batch
)

# 2. Filter records at source
EventSourceMapping(
    FilterCriteria={
        'Filters': [
            {
                'Pattern': json.dumps({
                    'eventName': ['INSERT', 'MODIFY'],  # Skip REMOVE events
                    'dynamodb': {
                        'NewImage': {
                            'Status': {'S': ['ACTIVE']}  # Only process active items
                        }
                    }
                })
            }
        ]
    }
)

# 3. Optimize Lambda
# - Right-size memory
# - Minimize cold starts
# - Use efficient libraries
```

---

## Summary

DynamoDB Streams provides a powerful, serverless way to build event-driven architectures:

✅ **Real-time** - Millisecond latency
✅ **Reliable** - Exactly-once delivery guarantee
✅ **Scalable** - Automatic shard management
✅ **Flexible** - Multiple view types and consumers
✅ **Cost-effective** - Pay only for what you use

**Next Steps:**
1. Review the companion Python code in `dynamodb_streams_processor.py`
2. Set up a test table with streams enabled
3. Create a simple Lambda processor
4. Monitor with CloudWatch
5. Implement error handling and idempotency
6. Scale to production workloads

For more information, see:
- [AWS DynamoDB Streams Documentation](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.html)
- [Lambda Event Source Mapping](https://docs.aws.amazon.com/lambda/latest/dg/with-ddb.html)
