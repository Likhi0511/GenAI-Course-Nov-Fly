# Database Setup Guide - Step 2

## 📋 Overview

This step sets up both databases required for the product onboarding platform:
1. **RDS PostgreSQL** - Vendors, validated products, upload history
2. **DynamoDB** - Upload processing tracker with streams

---

## 🗄️ Database Architecture

### Why Two Databases?

| Database | Purpose | Data Type | Why This Database? |
|----------|---------|-----------|-------------------|
| **RDS PostgreSQL** | Business-critical data | Vendors, Products, History | ACID transactions, complex queries, referential integrity |
| **DynamoDB** | Processing pipeline | Upload records | Fast writes, streams for workflow, auto-scaling |

### Data Flow

```
CSV Upload → DynamoDB (fast ingestion) → Stream → Validation → RDS (validated catalog)
                ↓                                                    ↑
         Audit trail                                      Final product catalog
```

---

## 📦 Files Included

### 1. rds_schema.sql
**PostgreSQL DDL for all tables**
- 5 tables: vendors, products, upload_history, product_categories, validation_errors
- 3 views: vendor_summary, recent_uploads, product_catalog
- Triggers for auto-updating timestamps
- Indexes for performance
- Sample data (3 vendors)

### 2. dynamodb_setup.py
**DynamoDB table creation script**
- Creates UploadRecords table
- Configures Streams (NEW_IMAGE)
- Sets up 2 GSIs (VendorIndex, StatusIndex)
- Includes sample data insertion

---

## 🚀 Setup Instructions

### Part A: RDS PostgreSQL Setup

#### Step 1: Create RDS Instance

**Option 1: AWS Console**
1. Go to RDS Console → Create database
2. Choose PostgreSQL (v14 or higher)
3. Template: Free tier (for learning) or Dev/Test
4. Settings:
   - DB instance identifier: `ecommerce-db`
   - Master username: `postgres`
   - Master password: (create secure password)
5. Instance configuration:
   - DB instance class: `db.t3.micro` (free tier)
   - Storage: 20 GB
6. Connectivity:
   - VPC: Default VPC
   - Public access: Yes (for testing) / No (for production)
   - Security group: Create new or use existing
7. Additional configuration:
   - Initial database name: `ecommerce_platform`
8. Create database

**Option 2: AWS CLI**
```bash
aws rds create-db-instance \
    --db-instance-identifier ecommerce-db \
    --db-instance-class db.t3.micro \
    --engine postgres \
    --engine-version 14.7 \
    --master-username postgres \
    --master-user-password YourSecurePassword123! \
    --allocated-storage 20 \
    --db-name ecommerce_platform \
    --backup-retention-period 7 \
    --vpc-security-group-ids sg-xxxxxxxx \
    --publicly-accessible
```

#### Step 2: Wait for Instance to be Available
```bash
aws rds wait db-instance-available \
    --db-instance-identifier ecommerce-db
```

#### Step 3: Get Connection Endpoint
```bash
aws rds describe-db-instances \
    --db-instance-identifier ecommerce-db \
    --query 'DBInstances[0].Endpoint.Address' \
    --output text
```

Example output: `ecommerce-db.xxxxx.us-east-1.rds.amazonaws.com`

#### Step 4: Connect to Database

**Using psql:**
```bash
psql -h ecommerce-db.xxxxx.us-east-1.rds.amazonaws.com \
     -U postgres \
     -d ecommerce_platform
```

**Using pgAdmin:**
1. Add new server
2. Host: `ecommerce-db.xxxxx.us-east-1.rds.amazonaws.com`
3. Port: `5432`
4. Database: `ecommerce_platform`
5. Username: `postgres`
6. Password: (your password)

#### Step 5: Run DDL Script
```bash
# From command line
psql -h ecommerce-db.xxxxx.us-east-1.rds.amazonaws.com \
     -U postgres \
     -d ecommerce_platform \
     -f rds_schema.sql

# Or copy-paste into psql prompt
\i /path/to/rds_schema.sql
```

#### Step 6: Verify Tables Created
```sql
-- List all tables
\dt

-- Check vendors inserted
SELECT vendor_id, vendor_name, email FROM vendors;

-- Check table counts
SELECT 
    'vendors' as table_name, COUNT(*) as rows FROM vendors
UNION ALL
SELECT 'products', COUNT(*) FROM products
UNION ALL
SELECT 'upload_history', COUNT(*) FROM upload_history
UNION ALL
SELECT 'product_categories', COUNT(*) FROM product_categories;
```

Expected output:
```
 table_name         | rows
--------------------+------
 vendors            |    3
 products           |    0
 upload_history     |    0
 product_categories |   20
```

---

### Part B: DynamoDB Setup

#### Step 1: Install boto3 (if not already installed)
```bash
pip install boto3
```

#### Step 2: Configure AWS Credentials

**Option 1: AWS CLI**
```bash
aws configure
# Enter:
#   AWS Access Key ID
#   AWS Secret Access Key
#   Default region: us-east-1
#   Default output format: json
```

**Option 2: Environment Variables**
```bash
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=us-east-1
```

**Option 3: IAM Role (if running on EC2)**
No configuration needed - uses instance profile

#### Step 3: Create DynamoDB Table
```bash
# Interactive mode
python dynamodb_setup.py
# Choose option 1 (Create table)

# Or direct execution
python dynamodb_setup.py 1
```

Expected output:
```
================================================================================
Creating DynamoDB Table: UploadRecords
================================================================================

Creating table with configuration:
{
  "TableName": "UploadRecords",
  "KeySchema": [
    {
      "AttributeName": "upload_id",
      "KeyType": "HASH"
    },
    ...
  ],
  ...
}

✓ Table creation initiated: UploadRecords
  Status: CREATING
  ARN: arn:aws:dynamodb:us-east-1:123456789:table/UploadRecords

Waiting for table to become ACTIVE...

✓ Table UploadRecords is now ACTIVE!

Table Details:
  Table Name: UploadRecords
  Table Status: ACTIVE
  Item Count: 0
  Table Size: 0 bytes
  Billing Mode: PAY_PER_REQUEST

DynamoDB Stream:
  Stream ARN: arn:aws:dynamodb:us-east-1:123456789:table/UploadRecords/stream/2024-12-21...
  Stream Enabled: True
  Stream View Type: NEW_IMAGE

Global Secondary Indexes:
  - VendorIndex (ACTIVE)
  - StatusIndex (ACTIVE)

================================================================================
Table created successfully!
================================================================================
```

#### Step 4: Verify Table in AWS Console
1. Go to DynamoDB Console
2. Tables → UploadRecords
3. Verify:
   - Status: Active
   - Partition key: upload_id
   - Sort key: record_id
   - Indexes tab: VendorIndex, StatusIndex
   - Exports and streams tab: Stream enabled

#### Step 5: Insert Sample Record (Optional)
```bash
python dynamodb_setup.py 3
```

#### Step 6: View Query Examples
```bash
python dynamodb_setup.py 4
```

---

## 📊 Database Schema Details

### RDS PostgreSQL Tables

#### Table 1: vendors
```sql
CREATE TABLE vendors (
    vendor_id VARCHAR(50) PRIMARY KEY,
    vendor_name VARCHAR(200) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(20),
    business_name VARCHAR(200),
    tax_id VARCHAR(50),
    address TEXT,
    city VARCHAR(100),
    state VARCHAR(50),
    country VARCHAR(50) DEFAULT 'USA',
    postal_code VARCHAR(20),
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Purpose:** Store vendor registration information
**Key Constraint:** vendor_id must exist before products can be uploaded

#### Table 2: products
```sql
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    vendor_id VARCHAR(50) REFERENCES vendors(vendor_id),
    vendor_product_id VARCHAR(100) NOT NULL,
    product_name VARCHAR(200) NOT NULL,
    category VARCHAR(100) NOT NULL,
    sku VARCHAR(100) UNIQUE NOT NULL,
    price DECIMAL(10, 2) CHECK (price > 0),
    stock_quantity INTEGER CHECK (stock_quantity >= 0),
    -- ... more fields
    UNIQUE(vendor_id, vendor_product_id)
);
```

**Purpose:** Validated product catalog
**Key Constraint:** SKU must be unique across entire platform

#### Table 3: upload_history
```sql
CREATE TABLE upload_history (
    upload_id VARCHAR(100) PRIMARY KEY,
    vendor_id VARCHAR(50) REFERENCES vendors(vendor_id),
    file_name VARCHAR(255) NOT NULL,
    total_records INTEGER DEFAULT 0,
    valid_records INTEGER DEFAULT 0,
    error_records INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'processing',
    -- ... more fields
    CHECK (valid_records + error_records = total_records)
);
```

**Purpose:** Track all upload attempts and results

#### Table 4: product_categories
```sql
CREATE TABLE product_categories (
    category_id SERIAL PRIMARY KEY,
    category_name VARCHAR(100) UNIQUE NOT NULL,
    parent_category VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE
);
```

**Purpose:** Valid category whitelist for validation
**Pre-loaded:** 20 categories including Electronics, Clothing, Home & Garden

#### Table 5: validation_errors
```sql
CREATE TABLE validation_errors (
    error_id SERIAL PRIMARY KEY,
    upload_id VARCHAR(100) REFERENCES upload_history(upload_id),
    vendor_id VARCHAR(50) REFERENCES vendors(vendor_id),
    row_number INTEGER NOT NULL,
    error_type VARCHAR(50) NOT NULL,
    error_message TEXT NOT NULL,
    original_data JSONB
);
```

**Purpose:** Detailed error tracking for analytics

---

### DynamoDB Table

#### UploadRecords
```python
{
    # Primary Key
    'upload_id': 'UPLOAD_20241221_103045',  # Partition Key
    'record_id': 'REC_001',                 # Sort Key
    
    # Data
    'vendor_id': 'VEND001',
    'row_number': 1,
    'product_data': { ... },                # Full CSV row data
    'status': 'pending_validation',         # pending_validation, validated, error
    'error_reason': None,
    'created_at': '2024-12-21T10:30:45Z'
}
```

**GSI 1: VendorIndex**
- Partition Key: vendor_id
- Sort Key: upload_id
- Use case: Query all uploads for a vendor

**GSI 2: StatusIndex**
- Partition Key: upload_id
- Sort Key: status
- Use case: Find error records within an upload

**Stream Configuration:**
- Enabled: True
- View Type: NEW_IMAGE (only need new data)
- Use case: Trigger validation Lambda

---

## 🔍 Testing the Setup

### Test 1: RDS - Vendor Registration

```sql
-- Insert a test vendor
INSERT INTO vendors (vendor_id, vendor_name, email, phone, business_name, city, state)
VALUES ('VEND999', 'Test Vendor', 'test@example.com', '+1-555-9999', 'Test Corp', 'Boston', 'MA');

-- Verify insertion
SELECT * FROM vendors WHERE vendor_id = 'VEND999';

-- Check vendor summary view
SELECT * FROM vendor_summary WHERE vendor_id = 'VEND999';
```

### Test 2: RDS - Product Insertion

```sql
-- Insert a test product
INSERT INTO products (
    vendor_id, vendor_product_id, product_name, category, 
    sku, brand, price, stock_quantity
)
VALUES (
    'VEND001', 'TEST001', 'Test Product', 'Electronics',
    'TEST-SKU-001', 'TestBrand', 99.99, 50
);

-- Verify insertion
SELECT * FROM products WHERE sku = 'TEST-SKU-001';

-- Check product catalog view
SELECT * FROM product_catalog WHERE vendor_id = 'VEND001';
```

### Test 3: DynamoDB - Insert Record

```python
import boto3
from decimal import Decimal
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('UploadRecords')

# Insert test record
table.put_item(Item={
    'upload_id': 'TEST_UPLOAD_001',
    'record_id': 'REC_001',
    'vendor_id': 'VEND001',
    'row_number': 1,
    'product_data': {
        'vendor_product_id': 'PROD001',
        'product_name': 'Test Product',
        'price': Decimal('29.99'),
        'stock_quantity': 100
    },
    'status': 'pending_validation',
    'created_at': datetime.utcnow().isoformat()
})

print("✓ Test record inserted!")
```

### Test 4: DynamoDB - Query Records

```python
from boto3.dynamodb.conditions import Key

# Query by upload_id
response = table.query(
    KeyConditionExpression=Key('upload_id').eq('TEST_UPLOAD_001')
)

print(f"Found {response['Count']} records")
for item in response['Items']:
    print(f"  Record: {item['record_id']}, Status: {item['status']}")
```

---

## 🛠️ Troubleshooting

### RDS Issues

**Problem:** Cannot connect to RDS instance
```bash
# Check security group allows your IP
aws ec2 describe-security-groups \
    --group-ids sg-xxxxxxxx \
    --query 'SecurityGroups[0].IpPermissions'

# Check if instance is publicly accessible
aws rds describe-db-instances \
    --db-instance-identifier ecommerce-db \
    --query 'DBInstances[0].PubliclyAccessible'
```

**Solution:**
1. Update security group to allow inbound on port 5432 from your IP
2. If using VPC, ensure proper routing

**Problem:** "peer authentication failed"
```
psql: error: connection to server at "xxx.rds.amazonaws.com", 
port 5432 failed: FATAL:  password authentication failed
```

**Solution:**
- Verify password is correct
- Check username (should be "postgres")
- Wait a few minutes if instance was just created

**Problem:** Table already exists
```
ERROR:  relation "vendors" already exists
```

**Solution:**
```sql
-- Drop and recreate (CAUTION: loses data)
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS upload_history CASCADE;
DROP TABLE IF EXISTS vendors CASCADE;

-- Then run schema again
\i rds_schema.sql
```

### DynamoDB Issues

**Problem:** "ResourceInUseException: Table already exists"
```python
botocore.errorfactory.ResourceInUseException: 
An error occurred (ResourceInUseException) when calling the CreateTable operation
```

**Solution:**
```bash
# Delete existing table
python dynamodb_setup.py 2
# Confirm with "yes"

# Recreate table
python dynamodb_setup.py 1
```

**Problem:** "AccessDeniedException"
```
botocore.exceptions.ClientError: An error occurred (AccessDeniedException)
```

**Solution:**
- Verify AWS credentials are configured: `aws sts get-caller-identity`
- Check IAM permissions include: `dynamodb:CreateTable`, `dynamodb:DescribeTable`

**Problem:** Stream not triggering
```
DynamoDB Stream exists but Lambda not being invoked
```

**Solution:**
1. Verify stream is enabled: Check AWS Console → DynamoDB → UploadRecords → Exports and streams
2. Check stream ARN is correct in Lambda event source mapping
3. Verify Lambda has permission to read from stream

---

## 📈 Performance Considerations

### RDS PostgreSQL

**Indexes Created:**
```sql
-- Vendors
CREATE INDEX idx_vendors_email ON vendors(email);
CREATE INDEX idx_vendors_status ON vendors(status);

-- Products
CREATE INDEX idx_products_vendor ON products(vendor_id);
CREATE INDEX idx_products_category ON products(category);
CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_products_search ON products 
    USING gin(to_tsvector('english', product_name || ' ' || COALESCE(description, '')));
```

**Connection Pooling:**
- Recommended for Lambda: Use RDS Proxy
- Reduces connection overhead
- Handles connection pooling automatically

### DynamoDB

**Billing Mode: PAY_PER_REQUEST**
- No capacity planning needed
- Auto-scales to workload
- Good for unpredictable traffic

**Alternative: PROVISIONED**
```python
# Change to provisioned mode with auto-scaling
'BillingMode': 'PROVISIONED',
'ProvisionedThroughput': {
    'ReadCapacityUnits': 5,
    'WriteCapacityUnits': 5
}
```

---

## 💰 Cost Estimation

### RDS PostgreSQL (Free Tier)
- **db.t3.micro**: 750 hours/month (free tier)
- **Storage**: 20 GB (free tier)
- **Backups**: 20 GB (free tier)
- **After Free Tier**: ~$15-20/month

### DynamoDB
- **Storage**: $0.25/GB/month
- **On-Demand Writes**: $1.25/million writes
- **On-Demand Reads**: $0.25/million reads
- **Streams**: $0.02/100K read requests
- **Expected Cost**: ~$5-10/month for testing

**Total Monthly Cost (after free tier):** ~$20-30

---

## ✅ Verification Checklist

- [ ] RDS instance created and accessible
- [ ] RDS database `ecommerce_platform` exists
- [ ] All 5 tables created in RDS
- [ ] 3 sample vendors inserted
- [ ] 20 product categories inserted
- [ ] Views created (vendor_summary, recent_uploads, product_catalog)
- [ ] DynamoDB table `UploadRecords` created
- [ ] DynamoDB table status: ACTIVE
- [ ] DynamoDB Streams enabled
- [ ] 2 GSIs created (VendorIndex, StatusIndex)
- [ ] Can connect to RDS from local machine
- [ ] Can insert/query DynamoDB from Python
- [ ] Security groups properly configured

---

## 🎯 Next Steps

Once both databases are set up, you're ready for:

**Step 3:** Lambda Functions
- CSV Parser Lambda
- Product Validator Lambda
- Error Processor Lambda

**Ready to proceed?** 🚀
