# Ray Document Processing Pipeline

Production-grade distributed document processing pipeline using AWS Ray, DynamoDB, S3, and Pinecone.

**Author:** Prudhvi  
**Organization:** Thoughtworks  
**Date:** January 2025

---

## Overview

This pipeline processes PDF documents through 5 stages:

1. **PDF Extraction** - Docling-based hybrid visual extraction
2. **Semantic Chunking** - Context-aware document chunking
3. **Metadata Enrichment** - AWS Comprehend NLP enrichment
4. **Embedding Generation** - OpenAI text embeddings
5. **Vector Loading** - Pinecone vector database storage

### Key Features

✅ **Distributed Processing** - Ray-based parallel execution  
✅ **State Management** - DynamoDB control plane with full audit trail  
✅ **Fault Tolerant** - Automatic retries and error recovery  
✅ **Scalable** - Process 1 or 10,000 documents  
✅ **Cost Optimized** - Auto-scaling and spot instance support  
✅ **Production Ready** - Comprehensive logging and monitoring  

---

## Architecture

```
S3 Upload → Lambda → DynamoDB Control Record
                            ↓
                    Ray Cluster Polls
                            ↓
        ┌──────────────────────────────────┐
        │  Parallel Processing Pipeline    │
        │  (5 stages × N workers)          │
        └──────────────────────────────────┘
                            ↓
        ┌──────────────────────────────────┐
        │  S3 Outputs + DynamoDB Audit     │
        │  + Pinecone Vector Store         │
        └──────────────────────────────────┘
```

---

## File Structure

```
ray_pipeline_package/
├── config.py                          # Centralized configuration
├── utils.py                           # Helper utilities
├── dynamodb_manager.py                # DynamoDB operations
├── ray_tasks.py                       # Ray remote tasks
├── ray_orchestrator.py                # Main orchestrator
├── s3_event_lambda.py                 # S3 event handler Lambda
│
├── docling_gold_standard_advanced.py  # PDF extraction module
├── chunk_semantic_gold.py             # Semantic chunking
├── enrich_chunks.py                   # Metadata enrichment
├── metadata_enricher.py               # AWS Comprehend integration
├── 02_openai_embeddings.py            # OpenAI embeddings
├── load_embeddings_to_pinecone.py     # Pinecone loader
│
├── requirements.txt                   # Python dependencies
├── Dockerfile                         # Docker image definition
├── .env.example                       # Environment variables template
└── README.md                          # This file
```

---

## Prerequisites

### AWS Resources

1. **S3 Bucket** with folder structure:
   - `input/` - PDF uploads trigger processing
   - `extracted/` - Docling outputs
   - `chunks/` - Semantic chunks
   - `enriched/` - Comprehend-enriched chunks
   - `embeddings/` - OpenAI embeddings
   - `errors/` - Failed processing artifacts

2. **DynamoDB Tables**:
   - `document_processing_control` - Main control table
   - `document_processing_audit` - Audit log
   - `pipeline_metrics_daily` - Aggregated metrics

3. **IAM Roles**:
   - Lambda execution role (S3 read, DynamoDB write)
   - Ray task role (S3 read/write, DynamoDB read/write, Comprehend)

4. **Lambda Function**:
   - Trigger: S3 PUT events on `input/` prefix
   - Code: `s3_event_lambda.py`

### External Services

1. **OpenAI API Key** - For embeddings and GPT-4 Vision
2. **Pinecone Account** - For vector storage

### Ray Cluster

- ECS Fargate or EC2 instances
- Ray 2.9.0+
- Python 3.9+

---

## Installation

### 1. Set Up Environment Variables

```bash
cp .env.example .env
# Edit .env with your actual credentials
```

Required variables:
- `OPENAI_API_KEY`
- `PINECONE_API_KEY`
- `AWS_REGION`
- `S3_BUCKET`
- `DYNAMODB_CONTROL_TABLE`

### 2. Install Dependencies

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 3. Build Docker Image (for Ray cluster)

```bash
docker build -t ray-document-pipeline:latest .
```

### 4. Deploy to AWS

See `RAY_JOB_DEPLOYMENT_GUIDE.md` for detailed deployment instructions.

---

## Local Testing

### Test Individual Stages

```python
# Test extraction
from ray_tasks import PDFExtractionTask
import ray

ray.init()
task = PDFExtractionTask.remote()
result = ray.get(task.process.remote(
    document_id='test_doc',
    s3_bucket='your-bucket',
    s3_key='input/test.pdf'
))
print(result)
```

### Test Full Pipeline

```bash
# Set up environment
export OPENAI_API_KEY='your-key'
export PINECONE_API_KEY='your-key'
export S3_BUCKET='your-bucket'

# Run orchestrator
python ray_orchestrator.py
```

---

## Production Deployment

### Option 1: ECS Fargate (Recommended)

1. Push Docker image to ECR
2. Create ECS task definition
3. Deploy Ray head node as service
4. Auto-scale Ray workers based on queue depth

See `RAY_JOB_DEPLOYMENT_GUIDE.md` for step-by-step instructions.

### Option 2: EC2 Ray Cluster

1. Launch EC2 instances with Ray AMI
2. Configure Ray cluster (head + workers)
3. Deploy orchestrator code
4. Set up auto-scaling groups

---

## Monitoring

### CloudWatch Metrics

- `DocumentsProcessed` - Total processed count
- `DocumentsFailed` - Failed documents count
- `ExtractionDuration` - Avg extraction time
- `EmbeddingCost` - OpenAI API costs

### DynamoDB Queries

```python
# Get pending documents
from dynamodb_manager import DynamoDBManager

db = DynamoDBManager()
pending = db.get_pending_documents(limit=10)

# Get audit trail
trail = db.get_audit_trail('doc_20250131_abc123')
```

### Ray Dashboard

Access at: `http://<ray-head-ip>:8265`

---

## Configuration

Edit `config.py` to adjust:

- **Resource Allocation**: CPU/memory per task
- **Timeouts**: Stage-specific timeouts
- **Batch Sizes**: Embedding and Pinecone batch sizes
- **Retry Logic**: Max retries and backoff strategy
- **Chunking**: Target/min/max chunk sizes

---

## Error Handling

### Automatic Retries

Failed stages retry up to 3 times with exponential backoff:
- Attempt 1: Immediate
- Attempt 2: 2 seconds delay
- Attempt 3: 4 seconds delay

### Quarantine

Documents failing all retries move to:
- DynamoDB: `status = 'FAILED'`
- S3: `input/_quarantine/`

### Manual Recovery

```python
from dynamodb_manager import DynamoDBManager

db = DynamoDBManager()

# Reset failed document to pending
db.control_table.update_item(
    Key={'document_id': 'doc_xyz', 'processing_version': 'v1'},
    UpdateExpression="SET #status = :status, retry_count = :zero",
    ExpressionAttributeNames={'#status': 'status'},
    ExpressionAttributeValues={':status': 'PENDING', ':zero': 0}
)
```

---

## Troubleshooting

### Pipeline Not Starting

1. Check Ray cluster is running: `ray status`
2. Verify DynamoDB tables exist
3. Check environment variables are set
4. Review CloudWatch logs

### Stage Failures

1. Check DynamoDB audit table for error details
2. Review S3 `errors/` prefix for failed artifacts
3. Check task logs in CloudWatch
4. Verify API keys are valid

### High Costs

1. Monitor OpenAI usage in DynamoDB metrics
2. Adjust batch sizes in `config.py`
3. Use Fargate Spot for workers (60% savings)
4. Implement S3 lifecycle policies

---

## Performance Tuning

### Scale Ray Workers

Adjust worker count based on queue depth:

```python
# In ray_orchestrator.py
pending_count = len(db.get_pending_documents(limit=1000))

if pending_count > 100:
    # Add more workers
    pass
elif pending_count < 10:
    # Reduce workers
    pass
```

### Optimize Batch Sizes

```python
# In config.py
EMBEDDING_BATCH_SIZE = 100  # Increase for faster processing
PINECONE_BATCH_SIZE = 100   # Increase for bulk uploads
```

### Resource Allocation

```python
# In config.py
EXTRACTION_NUM_CPUS = 4     # CPU-intensive tasks
EMBEDDING_NUM_CPUS = 2      # I/O-bound tasks
```

---

## Cost Optimization

### Estimated Costs (per 1000 documents)

| Service | Usage | Cost |
|---------|-------|------|
| OpenAI Embeddings | 500K tokens | $0.01 |
| AWS Comprehend | 1M chars | $0.001 |
| ECS Fargate Spot | 10 vCPU-hours | $0.40 |
| S3 Storage | 50 GB | $1.15 |
| DynamoDB | 1M writes | $1.25 |
| **Total** | | **~$2.82** |

### Reduction Strategies

1. Use Fargate Spot (60% discount)
2. Implement S3 lifecycle policies (move to Glacier after 30 days)
3. Use DynamoDB on-demand pricing
4. Batch OpenAI calls efficiently
5. Cache Comprehend results

---

## Security

### Secrets Management

Use AWS Secrets Manager for:
- OpenAI API key
- Pinecone API key
- Database credentials

```python
import boto3

secrets = boto3.client('secretsmanager')
openai_key = secrets.get_secret_value(SecretId='openai-api-key')['SecretString']
```

### IAM Policies

Principle of least privilege:
- Lambda: S3 read, DynamoDB write only
- Ray tasks: S3 read/write, DynamoDB read/write, Comprehend
- No admin or wildcard permissions

### Network Security

- VPC for Ray cluster
- Security groups restrict access
- S3 bucket policies limit access
- Enable encryption at rest

---

## Contributing

1. Fork the repository
2. Create feature branch
3. Add tests for new features
4. Submit pull request

---

## License

Educational use only. For production use, please contact Thoughtworks.

---

## Support

For questions or issues:
- Email: prudhvi@thoughtworks.com
- Slack: #applied-genai-course

---

## Changelog

### v1.0.0 (2025-01-31)
- Initial release
- 5-stage pipeline implementation
- DynamoDB integration
- Ray orchestration
- Complete monitoring suite
