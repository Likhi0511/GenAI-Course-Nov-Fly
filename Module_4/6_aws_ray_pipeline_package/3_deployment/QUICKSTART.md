# Quick Start Guide
## Get Ray Pipeline Running in 30 Minutes

**For:** Developers who want to test locally first  
**Prerequisites:** Docker, Python 3.9+, AWS CLI configured

---

## Step 1: Environment Setup (5 minutes)

```bash
# Clone/extract the package
cd ray_pipeline_package

# Create virtual environment
python3.9 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Download spaCy model
python -m spacy download en_core_web_sm

# Set up environment variables
cp .env.example .env
# Edit .env with your API keys
```

**Required in .env:**
- `OPENAI_API_KEY` - Get from https://platform.openai.com/
- `PINECONE_API_KEY` - Get from https://www.pinecone.io/
- `S3_BUCKET` - Your S3 bucket name
- `AWS_REGION` - e.g., us-east-1

---

## Step 2: AWS Resources Setup (10 minutes)

### Quick DynamoDB Setup

```bash
# Create control table
aws dynamodb create-table \
  --table-name document_processing_control \
  --attribute-definitions \
    AttributeName=document_id,AttributeType=S \
    AttributeName=processing_version,AttributeType=S \
    AttributeName=status,AttributeType=S \
    AttributeName=created_at,AttributeType=S \
  --key-schema \
    AttributeName=document_id,KeyType=HASH \
    AttributeName=processing_version,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --global-secondary-indexes \
    "[{\"IndexName\":\"status-index\",\"KeySchema\":[{\"AttributeName\":\"status\",\"KeyType\":\"HASH\"},{\"AttributeName\":\"created_at\",\"KeyType\":\"RANGE\"}],\"Projection\":{\"ProjectionType\":\"ALL\"}}]"

# Create audit table
aws dynamodb create-table \
  --table-name document_processing_audit \
  --attribute-definitions \
    AttributeName=document_id,AttributeType=S \
    AttributeName=timestamp,AttributeType=S \
  --key-schema \
    AttributeName=document_id,KeyType=HASH \
    AttributeName=timestamp,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST

# Create metrics table
aws dynamodb create-table \
  --table-name pipeline_metrics_daily \
  --attribute-definitions \
    AttributeName=date,AttributeType=S \
    AttributeName=metric_type,AttributeType=S \
  --key-schema \
    AttributeName=date,KeyType=HASH \
    AttributeName=metric_type,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST
```

### Quick S3 Setup

```bash
# Create bucket (replace with your unique name)
aws s3 mb s3://your-document-pipeline-test

# Create folders
aws s3api put-object --bucket your-document-pipeline-test --key input/
aws s3api put-object --bucket your-document-pipeline-test --key extracted/
aws s3api put-object --bucket your-document-pipeline-test --key chunks/
aws s3api put-object --bucket your-document-pipeline-test --key enriched/
aws s3api put-object --bucket your-document-pipeline-test --key embeddings/
```

---

## Step 3: Local Ray Test (5 minutes)

```bash
# Start local Ray cluster
ray start --head --dashboard-host=0.0.0.0

# Verify Ray is running
ray status

# Access Ray dashboard: http://localhost:8265
```

---

## Step 4: Test Individual Stages (5 minutes)

### Test PDF Extraction

```python
# test_extraction.py
import ray
from ray_tasks import PDFExtractionTask

ray.init(address='auto')

task = PDFExtractionTask.remote()
result = ray.get(task.process.remote(
    document_id='test_doc_001',
    s3_bucket='your-document-pipeline-test',
    s3_key='input/sample.pdf'  # Upload a test PDF first
))

print(result)
```

Run: `python test_extraction.py`

### Create Test Document in DynamoDB

```python
# create_test_record.py
from dynamodb_manager import DynamoDBManager

db = DynamoDBManager()
db.create_control_record(
    document_id='test_doc_001',
    s3_key='input/sample.pdf',
    file_size=1234567,
    bucket='your-document-pipeline-test'
)

print("Test record created!")
```

Run: `python create_test_record.py`

---

## Step 5: Run Full Pipeline (5 minutes)

### Upload Test PDF

```bash
# Upload test document
aws s3 cp sample.pdf s3://your-document-pipeline-test/input/
```

### Start Orchestrator

```bash
python ray_orchestrator.py
```

**What happens:**
1. Orchestrator polls DynamoDB every 30s
2. Finds pending document
3. Processes through all 5 stages
4. Updates DynamoDB with progress
5. Outputs results to S3 and Pinecone

### Monitor Progress

**Terminal 1: Orchestrator logs**
```bash
python ray_orchestrator.py
```

**Terminal 2: Ray dashboard**
```
http://localhost:8265
```

**Terminal 3: DynamoDB audit trail**
```bash
watch -n 5 'aws dynamodb scan --table-name document_processing_audit --limit 10'
```

---

## Verification Checklist

After pipeline completes:

- [ ] Check S3 for outputs:
  ```bash
  aws s3 ls s3://your-document-pipeline-test/extracted/ --recursive
  aws s3 ls s3://your-document-pipeline-test/chunks/
  aws s3 ls s3://your-document-pipeline-test/embeddings/
  ```

- [ ] Check DynamoDB control record:
  ```bash
  aws dynamodb get-item \
    --table-name document_processing_control \
    --key '{"document_id":{"S":"test_doc_001"},"processing_version":{"S":"v1"}}'
  ```

- [ ] Check Pinecone vectors:
  ```python
  from pinecone import Pinecone
  pc = Pinecone(api_key='your-key')
  index = pc.Index('financial-documents')
  stats = index.describe_index_stats()
  print(f"Total vectors: {stats['total_vector_count']}")
  ```

---

## Common Issues

### Issue: "Ray not connected"
```bash
# Solution: Start Ray
ray start --head --dashboard-host=0.0.0.0
```

### Issue: "OpenAI API error"
```bash
# Solution: Check API key
echo $OPENAI_API_KEY
# Update .env and restart
```

### Issue: "DynamoDB table not found"
```bash
# Solution: Verify tables exist
aws dynamodb list-tables
```

### Issue: "S3 permission denied"
```bash
# Solution: Check AWS credentials
aws sts get-caller-identity
```

---

## Next Steps

✅ **Local testing works?** → Deploy to AWS ECS (see RAY_JOB_DEPLOYMENT_GUIDE.md)  
✅ **Need custom config?** → Edit config.py  
✅ **Want to monitor?** → Set up CloudWatch dashboard  
✅ **Production ready?** → Review security best practices  

---

## Stopping Everything

```bash
# Stop Ray cluster
ray stop

# Deactivate virtual environment
deactivate

# Optional: Delete test AWS resources
aws dynamodb delete-table --table-name document_processing_control
aws dynamodb delete-table --table-name document_processing_audit
aws dynamodb delete-table --table-name pipeline_metrics_daily
aws s3 rb s3://your-document-pipeline-test --force
```

---

**Need Help?** Check README.md and RAY_JOB_DEPLOYMENT_GUIDE.md for detailed instructions.
