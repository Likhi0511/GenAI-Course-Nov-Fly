# ECR Lambda Deployment Guide with Secrets Manager

## 📋 Overview

This guide covers deploying the CSV Parser Lambda using:
1. **Docker Container Image** - Includes psycopg2 and dependencies
2. **Amazon ECR** - Container registry for Lambda
3. **AWS Secrets Manager** - Secure RDS credential storage

**Why Container Image?**
- ✅ Full control over dependencies (psycopg2 with PostgreSQL libs)
- ✅ Larger package size support (up to 10GB vs 250MB zip)
- ✅ Easier local testing with Docker
- ✅ Consistent environment

---

## 🎯 Complete Integration Flow - What Actually Happens

### **High-Level Architecture**

```
┌─────────────────┐
│   Vendor App    │ Uploads CSV via API/Console
└────────┬────────┘
         │
         ↓
┌─────────────────────────────────────────────────────────────┐
│                    S3 BUCKET                                │
│  ecommerce-product-uploads-{account-id}                     │
│                                                             │
│  uploads/VEND001/VEND001_20241221_103045.csv               │
└────────┬────────────────────────────────────────────────────┘
         │ (S3 Event Notification)
         ↓
┌─────────────────────────────────────────────────────────────┐
│              LAMBDA FUNCTION (Container)                     │
│  Name: csv-parser                                           │
│  Source: ECR Image                                          │
│  Trigger: S3 ObjectCreated                                  │
└────┬────────────────────────────────────────┬───────────────┘
     │                                        │
     │ (Retrieves credentials)               │ (Writes records)
     ↓                                        ↓
┌──────────────────┐                 ┌──────────────────┐
│ SECRETS MANAGER  │                 │    DYNAMODB      │
│                  │                 │                  │
│ Secret:          │                 │ Table:           │
│ ecommerce/rds/   │                 │ UploadRecords    │
│ credentials      │                 │                  │
│                  │                 │ Status:          │
│ {username,       │                 │ pending_         │
│  password,       │                 │ validation       │
│  host, port,     │                 │                  │
│  dbname}         │                 └──────┬───────────┘
└────┬─────────────┘                        │
     │                                      │ (DynamoDB Streams)
     │ (Connects)                           │ [Next Step]
     ↓                                      ↓
┌──────────────────────────────────────────────────────────┐
│                    RDS POSTGRESQL                         │
│  Database: ecommerce_platform                            │
│  VPC: Private subnet                                     │
│                                                          │
│  Tables:                                                 │
│  - vendors (verifies vendor exists)                      │
│  - upload_history (tracks upload status)                 │
│  - products (will be populated after validation)         │
└──────────────────────────────────────────────────────────┘
```

---

## 🔄 Detailed Step-by-Step Integration Flow

### **Phase 1: Pre-Upload Setup (One-Time)**

#### **1.1 Developer Prepares Lambda Code**
```
Developer Machine
├── lambda_csv_parser/
│   ├── Dockerfile              ← Defines container environment
│   ├── requirements.txt         ← Python dependencies
│   └── lambda_csv_parser.py    ← Lambda handler code
```

**What happens:**
- Developer writes Lambda function code
- Creates Dockerfile specifying Python 3.11 base image
- Lists dependencies (psycopg2, boto3, secrets-caching)

#### **1.2 Build Docker Image Locally**
```bash
docker buildx build --platform linux/amd64 --output type=docker --provenance=false -t csv-parser-lambda:latest --no-cache .
```

**What happens inside Docker build:**
```
Step 1: Pull AWS Lambda Python 3.11 base image
  ↓
Step 2: Install system dependencies (PostgreSQL dev libs, gcc)
  ↓
Step 3: Copy requirements.txt
  ↓
Step 4: Run pip install (downloads psycopg2-binary, boto3, etc.)
  ↓
Step 5: Copy lambda_csv_parser.py
  ↓
Step 6: Set CMD to lambda_csv_parser.lambda_handler
  ↓
Final: Create image layers (OS + Python + Code)
  Size: ~500 MB
```

**Verification:**
```bash
docker images
# REPOSITORY           TAG      IMAGE ID      SIZE
# csv-parser-lambda    latest   abc123def456  487MB
```

#### **1.3 Create ECR Repository**
```bash
aws ecr create-repository --repository-name csv-parser-lambda
```

**What AWS does:**
```
1. Creates private Docker registry in your AWS account
2. Generates repository URI:
   123456789012.dkr.ecr.us-east-1.amazonaws.com/csv-parser-lambda
3. Sets up encryption (AES-256)
4. Enables image scanning (optional)
5. Configures IAM permissions
```

**ECR Repository Structure:**
```
ECR Repository: csv-parser-lambda
├── Image: latest (tag)
│   ├── Digest: sha256:abc123...
│   ├── Size: 487 MB
│   ├── Layers: 12 layers
│   └── Pushed: 2024-12-21 10:30 UTC
```

#### **1.4 Authenticate Docker to ECR**
```bash
export ECR_URI=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_URI
```

**What happens:**
```
1. AWS CLI calls STS GetCallerIdentity
2. ECR generates temporary auth token (valid 12 hours)
3. Docker stores credentials in ~/.docker/config.json
4. Now Docker can push/pull from this ECR repository
```

#### **1.5 Push Image to ECR**
```bash
docker tag csv-parser-lambda:latest $ECR_URI/csv-parser-lambda:latest
docker push $ECR_URI/csv-parser-lambda:latest
```

**What happens during push:**
```
Layer 1: Base OS                    [Already exists in ECR]
Layer 2: Python 3.11 runtime        [Already exists in ECR]
Layer 3: PostgreSQL libraries       [Uploading: 45.2 MB]
Layer 4: Python packages            [Uploading: 89.1 MB]
Layer 5: Lambda code                [Uploading: 0.05 MB]
Layer 6: Config/Metadata            [Uploading: 0.01 MB]

Total uploaded: 134.36 MB (compressed)
Total size in ECR: 487 MB (uncompressed)

Progress: ████████████████████ 100%
Status: Image pushed successfully
Digest: sha256:abc123def456789...
```

**ECR stores:**
- Container image layers (deduplicated)
- Image manifest (JSON describing layers)
- Image tags (latest, v1.0.0, etc.)

#### **1.6 Create RDS Secret in Secrets Manager**
```bash
aws secretsmanager create-secret \
    --name ecommerce/rds/credentials \
    --secret-string '{"username":"postgres", "password":"xxx", ...}'
```

**What AWS does:**
```
1. Encrypts secret value using AWS KMS
2. Stores encrypted secret in Secrets Manager backend
3. Creates secret ARN:
   arn:aws:secretsmanager:us-east-1:123456789012:secret:ecommerce/rds/credentials-AbCdEf
4. Sets up automatic encryption key rotation (optional)
5. Configures IAM permissions for access
```

**Secret Storage:**
```
Secrets Manager
├── Secret Name: ecommerce/rds/credentials
├── ARN: arn:aws:secretsmanager:...:secret:ecommerce/rds/credentials-AbCdEf
├── Encryption: AWS KMS (aws/secretsmanager key)
├── Value (encrypted):
│   {
│     "username": "postgres",
│     "password": "SecureP@ssw0rd123!",
│     "host": "ecommerce-db.abc123.us-east-1.rds.amazonaws.com",
│     "port": 5432,
│     "dbname": "ecommerce_platform"
│   }
├── Version: AWSCURRENT
└── Last Updated: 2024-12-21 10:00 UTC
```

#### **1.7 Create Lambda Function from ECR Image**
```bash
aws lambda create-function \
    --function-name csv-parser \
    --package-type Image \
    --code ImageUri={ECR_URI}:latest
```

**What AWS Lambda does:**
```
1. Authenticates to ECR
2. Pulls container image from ECR
3. Extracts image layers
4. Creates Lambda execution environment:
   - Allocates compute resources (512 MB memory)
   - Sets up network interface (if VPC configured)
   - Configures runtime environment
5. Registers function with:
   - ARN: arn:aws:lambda:us-east-1:123456789012:function:csv-parser
   - Handler: lambda_csv_parser.lambda_handler (from CMD)
   - Timeout: 300 seconds
   - Memory: 512 MB
6. Creates CloudWatch Log Group: /aws/lambda/csv-parser
```

**Lambda Configuration:**
```
Lambda Function: csv-parser
├── Package Type: Image
├── Image URI: 123456789012.dkr.ecr.us-east-1.amazonaws.com/csv-parser-lambda:latest
├── Image Digest: sha256:abc123...
├── Runtime: Python 3.11 (from container)
├── Handler: lambda_csv_parser.lambda_handler
├── Memory: 512 MB
├── Timeout: 300 seconds (5 minutes)
├── IAM Role: lambda-csv-parser-ecr-role
├── Environment Variables:
│   ├── DYNAMODB_TABLE=UploadRecords
│   ├── RDS_SECRET_NAME=ecommerce/rds/credentials
│   └── AWS_REGION=us-east-1
└── VPC Configuration:
    ├── Subnets: [subnet-abc123, subnet-def456]
    └── Security Groups: [sg-xyz789]
```

#### **1.8 Configure S3 Event Notification**
```bash
aws s3api put-bucket-notification-configuration \
    --bucket ecommerce-product-uploads-{account-id} \
    --notification-configuration {...}
```

**What S3 does:**
```
1. Registers Lambda function ARN as event destination
2. Sets up event filters:
   - Event type: s3:ObjectCreated:*
   - Prefix: uploads/
   - Suffix: .csv
3. Creates internal event queue
4. Grants S3 service permission to invoke Lambda
```

**S3 Event Configuration:**
```
S3 Bucket: ecommerce-product-uploads-123456789012
└── Event Notifications:
    └── LambdaFunctionConfigurations:
        ├── Id: csv-upload-trigger
        ├── LambdaFunctionArn: arn:aws:lambda:...:function:csv-parser
        ├── Events: [s3:ObjectCreated:*]
        └── Filter:
            ├── Prefix: uploads/
            └── Suffix: .csv
```

---

### **Phase 2: Runtime Execution (Every Upload)**

#### **2.1 Vendor Uploads CSV File**

**Upload via AWS Console:**
```
User Action: Click "Upload" → Select file → Upload to uploads/VEND001/

S3 receives:
- File: VEND001_20241221_103045.csv
- Size: 8,192 bytes
- Content-Type: text/csv
- Upload timestamp: 2024-12-21T10:30:45Z
```

**Upload via AWS CLI:**
```bash
aws s3 cp VEND001_20241221_103045.csv \
    s3://ecommerce-product-uploads-123456789012/uploads/VEND001/
```

**What S3 does:**
```
1. Receives multipart upload
2. Stores object in appropriate storage class (STANDARD)
3. Generates object metadata:
   - ETag: "abc123def456..."
   - Size: 8192 bytes
   - Last-Modified: 2024-12-21T10:30:45Z
   - Storage Class: STANDARD
4. Creates object version (if versioning enabled)
5. Checks event notification rules
```

**S3 Object Structure:**
```
Bucket: ecommerce-product-uploads-123456789012
└── uploads/
    └── VEND001/
        └── VEND001_20241221_103045.csv
            ├── ETag: "abc123def456789..."
            ├── Size: 8,192 bytes
            ├── Storage Class: STANDARD
            ├── Encryption: AES-256
            ├── Version ID: null (or version ID if versioning enabled)
            └── Metadata:
                ├── Last-Modified: 2024-12-21T10:30:45.000Z
                ├── Content-Type: text/csv
                └── Server-Side-Encryption: AES256
```

#### **2.2 S3 Triggers Event Notification**

**S3 Event Matching:**
```
Uploaded: uploads/VEND001/VEND001_20241221_103045.csv
          ↓
Check Event Rules:
  ✓ Event type: ObjectCreated ← Match!
  ✓ Prefix: uploads/          ← Match!
  ✓ Suffix: .csv               ← Match!
          ↓
Trigger: Lambda csv-parser
```

**S3 Event Record Created:**
```json
{
  "Records": [
    {
      "eventVersion": "2.1",
      "eventSource": "aws:s3",
      "awsRegion": "us-east-1",
      "eventTime": "2024-12-21T10:30:45.678Z",
      "eventName": "ObjectCreated:Put",
      "userIdentity": {
        "principalId": "AWS:AIDAI123456789EXAMPLE"
      },
      "requestParameters": {
        "sourceIPAddress": "203.0.113.1"
      },
      "responseElements": {
        "x-amz-request-id": "C3D13FE58DE4C810",
        "x-amz-id-2": "FMyUVURIY8/IgAtTv8xRjskZQpcIZ9KG..."
      },
      "s3": {
        "s3SchemaVersion": "1.0",
        "configurationId": "csv-upload-trigger",
        "bucket": {
          "name": "ecommerce-product-uploads-123456789012",
          "ownerIdentity": {
            "principalId": "A3NL1KOZZKExample"
          },
          "arn": "arn:aws:s3:::ecommerce-product-uploads-123456789012"
        },
        "object": {
          "key": "uploads/VEND001/VEND001_20241221_103045.csv",
          "size": 8192,
          "eTag": "abc123def456789...",
          "versionId": "null",
          "sequencer": "00609E4F0B5B1D5ABC"
        }
      }
    }
  ]
}
```

**S3 sends event to Lambda:**
```
S3 Event Queue → Lambda Service → Invokes csv-parser function
```

#### **2.3 Lambda Cold Start (First Invocation)**

**What happens during cold start:**
```
Timeline: T+0ms to T+3000ms

T+0ms: Lambda Service receives invocation request
  ↓
T+10ms: Allocate execution environment
  - Request compute capacity (512 MB)
  - Create microVM
  ↓
T+100ms: Pull container image from ECR
  - Authenticate to ECR
  - Download image layers (only new layers, cached layers reused)
  - Extract to /var/task/
  ↓
T+500ms: Initialize runtime
  - Start Python 3.11 interpreter
  - Load AWS Lambda Runtime Interface Client
  - Set up environment variables
  ↓
T+800ms: Import Lambda handler
  - Execute global scope code
  - Import boto3, psycopg2, other modules
  - Initialize AWS clients (s3, dynamodb, cloudwatch)
  - Create Secrets Manager cache
  ↓
T+3000ms: Ready to execute handler
  - Lambda is "warm" for subsequent invocations
```

**Execution Environment:**
```
Lambda Execution Environment
├── /var/task/               ← Lambda code (from container)
│   ├── lambda_csv_parser.py
│   └── ... (Python packages)
├── /tmp/                    ← Writable temp space (512 MB)
├── Environment Variables:
│   ├── DYNAMODB_TABLE=UploadRecords
│   ├── RDS_SECRET_NAME=ecommerce/rds/credentials
│   ├── AWS_REGION=us-east-1
│   ├── AWS_LAMBDA_FUNCTION_NAME=csv-parser
│   ├── AWS_LAMBDA_FUNCTION_MEMORY_SIZE=512
│   └── AWS_LAMBDA_LOG_GROUP_NAME=/aws/lambda/csv-parser
├── Network:
│   ├── VPC: vpc-abc123
│   ├── Subnets: [subnet-abc123, subnet-def456]
│   ├── Security Group: sg-xyz789
│   └── ENI: eni-0a1b2c3d4e5f6
└── IAM Role: lambda-csv-parser-ecr-role
```

#### **2.4 Lambda Handler Execution Begins**

**Handler invoked with event:**
```python
def lambda_handler(event, context):
    # event = S3 event JSON from step 2.2
    # context = Lambda context object
```

**Lambda Context Object:**
```python
context.function_name = "csv-parser"
context.function_version = "$LATEST"
context.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:csv-parser"
context.memory_limit_in_mb = 512
context.aws_request_id = "1234-5678-90ab-cdef-..."
context.log_group_name = "/aws/lambda/csv-parser"
context.log_stream_name = "2024/12/21/[$LATEST]abc123..."
context.identity = None
context.client_context = None
```

#### **2.5 Step 1: Extract S3 Event Details**

**Code execution:**
```python
s3_event = event['Records'][0]['s3']
bucket_name = s3_event['bucket']['name']
# "ecommerce-product-uploads-123456789012"

object_key = s3_event['object']['key']
# "uploads/VEND001/VEND001_20241221_103045.csv"

file_size = s3_event['object']['size']
# 8192

file_name = object_key.split('/')[-1]
# "VEND001_20241221_103045.csv"

upload_id = f"UPLOAD_{timestamp_str}"
# "UPLOAD_20241221_103045"
```

**CloudWatch Logs (real-time):**
```
START RequestId: 1234-5678-90ab-cdef Version: $LATEST

================================================================================
CSV Parser Lambda - Started (Container Image)
================================================================================

>>> Step 1: Extracting S3 event details...
  Bucket: ecommerce-product-uploads-123456789012
  Key: uploads/VEND001/VEND001_20241221_103045.csv
  Size: 8192 bytes
  Filename: VEND001_20241221_103045.csv
  Upload ID: UPLOAD_20241221_103045
```

#### **2.6 Step 2: Retrieve RDS Credentials from Secrets Manager**

**Code execution:**
```python
def get_rds_credentials():
    secret_string = cache.get_secret_string(RDS_SECRET_NAME)
    # cache = SecretCache (initialized at module level)
    return json.loads(secret_string)
```

**What happens internally:**
```
1. Check local cache:
   cache.get_secret_string('ecommerce/rds/credentials')
   ↓
2. Cache miss (first invocation) or expired?
   ↓ YES
3. Call Secrets Manager API:
   secretsmanager.get_secret_value(SecretId='ecommerce/rds/credentials')
   ↓
4. Secrets Manager receives request:
   - Verifies IAM permissions
   - Retrieves encrypted secret from storage
   - Decrypts using KMS key
   - Returns plaintext secret
   ↓
5. Cache stores secret (TTL: 1 hour default):
   cache['ecommerce/rds/credentials'] = {
     "username": "postgres",
     "password": "SecureP@ssw0rd123!",
     "host": "ecommerce-db.abc123.us-east-1.rds.amazonaws.com",
     "port": 5432,
     "dbname": "ecommerce_platform"
   }
   ↓
6. Return secret to caller
```

**API Call Details:**
```
HTTP Request:
  POST https://secretsmanager.us-east-1.amazonaws.com/
  X-Amz-Target: secretsmanager.GetSecretValue
  Authorization: AWS4-HMAC-SHA256 ...
  Body: {"SecretId": "ecommerce/rds/credentials"}

HTTP Response:
  Status: 200 OK
  Body: {
    "ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:ecommerce/rds/credentials-AbCdEf",
    "Name": "ecommerce/rds/credentials",
    "VersionId": "AWSCURRENT",
    "SecretString": "{\"username\":\"postgres\",\"password\":\"...\", ...}",
    "CreatedDate": 1703152845.123
  }
```

**CloudWatch Logs:**
```
>>> Step 2: Verifying vendor...
  ✓ Retrieved RDS credentials from Secrets Manager
    Host: ecommerce-db.abc123.us-east-1.rds.amazonaws.com
    Database: ecommerce_platform
  Vendor ID: VEND001
```

**Subsequent invocations (warm Lambda):**
```
Cache hit! No API call needed.
Return cached credentials (valid for 1 hour).
Response time: <1ms vs 50ms for API call
```

#### **2.7 Step 3: Connect to RDS PostgreSQL**

**Code execution:**
```python
def get_db_connection():
    creds = get_rds_credentials()
    conn = psycopg2.connect(
        host=creds['host'],
        port=creds['port'],
        database=creds['dbname'],
        user=creds['username'],
        password=creds['password'],
        connect_timeout=5
    )
    return conn
```

**What happens during connection:**
```
1. Lambda resolves DNS:
   ecommerce-db.abc123.us-east-1.rds.amazonaws.com
   → 10.0.1.25 (private IP in VPC)
   
2. Lambda creates TCP connection:
   Source: Lambda ENI (10.0.10.15:54321)
   Destination: RDS (10.0.1.25:5432)
   ↓
3. Security Group evaluation:
   RDS Security Group (sg-xyz789):
   - Inbound rule: PostgreSQL (5432) from sg-lambda123 ← ALLOW
   ✓ Connection allowed
   
4. TCP handshake:
   SYN → SYN-ACK → ACK
   Connection established
   
5. PostgreSQL authentication:
   Client: "USER postgres"
   Server: "Send password (md5)"
   Client: "PASSWORD SecureP@ssw0rd123!"
   Server: "Authentication successful"
   
6. Database selection:
   Client: "USE ecommerce_platform"
   Server: "Ready for query"
```

**Network Flow:**
```
Lambda Function (VPC)
  └─ ENI: 10.0.10.15
      └─ Security Group: sg-lambda123
          ↓ Outbound: All traffic allowed
          ↓
      ┌─────────────────┐
      │  VPC Router     │
      └─────────────────┘
          ↓
RDS Instance (VPC)
  └─ Private IP: 10.0.1.25
      └─ Security Group: sg-xyz789
          ├─ Inbound: PostgreSQL (5432) from sg-lambda123 ✓
          └─ Connection accepted
```

**CloudWatch Logs:**
```
  ✓ Connected to RDS successfully
```

**Connection pooling (important!):**
```
Global scope (outside handler):
  conn = None  # Connection persists across invocations

First invocation:
  conn = psycopg2.connect(...)  # New connection

Subsequent invocations (warm Lambda):
  if conn is None or conn.closed:
    conn = psycopg2.connect(...)  # Reconnect if needed
  else:
    # Reuse existing connection! Faster!
```

#### **2.8 Step 4: Verify Vendor Exists**

**SQL Query execution:**
```python
cursor.execute(
    "SELECT vendor_id, status FROM vendors WHERE vendor_id = %s",
    ('VEND001',)
)
vendor = cursor.fetchone()
```

**What happens in PostgreSQL:**
```
1. Lambda sends SQL over connection:
   SELECT vendor_id, status FROM vendors WHERE vendor_id = 'VEND001';

2. PostgreSQL query execution:
   ↓ Parse SQL
   ↓ Plan query (use index idx_vendors_email if needed)
   ↓ Execute query
   ↓ Fetch row(s)

3. PostgreSQL sends result:
   Row: {'vendor_id': 'VEND001', 'status': 'active'}

4. Lambda receives result:
   vendor = {'vendor_id': 'VEND001', 'status': 'active'}

5. Business logic check:
   if vendor['status'] != 'active':
     raise ValueError("Vendor not active")
   ✓ Vendor is active, continue
```

**CloudWatch Logs:**
```
  ✓ Vendor VEND001 verified successfully
```

#### **2.9 Step 5: Create Upload History Record**

**SQL Insert:**
```python
cursor.execute("""
    INSERT INTO upload_history (
        upload_id, vendor_id, file_name, s3_key, 
        status, upload_timestamp, processing_started_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (upload_id) DO NOTHING
""", (
    'UPLOAD_20241221_103045',
    'VEND001',
    'VEND001_20241221_103045.csv',
    'uploads/VEND001/VEND001_20241221_103045.csv',
    'processing',
    datetime.utcnow(),
    datetime.utcnow()
))
conn.commit()
```

**PostgreSQL transaction:**
```
BEGIN TRANSACTION
  ↓
INSERT INTO upload_history ...
  ↓
Check UNIQUE constraint on upload_id
  ✓ No conflict
  ↓
Write to table
  ↓
Update indexes
  ↓
COMMIT
  ↓
Changes persisted to disk
```

**RDS Table State:**
```sql
ecommerce_platform=# SELECT * FROM upload_history WHERE upload_id = 'UPLOAD_20241221_103045';

 upload_id              | vendor_id | file_name                      | total_records | status
------------------------+-----------+-------------------------------+---------------+-----------
 UPLOAD_20241221_103045 | VEND001   | VEND001_20241221_103045.csv   | NULL          | processing
```

**CloudWatch Logs:**
```
>>> Step 3: Creating upload history record...
  ✓ Upload history record created: UPLOAD_20241221_103045
```

#### **2.10 Step 6: Download CSV from S3**

**S3 GetObject API call:**
```python
response = s3_client.get_object(
    Bucket='ecommerce-product-uploads-123456789012',
    Key='uploads/VEND001/VEND001_20241221_103045.csv'
)
csv_content = response['Body'].read().decode('utf-8')
```

**What happens:**
```
1. Lambda makes HTTPS request to S3:
   GET https://s3.us-east-1.amazonaws.com/ecommerce-product-uploads-123456789012/uploads/VEND001/VEND001_20241221_103045.csv
   Authorization: AWS4-HMAC-SHA256 ...

2. S3 validates request:
   ✓ IAM permissions (s3:GetObject)
   ✓ Bucket policy
   ✓ Object exists

3. S3 retrieves object:
   - Read from storage (EBS/S3)
   - Stream data to Lambda

4. Lambda receives response:
   {
     'Body': StreamingBody object,
     'ContentLength': 8192,
     'ContentType': 'text/csv',
     'ETag': '"abc123def456..."',
     'LastModified': datetime(2024, 12, 21, 10, 30, 45),
     'Metadata': {}
   }

5. Lambda reads stream:
   csv_content = response['Body'].read()
   # Reads 8,192 bytes

6. Decode to string:
   csv_content = csv_content.decode('utf-8')
   # Now ready for parsing
```

**CSV Content (example):**
```csv
vendor_product_id,product_name,category,subcategory,description,sku,brand,price,compare_at_price,stock_quantity,unit,weight_kg,dimensions_cm,image_url
PROD0001,Wireless Mouse - Model 651,Computer Accessories,Mice & Keyboards,Ergonomic wireless mouse...,CA-VEND001-0001,TechGear,19.99,,150,piece,0.25,12x8x4,https://images.example.com/mouse.jpg
PROD0002,USB-C Hub - 7 Port,Computer Accessories,USB Hubs,Multi-port USB-C hub...,CA-VEND001-0002,TechGear,34.99,39.99,75,piece,0.15,10x6x2,https://images.example.com/hub.jpg
... (29 more rows)
```

**CloudWatch Logs:**
```
>>> Step 4: Downloading CSV from S3...
  ✓ Downloaded 7842 characters
```

#### **2.11 Step 7: Parse CSV Rows**

**CSV parsing:**
```python
csv_reader = csv.DictReader(io.StringIO(csv_content))

for row in csv_reader:
    row_number += 1
    record_id = f"REC_{row_number:05d}"
    product_data = parse_csv_row(row, row_number)
    # ... create DynamoDB item
```

**What happens for each row:**
```
Row 1:
  {
    'vendor_product_id': 'PROD0001',
    'product_name': 'Wireless Mouse - Model 651',
    'category': 'Computer Accessories',
    'subcategory': 'Mice & Keyboards',
    'sku': 'CA-VEND001-0001',
    'price': '19.99',
    'stock_quantity': '150',
    ...
  }
  ↓
Parse row:
  product_data = {
    'vendor_product_id': 'PROD0001',
    'product_name': 'Wireless Mouse - Model 651',
    'category': 'Computer Accessories',
    'price': Decimal('19.99'),        ← Converted to Decimal
    'stock_quantity': 150,             ← Converted to int
    ...
  }
  ↓
Create DynamoDB item:
  {
    'upload_id': 'UPLOAD_20241221_103045',
    'record_id': 'REC_00001',
    'vendor_id': 'VEND001',
    'row_number': 1,
    'product_data': { ... },
    'status': 'pending_validation',
    'created_at': '2024-12-21T10:30:46.123Z'
  }
  ↓
Add to batch: records_to_insert.append(item)

Repeat for all 31 rows...
```

**CloudWatch Logs:**
```
>>> Step 5: Parsing CSV rows...
  ✓ Parsed 31 product records
```

#### **2.12 Step 8: Batch Insert to DynamoDB**

**DynamoDB BatchWriteItem:**
```python
table = dynamodb.Table('UploadRecords')

# Batch 1: Records 1-25
with table.batch_writer() as writer:
    for record in records[0:25]:
        writer.put_item(Item=record)

# Batch 2: Records 26-31
with table.batch_writer() as writer:
    for record in records[25:31]:
        writer.put_item(Item=record)
```

**What happens in DynamoDB:**
```
Batch 1 (25 items):
  ↓
Lambda sends BatchWriteItem request:
  {
    "RequestItems": {
      "UploadRecords": [
        {"PutRequest": {"Item": {...}}},  // REC_00001
        {"PutRequest": {"Item": {...}}},  // REC_00002
        ...
        {"PutRequest": {"Item": {...}}}   // REC_00025
      ]
    }
  }
  ↓
DynamoDB receives request:
  - Validate request (max 25 items ✓)
  - Compute partition for each item (hash upload_id)
  - Write to storage nodes
  - Update indexes (VendorIndex, StatusIndex)
  - Trigger DynamoDB Streams
  ↓
DynamoDB returns response:
  {
    "UnprocessedItems": {}  // All succeeded
  }

Batch 2 (6 items):
  [Same process for remaining records]
```

**DynamoDB Table State:**
```
Table: UploadRecords
Item Count: 31 (new items)

Items:
  PK: UPLOAD_20241221_103045, SK: REC_00001, status: pending_validation
  PK: UPLOAD_20241221_103045, SK: REC_00002, status: pending_validation
  ...
  PK: UPLOAD_20241221_103045, SK: REC_00031, status: pending_validation

Indexes updated:
  VendorIndex: VEND001 → UPLOAD_20241221_103045 (31 items)
  StatusIndex: UPLOAD_20241221_103045 → pending_validation (31 items)
```

**DynamoDB Streams triggered:**
```
For each insert, stream record created:
  {
    "eventID": "1",
    "eventName": "INSERT",
    "eventSource": "aws:dynamodb",
    "awsRegion": "us-east-1",
    "dynamodb": {
      "Keys": {
        "upload_id": {"S": "UPLOAD_20241221_103045"},
        "record_id": {"S": "REC_00001"}
      },
      "NewImage": {
        "upload_id": {"S": "UPLOAD_20241221_103045"},
        "record_id": {"S": "REC_00001"},
        "vendor_id": {"S": "VEND001"},
        "product_data": {"M": {...}},
        "status": {"S": "pending_validation"},
        ...
      },
      "SequenceNumber": "111",
      "SizeBytes": 1024,
      "StreamViewType": "NEW_IMAGE"
    }
  }

These stream records will trigger Validator Lambda (next step)!
```

**CloudWatch Logs:**
```
>>> Step 6: Inserting records into DynamoDB...
  ✓ Successfully inserted: 31
```

#### **2.13 Step 9: Update Upload History**

**SQL Update:**
```python
cursor.execute("""
    UPDATE upload_history 
    SET total_records = %s
    WHERE upload_id = %s
""", (31, 'UPLOAD_20241221_103045'))
conn.commit()
```

**PostgreSQL:**
```
UPDATE upload_history 
SET total_records = 31
WHERE upload_id = 'UPLOAD_20241221_103045';

Rows affected: 1
```

**RDS Table State:**
```sql
 upload_id              | total_records | status
------------------------+---------------+-----------
 UPLOAD_20241221_103045 | 31            | processing
```

**CloudWatch Logs:**
```
>>> Step 7: Updating upload history...
  ✓ Updated upload history with 31 total records
```

#### **2.14 Step 10: Publish CloudWatch Metrics**

**CloudWatch PutMetricData:**
```python
cloudwatch.put_metric_data(
    Namespace='EcommerceProductOnboarding',
    MetricData=[
        {
            'MetricName': 'CSVRecordsProcessed',
            'Value': 31,
            'Unit': 'Count',
            'Timestamp': datetime.utcnow(),
            'Dimensions': [{'Name': 'UploadId', 'Value': 'UPLOAD_20241221_103045'}]
        },
        ...
    ]
)
```

**What happens:**
```
Lambda sends metrics to CloudWatch:
  POST https://monitoring.us-east-1.amazonaws.com/
  Body: {
    "Namespace": "EcommerceProductOnboarding",
    "MetricData": [
      {
        "MetricName": "CSVRecordsProcessed",
        "Value": 31,
        "Unit": "Count",
        "Timestamp": "2024-12-21T10:30:48Z",
        "Dimensions": [{"Name": "UploadId", "Value": "UPLOAD_20241221_103045"}]
      },
      {
        "MetricName": "CSVRecordsSuccessful",
        "Value": 31,
        ...
      },
      {
        "MetricName": "CSVProcessingTime",
        "Value": 2.45,
        "Unit": "Seconds",
        ...
      }
    ]
  }

CloudWatch receives and stores:
  - Metrics indexed by namespace, metric name, dimensions
  - Available for queries, alarms, dashboards
  - Retention: 15 months
```

**CloudWatch Metrics Console:**
```
Namespace: EcommerceProductOnboarding

Metrics:
  - CSVRecordsProcessed: 31 (Count) at 10:30:48
  - CSVRecordsSuccessful: 31 (Count) at 10:30:48
  - CSVProcessingTime: 2.45 (Seconds) at 10:30:48

Dimensions:
  - UploadId: UPLOAD_20241221_103045
```

**CloudWatch Logs:**
```
>>> Step 8: Publishing metrics to CloudWatch...
  ✓ Metrics published to CloudWatch
```

#### **2.15 Lambda Execution Completes**

**Return success response:**
```python
return {
    'statusCode': 200,
    'body': json.dumps({
        'message': 'CSV parsed and inserted successfully',
        'upload_id': 'UPLOAD_20241221_103045',
        'vendor_id': 'VEND001',
        'total_records': 31,
        'successful_records': 31,
        'failed_records': 0,
        'processing_time_seconds': 2.45
    })
}
```

**Lambda cleanup:**
```
1. Close database connection (if connection pooling not used)
2. Flush CloudWatch logs
3. Return execution context to Lambda service
4. Lambda environment stays "warm" for ~15 minutes
   - Next invocation will skip cold start
   - Reuse connections, caches
```

**Final CloudWatch Logs:**
```
================================================================================
PROCESSING SUMMARY
================================================================================
Upload ID: UPLOAD_20241221_103045
Vendor ID: VEND001
File: VEND001_20241221_103045.csv
Total Records: 31
Successful: 31
Failed: 0
Processing Time: 2.45 seconds
================================================================================

✓ Records inserted into DynamoDB
✓ DynamoDB Streams will trigger Validator Lambda
✓ CSV Parser Lambda - Completed Successfully!

END RequestId: 1234-5678-90ab-cdef
REPORT RequestId: 1234-5678-90ab-cdef
Duration: 2450.12 ms
Billed Duration: 2451 ms
Memory Size: 512 MB
Max Memory Used: 128 MB
Init Duration: 3120.45 ms (cold start)
```

**Lambda invocation metrics:**
```
Invocation successful:
  - Duration: 2.45 seconds
  - Memory used: 128 MB / 512 MB (25%)
  - Cold start: 3.12 seconds (first invocation only)
  - Billed duration: 2.451 seconds
  - Cost: $0.000000834 (512 MB × 2.451s × $0.0000166667/GB-s)
```

---

### **Phase 3: Post-Processing (Next Steps)**

#### **3.1 DynamoDB Streams Triggers Validator Lambda**

**What happens next:**
```
DynamoDB Streams has 31 new records:
  - Record 1: INSERT UPLOAD_20241221_103045/REC_00001
  - Record 2: INSERT UPLOAD_20241221_103045/REC_00002
  - ...
  - Record 31: INSERT UPLOAD_20241221_103045/REC_00031

Stream batches records (up to 100 per batch):
  Batch 1: Records 1-31
    ↓
Triggers Validator Lambda:
  Function: product-validator
  Event: DynamoDB Stream batch
    ↓
Validator Lambda:
  1. Receives 31 stream records
  2. For each record:
     - Validate product data
     - If valid → Insert to RDS products table
     - If invalid → Send to SQS error queue
  3. Update DynamoDB status: validated/error
  4. Update RDS upload_history counts
```

**This will be the next Lambda function we create!**

---

## 🏗️ Architecture

---

## 📦 Files Structure

```
lambda_csv_parser/
├── Dockerfile                  # Container definition
├── requirements.txt            # Python dependencies
├── lambda_csv_parser.py       # Lambda function code
└── .dockerignore              # Files to exclude from image
```

---

## 🚀 Step-by-Step Deployment

### Part 1: Create RDS Secret in Secrets Manager

#### Step 1.1: Create Secret via Console

1. **Go to AWS Secrets Manager Console**
2. **Store a new secret** → **Other type of secret**
3. **Key/value pairs**:
   ```
   Key: username    Value: postgres
   Key: password    Value: your_secure_password_here
   Key: host        Value: ecommerce-db.xxxxx.rds.amazonaws.com
   Key: port        Value: 5432
   Key: dbname      Value: ecommerce_platform
   ```
4. **Encryption key**: Default (aws/secretsmanager)
5. **Next**
6. **Secret name**: `ecommerce/rds/credentials`
7. **Description**: RDS PostgreSQL credentials for product onboarding
8. **Next**
9. **Rotation**: Disable (or configure if needed)
10. **Next** → **Store**

#### Step 1.2: Create Secret via AWS CLI

```bash
# Create JSON file with credentials
cat > rds-secret.json << EOF
{
  "username": "postgres",
  "password": "YOUR_SECURE_PASSWORD",
  "host": "ecommerce-db.xxxxx.rds.amazonaws.com",
  "port": 5432,
  "dbname": "ecommerce_platform"
}
EOF

# Create secret
aws secretsmanager create-secret \
    --name ecommerce/rds/credentials \
    --description "RDS PostgreSQL credentials for product onboarding" \
    --secret-string file://rds-secret.json \
    --region us-east-1

# Clean up local file
rm rds-secret.json
```

#### Step 1.3: Verify Secret

```bash
# Get secret ARN
aws secretsmanager describe-secret \
    --secret-id ecommerce/rds/credentials \
    --query 'ARN' \
    --output text

# Test retrieval (masked)
aws secretsmanager get-secret-value \
    --secret-id ecommerce/rds/credentials \
    --query 'SecretString' \
    --output text
```

---

### Part 2: Create ECR Repository

#### Step 2.1: Create Repository via Console

1. **Go to ECR Console** → **Repositories**
2. **Create repository**
3. **Visibility settings**: Private
4. **Repository name**: `csv-parser-lambda`
5. **Tag immutability**: Disabled
6. **Image scan on push**: Enabled (recommended)
7. **Encryption**: AES-256
8. **Create repository**

#### Step 2.2: Create Repository via AWS CLI

```bash
# Create ECR repository
aws ecr create-repository \
    --repository-name csv-parser-lambda \
    --image-scanning-configuration scanOnPush=true \
    --region us-east-1

# Get repository URI
ECR_URI=$(aws ecr describe-repositories \
    --repository-names csv-parser-lambda \
    --query 'repositories[0].repositoryUri' \
    --output text)

echo "ECR Repository URI: ${ECR_URI}"
# Example: 123456789012.dkr.ecr.us-east-1.amazonaws.com/csv-parser-lambda
```

---

### Part 3: Build and Push Docker Image

#### Step 3.1: Navigate to Lambda Directory

```bash
cd lambda_csv_parser/
```

#### Step 3.2: Build Docker Image Locally

```bash
# Build image
docker build -t csv-parser-lambda:latest .

# Verify image
docker images | grep csv-parser-lambda

# Test image locally (optional)
docker run --rm csv-parser-lambda:latest
```

#### Step 3.3: Authenticate to ECR

```bash
# Get AWS account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1

# Login to ECR
aws ecr get-login-password --region ${REGION} | \
    docker login --username AWS --password-stdin \
    ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com
```

Expected output: `Login Succeeded`

#### Step 3.4: Tag and Push Image

```bash
# Get ECR URI
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/csv-parser-lambda"

# Tag image
docker tag csv-parser-lambda:latest ${ECR_URI}:latest

# Push to ECR
docker push ${ECR_URI}:latest
```

Expected output:
```
The push refers to repository [123456789012.dkr.ecr.us-east-1.amazonaws.com/csv-parser-lambda]
latest: digest: sha256:abc123... size: 1234
```

#### Step 3.5: Verify Image in ECR

```bash
# List images in repository
aws ecr describe-images \
    --repository-name csv-parser-lambda \
    --region ${REGION}
```

---

### Part 4: Create IAM Role for Lambda

#### Step 4.1: Create IAM Policy

**File: lambda-csv-parser-policy.json**

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
            "Sid": "S3ReadAccess",
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:GetObjectVersion"
            ],
            "Resource": "arn:aws:s3:::ecommerce-product-uploads-*/*"
        },
        {
            "Sid": "DynamoDBAccess",
            "Effect": "Allow",
            "Action": [
                "dynamodb:PutItem",
                "dynamodb:BatchWriteItem"
            ],
            "Resource": "arn:aws:dynamodb:*:*:table/UploadRecords"
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

#### Step 4.2: Create Role and Attach Policy

```bash
# Create trust policy
cat > trust-policy.json << EOF
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
    --role-name lambda-csv-parser-ecr-role \
    --assume-role-policy-document file://trust-policy.json

# Create custom policy
aws iam create-policy \
    --policy-name lambda-csv-parser-ecr-policy \
    --policy-document file://lambda-csv-parser-policy.json

# Get policy ARN
POLICY_ARN=$(aws iam list-policies \
    --query 'Policies[?PolicyName==`lambda-csv-parser-ecr-policy`].Arn' \
    --output text)

# Attach custom policy to role
aws iam attach-role-policy \
    --role-name lambda-csv-parser-ecr-role \
    --policy-arn ${POLICY_ARN}

# Attach AWS managed VPC execution policy
aws iam attach-role-policy \
    --role-name lambda-csv-parser-ecr-role \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole

# Get role ARN (save for Lambda creation)
ROLE_ARN=$(aws iam get-role \
    --role-name lambda-csv-parser-ecr-role \
    --query 'Role.Arn' \
    --output text)

echo "Role ARN: ${ROLE_ARN}"
```

---

### Part 5: Create Lambda Function from ECR Image

#### Step 5.1: Create Lambda Function

```bash
# Get ECR image URI
ECR_IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/csv-parser-lambda:latest"

# Get RDS secret ARN
SECRET_ARN=$(aws secretsmanager describe-secret \
    --secret-id ecommerce/rds/credentials \
    --query 'ARN' \
    --output text)

# Create Lambda function
aws lambda create-function \
    --function-name csv-parser \
    --package-type Image \
    --code ImageUri=${ECR_IMAGE_URI} \
    --role ${ROLE_ARN} \
    --timeout 300 \
    --memory-size 512 \
    --environment Variables="{
        DYNAMODB_TABLE=UploadRecords,
        RDS_SECRET_NAME=ecommerce/rds/credentials,
        AWS_REGION=${REGION}
    }" \
    --description "CSV Parser - Parses uploaded CSVs and inserts to DynamoDB"

echo "✓ Lambda function created!"
```

#### Step 5.2: Configure VPC (if RDS is in VPC)

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

# Get security group (or create new one)
RDS_SG=$(aws rds describe-db-instances \
    --db-instance-identifier ecommerce-db \
    --query 'DBInstances[0].VpcSecurityGroups[0].VpcSecurityGroupId' \
    --output text)

# Update Lambda VPC configuration
aws lambda update-function-configuration \
    --function-name csv-parser \
    --vpc-config SubnetIds=${SUBNET_IDS},SecurityGroupIds=${RDS_SG}

echo "✓ Lambda configured for VPC access"
```

---

### Part 6: Configure S3 Event Trigger

#### Step 6.1: Add Lambda Permission for S3

```bash
# Get S3 bucket name
BUCKET_NAME="ecommerce-product-uploads-${ACCOUNT_ID}"

# Add permission for S3 to invoke Lambda
aws lambda add-permission \
    --function-name csv-parser \
    --statement-id s3-trigger-permission \
    --action lambda:InvokeFunction \
    --principal s3.amazonaws.com \
    --source-arn arn:aws:s3:::${BUCKET_NAME}
```

#### Step 6.2: Configure S3 Notification

```bash
# Get Lambda function ARN
LAMBDA_ARN=$(aws lambda get-function \
    --function-name csv-parser \
    --query 'Configuration.FunctionArn' \
    --output text)

# Create notification configuration
cat > s3-notification.json << EOF
{
    "LambdaFunctionConfigurations": [
        {
            "Id": "csv-upload-trigger",
            "LambdaFunctionArn": "${LAMBDA_ARN}",
            "Events": ["s3:ObjectCreated:*"],
            "Filter": {
                "Key": {
                    "FilterRules": [
                        {
                            "Name": "prefix",
                            "Value": "uploads/"
                        },
                        {
                            "Name": "suffix",
                            "Value": ".csv"
                        }
                    ]
                }
            }
        }
    ]
}
EOF

# Apply notification configuration
aws s3api put-bucket-notification-configuration \
    --bucket ${BUCKET_NAME} \
    --notification-configuration file://s3-notification.json

echo "✓ S3 event trigger configured"
```

---

## 🧪 Testing

### Test 1: Test Lambda Function Directly

```bash
# Create test event
cat > test-event.json << EOF
{
    "Records": [
        {
            "s3": {
                "bucket": {
                    "name": "${BUCKET_NAME}"
                },
                "object": {
                    "key": "uploads/VEND001/VEND001_20241221_034236.csv",
                    "size": 8192
                }
            }
        }
    ]
}
EOF

# Invoke Lambda
aws lambda invoke \
    --function-name csv-parser \
    --payload file://test-event.json \
    --cli-binary-format raw-in-base64-out \
    response.json

# View response
cat response.json | jq .
```

### Test 2: Upload CSV to S3

```bash
# Upload CSV file
aws s3 cp VEND001_20241221_034236.csv \
    s3://${BUCKET_NAME}/uploads/VEND001/

# Watch Lambda logs
aws logs tail /aws/lambda/csv-parser --follow
```

### Test 3: Verify Secrets Manager Access

```bash
# Check Lambda can access secret
aws lambda invoke \
    --function-name csv-parser \
    --log-type Tail \
    --query 'LogResult' \
    --output text \
    response.json | base64 -d

# Look for: "✓ Retrieved RDS credentials from Secrets Manager"
```

### Test 4: Verify DynamoDB Records

```bash
# Query DynamoDB
aws dynamodb query \
    --table-name UploadRecords \
    --key-condition-expression "upload_id = :upload_id" \
    --expression-attribute-values '{":upload_id": {"S": "UPLOAD_20241221_034236"}}' \
    --limit 5
```

---

## 🔄 Update Deployment

### Update Lambda Code

```bash
# Rebuild image
cd lambda_csv_parser/
docker build -t csv-parser-lambda:latest .

# Tag new version
docker tag csv-parser-lambda:latest ${ECR_URI}:v2
docker tag csv-parser-lambda:latest ${ECR_URI}:latest

# Push to ECR
docker push ${ECR_URI}:v2
docker push ${ECR_URI}:latest

# Update Lambda function
aws lambda update-function-code \
    --function-name csv-parser \
    --image-uri ${ECR_URI}:latest

# Wait for update to complete
aws lambda wait function-updated \
    --function-name csv-parser

echo "✓ Lambda function updated!"
```

### Update Environment Variables

```bash
aws lambda update-function-configuration \
    --function-name csv-parser \
    --environment Variables="{
        DYNAMODB_TABLE=UploadRecords,
        RDS_SECRET_NAME=ecommerce/rds/credentials,
        AWS_REGION=us-east-1
    }"
```

---

## 📊 Monitoring

### CloudWatch Logs

```bash
# Tail logs in real-time
aws logs tail /aws/lambda/csv-parser --follow

# Get logs from last 10 minutes
aws logs tail /aws/lambda/csv-parser --since 10m

# Filter for errors
aws logs tail /aws/lambda/csv-parser --filter-pattern "ERROR"

# Filter for specific upload
aws logs tail /aws/lambda/csv-parser --filter-pattern "UPLOAD_20241221_034236"
```

### CloudWatch Metrics

```bash
# Get invocation count
aws cloudwatch get-metric-statistics \
    --namespace AWS/Lambda \
    --metric-name Invocations \
    --dimensions Name=FunctionName,Value=csv-parser \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 300 \
    --statistics Sum

# Get error count
aws cloudwatch get-metric-statistics \
    --namespace AWS/Lambda \
    --metric-name Errors \
    --dimensions Name=FunctionName,Value=csv-parser \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 300 \
    --statistics Sum

# Custom metrics
aws cloudwatch get-metric-statistics \
    --namespace EcommerceProductOnboarding \
    --metric-name CSVRecordsProcessed \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 300 \
    --statistics Sum
```

---

## 🛠️ Troubleshooting

### Issue 1: Lambda Can't Retrieve Secret

**Error**: `ResourceNotFoundException: Secrets Manager can't find the specified secret`

**Solution**:
```bash
# Verify secret exists
aws secretsmanager describe-secret \
    --secret-id ecommerce/rds/credentials

# Check IAM permissions
aws iam get-role-policy \
    --role-name lambda-csv-parser-ecr-role \
    --policy-name lambda-csv-parser-ecr-policy

# Verify secret ARN in policy matches actual secret
```

### Issue 2: RDS Connection Timeout

**Error**: `psycopg2.OperationalError: timeout expired`

**Solution**:
```bash
# Check Lambda is in correct VPC
aws lambda get-function-configuration \
    --function-name csv-parser \
    --query 'VpcConfig'

# Verify security group allows Lambda → RDS
aws ec2 describe-security-groups \
    --group-ids ${RDS_SG} \
    --query 'SecurityGroups[0].IpPermissions'

# Add inbound rule if missing
aws ec2 authorize-security-group-ingress \
    --group-id ${RDS_SG} \
    --protocol tcp \
    --port 5432 \
    --source-group ${LAMBDA_SG}
```

### Issue 3: Image Build Fails

**Error**: `ERROR: failed to solve: process "/bin/sh -c yum install..." did not complete successfully`

**Solution**:
```bash
# Clean Docker cache
docker system prune -a

# Rebuild with no cache
docker build --no-cache -t csv-parser-lambda:latest .
```

### Issue 4: ECR Push Permission Denied

**Error**: `denied: User is not authorized to perform: ecr:BatchCheckLayerAvailability`

**Solution**:
```bash
# Re-authenticate
aws ecr get-login-password --region ${REGION} | \
    docker login --username AWS --password-stdin \
    ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com

# Check IAM permissions for ECR
aws iam get-user-policy \
    --user-name your-username \
    --policy-name ecr-access
```

---

## ✅ Verification Checklist

- [ ] RDS secret created in Secrets Manager
- [ ] Secret contains all required fields (username, password, host, port, dbname)
- [ ] ECR repository created
- [ ] Docker image built successfully
- [ ] Docker image pushed to ECR
- [ ] IAM role created with correct policies
- [ ] Lambda function created from ECR image
- [ ] Lambda environment variables configured
- [ ] Lambda VPC configuration set (if RDS in VPC)
- [ ] S3 trigger configured
- [ ] Test upload successful
- [ ] Lambda logs show successful processing
- [ ] DynamoDB has records
- [ ] RDS upload_history updated
- [ ] CloudWatch metrics published

---

## 💡 Best Practices

1. **Secrets Rotation**: Enable automatic rotation for RDS credentials
2. **Image Tagging**: Use semantic versioning (v1.0.0, v1.1.0)
3. **Multi-stage Builds**: Optimize Docker image size
4. **Health Checks**: Implement Lambda health check endpoint
5. **Cost Optimization**: Use Lambda reserved concurrency
6. **Monitoring**: Set up CloudWatch alarms for errors

---

## 🎯 Next Steps

Once ECR Lambda is deployed and working:

1. **DynamoDB Streams → Validator Lambda** (also container-based)
2. **SQS → Error Processor Lambda**
3. **SNS Email Notifications**
4. **Glue DataBrew Integration**

**Ready to proceed with Validator Lambda?** 🚀
