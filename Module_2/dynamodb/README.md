# DynamoDB Complete Guide & Python Operations

A comprehensive guide and Python implementation for Amazon DynamoDB operations, covering everything from basic CRUD to advanced features like transactions, indexes, and streams.

## 📦 Contents

1. **dynamodb_guide.md** - Complete theoretical guide with best practices
2. **dynamodb_diagrams.html** - Visual diagrams for architecture concepts
3. **dynamodb_operations.py** - Production-ready Python code
4. **requirements.txt** - Python dependencies

## 🚀 Quick Start

### Prerequisites

```bash
# Install Python 3.8+
python --version

# Install AWS CLI (optional but recommended)
aws --version
```

### Installation

```bash
# 1. Clone or download the files

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure AWS credentials
aws configure
# Enter your AWS Access Key ID, Secret Access Key, and region
```

### AWS Credentials Setup

**Option 1: AWS CLI Configuration**
```bash
aws configure
# AWS Access Key ID: YOUR_ACCESS_KEY
# AWS Secret Access Key: YOUR_SECRET_KEY
# Default region name: us-east-1
# Default output format: json
```

**Option 2: Environment Variables**
```bash
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=us-east-1
```

**Option 3: IAM Role (for EC2/Lambda)**
- No credentials needed if running on AWS with IAM role attached

### Run the Demo

```bash
python dynamodb_operations.py
```

## 📚 Usage Examples

### 1. Initialize DynamoDB Manager

```python
from dynamodb_operations import DynamoDBManager

# For AWS DynamoDB
manager = DynamoDBManager(region_name='us-east-1')

# For Local DynamoDB (development)
manager = DynamoDBManager(
    region_name='us-east-1',
    endpoint_url='http://localhost:8000'
)
```

### 2. Create Table with Indexes

```python
# Create table with GSI and LSI
manager.create_table_with_indexes(
    table_name='Users',
    partition_key='UserID',
    sort_key='Timestamp',
    billing_mode='PAY_PER_REQUEST',
    global_secondary_indexes=[
        {
            'IndexName': 'EmailIndex',
            'PartitionKey': 'Email',
            'PartitionKeyType': 'S',
            'ProjectionType': 'ALL'
        }
    ],
    local_secondary_indexes=[
        {
            'IndexName': 'UserRatingIndex',
            'SortKey': 'Rating',
            'SortKeyType': 'N',
            'ProjectionType': 'ALL'
        }
    ],
    stream_enabled=True,
    ttl_attribute='ExpirationTime'
)
```

### 3. Insert Data

**Single Item:**
```python
manager.insert_item('Users', {
    'UserID': 'user123',
    'Email': 'john@example.com',
    'Name': 'John Doe',
    'Age': 30,
    'Timestamp': '2024-12-20T10:00:00Z'
})
```

**Batch Insert:**
```python
users = [
    {'UserID': 'user1', 'Name': 'Alice', 'Email': 'alice@example.com'},
    {'UserID': 'user2', 'Name': 'Bob', 'Email': 'bob@example.com'},
    # ... up to 25 items per batch
]
manager.batch_insert_items('Users', users)
```

### 4. Retrieve Data

**Get Item by Key:**
```python
user = manager.get_item('Users', {
    'UserID': 'user123',
    'Timestamp': '2024-12-20T10:00:00Z'
})
```

**Query with Partition Key:**
```python
from boto3.dynamodb.conditions import Key

# Get all records for a user
items = manager.query_items(
    'Users',
    Key('UserID').eq('user123')
)

# Query with sort key condition
items = manager.query_items(
    'Users',
    Key('UserID').eq('user123') & Key('Timestamp').begins_with('2024-12')
)
```

**Query with GSI:**
```python
# Query by email using EmailIndex
items = manager.query_items(
    'Users',
    Key('Email').eq('john@example.com'),
    index_name='EmailIndex'
)
```

**Query with Filter:**
```python
from boto3.dynamodb.conditions import Attr

items = manager.query_items(
    'Users',
    Key('UserID').eq('user123'),
    filter_expression=Attr('Age').gt(25) & Attr('Status').eq('active')
)
```

**Scan (use sparingly):**
```python
# Scan with filter
items = manager.scan_table(
    'Users',
    filter_expression=Attr('Age').between(25, 40)
)
```

### 5. Update Data

**Simple Update:**
```python
manager.update_item(
    'Users',
    {'UserID': 'user123', 'Timestamp': '2024-12-20T10:00:00Z'},
    'SET Age = :age, LastLogin = :login',
    {
        ':age': 31,
        ':login': '2024-12-20T14:30:00Z'
    }
)
```

**Conditional Update (Optimistic Locking):**
```python
# Update only if version matches
manager.update_item(
    'Users',
    {'UserID': 'user123', 'Timestamp': '2024-12-20T10:00:00Z'},
    'SET Balance = Balance + :amount, Version = Version + :inc',
    {':amount': 100, ':inc': 1},
    condition_expression='Version = :expected',
    condition_values={':expected': 5}
)
```

**Increment Counter:**
```python
manager.update_item(
    'Users',
    {'UserID': 'user123', 'Timestamp': '2024-12-20T10:00:00Z'},
    'SET LoginCount = if_not_exists(LoginCount, :zero) + :inc',
    {':zero': 0, ':inc': 1}
)
```

### 6. Delete Data

**Single Item:**
```python
manager.delete_item('Users', {
    'UserID': 'user123',
    'Timestamp': '2024-12-20T10:00:00Z'
})
```

**Batch Delete:**
```python
keys = [
    {'UserID': 'user1', 'Timestamp': '2024-12-01T10:00:00Z'},
    {'UserID': 'user2', 'Timestamp': '2024-12-02T11:00:00Z'},
]
manager.batch_delete_items('Users', keys)
```

### 7. Transactions

```python
transact_items = [
    {
        'Put': {
            'TableName': 'Users',
            'Item': {
                'UserID': {'S': 'user123'},
                'Name': {'S': 'John Doe'},
                'Balance': {'N': '1000'}
            }
        }
    },
    {
        'Update': {
            'TableName': 'Accounts',
            'Key': {'AccountID': {'S': 'acc123'}},
            'UpdateExpression': 'SET Balance = Balance - :amount',
            'ExpressionAttributeValues': {':amount': {'N': '100'}},
            'ConditionExpression': 'Balance >= :amount'
        }
    }
]

manager.transact_write_items(transact_items)
```

### 8. Time To Live (TTL)

```python
import time

# Enable TTL on table
manager.enable_ttl('Sessions', 'ExpirationTime')

# Insert item with TTL (expires in 1 hour)
manager.insert_item('Sessions', {
    'SessionID': 'sess123',
    'UserID': 'user123',
    'Data': 'session data',
    'ExpirationTime': int(time.time()) + 3600  # Unix timestamp
})

# Item will be automatically deleted after expiration
```

## 🏗️ Local Development

### Using DynamoDB Local

```bash
# 1. Download DynamoDB Local
wget https://s3.us-west-2.amazonaws.com/dynamodb-local/dynamodb_local_latest.tar.gz
tar -xzf dynamodb_local_latest.tar.gz

# 2. Start DynamoDB Local
java -Djava.library.path=./DynamoDBLocal_lib -jar DynamoDBLocal.jar -sharedDb

# 3. Use in Python with endpoint_url
manager = DynamoDBManager(
    region_name='us-east-1',
    endpoint_url='http://localhost:8000'
)
```

### Using Docker

```bash
# Run DynamoDB Local in Docker
docker run -p 8000:8000 amazon/dynamodb-local

# In Python
manager = DynamoDBManager(
    region_name='us-east-1',
    endpoint_url='http://localhost:8000'
)
```

## 📊 Best Practices

### 1. Choose the Right Primary Key

```python
# ✅ Good: High cardinality partition key
partition_key='UserID'  # Many unique users

# ❌ Bad: Low cardinality
partition_key='Status'  # Only 'active', 'inactive'
```

### 2. Use Sparse Indexes

```python
# Only include items with the attribute in the index
# Saves cost by not indexing all items
global_secondary_indexes=[{
    'IndexName': 'PremiumUserIndex',
    'PartitionKey': 'PremiumSince',  # Only premium users have this
    'ProjectionType': 'ALL'
}]
```

### 3. Use Batch Operations

```python
# ✅ Efficient: Batch write
manager.batch_insert_items('Users', items)

# ❌ Inefficient: Multiple single writes
for item in items:
    manager.insert_item('Users', item)
```

### 4. Prefer Query over Scan

```python
# ✅ Efficient: Query with partition key
items = manager.query_items('Users', Key('UserID').eq('user123'))

# ❌ Inefficient: Scan entire table
items = manager.scan_table('Users', filter_expression=Attr('UserID').eq('user123'))
```

### 5. Use Projection Expressions

```python
# Only retrieve needed attributes to save bandwidth
table.get_item(
    Key={'UserID': 'user123'},
    ProjectionExpression='Name,Email'
)
```

## 🔧 Common Patterns

### Pattern 1: Time-Series Data

```python
# Table design
manager.create_table_with_indexes(
    table_name='SensorData',
    partition_key='DeviceID',
    sort_key='Timestamp',
    billing_mode='PAY_PER_REQUEST'
)

# Query recent readings
recent_data = manager.query_items(
    'SensorData',
    Key('DeviceID').eq('device123') & Key('Timestamp').between(
        '2024-12-01T00:00:00Z',
        '2024-12-20T23:59:59Z'
    )
)
```

### Pattern 2: Single Table Design

```python
# Store multiple entity types in one table
items = [
    # User profile
    {'PK': 'USER#user123', 'SK': 'PROFILE', 'Name': 'John'},
    
    # User's orders
    {'PK': 'USER#user123', 'SK': 'ORDER#2024-12-01', 'Total': 150},
    {'PK': 'USER#user123', 'SK': 'ORDER#2024-12-15', 'Total': 75},
    
    # Product
    {'PK': 'PRODUCT#prod456', 'SK': 'METADATA', 'Name': 'Laptop'},
    
    # Product reviews
    {'PK': 'PRODUCT#prod456', 'SK': 'REVIEW#user123', 'Rating': 5}
]
```

### Pattern 3: Leaderboard

```python
# Use GSI for ranking
manager.create_table_with_indexes(
    table_name='GameScores',
    partition_key='UserID',
    sort_key='GameID',
    global_secondary_indexes=[{
        'IndexName': 'LeaderboardIndex',
        'PartitionKey': 'GameID',
        'SortKey': 'Score',
        'ProjectionType': 'ALL'
    }]
)

# Get top 10 players for a game
top_players = manager.query_items(
    'GameScores',
    Key('GameID').eq('game123'),
    index_name='LeaderboardIndex',
    scan_forward=False,  # Descending order
    limit=10
)
```

## 💰 Cost Optimization

### 1. Choose Right Billing Mode

```python
# Predictable workload: Use PROVISIONED
manager.create_table_with_indexes(
    table_name='Users',
    partition_key='UserID',
    billing_mode='PROVISIONED',
    read_capacity=10,
    write_capacity=5
)

# Unpredictable workload: Use PAY_PER_REQUEST
manager.create_table_with_indexes(
    table_name='Users',
    partition_key='UserID',
    billing_mode='PAY_PER_REQUEST'
)
```

### 2. Use Eventually Consistent Reads

```python
# 50% cheaper than strongly consistent
items = manager.query_items(
    'Users',
    Key('UserID').eq('user123'),
    consistent_read=False  # Default, eventually consistent
)
```

### 3. Implement Data Archival

```python
import time

# Add TTL for automatic deletion
expiration_time = int(time.time()) + (90 * 24 * 60 * 60)  # 90 days

manager.insert_item('Logs', {
    'LogID': 'log123',
    'Message': 'Some log data',
    'ExpirationTime': expiration_time
})
```

## 🐛 Troubleshooting

### Common Errors

**1. ProvisionedThroughputExceededException**
```
Solution: Increase provisioned capacity or switch to On-Demand mode
```

**2. ValidationException: One or more parameter values were invalid**
```
Solution: Check attribute types, ensure key schema matches table definition
```

**3. ConditionalCheckFailedException**
```
Solution: Condition in update/delete not met, check condition expression
```

**4. ResourceNotFoundException**
```
Solution: Table doesn't exist or wrong region/endpoint
```

## 📖 Additional Resources

- [AWS DynamoDB Documentation](https://docs.aws.amazon.com/dynamodb/)
- [Boto3 DynamoDB Guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/dynamodb.html)
- [DynamoDB Best Practices](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/best-practices.html)
- [NoSQL Workbench for DynamoDB](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/workbench.html)

## 🔐 IAM Permissions

Minimum IAM policy for DynamoDB operations:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:BatchWriteItem",
        "dynamodb:BatchGetItem",
        "dynamodb:DescribeTable",
        "dynamodb:CreateTable",
        "dynamodb:UpdateTable",
        "dynamodb:DeleteTable",
        "dynamodb:DescribeTimeToLive",
        "dynamodb:UpdateTimeToLive"
      ],
      "Resource": [
        "arn:aws:dynamodb:*:*:table/YourTableName",
        "arn:aws:dynamodb:*:*:table/YourTableName/index/*"
      ]
    }
  ]
}
```

## 📝 License

This code is provided as educational material and can be freely used and modified.

## 🤝 Contributing

Suggestions and improvements are welcome! This is designed as a comprehensive learning resource for DynamoDB operations.

---

**Created by:** Data Engineering Team  
**Last Updated:** December 2024  
**Python Version:** 3.8+  
**Boto3 Version:** 1.34.0+