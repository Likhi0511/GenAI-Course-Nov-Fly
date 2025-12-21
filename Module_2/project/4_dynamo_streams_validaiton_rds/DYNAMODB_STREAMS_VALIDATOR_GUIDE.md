# DynamoDB Streams → Lambda Validator Integration Guide

## 📋 Overview

This guide covers the complete setup of the Product Validator Lambda triggered by DynamoDB Streams:

**Complete Flow:**
```
CSV Upload → CSV Parser → DynamoDB UploadRecords → DynamoDB Streams → Validator Lambda → RDS Products / SQS Errors
```

**What This Step Does:**
- ✅ Reads records from DynamoDB Streams
- ✅ Validates product data against business rules
- ✅ Inserts valid products to RDS `products` table
- ✅ Sends invalid products to SQS error queue
- ✅ Updates DynamoDB record status
- ✅ Tracks validation errors in RDS
- ✅ Updates upload history with counts

---

## 🎯 What Actually Happens - Complete Integration Flow

### **Phase 1: DynamoDB Streams Configuration**

#### **What is DynamoDB Streams?**

DynamoDB Streams captures **a time-ordered sequence of item-level changes** in a DynamoDB table. When you enable streams on the `UploadRecords` table, every INSERT, MODIFY, or DELETE operation creates a **stream record**.

**Stream Record Structure:**
```json
{
  "eventID": "1234567890",
  "eventName": "INSERT",
  "eventVersion": "1.1",
  "eventSource": "aws:dynamodb",
  "awsRegion": "us-east-1",
  "dynamodb": {
    "ApproximateCreationDateTime": 1703152845.0,
    "Keys": {
      "upload_id": {"S": "UPLOAD_20241221_103045"},
      "record_id": {"S": "REC_00001"}
    },
    "NewImage": {
      "upload_id": {"S": "UPLOAD_20241221_103045"},
      "record_id": {"S": "REC_00001"},
      "vendor_id": {"S": "VEND001"},
      "row_number": {"N": "1"},
      "product_data": {
        "M": {
          "vendor_product_id": {"S": "PROD0001"},
          "product_name": {"S": "Wireless Mouse - Model 651"},
          "category": {"S": "Computer Accessories"},
          "sku": {"S": "CA-VEND001-0001"},
          "price": {"N": "19.99"},
          "stock_quantity": {"N": "150"},
          "brand": {"S": "TechGear"},
          "description": {"S": "Ergonomic wireless mouse..."},
          "unit": {"S": "piece"},
          "weight_kg": {"N": "0.25"},
          "dimensions_cm": {"S": "12x8x4"},
          "image_url": {"S": "https://images.example.com/mouse.jpg"}
        }
      },
      "status": {"S": "pending_validation"},
      "created_at": {"S": "2024-12-21T10:30:46.123Z"}
    },
    "SequenceNumber": "111",
    "SizeBytes": 1024,
    "StreamViewType": "NEW_IMAGE"
  }
}
```

**Important Fields:**
- **eventName**: INSERT (new record), MODIFY (updated), REMOVE (deleted)
- **Keys**: Primary key (upload_id + record_id)
- **NewImage**: Complete new item data (because StreamViewType = NEW_IMAGE)
- **SequenceNumber**: Unique identifier for ordering

#### **How Streams Work:**

```
DynamoDB Table: UploadRecords
  ↓ (Stream enabled with NEW_IMAGE)
  ↓
DynamoDB Stream (24-hour retention)
├── Shard 1: Records 1-1000
├── Shard 2: Records 1001-2000
└── Shard 3: Records 2001-3000
  ↓ (Batch records every ~1 second or 100 records)
  ↓
Lambda Event Source Mapping
  - BatchSize: 100 (max records per invocation)
  - MaximumBatchingWindowInSeconds: 0 (process immediately)
  - StartingPosition: LATEST (only new records)
  ↓
Validator Lambda Invoked
  - Receives batch of stream records
  - Processes each record
  - Returns success/failure
```

**Stream Sharding:**
```
When CSV Parser inserts 31 records to DynamoDB:
  ↓
31 INSERT operations create 31 stream records
  ↓
DynamoDB assigns records to shards based on partition key hash
  ↓
Example distribution:
  Shard 1: REC_00001 to REC_00010 (10 records)
  Shard 2: REC_00011 to REC_00020 (10 records)
  Shard 3: REC_00021 to REC_00031 (11 records)
  ↓
Lambda invoked 3 times (once per shard batch)
  OR
Lambda invoked 1 time (if all fit in single batch)
```

#### **Stream to Lambda Flow:**

```
T+0ms: CSV Parser completes
  - 31 records inserted into DynamoDB
  - 31 stream records created
  
T+10ms: DynamoDB Stream processing
  - Records available in stream
  - Grouped into batches
  
T+20ms: Event Source Mapping polls stream
  - Retrieves batch of records (up to 100)
  - Prepares Lambda event
  
T+50ms: Lambda invoked
  - Event contains stream records
  - Lambda starts processing
  
T+2000ms: Lambda completes
  - Returns success
  - Stream records marked as processed
  - Stream checkpoint updated
```

---

### **Phase 2: Lambda Event Source Mapping**

#### **What is Event Source Mapping?**

Event Source Mapping is an AWS Lambda resource that **reads from DynamoDB Streams** and **invokes your Lambda function** with batches of records.

**Configuration:**
```json
{
  "UUID": "12345678-1234-1234-1234-123456789012",
  "BatchSize": 100,
  "StartingPosition": "LATEST",
  "EventSourceArn": "arn:aws:dynamodb:us-east-1:123456789012:table/UploadRecords/stream/2024-12-21T10:30:00.000",
  "FunctionArn": "arn:aws:lambda:us-east-1:123456789012:function:product-validator",
  "State": "Enabled",
  "StateTransitionReason": "User initiated",
  "LastProcessingResult": "OK",
  "MaximumBatchingWindowInSeconds": 0,
  "MaximumRecordAgeInSeconds": 604800,
  "BisectBatchOnFunctionError": false,
  "MaximumRetryAttempts": 10000,
  "ParallelizationFactor": 1,
  "DestinationConfig": {
    "OnFailure": {}
  }
}
```

**Key Parameters:**

1. **BatchSize: 100**
   - Maximum records per Lambda invocation
   - Larger batches = fewer invocations = lower cost
   - But larger batches = longer processing time

2. **StartingPosition: LATEST**
   - Only process new records (after mapping created)
   - Alternative: TRIM_HORIZON (process from oldest available)

3. **MaximumBatchingWindowInSeconds: 0**
   - Don't wait to accumulate records
   - Process immediately when records available
   - Set to 1-300 for batching delay

4. **MaximumRetryAttempts: 10000**
   - Retry failed batches up to 10,000 times
   - Useful for transient errors

5. **ParallelizationFactor: 1**
   - Number of concurrent Lambda instances per shard
   - Set to 2-10 for higher throughput

#### **Polling Behavior:**

```
Event Source Mapping (continuous loop):
  ↓
1. Poll DynamoDB Stream (GetRecords API)
   - Check each shard for new records
   - Retrieve up to BatchSize records
   
2. Records available?
   NO → Wait 1 second → Poll again
   YES ↓
   
3. Prepare Lambda event
   - Convert stream records to Lambda event format
   - Add metadata (eventSourceArn, etc.)
   
4. Invoke Lambda function
   - Synchronous invocation
   - Wait for response
   
5. Lambda success?
   YES → Mark records as processed → Update checkpoint
   NO → Retry (up to MaximumRetryAttempts)
```

**Checkpoint Management:**
```
Stream Checkpoint (per shard):
  - Tracks last processed sequence number
  - Stored by Lambda service
  - Ensures records processed exactly once
  
Example:
  Shard 1 checkpoint: SequenceNumber 110
  - Records 1-110 already processed
  - Next poll starts from SequenceNumber 111
```

---

### **Phase 3: Validator Lambda Execution**

#### **3.1 Lambda Receives Stream Event**

**Event Structure:**
```json
{
  "Records": [
    {
      "eventID": "1",
      "eventName": "INSERT",
      "eventSource": "aws:dynamodb",
      "awsRegion": "us-east-1",
      "dynamodb": {
        "ApproximateCreationDateTime": 1703152845.0,
        "Keys": {...},
        "NewImage": {...},
        "SequenceNumber": "111",
        "SizeBytes": 1024,
        "StreamViewType": "NEW_IMAGE"
      },
      "eventSourceARN": "arn:aws:dynamodb:us-east-1:123456789012:table/UploadRecords/stream/2024-12-21T10:30:00.000"
    },
    // ... up to 99 more records
  ]
}
```

**Handler receives event:**
```python
def lambda_handler(event, context):
    # event['Records'] = list of stream records
    # len(event['Records']) = 1 to 100
    
    for stream_record in event['Records']:
        # Process each record
```

#### **3.2 Parse DynamoDB Stream Record**

**DynamoDB uses custom type format:**
```json
{
  "vendor_product_id": {"S": "PROD0001"},  // String
  "price": {"N": "19.99"},                 // Number
  "stock_quantity": {"N": "150"},          // Number
  "status": {"S": "pending_validation"},   // String
  "product_data": {"M": {...}}             // Map
}
```

**Lambda converts to Python types:**
```python
# Extract values from DynamoDB format
upload_id = new_image['upload_id']['S']
# "UPLOAD_20241221_103045"

price = Decimal(new_image['product_data']['M']['price']['N'])
# Decimal('19.99')

stock = int(new_image['product_data']['M']['stock_quantity']['N'])
# 150
```

**Why Decimal instead of float?**
```python
# Python floats have precision issues
price = float('19.99')  # 19.990000000000002

# DynamoDB requires Decimal for precision
price = Decimal('19.99')  # Exact: 19.99
```

#### **3.3 Validation Process**

**Validation Pipeline:**
```
Product Data
  ↓
1. Required Fields Check
   - vendor_product_id ✓
   - product_name ✓
   - category ✓
   - sku ✓
   - price ✓
   - stock_quantity ✓
  ↓
2. Price Validation
   - price >= 0.01 ✓
   - price <= 999,999.99 ✓
  ↓
3. Stock Validation
   - stock >= 0 ✓
   - stock <= 1,000,000 ✓
  ↓
4. Field Length Validation
   - product_name <= 200 chars ✓
   - description <= 2000 chars ✓
   - sku <= 100 chars ✓
  ↓
5. Category Validation (RDS Query)
   SELECT * FROM product_categories 
   WHERE category_name = 'Computer Accessories'
   AND is_active = TRUE
   ✓ Found
  ↓
6. SKU Uniqueness Check (RDS Query)
   SELECT * FROM products WHERE sku = 'CA-VEND001-0001'
   ✓ Not found (unique!)
  ↓
7. Vendor Product ID Uniqueness (RDS Query)
   SELECT * FROM products 
   WHERE vendor_id = 'VEND001' 
   AND vendor_product_id = 'PROD0001'
   ✓ Not found (unique!)
  ↓
ALL VALIDATIONS PASSED! ✓
```

**Example Validation Failures:**

**Failure 1: Missing Required Field**
```python
product_data = {
  'vendor_product_id': 'PROD0001',
  'product_name': 'Wireless Mouse',
  'category': 'Computer Accessories',
  # Missing: sku, price, stock_quantity
}

Result:
  is_valid = False
  error_type = 'MISSING_REQUIRED_FIELDS'
  error_message = 'Missing required fields: sku, price, stock_quantity'
```

**Failure 2: Invalid Price**
```python
product_data = {
  'price': Decimal('-10.00')  # Negative price!
}

Result:
  is_valid = False
  error_type = 'INVALID_PRICE'
  error_message = 'Price must be at least 0.01'
```

**Failure 3: Duplicate SKU**
```python
# Product with SKU 'CA-VEND001-0001' already exists
product_data = {
  'sku': 'CA-VEND001-0001'
}

RDS Query:
  SELECT product_id, vendor_id FROM products WHERE sku = 'CA-VEND001-0001'
  Result: 1 row found

Result:
  is_valid = False
  error_type = 'DUPLICATE_SKU'
  error_message = 'Duplicate SKU: CA-VEND001-0001 already exists (Product ID: 12345, Vendor: VEND002)'
```

**Failure 4: Invalid Category**
```python
product_data = {
  'category': 'InvalidCategory'
}

RDS Query:
  SELECT category_id FROM product_categories 
  WHERE category_name = 'InvalidCategory' AND is_active = TRUE
  Result: 0 rows

Result:
  is_valid = False
  error_type = 'INVALID_CATEGORY'
  error_message = 'Invalid category: InvalidCategory. Category not found in allowed list.'
```

#### **3.4 Valid Product Flow**

**When validation passes:**

```
Product: PROD0001 - Wireless Mouse
  ↓
Validation: ALL PASSED ✓
  ↓
Insert to RDS products table:
  
  BEGIN TRANSACTION;
  
  INSERT INTO products (
    vendor_id, vendor_product_id, product_name, category,
    subcategory, description, sku, brand, price, compare_at_price,
    stock_quantity, unit, weight_kg, dimensions_cm, image_url,
    upload_id, status
  )
  VALUES (
    'VEND001', 'PROD0001', 'Wireless Mouse - Model 651', 
    'Computer Accessories', 'Mice & Keyboards', 
    'Ergonomic wireless mouse...', 'CA-VEND001-0001',
    'TechGear', 19.99, NULL, 150, 'piece', 0.25, 
    '12x8x4', 'https://...', 'UPLOAD_20241221_103045', 'active'
  )
  RETURNING product_id;
  
  -- Returns: product_id = 12345
  
  COMMIT;
  ↓
Update DynamoDB record status:
  
  UPDATE UploadRecords
  SET status = 'validated',
      processed_at = '2024-12-21T10:31:15.456Z'
  WHERE upload_id = 'UPLOAD_20241221_103045'
    AND record_id = 'REC_00001';
  ↓
Update RDS upload_history:
  
  UPDATE upload_history
  SET valid_records = valid_records + 1,
      status = CASE 
        WHEN (valid_records + 1 + error_records) = total_records 
        THEN 'completed'
        ELSE 'processing'
      END
  WHERE upload_id = 'UPLOAD_20241221_103045';
  ↓
Result: Product successfully onboarded! ✓
```

**RDS Tables After Valid Product:**

```sql
-- products table
SELECT product_id, vendor_id, sku, product_name, price, stock_quantity, status
FROM products 
WHERE upload_id = 'UPLOAD_20241221_103045';

 product_id | vendor_id | sku               | product_name           | price | stock_quantity | status
------------+-----------+-------------------+------------------------+-------+----------------+--------
 12345      | VEND001   | CA-VEND001-0001   | Wireless Mouse - M651  | 19.99 | 150            | active

-- upload_history table
SELECT upload_id, total_records, valid_records, error_records, status
FROM upload_history
WHERE upload_id = 'UPLOAD_20241221_103045';

 upload_id              | total_records | valid_records | error_records | status
------------------------+---------------+---------------+---------------+-----------
 UPLOAD_20241221_103045 | 31            | 1             | 0             | processing
```

#### **3.5 Invalid Product Flow**

**When validation fails:**

```
Product: PROD0999 - Invalid Product
  ↓
Validation: FAILED ✗
  error_type = 'INVALID_PRICE'
  error_message = 'Price must be at least 0.01'
  ↓
Send error to SQS queue:
  
  Message Body:
  {
    "upload_id": "UPLOAD_20241221_103045",
    "vendor_id": "VEND001",
    "record_id": "REC_00015",
    "row_number": 15,
    "error_type": "INVALID_PRICE",
    "error_message": "Price must be at least 0.01",
    "product_data": {
      "vendor_product_id": "PROD0999",
      "price": -10.00,
      ...
    },
    "timestamp": "2024-12-21T10:31:15.789Z"
  }
  
  Message Attributes:
  - upload_id: UPLOAD_20241221_103045
  - vendor_id: VEND001
  - error_type: INVALID_PRICE
  ↓
Insert error to RDS validation_errors table:
  
  INSERT INTO validation_errors (
    upload_id, vendor_id, row_number, vendor_product_id,
    error_type, error_field, error_message, original_data
  )
  VALUES (
    'UPLOAD_20241221_103045', 'VEND001', 15, 'PROD0999',
    'INVALID_PRICE', NULL, 'Price must be at least 0.01',
    '{"vendor_product_id": "PROD0999", "price": -10.00, ...}'::jsonb
  );
  ↓
Update DynamoDB record status:
  
  UPDATE UploadRecords
  SET status = 'error',
      error_reason = 'INVALID_PRICE',
      error_details = 'Price must be at least 0.01',
      processed_at = '2024-12-21T10:31:15.789Z'
  WHERE upload_id = 'UPLOAD_20241221_103045'
    AND record_id = 'REC_00015';
  ↓
Update RDS upload_history:
  
  UPDATE upload_history
  SET error_records = error_records + 1,
      status = CASE 
        WHEN (valid_records + error_records + 1) = total_records 
        THEN 'partial'
        ELSE 'processing'
      END
  WHERE upload_id = 'UPLOAD_20241221_103045';
  ↓
Result: Error tracked and queued for notification ✗
```

**RDS Tables After Invalid Product:**

```sql
-- validation_errors table
SELECT error_id, upload_id, row_number, error_type, error_message
FROM validation_errors
WHERE upload_id = 'UPLOAD_20241221_103045';

 error_id | upload_id              | row_number | error_type    | error_message
----------+------------------------+------------+---------------+---------------------------
 1        | UPLOAD_20241221_103045 | 15         | INVALID_PRICE | Price must be at least...

-- upload_history table
SELECT upload_id, total_records, valid_records, error_records, status
FROM upload_history
WHERE upload_id = 'UPLOAD_20241221_103045';

 upload_id              | total_records | valid_records | error_records | status
------------------------+---------------+---------------+---------------+-----------
 UPLOAD_20241221_103045 | 31            | 1             | 1             | processing
```

#### **3.6 Batch Processing Example**

**Processing 31 records from stream:**

```
Lambda invoked with 31 stream records
  ↓
Record 1: PROD0001 - Wireless Mouse
  Validation: PASS ✓
  → RDS: Inserted (product_id: 12345)
  → DynamoDB: status = 'validated'
  → Counts: valid_count = 1
  
Record 2: PROD0002 - USB-C Hub
  Validation: PASS ✓
  → RDS: Inserted (product_id: 12346)
  → DynamoDB: status = 'validated'
  → Counts: valid_count = 2
  
Record 3: PROD0003 - Invalid Price
  Validation: FAIL ✗ (INVALID_PRICE)
  → SQS: Error queued
  → RDS: Error logged
  → DynamoDB: status = 'error'
  → Counts: error_count = 1
  
... (28 more records)

Record 31: PROD0031 - Laptop Stand
  Validation: PASS ✓
  → RDS: Inserted (product_id: 12375)
  → DynamoDB: status = 'validated'
  → Counts: valid_count = 29
  ↓
Final Counts:
  Total: 31
  Valid: 29
  Errors: 2
  Success Rate: 93.5%
  ↓
Update upload_history:
  valid_records = 29
  error_records = 2
  status = 'partial' (because error_records > 0)
  processing_completed_at = CURRENT_TIMESTAMP
  ↓
Publish CloudWatch Metrics:
  - ProductsValidated: 29
  - ProductsRejected: 2
  - ValidationProcessingTime: 3.45 seconds
```

---

### **Phase 4: Post-Validation Flow**

#### **4.1 Upload Completion Detection**

**How does Lambda know upload is complete?**

```sql
-- After each batch, check upload_history
SELECT 
  upload_id,
  total_records,
  valid_records,
  error_records,
  (valid_records + error_records) AS processed_records,
  CASE 
    WHEN (valid_records + error_records) = total_records THEN 'COMPLETE'
    ELSE 'IN_PROGRESS'
  END AS processing_status
FROM upload_history
WHERE upload_id = 'UPLOAD_20241221_103045';

Result:
 upload_id              | total | valid | error | processed | processing_status
------------------------+-------+-------+-------+-----------+------------------
 UPLOAD_20241221_103045 | 31    | 29    | 2     | 31        | COMPLETE
```

**When complete, upload_history status updated:**
```sql
UPDATE upload_history
SET 
  status = CASE 
    WHEN error_records > 0 THEN 'partial'
    ELSE 'completed'
  END,
  processing_completed_at = CURRENT_TIMESTAMP
WHERE upload_id = 'UPLOAD_20241221_103045';

Result:
  status = 'partial' (because 2 errors)
  processing_completed_at = '2024-12-21T10:31:18.123Z'
```

#### **4.2 SQS Error Queue**

**Purpose:** Aggregate errors for batch notification

**Queue Structure:**
```
SQS Queue: product-validation-errors
├── Message 1 (REC_00003):
│   {
│     "upload_id": "UPLOAD_20241221_103045",
│     "error_type": "INVALID_PRICE",
│     "error_message": "Price must be at least 0.01",
│     ...
│   }
├── Message 2 (REC_00027):
│   {
│     "upload_id": "UPLOAD_20241221_103045",
│     "error_type": "DUPLICATE_SKU",
│     "error_message": "Duplicate SKU: CA-VEND001-0027...",
│     ...
│   }
└── ... (all errors from this upload)
```

**Next Step:** Error Processor Lambda
- Triggered by SQS (batch of errors)
- Generates error CSV file
- Uploads to S3: `errors/VEND001/UPLOAD_20241221_103045_errors.csv`
- Triggers SNS email notification to vendor

#### **4.3 Final State**

**After all 31 records processed:**

**DynamoDB: UploadRecords**
```
upload_id: UPLOAD_20241221_103045
├── REC_00001: status = 'validated' ✓
├── REC_00002: status = 'validated' ✓
├── REC_00003: status = 'error' (INVALID_PRICE) ✗
├── ...
├── REC_00027: status = 'error' (DUPLICATE_SKU) ✗
└── REC_00031: status = 'validated' ✓

Total: 31 records
Validated: 29 (93.5%)
Errors: 2 (6.5%)
```

**RDS: products table**
```sql
SELECT COUNT(*) FROM products WHERE upload_id = 'UPLOAD_20241221_103045';
-- Result: 29 (only valid products)
```

**RDS: validation_errors table**
```sql
SELECT COUNT(*) FROM validation_errors WHERE upload_id = 'UPLOAD_20241221_103045';
-- Result: 2 (only errors)
```

**RDS: upload_history table**
```sql
SELECT * FROM upload_history WHERE upload_id = 'UPLOAD_20241221_103045';

 upload_id              | total | valid | error | status  | completed_at
------------------------+-------+-------+-------+---------+-------------------------
 UPLOAD_20241221_103045 | 31    | 29    | 2     | partial | 2024-12-21T10:31:18.123Z
```

---

## 🏗️ Architecture Diagram

```
                    ┌─────────────────────────────────────────┐
                    │     DYNAMODB STREAMS INTEGRATION        │
                    └─────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: CSV Parser Inserts Records                                         │
│                                                                             │
│  CSV Parser Lambda                                                          │
│  ↓ BatchWriteItem (31 records)                                             │
│  DynamoDB: UploadRecords                                                    │
│  ├── UPLOAD_20241221_103045 / REC_00001 (status: pending_validation)       │
│  ├── UPLOAD_20241221_103045 / REC_00002 (status: pending_validation)       │
│  └── ... (31 total records)                                                │
└────────────────────────────────────────────────────────────────────────────┘
                              ↓
                    DynamoDB Streams Enabled
                              ↓
┌────────────────────────────────────────────────────────────────────────────┐
│ STEP 2: DynamoDB Streams Captures Changes                                  │
│                                                                             │
│  DynamoDB Stream                                                            │
│  ├── Stream Record 1 (INSERT - REC_00001)                                  │
│  │   └── NewImage: {upload_id, record_id, product_data, status, ...}      │
│  ├── Stream Record 2 (INSERT - REC_00002)                                  │
│  └── ... (31 stream records total)                                         │
│                                                                             │
│  Stream Retention: 24 hours                                                │
│  Stream Shards: 1-3 (depends on throughput)                                │
└────────────────────────────────────────────────────────────────────────────┘
                              ↓
                  Event Source Mapping Polls
                              ↓
┌────────────────────────────────────────────────────────────────────────────┐
│ STEP 3: Event Source Mapping Batches Records                              │
│                                                                             │
│  Event Source Mapping Configuration                                         │
│  ├── BatchSize: 100                                                        │
│  ├── StartingPosition: LATEST                                              │
│  ├── MaximumRetryAttempts: 10000                                           │
│  └── Parallelization: 1                                                    │
│                                                                             │
│  Batching Logic:                                                            │
│  ├── Collect up to 100 records                                             │
│  ├── OR wait 0 seconds (MaximumBatchingWindow)                             │
│  └── Invoke Lambda with batch                                              │
└────────────────────────────────────────────────────────────────────────────┘
                              ↓
              Lambda Invoked with Stream Event
                              ↓
┌────────────────────────────────────────────────────────────────────────────┐
│ STEP 4: Validator Lambda Processes Each Record                            │
│                                                                             │
│  For each stream record (31 total):                                        │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │ Parse Stream Record                                                   │ │
│  │ ↓                                                                     │ │
│  │ Extract: upload_id, record_id, vendor_id, product_data              │ │
│  │ Convert DynamoDB types to Python types                               │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                              ↓                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │ Validate Product Data                                                 │ │
│  │ ├─ Required fields ✓                                                  │ │
│  │ ├─ Price range ✓                                                      │ │
│  │ ├─ Stock range ✓                                                      │ │
│  │ ├─ Field lengths ✓                                                    │ │
│  │ ├─ Category exists (RDS query) ✓                                     │ │
│  │ ├─ SKU unique (RDS query) ✓                                          │ │
│  │ └─ Vendor product ID unique (RDS query) ✓                            │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                              ↓                                              │
│                     Valid or Invalid?                                       │
│                              ↓                                              │
│              ┌───────────────┴───────────────┐                             │
│              ↓                               ↓                             │
│       VALID PRODUCT                   INVALID PRODUCT                      │
│              ↓                               ↓                             │
│  ┌────────────────────────┐     ┌────────────────────────┐               │
│  │ Insert to RDS          │     │ Send Error to SQS      │               │
│  │ ↓                      │     │ ↓                      │               │
│  │ products table         │     │ Error Queue Message    │               │
│  │ (product_id: 12345)    │     │ {error_type, msg, ...} │               │
│  └────────────────────────┘     └────────────────────────┘               │
│              ↓                               ↓                             │
│  ┌────────────────────────┐     ┌────────────────────────┐               │
│  │ Update DynamoDB        │     │ Insert to RDS          │               │
│  │ ↓                      │     │ ↓                      │               │
│  │ status: 'validated'    │     │ validation_errors      │               │
│  │ processed_at: NOW      │     │ table                  │               │
│  └────────────────────────┘     └────────────────────────┘               │
│              ↓                               ↓                             │
│              └───────────────┬───────────────┘                             │
│                              ↓                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │ Update DynamoDB Record Status                                         │ │
│  │ ↓                                                                     │ │
│  │ SET status = 'validated' OR 'error'                                  │ │
│  │ SET processed_at = CURRENT_TIMESTAMP                                 │ │
│  │ SET error_reason, error_details (if error)                           │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  After all 31 records processed:                                           │
│  ├─ Valid products: 29                                                     │
│  ├─ Invalid products: 2                                                    │
│  └─ Success rate: 93.5%                                                    │
└────────────────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────────────────┐
│ STEP 5: Update Upload History & Publish Metrics                           │
│                                                                             │
│  RDS: upload_history                                                        │
│  ↓                                                                          │
│  UPDATE upload_history                                                      │
│  SET valid_records = 29,                                                   │
│      error_records = 2,                                                    │
│      status = 'partial',  -- (because errors > 0)                          │
│      processing_completed_at = CURRENT_TIMESTAMP                           │
│  WHERE upload_id = 'UPLOAD_20241221_103045';                               │
│                                                                             │
│  CloudWatch Metrics                                                         │
│  ├─ ProductsValidated: 29                                                  │
│  ├─ ProductsRejected: 2                                                    │
│  └─ ValidationProcessingTime: 3.45 seconds                                 │
└────────────────────────────────────────────────────────────────────────────┘
                              ↓
                      NEXT STEPS
                              ↓
┌────────────────────────────────────────────────────────────────────────────┐
│ Error Processor Lambda (triggered by SQS)                                  │
│ ├─ Aggregates all errors for upload                                        │
│ ├─ Generates error CSV                                                     │
│ ├─ Uploads to S3: errors/VEND001/UPLOAD_20241221_103045_errors.csv        │
│ └─ Triggers SNS notification to vendor                                     │
│                                                                             │
│ SNS Email Notification                                                      │
│ ├─ Subject: "Product Upload Validation Complete (93.5% success)"          │
│ ├─ Body: Summary of valid/invalid products                                │
│ └─ Attachment: Error CSV download link                                     │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Deployment Instructions

### Part 1: Create SQS Error Queue

#### Step 1.1: Create Queue via Console

1. **Go to SQS Console** → Create queue
2. **Type**: Standard queue
3. **Name**: `product-validation-errors`
4. **Configuration**:
   - Visibility timeout: 5 minutes
   - Message retention: 4 days
   - Receive message wait time: 0 seconds (short polling)
   - Maximum message size: 256 KB
5. **Dead-letter queue**: Enabled
   - Target queue: Create new `product-validation-errors-dlq`
   - Maximum receives: 3
6. **Create queue**

#### Step 1.2: Create Queue via AWS CLI

```bash
# Create dead-letter queue first
aws sqs create-queue \
    --queue-name product-validation-errors-dlq \
    --region us-east-1

# Get DLQ ARN
DLQ_ARN=$(aws sqs get-queue-attributes \
    --queue-url $(aws sqs get-queue-url --queue-name product-validation-errors-dlq --query 'QueueUrl' --output text) \
    --attribute-names QueueArn \
    --query 'Attributes.QueueArn' \
    --output text)

# Create main queue with DLQ
aws sqs create-queue \
    --queue-name product-validation-errors \
    --attributes '{
        "VisibilityTimeout": "300",
        "MessageRetentionPeriod": "345600",
        "ReceiveMessageWaitTimeSeconds": "0",
        "RedrivePolicy": "{\"deadLetterTargetArn\":\"'${DLQ_ARN}'\",\"maxReceiveCount\":\"3\"}"
    }' \
    --region us-east-1

# Get queue URL (save for Lambda env var)
SQS_QUEUE_URL=$(aws sqs get-queue-url \
    --queue-name product-validation-errors \
    --query 'QueueUrl' \
    --output text)

echo "SQS Queue URL: ${SQS_QUEUE_URL}"
```

---

### Part 2: Build and Push Validator Lambda to ECR

#### Step 2.1: Create ECR Repository

```bash
# Create repository
aws ecr create-repository \
    --repository-name product-validator-lambda \
    --image-scanning-configuration scanOnPush=true \
    --region us-east-1

# Get repository URI
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_VALIDATOR_URI="${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/product-validator-lambda"

echo "ECR Repository URI: ${ECR_VALIDATOR_URI}"
```

#### Step 2.2: Build and Push Image

```bash
# Navigate to validator directory
cd lambda_product_validator/

# Build Docker image
docker build -t product-validator-lambda:latest .

# Authenticate to ECR
aws ecr get-login-password --region us-east-1 | \
    docker login --username AWS --password-stdin \
    ${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com

# Tag image
docker tag product-validator-lambda:latest ${ECR_VALIDATOR_URI}:latest

# Push to ECR
docker push ${ECR_VALIDATOR_URI}:latest

echo "✓ Image pushed to ECR"
```

---

### Part 3: Create IAM Role for Validator Lambda

#### Step 3.1: Create IAM Policy

**File: lambda-product-validator-policy.json**

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "CloudWatchLogs",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:*:*:*"
        },
        {
            "Sid": "DynamoDBReadWrite",
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:UpdateItem",
                "dynamodb:PutItem"
            ],
            "Resource": "arn:aws:dynamodb:*:*:table/UploadRecords"
        },
        {
            "Sid": "DynamoDBStreams",
            "Effect": "Allow",
            "Action": [
                "dynamodb:DescribeStream",
                "dynamodb:GetRecords",
                "dynamodb:GetShardIterator",
                "dynamodb:ListStreams"
            ],
            "Resource": "arn:aws:dynamodb:*:*:table/UploadRecords/stream/*"
        },
        {
            "Sid": "SQSSendMessage",
            "Effect": "Allow",
            "Action": [
                "sqs:SendMessage",
                "sqs:GetQueueUrl"
            ],
            "Resource": "arn:aws:sqs:*:*:product-validation-errors"
        },
        {
            "Sid": "SecretsManagerAccess",
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue"
            ],
            "Resource": "arn:aws:secretsmanager:*:*:secret:ecommerce/rds/credentials-*"
        },
        {
            "Sid": "CloudWatchMetrics",
            "Effect": "Allow",
            "Action": [
                "cloudwatch:PutMetricData"
            ],
            "Resource": "*"
        },
        {
            "Sid": "VPCNetworkInterface",
            "Effect": "Allow",
            "Action": [
                "ec2:CreateNetworkInterface",
                "ec2:DescribeNetworkInterfaces",
                "ec2:DeleteNetworkInterface",
                "ec2:AssignPrivateIpAddresses",
                "ec2:UnassignPrivateIpAddresses"
            ],
            "Resource": "*"
        }
    ]
}
```

#### Step 3.2: Create Role and Attach Policy

```bash
# Create trust policy
cat > trust-policy-validator.json << EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "lambda.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}
EOF

# Create IAM role
aws iam create-role \
    --role-name lambda-product-validator-role \
    --assume-role-policy-document file://trust-policy-validator.json

# Create custom policy
aws iam create-policy \
    --policy-name lambda-product-validator-policy \
    --policy-document file://lambda-product-validator-policy.json

# Get policy ARN
VALIDATOR_POLICY_ARN=$(aws iam list-policies \
    --query 'Policies[?PolicyName==`lambda-product-validator-policy`].Arn' \
    --output text)

# Attach custom policy
aws iam attach-role-policy \
    --role-name lambda-product-validator-role \
    --policy-arn ${VALIDATOR_POLICY_ARN}

# Attach AWS managed VPC policy
aws iam attach-role-policy \
    --role-name lambda-product-validator-role \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole

# Get role ARN
VALIDATOR_ROLE_ARN=$(aws iam get-role \
    --role-name lambda-product-validator-role \
    --query 'Role.Arn' \
    --output text)

echo "Role ARN: ${VALIDATOR_ROLE_ARN}"
```

---

### Part 4: Create Validator Lambda Function

#### Step 4.1: Create Lambda Function

```bash
# Get ECR image URI
ECR_VALIDATOR_IMAGE="${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/product-validator-lambda:latest"

# Get SQS queue URL
SQS_QUEUE_URL=$(aws sqs get-queue-url \
    --queue-name product-validation-errors \
    --query 'QueueUrl' \
    --output text)

# Create Lambda function
aws lambda create-function \
    --function-name product-validator \
    --package-type Image \
    --code ImageUri=${ECR_VALIDATOR_IMAGE} \
    --role ${VALIDATOR_ROLE_ARN} \
    --timeout 300 \
    --memory-size 512 \
    --environment Variables="{
        DYNAMODB_TABLE=UploadRecords,
        RDS_SECRET_NAME=ecommerce/rds/credentials,
        SQS_ERROR_QUEUE_URL=${SQS_QUEUE_URL},
        AWS_REGION=us-east-1
    }" \
    --description "Product Validator - Validates products from DynamoDB Streams"

echo "✓ Lambda function created!"
```

#### Step 4.2: Configure VPC (if RDS in VPC)

```bash
# Get VPC details from RDS
RDS_VPC=$(aws rds describe-db-instances \
    --db-instance-identifier ecommerce-db \
    --query 'DBInstances[0].DBSubnetGroup.VpcId' \
    --output text)

# Get subnet IDs
SUBNET_IDS=$(aws rds describe-db-instances \
    --db-instance-identifier ecommerce-db \
    --query 'DBInstances[0].DBSubnetGroup.Subnets[*].SubnetIdentifier' \
    --output text | tr '\t' ',')

# Get security group
RDS_SG=$(aws rds describe-db-instances \
    --db-instance-identifier ecommerce-db \
    --query 'DBInstances[0].VpcSecurityGroups[0].VpcSecurityGroupId' \
    --output text)

# Update Lambda VPC configuration
aws lambda update-function-configuration \
    --function-name product-validator \
    --vpc-config SubnetIds=${SUBNET_IDS},SecurityGroupIds=${RDS_SG}

echo "✓ Lambda configured for VPC access"
```

---

### Part 5: Configure DynamoDB Streams Event Source Mapping

#### Step 5.1: Get DynamoDB Stream ARN

```bash
# Get stream ARN
STREAM_ARN=$(aws dynamodb describe-table \
    --table-name UploadRecords \
    --query 'Table.LatestStreamArn' \
    --output text)

echo "Stream ARN: ${STREAM_ARN}"
```

#### Step 5.2: Create Event Source Mapping

```bash
# Create event source mapping
aws lambda create-event-source-mapping \
    --function-name product-validator \
    --event-source-arn ${STREAM_ARN} \
    --starting-position LATEST \
    --batch-size 100 \
    --maximum-batching-window-in-seconds 0 \
    --maximum-record-age-in-seconds 604800 \
    --maximum-retry-attempts 10000 \
    --parallelization-factor 1

echo "✓ Event source mapping created"
```

**Configuration Explained:**
- `--starting-position LATEST`: Only process new records (after mapping created)
- `--batch-size 100`: Process up to 100 records per Lambda invocation
- `--maximum-batching-window-in-seconds 0`: Don't wait to batch, process immediately
- `--maximum-record-age-in-seconds 604800`: Discard records older than 7 days
- `--maximum-retry-attempts 10000`: Retry failed batches up to 10,000 times
- `--parallelization-factor 1`: One concurrent Lambda per shard

#### Step 5.3: Verify Event Source Mapping

```bash
# List event source mappings
aws lambda list-event-source-mappings \
    --function-name product-validator

# Check status (should be "Enabled" or "Enabling")
aws lambda list-event-source-mappings \
    --function-name product-validator \
    --query 'EventSourceMappings[0].State' \
    --output text
```

---

## 🧪 Testing

### Test 1: End-to-End Upload Test

```bash
# Upload a CSV file to S3 (triggers CSV Parser)
BUCKET_NAME="ecommerce-product-uploads-${ACCOUNT_ID}"

aws s3 cp VEND001_20241221_034236.csv \
    s3://${BUCKET_NAME}/uploads/VEND001/

# Monitor CSV Parser logs
echo "Watching CSV Parser logs..."
aws logs tail /aws/lambda/csv-parser --follow &
CSV_PARSER_PID=$!

# Monitor Validator logs
echo "Watching Product Validator logs..."
aws logs tail /aws/lambda/product-validator --follow &
VALIDATOR_PID=$!

# Wait 10 seconds
sleep 10

# Stop log tailing
kill $CSV_PARSER_PID $VALIDATOR_PID

echo "✓ Check logs above for results"
```

### Test 2: Verify Products Inserted to RDS

```sql
-- Connect to RDS
psql -h ecommerce-db.xxxxx.rds.amazonaws.com \
     -U postgres \
     -d ecommerce_platform

-- Check products table
SELECT COUNT(*) FROM products WHERE upload_id = 'UPLOAD_20241221_034236';
-- Should return: 29 (if 2 errors as expected)

-- Check validation errors
SELECT COUNT(*) FROM validation_errors WHERE upload_id = 'UPLOAD_20241221_034236';
-- Should return: 2

-- Check upload history
SELECT upload_id, total_records, valid_records, error_records, status
FROM upload_history
WHERE upload_id = 'UPLOAD_20241221_034236';
-- Should show: total=31, valid=29, error=2, status='partial'
```

### Test 3: Verify SQS Error Queue

```bash
# Check queue for messages
aws sqs receive-message \
    --queue-url ${SQS_QUEUE_URL} \
    --max-number-of-messages 10 \
    --visibility-timeout 30 \
    --wait-time-seconds 0

# Should return 2 error messages (if 2 products failed validation)
```

### Test 4: Verify DynamoDB Record Status

```python
import boto3

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('UploadRecords')

# Query all records for upload
response = table.query(
    KeyConditionExpression='upload_id = :upload_id',
    ExpressionAttributeValues={
        ':upload_id': 'UPLOAD_20241221_034236'
    }
)

# Count by status
validated = sum(1 for item in response['Items'] if item['status'] == 'validated')
errors = sum(1 for item in response['Items'] if item['status'] == 'error')

print(f"Validated: {validated}")
print(f"Errors: {errors}")
print(f"Total: {response['Count']}")

# Should show: Validated=29, Errors=2, Total=31
```

### Test 5: Check CloudWatch Metrics

```bash
# Get validation metrics
aws cloudwatch get-metric-statistics \
    --namespace EcommerceProductOnboarding \
    --metric-name ProductsValidated \
    --dimensions Name=UploadId,Value=UPLOAD_20241221_034236 \
    --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 300 \
    --statistics Sum

# Should show: Sum = 29

# Get rejection metrics
aws cloudwatch get-metric-statistics \
    --namespace EcommerceProductOnboarding \
    --metric-name ProductsRejected \
    --dimensions Name=UploadId,Value=UPLOAD_20241221_034236 \
    --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 300 \
    --statistics Sum

# Should show: Sum = 2
```

---

## 📊 Expected Results

### CloudWatch Logs - Validator Lambda

```
START RequestId: abcd-1234-5678-efgh
================================================================================
Product Validator Lambda - Started (Container Image)
================================================================================

>>> Processing 31 stream records...

  Record REC_00001 (Row 1): CA-VEND001-0001
    ✓ VALID - Inserted to RDS (Product ID: 12345)

  Record REC_00002 (Row 2): CA-VEND001-0002
    ✓ VALID - Inserted to RDS (Product ID: 12346)

  Record REC_00003 (Row 3): CA-VEND001-0003
    ✗ INVALID - INVALID_PRICE: Price must be at least 0.01

  ... (28 more records)

  Record REC_00031 (Row 31): CA-VEND001-0031
    ✓ VALID - Inserted to RDS (Product ID: 12375)

>>> Updating upload history...

>>> Publishing metrics to CloudWatch...
  ✓ Metrics published to CloudWatch

================================================================================
VALIDATION SUMMARY
================================================================================
Upload IDs: UPLOAD_20241221_034236
Total Records Processed: 31
Valid Products: 29
Invalid Products: 2
Success Rate: 93.5%
Processing Time: 3.45 seconds
================================================================================

✓ Product Validator Lambda - Completed Successfully!

END RequestId: abcd-1234-5678-efgh
REPORT RequestId: abcd-1234-5678-efgh
Duration: 3450.23 ms
Billed Duration: 3451 ms
Memory Size: 512 MB
Max Memory Used: 256 MB
```

### RDS Query Results

```sql
-- Products inserted
ecommerce_platform=# SELECT product_id, sku, product_name, price, status 
FROM products 
WHERE upload_id = 'UPLOAD_20241221_034236' 
ORDER BY product_id 
LIMIT 5;

 product_id | sku               | product_name              | price | status
------------+-------------------+---------------------------+-------+--------
 12345      | CA-VEND001-0001   | Wireless Mouse - M651     | 19.99 | active
 12346      | CA-VEND001-0002   | USB-C Hub - 7 Port        | 34.99 | active
 12347      | CA-VEND001-0004   | Bluetooth Keyboard        | 45.99 | active
 12348      | CA-VEND001-0005   | Wireless Headphones       | 79.99 | active
 12349      | CA-VEND001-0006   | External SSD 1TB          | 89.99 | active
(5 rows)

-- Validation errors
ecommerce_platform=# SELECT error_id, row_number, error_type, error_message 
FROM validation_errors 
WHERE upload_id = 'UPLOAD_20241221_034236';

 error_id | row_number | error_type    | error_message
----------+------------+---------------+---------------------------
 1        | 3          | INVALID_PRICE | Price must be at least...
 2        | 27         | DUPLICATE_SKU | Duplicate SKU: CA-VEND...
(2 rows)

-- Upload history
ecommerce_platform=# SELECT * FROM upload_history 
WHERE upload_id = 'UPLOAD_20241221_034236';

 upload_id              | vendor_id | file_name                    | total | valid | error | status  
------------------------+-----------+------------------------------+-------+-------+-------+---------
 UPLOAD_20241221_034236 | VEND001   | VEND001_20241221_034236.csv | 31    | 29    | 2     | partial
```

---

## 🛠️ Troubleshooting

### Issue 1: Lambda Not Triggered by Streams

**Symptoms:** Records inserted to DynamoDB but Validator Lambda not invoked

**Check Event Source Mapping:**
```bash
aws lambda list-event-source-mappings \
    --function-name product-validator

# Look for:
# - State: "Enabled" (not "Disabled" or "Disabling")
# - LastProcessingResult: "OK" (not "PROBLEM_DESCRIPTION")
```

**Common Causes:**
1. **Stream disabled**: Check DynamoDB table has streams enabled
2. **Mapping disabled**: Enable mapping manually
3. **IAM permissions**: Lambda role needs `dynamodb:GetRecords`, `dynamodb:GetShardIterator`

**Fix:**
```bash
# Enable event source mapping
MAPPING_UUID=$(aws lambda list-event-source-mappings \
    --function-name product-validator \
    --query 'EventSourceMappings[0].UUID' \
    --output text)

aws lambda update-event-source-mapping \
    --uuid ${MAPPING_UUID} \
    --enabled
```

### Issue 2: Validation Errors Not Appearing in SQS

**Symptoms:** Invalid products detected but SQS queue empty

**Check:**
```bash
# Verify SQS_ERROR_QUEUE_URL environment variable
aws lambda get-function-configuration \
    --function-name product-validator \
    --query 'Environment.Variables.SQS_ERROR_QUEUE_URL'

# Check Lambda logs for SQS errors
aws logs tail /aws/lambda/product-validator --filter-pattern "SQS"
```

**Fix:**
```bash
# Update environment variable
aws lambda update-function-configuration \
    --function-name product-validator \
    --environment Variables="{
        DYNAMODB_TABLE=UploadRecords,
        RDS_SECRET_NAME=ecommerce/rds/credentials,
        SQS_ERROR_QUEUE_URL=${SQS_QUEUE_URL},
        AWS_REGION=us-east-1
    }"
```

### Issue 3: RDS Connection Errors

**Symptoms:** `psycopg2.OperationalError: timeout expired`

**Check VPC Configuration:**
```bash
# Verify Lambda in same VPC as RDS
aws lambda get-function-configuration \
    --function-name product-validator \
    --query 'VpcConfig'

# Check security group allows Lambda → RDS
aws ec2 describe-security-groups \
    --group-ids ${RDS_SG}
```

**Fix:**
```bash
# Add inbound rule to RDS security group
aws ec2 authorize-security-group-ingress \
    --group-id ${RDS_SG} \
    --protocol tcp \
    --port 5432 \
    --source-group ${LAMBDA_SG}
```

### Issue 4: Duplicate SKU Errors

**Symptoms:** Many products failing with "Duplicate SKU" error

**Investigate:**
```sql
-- Find duplicate SKUs
SELECT sku, COUNT(*) 
FROM products 
GROUP BY sku 
HAVING COUNT(*) > 1;

-- Check if test data being re-uploaded
SELECT upload_id, file_name, COUNT(*) 
FROM upload_history 
GROUP BY upload_id, file_name 
HAVING COUNT(*) > 1;
```

**Fix:**
- Delete test products before re-uploading same CSV
- Generate unique SKUs for each test run
- Use upload_id in SKU generation

---

## ✅ Verification Checklist

- [ ] SQS error queue created
- [ ] SQS dead-letter queue created
- [ ] ECR repository created for validator
- [ ] Docker image built and pushed
- [ ] IAM role created with correct policies
- [ ] Lambda function created from ECR image
- [ ] Lambda environment variables configured
- [ ] Lambda VPC configuration set (if RDS in VPC)
- [ ] DynamoDB Streams event source mapping created
- [ ] Event source mapping state: Enabled
- [ ] Test upload successful (CSV Parser → DynamoDB)
- [ ] Validator Lambda triggered by streams
- [ ] Valid products inserted to RDS
- [ ] Invalid products sent to SQS
- [ ] DynamoDB records updated with status
- [ ] Upload history updated with counts
- [ ] CloudWatch metrics published

---

## 🎯 Next Steps

Once DynamoDB Streams → Validator Lambda is working:

**Step 5:** SQS → Error Processor Lambda
- Aggregates errors from SQS queue
- Generates error CSV file
- Uploads to S3 `errors/` prefix
- Triggers SNS email notification

**Step 6:** SNS Email Notifications
- Sends summary email to vendor
- Includes error CSV download link
- Provides upload statistics

**Ready to create Error Processor Lambda?** 🚀