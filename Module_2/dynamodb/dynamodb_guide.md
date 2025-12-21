# Amazon DynamoDB Complete Guide

## Table of Contents
1. [What is DynamoDB?](#what-is-dynamodb)
2. [Core Concepts](#core-concepts)
3. [Architecture](#architecture)
4. [Table Design](#table-design)
5. [Indexes](#indexes)
6. [Capacity Modes](#capacity-modes)
7. [Best Practices](#best-practices)
8. [Use Cases](#use-cases)

---

## What is DynamoDB?

Amazon DynamoDB is a fully managed NoSQL database service that provides:
- **Fast and predictable performance** with seamless scalability
- **Single-digit millisecond latency** at any scale
- **Automatic scaling** based on traffic patterns
- **Multi-AZ replication** for high availability
- **Built-in security** with encryption at rest and in transit

### Key Characteristics

| Feature | Description |
|---------|-------------|
| Database Type | NoSQL Key-Value and Document Store |
| Performance | Single-digit millisecond latency |
| Scalability | Automatic, unlimited storage |
| Availability | 99.99% SLA, Multi-AZ replication |
| Consistency | Eventually consistent or strongly consistent reads |
| Pricing | Pay per request or provisioned capacity |

---

## Core Concepts

### 1. Tables
A table is a collection of items (similar to rows in relational databases).

### 2. Items
An item is a collection of attributes (similar to a row). Each item must have:
- **Partition Key** (required)
- **Sort Key** (optional)
- Additional attributes

### 3. Attributes
Key-value pairs that make up an item. Attributes can be:
- **Scalar types**: String, Number, Binary, Boolean, Null
- **Document types**: List, Map
- **Set types**: String Set, Number Set, Binary Set

### 4. Primary Keys

**Two types of primary keys:**

**A. Partition Key (Simple Primary Key)**
- Single attribute that uniquely identifies an item
- Used for hash-based distribution across partitions
- Example: `UserID`

**B. Composite Primary Key (Partition Key + Sort Key)**
- Partition Key + Sort Key together uniquely identify an item
- Items with same partition key are stored together, sorted by sort key
- Example: `UserID` (partition) + `Timestamp` (sort)

### 5. Secondary Indexes

**Global Secondary Index (GSI)**
- Different partition key and sort key from base table
- Can be created/deleted after table creation
- Has its own provisioned throughput
- Eventually consistent reads only

**Local Secondary Index (LSI)**
- Same partition key as base table, different sort key
- Must be created at table creation time
- Shares provisioned throughput with base table
- Supports strongly consistent reads

---

## Architecture

### DynamoDB Internal Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   AWS SDK    │  │   AWS CLI    │  │  AWS Console │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              DynamoDB Service (Request Router)              │
│              • Authentication & Authorization               │
│              • Request Validation                           │
│              • Routing to Partitions                        │
└─────────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Storage Layer                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Partition 1 │  │  Partition 2 │  │  Partition N │      │
│  │  (10GB max)  │  │  (10GB max)  │  │  (10GB max)  │      │
│  │              │  │              │  │              │      │
│  │  AZ-1  AZ-2  │  │  AZ-1  AZ-2  │  │  AZ-1  AZ-2  │      │
│  │  AZ-3        │  │  AZ-3        │  │  AZ-3        │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         ▲                ▲                  ▲               │
│         └────────────────┴──────────────────┘               │
│              Automatic Replication                          │
└─────────────────────────────────────────────────────────────┘
```

### Data Distribution

```
Table: Users
Partition Key: UserID (Hash Function Applied)

Hash(UserID='user123') → Partition 1
Hash(UserID='user456') → Partition 2
Hash(UserID='user789') → Partition 3

┌─────────────────────┐
│    Partition 1      │
│  UserID='user123'   │
│  UserID='user147'   │
│  UserID='user199'   │
└─────────────────────┘

┌─────────────────────┐
│    Partition 2      │
│  UserID='user456'   │
│  UserID='user482'   │
│  UserID='user401'   │
└─────────────────────┘

┌─────────────────────┐
│    Partition 3      │
│  UserID='user789'   │
│  UserID='user711'   │
│  UserID='user823'   │
└─────────────────────┘
```

---

## Table Design

### Design Pattern 1: Simple Key-Value Store

**Use Case**: User profiles, configuration data

```
Table: UserProfiles
Partition Key: UserID
Attributes: Name, Email, CreatedAt, Settings (Map)

Item Example:
{
  "UserID": "user123",
  "Name": "John Doe",
  "Email": "john@example.com",
  "CreatedAt": "2024-01-15T10:30:00Z",
  "Settings": {
    "Theme": "dark",
    "Language": "en"
  }
}
```

### Design Pattern 2: Composite Primary Key

**Use Case**: Time-series data, order history, IoT sensor data

```
Table: OrderHistory
Partition Key: UserID
Sort Key: OrderTimestamp
Attributes: OrderID, TotalAmount, Status

Item Examples:
{
  "UserID": "user123",
  "OrderTimestamp": "2024-12-01T10:30:00Z",
  "OrderID": "ORD-001",
  "TotalAmount": 150.00,
  "Status": "Delivered"
}
{
  "UserID": "user123",
  "OrderTimestamp": "2024-12-15T14:20:00Z",
  "OrderID": "ORD-002",
  "TotalAmount": 75.50,
  "Status": "Shipped"
}
```

### Design Pattern 3: Single Table Design

**Advanced pattern where multiple entity types share one table**

```
Table: AppData
Partition Key: PK
Sort Key: SK

User Entity:
PK = "USER#user123"
SK = "PROFILE"

User's Orders:
PK = "USER#user123"
SK = "ORDER#2024-12-01"

Product Entity:
PK = "PRODUCT#prod456"
SK = "METADATA"

Product Reviews:
PK = "PRODUCT#prod456"
SK = "REVIEW#user789#2024-12-01"
```

---

## Indexes

### Visual Representation of Indexes

```
BASE TABLE: Products
┌──────────────┬──────────────┬────────┬──────────┬───────────┐
│ ProductID(PK)│ Category     │ Price  │ Rating   │ Stock     │
├──────────────┼──────────────┼────────┼──────────┼───────────┤
│ PROD-001     │ Electronics  │ 299.99 │ 4.5      │ 100       │
│ PROD-002     │ Books        │ 19.99  │ 4.8      │ 50        │
│ PROD-003     │ Electronics  │ 499.99 │ 4.2      │ 25        │
│ PROD-004     │ Clothing     │ 59.99  │ 4.7      │ 200       │
└──────────────┴──────────────┴────────┴──────────┴───────────┘

GLOBAL SECONDARY INDEX (GSI): CategoryIndex
Partition Key: Category
Sort Key: Price

┌──────────────┬────────┬──────────────┬────────┬──────────┐
│ Category(PK) │Price(SK)│ ProductID   │ Rating │ Stock    │
├──────────────┼────────┼──────────────┼────────┼──────────┤
│ Books        │ 19.99  │ PROD-002     │ 4.8    │ 50       │
│ Clothing     │ 59.99  │ PROD-004     │ 4.7    │ 200      │
│ Electronics  │ 299.99 │ PROD-001     │ 4.5    │ 100      │
│ Electronics  │ 499.99 │ PROD-003     │ 4.2    │ 25       │
└──────────────┴────────┴──────────────┴────────┴──────────┘

Query: "Get all Electronics sorted by price"
→ Use CategoryIndex with Category='Electronics'
```

### Index Selection Decision Tree

```
Do you need to query by attributes other than the primary key?
│
├─ NO → Use base table only
│
└─ YES → Do you need a different partition key?
    │
    ├─ YES → Use Global Secondary Index (GSI)
    │   │
    │   └─ Can you add it after table creation? → YES (GSI)
    │
    └─ NO → Same partition key, different sort key?
        │
        └─ YES → Use Local Secondary Index (LSI)
            │
            └─ Must be created at table creation time
```

---

## Capacity Modes

### 1. On-Demand Mode

**Best for:**
- Unpredictable workloads
- New applications with unknown traffic
- Spiky or short-lived peaks

**Pricing**: Pay per request (reads/writes)
- Write: $1.25 per million write request units
- Read: $0.25 per million read request units

**Characteristics**:
- Instant scaling
- No capacity planning required
- Higher cost per request

### 2. Provisioned Mode

**Best for:**
- Predictable workloads
- Consistent traffic patterns
- Cost optimization for steady state

**Pricing**: Pay for provisioned capacity
- Write Capacity Unit (WCU): 1 write/sec for items up to 1KB
- Read Capacity Unit (RCU): 1 strongly consistent read/sec for items up to 4KB

**Characteristics**:
- Auto-scaling available
- Reserved capacity for cost savings
- Lower cost per request at steady state

### Capacity Calculation Examples

**Write Capacity Units (WCU)**:
```
Example: Write 100 items/second, each 2KB
Calculation: 100 items × (2KB / 1KB) = 200 WCU
```

**Read Capacity Units (RCU)**:
```
Strongly Consistent Reads:
Example: Read 50 items/second, each 8KB
Calculation: 50 items × (8KB / 4KB) = 100 RCU

Eventually Consistent Reads (default):
Example: Read 50 items/second, each 8KB
Calculation: 50 items × (8KB / 4KB) / 2 = 50 RCU
```

---

## Query vs Scan

### Query Operation

```
Table: OrderHistory
PK: UserID | SK: OrderTimestamp

Query: Get all orders for user123 in December 2024

┌─────────────────────────────────────────┐
│       Partition: user123                │
│  ┌───────────────────────────────────┐  │
│  │ 2024-11-15T10:00:00Z (Skipped)   │  │
│  ├───────────────────────────────────┤  │
│  │ 2024-12-01T14:30:00Z ✓ Returned  │  │ ← Efficient!
│  ├───────────────────────────────────┤  │   Only reads
│  │ 2024-12-10T09:15:00Z ✓ Returned  │  │   relevant
│  ├───────────────────────────────────┤  │   partition
│  │ 2024-12-20T16:45:00Z ✓ Returned  │  │
│  ├───────────────────────────────────┤  │
│  │ 2025-01-05T11:20:00Z (Skipped)   │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘

Result: Fast, efficient, low cost
```

### Scan Operation

```
Table: Products (10,000 items across all partitions)

Scan: Find all products with Price < 50

┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│Partition1│ │Partition2│ │Partition3│ │PartitionN│
│ Read All │ │ Read All │ │ Read All │ │ Read All │ ← Inefficient!
│ Filter   │ │ Filter   │ │ Filter   │ │ Filter   │   Reads entire
│ Return 10│ │ Return 8 │ │ Return 12│ │ Return 5 │   table, then
└──────────┘ └──────────┘ └──────────┘ └──────────┘   filters

Result: Slow, expensive, high RCU consumption
Scanned: 10,000 items
Returned: 35 items (but charged for 10,000!)
```

---

## DynamoDB Streams

### Stream Architecture

```
DynamoDB Table
    │
    ├─ Item Modified (INSERT/UPDATE/DELETE)
    │
    ▼
Stream Record Created
┌─────────────────────────────────────┐
│ EventID: unique-id                  │
│ EventName: INSERT|MODIFY|REMOVE     │
│ EventVersion: 1.1                   │
│ EventSource: aws:dynamodb           │
│ StreamViewType:                     │
│   - KEYS_ONLY                       │
│   - NEW_IMAGE                       │
│   - OLD_IMAGE                       │
│   - NEW_AND_OLD_IMAGES              │
└─────────────────────────────────────┘
    │
    ▼
Stream Consumer (Lambda, Kinesis, etc.)
```

**Use Cases**:
- Real-time analytics
- Data replication
- Audit trails
- Triggering workflows
- Cross-region replication

---

## Best Practices

### 1. Partition Key Design

**✅ Good Partition Key:**
- High cardinality (many unique values)
- Even distribution of access patterns
- Examples: UserID, OrderID, DeviceID

**❌ Bad Partition Key:**
- Low cardinality
- Uneven access (hot partitions)
- Examples: Status (only "active"/"inactive"), Country (some countries much larger)

### 2. Use Sparse Indexes

Only items with the index key attributes are included in the index (saves cost).

```
Base Table: Users (1 million items)
GSI: PremiumUserIndex on attribute "PremiumSince"

Only premium users (100K) have "PremiumSince" attribute
→ GSI only contains 100K items (saves 90% storage cost)
```

### 3. Implement Optimistic Locking

Use conditional writes with version numbers to prevent lost updates.

```python
# Include version in each item
Item = {
    'UserID': 'user123',
    'Balance': 100,
    'Version': 5
}

# Update only if version matches (prevents race conditions)
table.update_item(
    Key={'UserID': 'user123'},
    UpdateExpression='SET Balance = Balance + :val, Version = Version + :inc',
    ConditionExpression='Version = :expected_version',
    ExpressionAttributeValues={
        ':val': 50,
        ':inc': 1,
        ':expected_version': 5
    }
)
```

### 4. Use Batch Operations

**Single Operations**: 25 WCU for 25 writes
**Batch Operation**: 25 WCU for 25 writes (same cost, better performance)

```python
# More efficient
with table.batch_writer() as batch:
    for item in items:
        batch.put_item(Item=item)
```

### 5. Enable Point-in-Time Recovery (PITR)

- Continuous backups for 35 days
- Restore to any point in time
- No performance impact
- Minimal cost (~$0.20 per GB per month)

---

## Common Anti-Patterns to Avoid

### ❌ Anti-Pattern 1: Using Scan for Queries

**Problem**: Scanning entire table for specific items
```python
# BAD: Scans entire table
response = table.scan(
    FilterExpression='Category = :cat',
    ExpressionAttributeValues={':cat': 'Electronics'}
)
```

**Solution**: Use GSI or proper Query
```python
# GOOD: Uses CategoryIndex GSI
response = table.query(
    IndexName='CategoryIndex',
    KeyConditionExpression='Category = :cat',
    ExpressionAttributeValues={':cat': 'Electronics'}
)
```

### ❌ Anti-Pattern 2: Storing Large Attributes

**Problem**: Attributes > 400KB waste capacity units
**Solution**: Store large data in S3, keep reference in DynamoDB

```python
# Store in S3
s3.put_object(Bucket='my-bucket', Key='user123/profile.jpg', Body=image_data)

# Store reference in DynamoDB
table.put_item(Item={
    'UserID': 'user123',
    'ProfileImageURL': 's3://my-bucket/user123/profile.jpg'
})
```

### ❌ Anti-Pattern 3: Using DynamoDB as a Queue

**Problem**: Frequent scans and deletes for queue-like patterns
**Solution**: Use SQS (Simple Queue Service) for queue workloads

---

## Cost Optimization Tips

1. **Use On-Demand for unpredictable workloads, Provisioned for steady state**
2. **Enable Auto Scaling** for provisioned capacity
3. **Use Eventually Consistent Reads** when possible (50% cheaper)
4. **Implement TTL** (Time To Live) for automatic deletion of expired items
5. **Use projection expressions** to retrieve only needed attributes
6. **Archive old data** to S3 using DynamoDB export or Glue ETL
7. **Monitor with CloudWatch** to optimize capacity settings

---

## Use Cases by Industry

### E-Commerce
- Shopping cart management
- Product catalog
- Order history
- User sessions
- Real-time inventory

### Gaming
- Player profiles
- Leaderboards
- Game state management
- Session data
- In-game items

### IoT
- Device metadata
- Sensor data (time-series)
- Device shadow state
- Telemetry data
- Event logs

### Financial Services
- Transaction history
- User accounts
- Fraud detection data
- Real-time balances
- Trading data

### Media & Entertainment
- Content metadata
- User preferences
- Viewing history
- Recommendation data
- Content delivery tracking

---

## Comparison with Other Databases

| Feature | DynamoDB | RDS (PostgreSQL) | MongoDB Atlas |
|---------|----------|------------------|---------------|
| Type | NoSQL Key-Value/Document | SQL Relational | NoSQL Document |
| Scaling | Automatic, horizontal | Vertical, read replicas | Automatic, horizontal |
| Performance | Single-digit ms | Milliseconds to seconds | Milliseconds |
| Schema | Schema-less | Fixed schema | Flexible schema |
| Transactions | ACID on single item, limited multi-item | Full ACID | ACID |
| Query Flexibility | Limited (key-based) | Very flexible (SQL) | Flexible (rich queries) |
| Cost Model | Pay per request/capacity | Pay for instances | Pay for instances |
| Maintenance | Fully managed | Managed | Fully managed |

---

## DynamoDB Limits

| Resource | Limit |
|----------|-------|
| Maximum item size | 400 KB |
| Maximum partition size | 10 GB |
| Partition throughput | 3000 RCU or 1000 WCU |
| Attribute name length | 64KB |
| Number of LSIs | 5 per table |
| Number of GSIs | 20 per table |
| Batch operations | 25 items or 16MB |
| Query/Scan result set | 1 MB per call |
| Transaction items | 100 items or 4MB |

---

## Security Best Practices

### 1. Use IAM Roles and Policies
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:Query"
      ],
      "Resource": "arn:aws:dynamodb:region:account:table/Users",
      "Condition": {
        "ForAllValues:StringEquals": {
          "dynamodb:LeadingKeys": ["${aws:userid}"]
        }
      }
    }
  ]
}
```

### 2. Enable Encryption at Rest
- Use AWS managed keys (default)
- Or customer managed keys (CMK) for compliance

### 3. Enable Encryption in Transit
- All DynamoDB API calls use HTTPS/TLS

### 4. Use VPC Endpoints
- Keep traffic within AWS network
- No internet gateway needed
- Reduces costs and improves security

### 5. Enable CloudTrail Logging
- Audit all DynamoDB API calls
- Track who accessed what data
- Compliance and forensics

---

## Monitoring and Troubleshooting

### Key CloudWatch Metrics

1. **ConsumedReadCapacityUnits / ConsumedWriteCapacityUnits**
   - Monitor actual vs provisioned capacity
   - Alert on throttling

2. **UserErrors**
   - Track client-side errors (400 errors)
   - Common: ValidationException, ConditionalCheckFailedException

3. **SystemErrors**
   - Track server-side errors (500 errors)
   - Should be rare, contact AWS if persistent

4. **Throttled Requests**
   - ReadThrottleEvents / WriteThrottleEvents
   - Indicates insufficient capacity

5. **Latency Metrics**
   - SuccessfulRequestLatency
   - Track p99, p95, p50 latencies

### Common Issues and Solutions

**Issue: High latency on queries**
- Solution: Add appropriate GSI, use Query instead of Scan

**Issue: Throttling errors**
- Solution: Increase provisioned capacity or switch to On-Demand

**Issue: Hot partition**
- Solution: Redesign partition key for better distribution

**Issue: High costs**
- Solution: Use sparse indexes, implement TTL, archive old data

---

## Conclusion

DynamoDB excels at:
- ✅ High-scale, low-latency workloads
- ✅ Unpredictable or spiky traffic
- ✅ Key-value access patterns
- ✅ Time-series data
- ✅ Serverless architectures

Consider alternatives when you need:
- ❌ Complex joins and aggregations
- ❌ Ad-hoc analytical queries
- ❌ Full-text search
- ❌ ACID transactions across multiple tables
- ❌ Traditional SQL queries

**The key to success with DynamoDB is understanding your access patterns upfront and designing your schema accordingly.**
