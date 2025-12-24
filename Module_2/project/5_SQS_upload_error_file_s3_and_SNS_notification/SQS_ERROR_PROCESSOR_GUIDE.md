# SQS → Error Processor Lambda → S3 → SNS Integration Guide

## 📋 Overview

This guide covers the **Error Processor Lambda** - the final step in the validation pipeline:

**Complete Flow:**
```
Validator Lambda → SQS Error Queue → Error Processor Lambda → S3 Error CSV → SNS Email Notification
```

**What This Step Does:**
- ✅ Reads error messages from SQS queue (batch processing)
- ✅ Groups errors by upload_id
- ✅ Generates error CSV files
- ✅ Uploads error CSVs to S3 (`errors/` prefix)
- ✅ Updates RDS upload_history with error file location
- ✅ Checks if upload is complete
- ✅ Triggers SNS email notification to vendor

---

## 🎯 What Actually Happens - Complete Integration Flow

### **Phase 1: SQS Queue Structure**

#### **What is the SQS Error Queue?**

The SQS (Simple Queue Service) error queue **aggregates validation errors** from the Validator Lambda. Instead of processing errors one-by-one, we batch them together for efficient error reporting.

**Why Use SQS?**
```
Without SQS (direct processing):
  Validator finds error → Generate CSV immediately → Upload to S3
  Problem: 2 errors = 2 CSV files, 2 emails 🚫

With SQS (batched processing):
  Validator finds error → Send to queue
  All errors collected → Process once → 1 CSV file, 1 email ✓
```

**Queue Structure:**
```
SQS Queue: product-validation-errors
├── Configuration:
│   ├── Type: Standard Queue
│   ├── Visibility Timeout: 5 minutes
│   ├── Message Retention: 4 days
│   ├── Maximum Message Size: 256 KB
│   └── Dead-Letter Queue: Enabled (3 retries)
│
├── Messages (example from UPLOAD_20241221_103045):
│   ├── Message 1 (REC_00003):
│   │   {
│   │     "upload_id": "UPLOAD_20241221_103045",
│   │     "vendor_id": "VEND001",
│   │     "record_id": "REC_00003",
│   │     "row_number": 3,
│   │     "error_type": "INVALID_PRICE",
│   │     "error_message": "Price must be at least 0.01",
│   │     "product_data": {...},
│   │     "timestamp": "2024-12-21T10:31:15.789Z"
│   │   }
│   │
│   └── Message 2 (REC_00027):
│       {
│         "upload_id": "UPLOAD_20241221_103045",
│         "vendor_id": "VEND001",
│         "record_id": "REC_00027",
│         "row_number": 27,
│         "error_type": "DUPLICATE_SKU",
│         "error_message": "Duplicate SKU: CA-VEND001-0027...",
│         "product_data": {...},
│         "timestamp": "2024-12-21T10:31:18.456Z"
│       }
│
└── Metrics:
    ├── ApproximateNumberOfMessages: 2
    ├── ApproximateAgeOfOldestMessage: 45 seconds
    └── NumberOfMessagesReceived: 2
```

**Message Attributes (for filtering):**
```json
{
  "upload_id": {
    "StringValue": "UPLOAD_20241221_103045",
    "DataType": "String"
  },
  "vendor_id": {
    "StringValue": "VEND001",
    "DataType": "String"
  },
  "error_type": {
    "StringValue": "INVALID_PRICE",
    "DataType": "String"
  }
}
```

#### **SQS Trigger Configuration:**

**Event Source Mapping:**
```json
{
  "UUID": "12345678-1234-1234-1234-123456789012",
  "BatchSize": 10,
  "Enabled": true,
  "EventSourceArn": "arn:aws:sqs:us-east-1:123456789012:product-validation-errors",
  "FunctionArn": "arn:aws:lambda:us-east-1:123456789012:function:error-processor",
  "MaximumBatchingWindowInSeconds": 30,
  "FunctionResponseTypes": ["ReportBatchItemFailures"]
}
```

**Configuration Explained:**
- **BatchSize: 10** - Process up to 10 error messages per invocation
- **MaximumBatchingWindowInSeconds: 30** - Wait up to 30 seconds to collect batch
- **FunctionResponseTypes** - Report partial failures (don't delete successfully processed messages)

**Batching Behavior:**
```
Scenario 1: Errors arrive quickly
  T+0s: Error 1 arrives → Queue
  T+1s: Error 2 arrives → Queue
  T+2s: Error 3 arrives → Queue
  ...
  T+10s: Error 10 arrives → Queue
  T+10s: Batch size (10) reached → Lambda invoked immediately

Scenario 2: Errors arrive slowly
  T+0s: Error 1 arrives → Queue
  T+5s: Error 2 arrives → Queue
  T+30s: Batching window (30s) expires → Lambda invoked with 2 messages

Scenario 3: Upload complete
  T+0s: All validation done, 2 errors total
  T+30s: Batching window expires → Lambda invoked with 2 messages
```

---

### **Phase 2: Lambda Execution Flow**

#### **2.1 Lambda Receives SQS Batch**

**SQS Event Structure:**
```json
{
  "Records": [
    {
      "messageId": "19dd0b57-b21e-4ac1-bd88-01bbb068cb78",
      "receiptHandle": "AQEBwJnKyrHigUMZj6rYigCgxlaS3SLy0a...",
      "body": "{\"upload_id\":\"UPLOAD_20241221_103045\",\"vendor_id\":\"VEND001\",...}",
      "attributes": {
        "ApproximateReceiveCount": "1",
        "SentTimestamp": "1703152875789",
        "SenderId": "AIDAI123456EXAMPLE",
        "ApproximateFirstReceiveTimestamp": "1703152906000"
      },
      "messageAttributes": {
        "upload_id": {
          "stringValue": "UPLOAD_20241221_103045",
          "dataType": "String"
        }
      },
      "md5OfBody": "7b270e59b47ff90a553787216d55d91d",
      "eventSource": "aws:sqs",
      "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:product-validation-errors",
      "awsRegion": "us-east-1"
    },
    // ... up to 9 more messages
  ]
}
```

**Lambda Handler Receives:**
```python
def lambda_handler(event, context):
    # event['Records'] = list of SQS messages (1-10)
    # Each message contains error details in Body
    
    for record in event['Records']:
        body = json.loads(record['Body'])
        # Extract error details
```

#### **2.2 Parse and Group Errors**

**Step-by-Step Processing:**

```
Lambda receives 2 SQS messages
  ↓
Message 1:
  Body: {"upload_id": "UPLOAD_20241221_103045", "row_number": 3, "error_type": "INVALID_PRICE", ...}
  ↓
Parse JSON from Body:
  {
    "upload_id": "UPLOAD_20241221_103045",
    "vendor_id": "VEND001",
    "record_id": "REC_00003",
    "row_number": 3,
    "error_type": "INVALID_PRICE",
    "error_message": "Price must be at least 0.01",
    "product_data": {
      "vendor_product_id": "PROD0003",
      "product_name": "Wireless Charger",
      "sku": "CA-VEND001-0003",
      "price": -10.00,
      ...
    }
  }
  ↓
Add to errors list
  ↓
Message 2:
  (Same process)
  ↓
Group by upload_id:
  {
    "UPLOAD_20241221_103045": [
      {row_number: 3, error_type: "INVALID_PRICE", ...},
      {row_number: 27, error_type: "DUPLICATE_SKU", ...}
    ]
  }
```

**Grouping Logic:**
```python
grouped_errors = defaultdict(list)

for error in errors:
    upload_id = error['upload_id']
    grouped_errors[upload_id].append(error)

# Result:
# grouped_errors = {
#   'UPLOAD_20241221_103045': [error1, error2],
#   'UPLOAD_20250101_140530': [error3, error4, error5]
# }
```

**Why Group by upload_id?**
- One CSV file per upload (not per error)
- One email per upload (not per error)
- Easier vendor troubleshooting

#### **2.3 Generate Error CSV**

**CSV Generation Process:**

```
Errors for UPLOAD_20241221_103045:
  [
    {row_number: 3, error_type: "INVALID_PRICE", ...},
    {row_number: 27, error_type: "DUPLICATE_SKU", ...}
  ]
  ↓
Sort by row_number:
  [
    {row_number: 3, ...},
    {row_number: 27, ...}
  ]
  ↓
Generate CSV:
```

**CSV Format:**
```csv
Row Number,Vendor Product ID,SKU,Product Name,Category,Error Type,Error Message,Price,Stock Quantity,Brand,Description
3,PROD0003,CA-VEND001-0003,Wireless Charger,Computer Accessories,INVALID_PRICE,Price must be at least 0.01,-10.00,100,TechGear,Fast wireless charging pad for smartphones...
27,PROD0027,CA-VEND001-0027,USB Cable - Type C,Computer Accessories,DUPLICATE_SKU,Duplicate SKU: CA-VEND001-0027 already exists (Product ID: 8765, Vendor: VEND002),15.99,200,TechGear,Premium braided USB-C cable 6ft...
```

**CSV Generation Code:**
```python
output = io.StringIO()
writer = csv.writer(output)

# Header
writer.writerow([
    'Row Number', 'Vendor Product ID', 'SKU', 
    'Product Name', 'Category', 'Error Type', 
    'Error Message', 'Price', 'Stock Quantity', 
    'Brand', 'Description'
])

# Data rows (sorted by row_number)
for error in sorted(errors, key=lambda x: x['row_number']):
    product_data = error['product_data']
    writer.writerow([
        error['row_number'],
        product_data.get('vendor_product_id', ''),
        product_data.get('sku', ''),
        product_data.get('product_name', ''),
        product_data.get('category', ''),
        error['error_type'],
        error['error_message'],
        str(product_data.get('price', '')),
        str(product_data.get('stock_quantity', '')),
        product_data.get('brand', ''),
        product_data.get('description', '')[:100] + '...'
    ])

csv_content = output.getvalue()
# CSV ready for upload!
```

**CSV Size Estimation:**
```
Per row: ~200 bytes average
2 errors = ~400 bytes
100 errors = ~20 KB
1000 errors = ~200 KB (well within limits)
```

#### **2.4 Upload Error CSV to S3**

**S3 Upload Process:**

```
CSV Content (in memory)
  ↓
Generate S3 Key:
  s3_key = f"errors/{vendor_id}/{upload_id}_errors.csv"
  Example: "errors/VEND001/UPLOAD_20241221_103045_errors.csv"
  ↓
S3 PutObject API:
  PUT /errors/VEND001/UPLOAD_20241221_103045_errors.csv
  Content-Type: text/csv
  Metadata:
    - upload_id: UPLOAD_20241221_103045
    - vendor_id: VEND001
    - generated_at: 2024-12-21T10:31:50.123Z
  ↓
S3 Response:
  ETag: "d41d8cd98f00b204e9800998ecf8427e"
  VersionId: null (or version ID if versioning enabled)
  ↓
Success! CSV available at:
  s3://ecommerce-product-uploads-123456789012/errors/VEND001/UPLOAD_20241221_103045_errors.csv
```

**S3 Bucket Structure After Upload:**
```
ecommerce-product-uploads-123456789012/
├── uploads/
│   └── VEND001/
│       └── VEND001_20241221_103045.csv (original upload)
│
└── errors/
    └── VEND001/
        └── UPLOAD_20241221_103045_errors.csv (error report) ← NEW!
```

**Presigned URL Generation:**
```python
# Generate download link (expires in 7 days)
error_file_url = s3_client.generate_presigned_url(
    'get_object',
    Params={
        'Bucket': 'ecommerce-product-uploads-123456789012',
        'Key': 'errors/VEND001/UPLOAD_20241221_103045_errors.csv'
    },
    ExpiresIn=604800  # 7 days in seconds
)

# Result:
# https://ecommerce-product-uploads-123456789012.s3.amazonaws.com/errors/VEND001/UPLOAD_20241221_103045_errors.csv?
# AWSAccessKeyId=AKIAIOSFODNN7EXAMPLE&
# Expires=1703757910&
# Signature=bWq2s1WEIj%2BVKDpLI2zXXXXXXXXXXXX%3D
```

**Why Presigned URL?**
- Bucket is private (no public access)
- Vendor can download without AWS credentials
- Link expires after 7 days (security)
- Trackable (S3 access logs)

#### **2.5 Update Upload History**

**RDS Update:**
```sql
UPDATE upload_history 
SET error_file_s3_key = 'errors/VEND001/UPLOAD_20241221_103045_errors.csv'
WHERE upload_id = 'UPLOAD_20241221_103045';

-- Result:
-- upload_id: UPLOAD_20241221_103045
-- error_file_s3_key: errors/VEND001/UPLOAD_20241221_103045_errors.csv (NEW!)
```

**Upload History After Update:**
```sql
SELECT * FROM upload_history WHERE upload_id = 'UPLOAD_20241221_103045';

 upload_id              | file_name                    | total | valid | error | status  | error_file_s3_key
------------------------+------------------------------+-------+-------+-------+---------+----------------------------------
 UPLOAD_20241221_103045 | VEND001_20241221_103045.csv | 31    | 29    | 2     | partial | errors/VEND001/UPLOAD_...csv ← NEW!
```

**Purpose:**
- Link upload to error report
- Vendor dashboard can show error CSV download link
- Audit trail (which uploads had errors)

#### **2.6 Check Upload Completion**

**Completion Logic:**
```sql
SELECT 
  upload_id,
  total_records,
  valid_records,
  error_records,
  (valid_records + error_records) AS processed_records,
  CASE 
    WHEN (valid_records + error_records) = total_records THEN TRUE
    ELSE FALSE
  END AS is_complete
FROM upload_history
WHERE upload_id = 'UPLOAD_20241221_103045';

Result:
 upload_id              | total | valid | error | processed | is_complete
------------------------+-------+-------+-------+-----------+-------------
 UPLOAD_20241221_103045 | 31    | 29    | 2     | 31        | TRUE ✓
```

**Why Check Completion?**

```
Scenario 1: Upload with 31 products
  - Validator processes all 31 records
  - Error Processor receives 2 errors in SQS
  - Check: 29 valid + 2 errors = 31 total ✓
  - Upload COMPLETE → Trigger SNS notification

Scenario 2: Upload with 1000 products
  - Validator processes first 100 records
  - Error Processor receives 5 errors in SQS
  - Check: 95 valid + 5 errors = 100 ≠ 1000 total
  - Upload STILL PROCESSING → Wait for more errors
  
  (Later...)
  - All 1000 processed
  - Error Processor receives final errors
  - Check: 950 valid + 50 errors = 1000 total ✓
  - Upload COMPLETE → Trigger SNS notification
```

**State Transitions:**
```
upload_history.status:
  'processing' → Still validating records
  'completed' → All valid, no errors (100% success)
  'partial' → Some valid, some errors (<100% success)
  'failed' → All errors (0% success - rare)
```

#### **2.7 Trigger SNS Notification**

**SNS Topic Structure:**
```
SNS Topic: product-upload-notifications
├── ARN: arn:aws:sns:us-east-1:123456789012:product-upload-notifications
├── Subscriptions:
│   ├── Email: vendor@example.com (for VEND001)
│   ├── Email: support@company.com (for all uploads)
│   └── SQS: notification-archive-queue (for logging)
└── Attributes:
    ├── DisplayName: Product Upload Notifications
    └── DeliveryPolicy: {...}
```

**SNS Message Construction:**

```python
# Subject (appears in email subject line)
subject = f"Product Upload Complete - {file_name} (93.5% Success)"

# Message body (email content)
message = """
Product Upload Validation Complete
===================================

Upload ID: UPLOAD_20241221_103045
File Name: VEND001_20241221_103045.csv
Vendor: TechGear (VEND001)

Results:
--------
Total Products: 31
Valid Products: 29 (93.5%)
Invalid Products: 2 (6.5%)

Status: PARTIAL

Error Details:
--------------
An error report has been generated with details of the 2 products that failed validation.

Download Error Report: https://ecommerce-product-uploads-123456789012.s3.amazonaws.com/errors/VEND001/UPLOAD_20241221_103045_errors.csv?...
(Link expires in 7 days)

Please review the error report and correct the issues before re-uploading.

What's Next:
------------
- Valid products (29) are now live in the catalog
- Invalid products (2) need to be corrected and re-uploaded

For support, please contact: support@example.com

---
This is an automated notification from the Product Onboarding System.
"""

# Message attributes (for filtering)
message_attributes = {
    'upload_id': 'UPLOAD_20241221_103045',
    'vendor_id': 'VEND001',
    'vendor_email': 'contact@techgear.com',
    'status': 'partial'
}
```

**SNS Publish API:**
```python
response = sns_client.publish(
    TopicArn='arn:aws:sns:us-east-1:123456789012:product-upload-notifications',
    Subject=subject,
    Message=message,
    MessageAttributes={
        'upload_id': {'StringValue': 'UPLOAD_20241221_103045', 'DataType': 'String'},
        'vendor_id': {'StringValue': 'VEND001', 'DataType': 'String'},
        'vendor_email': {'StringValue': 'contact@techgear.com', 'DataType': 'String'},
        'status': {'StringValue': 'partial', 'DataType': 'String'}
    }
)

# Response:
# {
#   'MessageId': '12345678-1234-1234-1234-123456789012',
#   'SequenceNumber': None
# }
```

**SNS Message Delivery:**
```
SNS Topic
  ↓
SNS evaluates subscriptions
  ↓
Email Subscription (vendor@example.com):
  ↓
Amazon SES (Simple Email Service)
  ↓
Email delivered to vendor's inbox
  
  From: AWS Notifications <no-reply@sns.amazonaws.com>
  Subject: Product Upload Complete - VEND001_20241221_103045.csv (93.5% Success)
  Body: [Message content from above]
  
  Links in email:
  - Download Error Report (presigned S3 URL)
```

**Email Appearance:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Product Upload Validation Complete

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Upload ID: UPLOAD_20241221_103045
File Name: VEND001_20241221_103045.csv
Vendor: TechGear (VEND001)

Results:
--------
Total Products: 31
Valid Products: 29 (93.5%)
Invalid Products: 2 (6.5%)

Status: PARTIAL

Error Details:
--------------
An error report has been generated with details of the 2 
products that failed validation.

[Download Error Report]  ← Clickable link

Please review the error report and correct the issues 
before re-uploading.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

### **Phase 3: Complete Pipeline Example**

**Full Flow (31 products, 2 errors):**

```
T+0s: Vendor uploads CSV
  ↓
T+2s: CSV Parser Lambda completes
  - 31 records inserted to DynamoDB
  ↓
T+3s: DynamoDB Streams triggers Validator Lambda
  ↓
T+3s-6s: Validator Lambda processes 31 records
  - 29 valid → RDS products table
  - 2 invalid → SQS error queue
  ↓
T+33s: SQS batching window expires (30s timeout)
  - Error Processor Lambda invoked with 2 messages
  ↓
T+33s-35s: Error Processor Lambda runs
  Step 1: Parse 2 SQS messages ✓
  Step 2: Group by upload_id (1 unique upload) ✓
  Step 3: Generate error CSV (2 rows) ✓
  Step 4: Upload to S3 ✓
  Step 5: Update upload_history ✓
  Step 6: Check completion (31 = 29 + 2) ✓ COMPLETE!
  Step 7: Trigger SNS notification ✓
  ↓
T+35s: SNS sends email
  ↓
T+37s: Vendor receives email with error CSV link
  ↓
DONE! Total time: 37 seconds
```

**RDS Final State:**

```sql
-- products table: 29 new products
SELECT COUNT(*) FROM products WHERE upload_id = 'UPLOAD_20241221_103045';
-- Result: 29

-- validation_errors table: 2 errors logged
SELECT COUNT(*) FROM validation_errors WHERE upload_id = 'UPLOAD_20241221_103045';
-- Result: 2

-- upload_history table: Complete summary
SELECT * FROM upload_history WHERE upload_id = 'UPLOAD_20241221_103045';

 upload_id              | total | valid | error | status  | error_file_s3_key           | completed_at
------------------------+-------+-------+-------+---------+-----------------------------+-------------------------
 UPLOAD_20241221_103045 | 31    | 29    | 2     | partial | errors/VEND001/...csv       | 2024-12-21T10:31:50.123Z
```

**S3 Final State:**
```
s3://ecommerce-product-uploads-123456789012/
├── uploads/VEND001/VEND001_20241221_103045.csv (original)
└── errors/VEND001/UPLOAD_20241221_103045_errors.csv (error report)
```

**SQS Final State:**
```
Queue: product-validation-errors
Messages: 0 (all processed and deleted)
Dead-Letter Queue: 0 (no failures)
```

---

## 🚀 Deployment Instructions

### Part 1: Create SNS Topic for Notifications

#### Step 1.1: Create SNS Topic

```bash
# Create SNS topic
aws sns create-topic \
    --name product-upload-notifications \
    --region us-east-1

# Get topic ARN (save for Lambda env var)
SNS_TOPIC_ARN=$(aws sns list-topics \
    --query 'Topics[?contains(TopicArn, `product-upload-notifications`)].TopicArn' \
    --output text)

echo "SNS Topic ARN: ${SNS_TOPIC_ARN}"
```

#### Step 1.2: Subscribe Email to Topic

```bash
# Subscribe vendor email (repeat for each vendor)
aws sns subscribe \
    --topic-arn ${SNS_TOPIC_ARN} \
    --protocol email \
    --notification-endpoint contact@techgear.com

# Subscribe support email
aws sns subscribe \
    --topic-arn ${SNS_TOPIC_ARN} \
    --protocol email \
    --notification-endpoint support@yourcompany.com

# Note: Recipients will receive confirmation email
# They must click "Confirm subscription" link
```

#### Step 1.3: Confirm Subscriptions

```
1. Check email inbox (contact@techgear.com)
2. Find email: "AWS Notification - Subscription Confirmation"
3. Click "Confirm subscription" link
4. See message: "Subscription confirmed!"

Repeat for all email addresses
```

#### Step 1.4: Verify Subscriptions

```bash
# List subscriptions
aws sns list-subscriptions-by-topic \
    --topic-arn ${SNS_TOPIC_ARN}

# Check for "SubscriptionArn" (not "PendingConfirmation")
```

---

### Part 2: Build and Push Error Processor Lambda to ECR

#### Step 2.1: Create ECR Repository

```bash
# Create repository
aws ecr create-repository \
    --repository-name error-processor-lambda \
    --image-scanning-configuration scanOnPush=true \
    --region us-east-1

# Get repository URI
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_ERROR_PROCESSOR_URI="${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/error-processor-lambda"

echo "ECR Repository URI: ${ECR_ERROR_PROCESSOR_URI}"
```

#### Step 2.2: Build and Push Image

```bash
# Navigate to error processor directory
cd lambda_error_processor/

# Build Docker image
docker build -t error-processor-lambda:latest .

# Authenticate to ECR
aws ecr get-login-password --region us-east-1 | \
    docker login --username AWS --password-stdin \
    ${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com

# Tag image
docker tag error-processor-lambda:latest ${ECR_ERROR_PROCESSOR_URI}:latest

# Push to ECR
docker push ${ECR_ERROR_PROCESSOR_URI}:latest

echo "✓ Image pushed to ECR"
```

---

### Part 3: Create IAM Role for Error Processor Lambda

#### Step 3.1: Create IAM Policy

**File: lambda-error-processor-policy.json**

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
            "Sid": "SQSConsumeMessages",
            "Effect": "Allow",
            "Action": [
                "sqs:ReceiveMessage",
                "sqs:DeleteMessage",
                "sqs:GetQueueAttributes"
            ],
            "Resource": "arn:aws:sqs:*:*:product-validation-errors"
        },
        {
            "Sid": "S3UploadErrorCSV",
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:PutObjectAcl"
            ],
            "Resource": "arn:aws:s3:::ecommerce-product-uploads-*/errors/*"
        },
        {
            "Sid": "SNSPublishNotification",
            "Effect": "Allow",
            "Action": [
                "sns:Publish"
            ],
            "Resource": "arn:aws:sns:*:*:product-upload-notifications"
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
cat > trust-policy-error-processor.json << EOF
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
    --role-name lambda-error-processor-role \
    --assume-role-policy-document file://trust-policy-error-processor.json

# Create custom policy
aws iam create-policy \
    --policy-name lambda-error-processor-policy \
    --policy-document file://lambda-error-processor-policy.json

# Get policy ARN
ERROR_PROCESSOR_POLICY_ARN=$(aws iam list-policies \
    --query 'Policies[?PolicyName==`lambda-error-processor-policy`].Arn' \
    --output text)

# Attach custom policy
aws iam attach-role-policy \
    --role-name lambda-error-processor-role \
    --policy-arn ${ERROR_PROCESSOR_POLICY_ARN}

# Attach AWS managed VPC policy
aws iam attach-role-policy \
    --role-name lambda-error-processor-role \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole

# Get role ARN
ERROR_PROCESSOR_ROLE_ARN=$(aws iam get-role \
    --role-name lambda-error-processor-role \
    --query 'Role.Arn' \
    --output text)

echo "Role ARN: ${ERROR_PROCESSOR_ROLE_ARN}"
```

---

### Part 4: Create Error Processor Lambda Function

#### Step 4.1: Create Lambda Function

```bash
# Get ECR image URI
ECR_ERROR_PROCESSOR_IMAGE="${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/error-processor-lambda:latest"

# Get S3 bucket name
S3_BUCKET_NAME="ecommerce-product-uploads-${ACCOUNT_ID}"

# Create Lambda function
aws lambda create-function \
    --function-name error-processor \
    --package-type Image \
    --code ImageUri=${ECR_ERROR_PROCESSOR_IMAGE} \
    --role ${ERROR_PROCESSOR_ROLE_ARN} \
    --timeout 300 \
    --memory-size 256 \
    --environment Variables="{
        RDS_SECRET_NAME=ecommerce/rds/credentials,
        S3_BUCKET_NAME=${S3_BUCKET_NAME},
        SNS_TOPIC_ARN=${SNS_TOPIC_ARN},
        AWS_REGION=us-east-1
    }" \
    --description "Error Processor - Aggregates errors and sends notifications"

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
    --function-name error-processor \
    --vpc-config SubnetIds=${SUBNET_IDS},SecurityGroupIds=${RDS_SG}

echo "✓ Lambda configured for VPC access"
```

---

### Part 5: Configure SQS Event Source Mapping

#### Step 5.1: Get SQS Queue ARN

```bash
# Get queue URL
SQS_QUEUE_URL=$(aws sqs get-queue-url \
    --queue-name product-validation-errors \
    --query 'QueueUrl' \
    --output text)

# Get queue ARN
SQS_QUEUE_ARN=$(aws sqs get-queue-attributes \
    --queue-url ${SQS_QUEUE_URL} \
    --attribute-names QueueArn \
    --query 'Attributes.QueueArn' \
    --output text)

echo "SQS Queue ARN: ${SQS_QUEUE_ARN}"
```

#### Step 5.2: Create Event Source Mapping

```bash
# Create event source mapping
aws lambda create-event-source-mapping \
    --function-name error-processor \
    --event-source-arn ${SQS_QUEUE_ARN} \
    --batch-size 10 \
    --maximum-batching-window-in-seconds 30 \
    --function-response-types ReportBatchItemFailures

echo "✓ Event source mapping created"
```

**Configuration Explained:**
- `--batch-size 10`: Process up to 10 error messages per invocation
- `--maximum-batching-window-in-seconds 30`: Wait up to 30 seconds to collect batch
- `--function-response-types ReportBatchItemFailures`: Partial batch failure support

#### Step 5.3: Verify Event Source Mapping

```bash
# List event source mappings
aws lambda list-event-source-mappings \
    --function-name error-processor

# Check status (should be "Enabled" or "Enabling")
aws lambda list-event-source-mappings \
    --function-name error-processor \
    --query 'EventSourceMappings[0].State' \
    --output text
```

---

## 🧪 Testing

### Test 1: End-to-End Upload with Errors

```bash
# Upload CSV with intentional errors (VEND002 has ~2 errors)
BUCKET_NAME="ecommerce-product-uploads-${ACCOUNT_ID}"

aws s3 cp VEND002_20241221_034236.csv \
    s3://${BUCKET_NAME}/uploads/VEND002/

echo "Waiting for processing... (allow 60 seconds)"
sleep 60

# Check if error CSV was created
aws s3 ls s3://${BUCKET_NAME}/errors/VEND002/

# Should show: UPLOAD_20241221_034236_errors.csv
```

### Test 2: Verify Error CSV Content

```bash
# Download error CSV
aws s3 cp s3://${BUCKET_NAME}/errors/VEND002/UPLOAD_20241221_034236_errors.csv .

# View content
cat UPLOAD_20241221_034236_errors.csv

# Should show CSV with error details
```

### Test 3: Verify SNS Email Notification

```
1. Check vendor email inbox (sales@stylewear.com for VEND002)
2. Find email: "Product Upload Complete - VEND002_20241221_034236.csv"
3. Verify email contains:
   - Upload summary (Total, Valid, Invalid)
   - Success rate percentage
   - Download link for error CSV
   - Next steps instructions
```

### Test 4: Verify RDS Upload History

```sql
-- Connect to RDS
psql -h ecommerce-db.xxxxx.rds.amazonaws.com \
     -U postgres \
     -d ecommerce_platform

-- Check upload history
SELECT 
  upload_id,
  file_name,
  total_records,
  valid_records,
  error_records,
  status,
  error_file_s3_key,
  processing_completed_at
FROM upload_history
WHERE upload_id LIKE 'UPLOAD_20241221%'
ORDER BY upload_timestamp DESC;

-- Should show error_file_s3_key populated
```

### Test 5: Check CloudWatch Logs

```bash
# Tail error processor logs
aws logs tail /aws/lambda/error-processor --follow

# Should show:
# - SQS messages parsed
# - Errors grouped by upload
# - CSV generated
# - S3 upload successful
# - SNS notification triggered
```

---

## 📊 Expected Results

### CloudWatch Logs - Error Processor Lambda

```
START RequestId: xyz-123-abc
================================================================================
Error Processor Lambda - Started (Container Image)
================================================================================

>>> Step 1: Parsing 2 SQS messages...
  ✓ Parsed error: UPLOAD_20241221_034236 - Row 8
  ✓ Parsed error: UPLOAD_20241221_034236 - Row 24
  Total parsed: 2/2

>>> Step 2: Grouping errors by upload_id...
  Unique uploads: 1
    UPLOAD_20241221_034236: 2 errors

>>> Step 3: Processing errors for each upload...

  Processing upload: UPLOAD_20241221_034236
    Errors: 2
    Creating error CSV...
      ✓ CSV created (512 bytes)
    Uploading to S3...
      ✓ Uploaded error CSV to S3: s3://ecommerce-product-uploads-.../errors/VEND002/UPLOAD_20241221_034236_errors.csv
    Updating upload history...
      ✓ Updated upload_history with error file location
    Checking upload completion...
      ✓ Upload complete!
        Total: 28
        Valid: 26
        Errors: 2
    Triggering SNS notification...
      ✓ SNS notification triggered: 12345678-1234-1234-1234-123456789012

>>> Step 4: Publishing metrics to CloudWatch...
  ✓ Metrics published to CloudWatch

================================================================================
ERROR PROCESSING SUMMARY
================================================================================
Total SQS Messages: 2
Errors Processed: 2
Unique Uploads: 1
Processing Time: 1.23 seconds
================================================================================

✓ Error Processor Lambda - Completed Successfully!

END RequestId: xyz-123-abc
REPORT RequestId: xyz-123-abc
Duration: 1230.45 ms
Billed Duration: 1231 ms
Memory Size: 256 MB
Max Memory Used: 128 MB
```

### Email Notification

```
Subject: Product Upload Complete - VEND002_20241221_034236.csv (92.9% Success)

Body:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Product Upload Validation Complete

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Upload ID: UPLOAD_20241221_034236
File Name: VEND002_20241221_034236.csv
Vendor: StyleWear (VEND002)

Results:
--------
Total Products: 28
Valid Products: 26 (92.9%)
Invalid Products: 2 (7.1%)

Status: PARTIAL

Error Details:
--------------
An error report has been generated with details of the 2 
products that failed validation.

[Download Error Report]  ← Clickable presigned URL

Please review the error report and correct the issues 
before re-uploading.

What's Next:
------------
- Valid products (26) are now live in the catalog
- Invalid products (2) need to be corrected and re-uploaded

For support, please contact: support@example.com

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Error CSV Content

```csv
Row Number,Vendor Product ID,SKU,Product Name,Category,Error Type,Error Message,Price,Stock Quantity,Brand,Description
8,PROD0008,CL-VEND002-0008,Leather Jacket,Clothing,INVALID_PRICE,Price must be at least 0.01,-50.00,25,StyleWear,Premium leather jacket with...
24,PROD0024,CL-VEND002-0024,Winter Coat,Clothing,FIELD_LENGTH_EXCEEDED,product_name exceeds maximum length of 200 characters,199.99,30,StyleWear,This is an extremely long product name that exceeds the maximum allowed length...
```

---

## 🛠️ Troubleshooting

### Issue 1: SNS Email Not Received

**Symptoms:** Error processor completes but vendor doesn't receive email

**Check Subscription Status:**
```bash
aws sns list-subscriptions-by-topic \
    --topic-arn ${SNS_TOPIC_ARN}

# Look for SubscriptionArn (not "PendingConfirmation")
```

**Fix:**
1. Check spam folder
2. Confirm subscription (click link in confirmation email)
3. Verify email address is correct
4. Check SNS topic has correct permissions

### Issue 2: Error CSV Not Created

**Symptoms:** Lambda runs but no CSV in S3

**Check Logs:**
```bash
aws logs tail /aws/lambda/error-processor --filter-pattern "ERROR"
```

**Common Causes:**
- S3 bucket name incorrect
- IAM permissions missing (s3:PutObject)
- S3 bucket in different region

**Fix:**
```bash
# Verify bucket exists
aws s3 ls s3://${S3_BUCKET_NAME}/

# Test S3 upload manually
echo "test" | aws s3 cp - s3://${S3_BUCKET_NAME}/errors/test.txt
```

### Issue 3: Lambda Not Triggered by SQS

**Symptoms:** Messages in SQS but Lambda not invoked

**Check Event Source Mapping:**
```bash
aws lambda list-event-source-mappings \
    --function-name error-processor

# Look for State: "Enabled"
```

**Fix:**
```bash
# Get mapping UUID
MAPPING_UUID=$(aws lambda list-event-source-mappings \
    --function-name error-processor \
    --query 'EventSourceMappings[0].UUID' \
    --output text)

# Enable mapping
aws lambda update-event-source-mapping \
    --uuid ${MAPPING_UUID} \
    --enabled
```

---

## ✅ Verification Checklist

- [ ] SNS topic created
- [ ] Email subscriptions confirmed (vendor emails)
- [ ] ECR repository created
- [ ] Docker image built and pushed
- [ ] IAM role created with correct policies
- [ ] Lambda function created from ECR image
- [ ] Lambda environment variables configured
- [ ] Lambda VPC configuration set (if RDS in VPC)
- [ ] SQS event source mapping created
- [ ] Event source mapping state: Enabled
- [ ] Test upload with errors completed
- [ ] Error CSV uploaded to S3
- [ ] Upload history updated with error file location
- [ ] SNS notification sent
- [ ] Vendor received email
- [ ] Error CSV downloadable via presigned URL
- [ ] CloudWatch metrics published

---

## 🎯 Complete Pipeline Summary

You now have a **complete, production-ready product onboarding pipeline**:

```
1. Vendor uploads CSV → S3
   ↓
2. S3 Event → CSV Parser Lambda
   - Parses CSV
   - Inserts to DynamoDB UploadRecords
   ↓
3. DynamoDB Streams → Validator Lambda
   - Validates each product
   - Valid → RDS products table
   - Invalid → SQS error queue
   ↓
4. SQS → Error Processor Lambda
   - Generates error CSV
   - Uploads to S3
   - Updates upload history
   - Triggers SNS notification
   ↓
5. SNS → Email to Vendor
   - Upload summary
   - Error CSV download link
   - Next steps
   ↓
COMPLETE! ✓
```

**Ready for production!** 🚀