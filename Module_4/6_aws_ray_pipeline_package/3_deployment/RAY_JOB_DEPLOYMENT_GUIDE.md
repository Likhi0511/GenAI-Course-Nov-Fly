# Ray Job Deployment Guide - AWS Console/UI
## Step-by-Step Instructions for Production Deployment

**Author:** Prudhvi  
**Organization:** Thoughtworks  
**Date:** January 2025  
**Audience:** DevOps Engineers, Platform Engineers

---

## Table of Contents

1. [Prerequisites Setup](#prerequisites-setup)
2. [DynamoDB Tables Creation](#dynamodb-tables-creation)
3. [S3 Bucket Configuration](#s3-bucket-configuration)
4. [IAM Roles and Policies](#iam-roles-and-policies)
5. [Lambda Function Deployment](#lambda-function-deployment)
6. [Docker Image Build and Push](#docker-image-build-and-push)
7. [ECS Cluster Setup](#ecs-cluster-setup)
8. [Ray Head Node Deployment](#ray-head-node-deployment)
9. [Ray Worker Auto-Scaling](#ray-worker-auto-scaling)
10. [Testing and Validation](#testing-and-validation)
11. [Monitoring Setup](#monitoring-setup)
12. [Troubleshooting](#troubleshooting)

---

## Prerequisites Setup

### Required AWS Services

✅ AWS Account with appropriate permissions  
✅ AWS CLI installed and configured  
✅ Docker installed locally  
✅ OpenAI API key  
✅ Pinecone account and API key  

### Install AWS CLI

```bash
# Install AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Configure credentials
aws configure
```

### Install Docker

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install docker.io docker-compose

# Start Docker service
sudo systemctl start docker
sudo systemctl enable docker

# Add user to docker group
sudo usermod -aG docker $USER
```

---

## DynamoDB Tables Creation

### 1. Create Control Table

**Navigate to:** AWS Console → DynamoDB → Tables → Create table

#### Table Settings

| Setting | Value |
|---------|-------|
| Table name | `document_processing_control` |
| Partition key | `document_id` (String) |
| Sort key | `processing_version` (String) |
| Table settings | Default settings |
| Read capacity | On-demand |
| Write capacity | On-demand |

#### Create Global Secondary Index 1: Status Index

**After table creation:**

1. Click on table → Indexes → Create index
2. Configuration:
   - Index name: `status-index`
   - Partition key: `status` (String)
   - Sort key: `created_at` (String)
   - Projection: All attributes

#### Create Global Secondary Index 2: Stage Status Index

1. Click on Indexes → Create index
2. Configuration:
   - Index name: `stage-status-index`
   - Partition key: `current_stage` (String)
   - Sort key: `updated_at` (String)
   - Projection: All attributes

#### Enable TTL

1. Click on table → Additional settings → Time to Live (TTL)
2. TTL attribute: `ttl`
3. Click "Enable TTL"

### 2. Create Audit Table

**Navigate to:** DynamoDB → Tables → Create table

| Setting | Value |
|---------|-------|
| Table name | `document_processing_audit` |
| Partition key | `document_id` (String) |
| Sort key | `timestamp` (String) |
| Read capacity | On-demand |
| Write capacity | On-demand |

Enable TTL on `ttl` attribute.

### 3. Create Metrics Table

**Navigate to:** DynamoDB → Tables → Create table

| Setting | Value |
|---------|-------|
| Table name | `pipeline_metrics_daily` |
| Partition key | `date` (String) |
| Sort key | `metric_type` (String) |
| Read capacity | On-demand |
| Write capacity | On-demand |

### Verification

```bash
# List all tables
aws dynamodb list-tables

# Describe control table
aws dynamodb describe-table --table-name document_processing_control

# Verify indexes
aws dynamodb describe-table --table-name document_processing_control \
  --query "Table.GlobalSecondaryIndexes[*].IndexName"
```

---

## S3 Bucket Configuration

### 1. Create S3 Bucket

**Navigate to:** AWS Console → S3 → Create bucket

| Setting | Value |
|---------|-------|
| Bucket name | `your-document-pipeline` (must be globally unique) |
| Region | `us-east-1` (or your preferred region) |
| Block all public access | ✅ Enabled |
| Bucket versioning | ✅ Enabled |
| Server-side encryption | ✅ Enabled (SSE-S3) |

### 2. Create Folder Structure

After bucket creation, create these folders:

```
Click "Create folder" for each:
├── input/
├── extracted/
├── chunks/
├── enriched/
├── embeddings/
└── errors/
```

### 3. Configure Lifecycle Policies

**Navigate to:** S3 → Your bucket → Management → Lifecycle rules

#### Rule 1: Input Files

1. Click "Create lifecycle rule"
2. Configuration:
   - Rule name: `input-lifecycle`
   - Prefix: `input/`
   - Transitions:
     - After 30 days → Intelligent-Tiering
     - After 90 days → Glacier Flexible Retrieval
   - Expiration: 365 days

#### Rule 2: Processed Files

1. Create lifecycle rule
2. Configuration:
   - Rule name: `processed-lifecycle`
   - Prefix: `extracted/,chunks/,enriched/`
   - Transitions:
     - After 7 days → Intelligent-Tiering
     - After 30 days → Glacier Flexible Retrieval
   - Expiration: 90 days

#### Rule 3: Embeddings (Long-term)

1. Create lifecycle rule
2. Configuration:
   - Rule name: `embeddings-lifecycle`
   - Prefix: `embeddings/`
   - Transitions:
     - After 7 days → Intelligent-Tiering
   - Expiration: Never (unchecked)

#### Rule 4: Errors

1. Create lifecycle rule
2. Configuration:
   - Rule name: `errors-lifecycle`
   - Prefix: `errors/`
   - Transitions:
     - After 1 day → Intelligent-Tiering
     - After 7 days → Glacier Flexible Retrieval
   - Expiration: 180 days

### 4. Enable Event Notifications

**Navigate to:** S3 → Your bucket → Properties → Event notifications

1. Click "Create event notification"
2. Configuration:
   - Event name: `pdf-upload-trigger`
   - Prefix: `input/`
   - Suffix: `.pdf`
   - Event types: 
     - ✅ All object create events
   - Destination: Lambda function
   - Lambda function: `s3-document-processor` (will create in next section)

### Verification

```bash
# List bucket contents
aws s3 ls s3://your-document-pipeline/

# Verify lifecycle rules
aws s3api get-bucket-lifecycle-configuration --bucket your-document-pipeline

# Test upload
echo "test" > test.txt
aws s3 cp test.txt s3://your-document-pipeline/input/test.txt
```

---

## IAM Roles and Policies

### 1. Lambda Execution Role

**Navigate to:** IAM → Roles → Create role

#### Role Creation

1. **Trusted entity type:** AWS service
2. **Use case:** Lambda
3. **Role name:** `LambdaS3DynamoDBRole`

#### Attach Policies

**Policy 1: S3 Read Access**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-document-pipeline",
        "arn:aws:s3:::your-document-pipeline/*"
      ]
    }
  ]
}
```

**Policy 2: DynamoDB Write Access**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:UpdateItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:us-east-1:*:table/document_processing_control",
        "arn:aws:dynamodb:us-east-1:*:table/document_processing_audit"
      ]
    }
  ]
}
```

**Policy 3: CloudWatch Logs**

Attach managed policy: `AWSLambdaBasicExecutionRole`

### 2. ECS Task Execution Role

**Navigate to:** IAM → Roles → Create role

#### Role Creation

1. **Trusted entity type:** AWS service
2. **Use case:** Elastic Container Service → Elastic Container Service Task
3. **Role name:** `ECSTaskExecutionRole`

#### Attach Policies

Attach managed policy: `AmazonECSTaskExecutionRolePolicy`

### 3. Ray Task Role

**Navigate to:** IAM → Roles → Create role

#### Role Creation

1. **Trusted entity type:** AWS service
2. **Use case:** Elastic Container Service → Elastic Container Service Task
3. **Role name:** `RayDocumentProcessingTaskRole`

#### Create Custom Policy

**Policy Name:** `RayPipelinePolicy`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3Access",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-document-pipeline",
        "arn:aws:s3:::your-document-pipeline/*"
      ]
    },
    {
      "Sid": "DynamoDBAccess",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query",
        "dynamodb:Scan"
      ],
      "Resource": [
        "arn:aws:dynamodb:us-east-1:*:table/document_processing_control",
        "arn:aws:dynamodb:us-east-1:*:table/document_processing_control/index/*",
        "arn:aws:dynamodb:us-east-1:*:table/document_processing_audit",
        "arn:aws:dynamodb:us-east-1:*:table/pipeline_metrics_daily"
      ]
    },
    {
      "Sid": "ComprehendAccess",
      "Effect": "Allow",
      "Action": [
        "comprehend:DetectEntities",
        "comprehend:DetectKeyPhrases",
        "comprehend:DetectSentiment"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SecretsManagerAccess",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:*:secret:openai-api-key*",
        "arn:aws:secretsmanager:us-east-1:*:secret:pinecone-api-key*"
      ]
    },
    {
      "Sid": "CloudWatchMetrics",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:PutMetricData"
      ],
      "Resource": "*"
    }
  ]
}
```

### Verification

```bash
# List roles
aws iam list-roles --query 'Roles[?contains(RoleName, `Ray`) || contains(RoleName, `Lambda`) || contains(RoleName, `ECS`)].RoleName'

# Get role details
aws iam get-role --role-name RayDocumentProcessingTaskRole

# List attached policies
aws iam list-attached-role-policies --role-name RayDocumentProcessingTaskRole
```

---

## Lambda Function Deployment

### 1. Create Secrets in Secrets Manager

**Navigate to:** Secrets Manager → Store a new secret

#### Secret 1: OpenAI API Key

1. Secret type: Other type of secret
2. Key/value pairs:
   - Key: `OPENAI_API_KEY`
   - Value: `sk-your-openai-key-here`
3. Secret name: `openai-api-key`

#### Secret 2: Pinecone API Key

1. Secret type: Other type of secret
2. Key/value pairs:
   - Key: `PINECONE_API_KEY`
   - Value: `your-pinecone-key-here`
3. Secret name: `pinecone-api-key`

### 2. Package Lambda Function

```bash
# Create 3_deployment package directory
mkdir lambda_package
cd lambda_package

# Copy Lambda function
cp ../s3_event_lambda.py lambda_function.py

# Create 3_deployment package
zip -r lambda_deployment.zip lambda_function.py

# Verify
unzip -l lambda_deployment.zip
```

### 3. Create Lambda Function

**Navigate to:** Lambda → Functions → Create function

| Setting | Value |
|---------|-------|
| Function name | `s3-document-processor` |
| Runtime | Python 3.9 |
| Architecture | x86_64 |
| Execution role | Use existing role: `LambdaS3DynamoDBRole` |

#### Upload Code

1. Click on function → Code → Upload from → .zip file
2. Upload `lambda_deployment.zip`

#### Configure Environment Variables

**Navigate to:** Configuration → Environment variables → Edit

Add these variables:

| Key | Value |
|-----|-------|
| `CONTROL_TABLE_NAME` | `document_processing_control` |
| `AUDIT_TABLE_NAME` | `document_processing_audit` |
| `AWS_REGION` | `us-east-1` |

#### Configure Function Settings

**Navigate to:** Configuration → General configuration → Edit

| Setting | Value |
|---------|-------|
| Memory | 256 MB |
| Timeout | 1 min |
| Ephemeral storage | 512 MB |

### 4. Add S3 Trigger

**Navigate to:** Function → Add trigger

| Setting | Value |
|---------|-------|
| Trigger | S3 |
| Bucket | `your-document-pipeline` |
| Event type | All object create events |
| Prefix | `input/` |
| Suffix | `.pdf` |

### 5. Test Lambda Function

1. Click "Test" tab
2. Create new test event:

```json
{
  "Records": [
    {
      "s3": {
        "bucket": {
          "name": "your-document-pipeline"
        },
        "object": {
          "key": "input/test_document.pdf",
          "size": 2457600
        }
      }
    }
  ]
}
```

3. Click "Test"
4. Verify execution succeeds
5. Check DynamoDB for new record

### Verification

```bash
# Invoke Lambda manually
aws lambda invoke \
  --function-name s3-document-processor \
  --payload file://test_event.json \
  response.json

# View logs
aws logs tail /aws/lambda/s3-document-processor --follow

# Check DynamoDB
aws dynamodb scan --table-name document_processing_control --limit 5
```

---

## Docker Image Build and Push

### 1. Create ECR Repository

**Navigate to:** ECR → Repositories → Create repository

| Setting | Value |
|---------|-------|
| Visibility | Private |
| Repository name | `ray-document-pipeline` |
| Tag immutability | Disabled |
| Scan on push | Enabled |
| Encryption | AES-256 |

### 2. Authenticate Docker with ECR

```bash
# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Get ECR login password
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com
```

### 3. Build Docker Image

```bash
# Navigate to pipeline package directory
cd ray_pipeline_package

# Build image
docker build -t ray-document-pipeline:latest .

# Tag for ECR
docker tag ray-document-pipeline:latest \
  ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/ray-document-pipeline:latest

docker tag ray-document-pipeline:latest \
  ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/ray-document-pipeline:v1.0.0
```

### 4. Push to ECR

```bash
# Push latest tag
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/ray-document-pipeline:latest

# Push version tag
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/ray-document-pipeline:v1.0.0
```

### 5. Verify Image

```bash
# List images in repository
aws ecr describe-images --repository-name ray-document-pipeline

# Get image URI
IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/ray-document-pipeline:latest"
echo $IMAGE_URI
```

### Test Image Locally (Optional)

```bash
# Run container locally
docker run -it \
  -e AWS_REGION=us-east-1 \
  -e S3_BUCKET=your-document-pipeline \
  -e OPENAI_API_KEY=sk-your-key \
  -e PINECONE_API_KEY=your-key \
  ray-document-pipeline:latest \
  /bin/bash

# Inside container, verify Ray
python -c "import ray; print(ray.__version__)"
```

---

## ECS Cluster Setup

### 1. Create VPC (if needed)

**Navigate to:** VPC → Your VPCs → Create VPC

Use VPC Wizard → "VPC with Public and Private Subnets"

| Setting | Value |
|---------|-------|
| Name | `ray-pipeline-vpc` |
| IPv4 CIDR | `10.0.0.0/16` |
| Public subnet CIDR | `10.0.1.0/24` |
| Private subnet CIDR | `10.0.2.0/24` |
| NAT Gateway | Yes (for private subnet) |

### 2. Create ECS Cluster

**Navigate to:** ECS → Clusters → Create cluster

#### Cluster Configuration

| Setting | Value |
|---------|-------|
| Cluster name | `ray-document-pipeline` |
| Infrastructure | AWS Fargate (serverless) |
| Default namespace | `ray-pipeline` |

#### Monitoring (Optional)

| Setting | Value |
|---------|-------|
| Container Insights | ✅ Enabled |

Click "Create"

### 3. Create Security Group for Ray

**Navigate to:** VPC → Security Groups → Create security group

| Setting | Value |
|---------|-------|
| Name | `ray-cluster-sg` |
| Description | Security group for Ray cluster |
| VPC | `ray-pipeline-vpc` |

#### Inbound Rules

| Type | Protocol | Port Range | Source | Description |
|------|----------|------------|--------|-------------|
| Custom TCP | TCP | 6379 | Security group ID | Ray GCS |
| Custom TCP | TCP | 8265 | Your IP | Ray Dashboard |
| Custom TCP | TCP | 10001 | Security group ID | Ray Client |
| All traffic | All | All | Security group ID | Ray inter-node |

#### Outbound Rules

| Type | Protocol | Port Range | Destination | Description |
|------|----------|------------|-------------|-------------|
| All traffic | All | All | 0.0.0.0/0 | Allow all outbound |

### Verification

```bash
# List clusters
aws ecs list-clusters

# Describe cluster
aws ecs describe-clusters --clusters ray-document-pipeline

# List services (should be empty initially)
aws ecs list-services --cluster ray-document-pipeline
```

---

## Ray Head Node Deployment

### 1. Create Task Definition

**Navigate to:** ECS → Task Definitions → Create new task definition

#### Task Definition Configuration

| Setting | Value |
|---------|-------|
| Task definition family | `ray-head-node` |
| Launch type | Fargate |
| Operating system | Linux/X86_64 |
| Task role | `RayDocumentProcessingTaskRole` |
| Task execution role | `ECSTaskExecutionRole` |

#### Task Size

| Setting | Value |
|---------|-------|
| CPU | 2 vCPU |
| Memory | 8 GB |

#### Container Definition

Click "Add container"

| Setting | Value |
|---------|-------|
| Container name | `ray-head` |
| Image URI | `<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/ray-document-pipeline:latest` |
| Essential | ✅ Yes |

#### Port Mappings

| Container port | Protocol | Name |
|----------------|----------|------|
| 6379 | TCP | ray-gcs |
| 8265 | TCP | ray-dashboard |
| 10001 | TCP | ray-client |

#### Environment Variables

Add these:

| Key | Value Type | Value |
|-----|------------|-------|
| `AWS_REGION` | Value | `us-east-1` |
| `S3_BUCKET` | Value | `your-document-pipeline` |
| `DYNAMODB_CONTROL_TABLE` | Value | `document_processing_control` |
| `DYNAMODB_AUDIT_TABLE` | Value | `document_processing_audit` |
| `RAY_ADDRESS` | Value | `auto` |
| `OPENAI_API_KEY` | ValueFrom | `arn:aws:secretsmanager:...:secret:openai-api-key` |
| `PINECONE_API_KEY` | ValueFrom | `arn:aws:secretsmanager:...:secret:pinecone-api-key` |

#### Command Override

```json
[
  "ray",
  "start",
  "--head",
  "--port=6379",
  "--dashboard-host=0.0.0.0",
  "--dashboard-port=8265",
  "--block"
]
```

#### Log Configuration

| Setting | Value |
|---------|-------|
| Log driver | awslogs |
| awslogs-group | `/ecs/ray-head-node` |
| awslogs-region | `us-east-1` |
| awslogs-stream-prefix | `ray-head` |

Create log group in CloudWatch if needed:

```bash
aws logs create-log-group --log-group-name /ecs/ray-head-node
```

### 2. Create Service for Ray Head

**Navigate to:** ECS → Clusters → ray-document-pipeline → Services → Create

#### Service Configuration

| Setting | Value |
|---------|-------|
| Launch type | Fargate |
| Task definition | `ray-head-node:1` (latest) |
| Service name | `ray-head` |
| Number of tasks | 1 |

#### Networking

| Setting | Value |
|---------|-------|
| VPC | `ray-pipeline-vpc` |
| Subnets | Select public subnet |
| Security group | `ray-cluster-sg` |
| Public IP | ENABLED |

#### Load Balancing

| Setting | Value |
|---------|-------|
| Load balancer type | None (for now) |

Click "Create"

### 3. Get Ray Head IP Address

**Navigate to:** ECS → Clusters → ray-document-pipeline → Services → ray-head → Tasks

1. Click on running task
2. Note "Public IP" address
3. Access Ray Dashboard: `http://<PUBLIC_IP>:8265`

### Verification

```bash
# List tasks
aws ecs list-tasks --cluster ray-document-pipeline --service-name ray-head

# Describe task
TASK_ARN=$(aws ecs list-tasks --cluster ray-document-pipeline --service-name ray-head --query 'taskArns[0]' --output text)
aws ecs describe-tasks --cluster ray-document-pipeline --tasks $TASK_ARN

# Get public IP
aws ecs describe-tasks --cluster ray-document-pipeline --tasks $TASK_ARN \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' --output text | \
  xargs -I {} aws ec2 describe-network-interfaces --network-interface-ids {} \
  --query 'NetworkInterfaces[0].Association.PublicIp' --output text

# View logs
aws logs tail /ecs/ray-head-node --follow
```

---

## Ray Worker Auto-Scaling

### 1. Create Worker Task Definition

**Navigate to:** ECS → Task Definitions → Create new task definition

#### Task Definition Configuration

| Setting | Value |
|---------|-------|
| Task definition family | `ray-worker-node` |
| Launch type | Fargate |
| Fargate platform version | LATEST |
| Operating system | Linux/X86_64 |
| Task role | `RayDocumentProcessingTaskRole` |
| Task execution role | `ECSTaskExecutionRole` |

#### Task Size

| Setting | Value |
|---------|-------|
| CPU | 1 vCPU |
| Memory | 4 GB |

#### Container Definition

| Setting | Value |
|---------|-------|
| Container name | `ray-worker` |
| Image URI | Same as head node |
| Essential | ✅ Yes |

#### Environment Variables

Same as head node, plus:

| Key | Value |
|-----|-------|
| `RAY_ADDRESS` | `<RAY_HEAD_PUBLIC_IP>:6379` |

#### Command Override

```json
[
  "ray",
  "start",
  "--address=<RAY_HEAD_PUBLIC_IP>:6379",
  "--num-cpus=1",
  "--block"
]
```

**Note:** Replace `<RAY_HEAD_PUBLIC_IP>` with actual IP from previous section

### 2. Create Worker Service

**Navigate to:** ECS → Clusters → ray-document-pipeline → Services → Create

#### Service Configuration

| Setting | Value |
|---------|-------|
| Task definition | `ray-worker-node:1` |
| Service name | `ray-workers` |
| Number of tasks | 2 (initial) |

#### Auto Scaling

| Setting | Value |
|---------|-------|
| Configure Service Auto Scaling | ✅ Yes |
| Minimum number of tasks | 1 |
| Maximum number of tasks | 10 |

#### Auto Scaling Policy

**Policy 1: Scale Up**

| Setting | Value |
|---------|-------|
| Policy name | `ScaleUpOnPending` |
| ECS service metric | None (custom) |
| Target tracking scaling | No |
| Step scaling | Yes |

CloudWatch alarm configuration:
- Metric: Custom metric `PendingDocuments`
- Namespace: `DocumentPipeline`
- Threshold: > 10
- Action: Add 2 tasks

**Policy 2: Scale Down**

| Setting | Value |
|---------|-------|
| Policy name | `ScaleDownOnIdle` |
| Threshold | < 5 pending documents |
| Action: Remove 1 task |

### 3. Deploy Orchestrator

Once Ray cluster is running, deploy the orchestrator:

```bash
# SSH into Ray head node (or use ECS Exec)
aws ecs execute-command \
  --cluster ray-document-pipeline \
  --task <TASK_ID> \
  --container ray-head \
  --command "/bin/bash" \
  --interactive

# Inside container
cd /app
python ray_orchestrator.py
```

**Better Approach:** Create separate task definition for orchestrator

---

## Testing and Validation

### 1. Upload Test PDF

```bash
# Upload test PDF to S3
aws s3 cp test_document.pdf s3://your-document-pipeline/input/
```

### 2. Verify Lambda Execution

```bash
# Check Lambda logs
aws logs tail /aws/lambda/s3-document-processor --follow

# Check DynamoDB for new record
aws dynamodb scan --table-name document_processing_control \
  --filter-expression "attribute_exists(document_id)" \
  --limit 1
```

### 3. Monitor Pipeline Execution

#### Ray Dashboard

Access: `http://<RAY_HEAD_IP>:8265`

Check:
- Tasks running
- Resource utilization
- Task logs

#### DynamoDB Audit Trail

```bash
# Get document ID from control table
DOC_ID=$(aws dynamodb scan --table-name document_processing_control \
  --limit 1 --query 'Items[0].document_id.S' --output text)

# Query audit trail
aws dynamodb query --table-name document_processing_audit \
  --key-condition-expression "document_id = :doc_id" \
  --expression-attribute-values '{":doc_id":{"S":"'"$DOC_ID"'"}}' \
  --scan-index-forward
```

#### CloudWatch Logs

```bash
# View orchestrator logs
aws logs tail /ecs/ray-orchestrator --follow

# View worker logs
aws logs tail /ecs/ray-worker-node --follow
```

### 4. Verify Outputs

```bash
# Check S3 outputs
aws s3 ls s3://your-document-pipeline/extracted/ --recursive
aws s3 ls s3://your-document-pipeline/chunks/ --recursive
aws s3 ls s3://your-document-pipeline/embeddings/ --recursive
```

### 5. Test Pinecone

```python
from pinecone import Pinecone

pc = Pinecone(api_key='your-key')
index = pc.Index('financial-documents')

# Check stats
stats = index.describe_index_stats()
print(f"Total vectors: {stats['total_vector_count']}")

# Test query
results = index.query(
    vector=[0.1] * 1536,
    top_k=5,
    include_metadata=True
)
print(results)
```

---

## Monitoring Setup

### 1. CloudWatch Dashboard

**Navigate to:** CloudWatch → Dashboards → Create dashboard

**Dashboard name:** `DocumentPipeline`

#### Add Widgets

**Widget 1: Document Processing Status**

- Widget type: Line graph
- Metrics:
  - `DocumentPipeline/DocumentsProcessed`
  - `DocumentPipeline/DocumentsFailed`
  - `DocumentPipeline/DocumentsInProgress`
- Period: 5 minutes

**Widget 2: Stage Durations**

- Widget type: Stacked area
- Metrics:
  - `DocumentPipeline/ExtractionDuration`
  - `DocumentPipeline/ChunkingDuration`
  - `DocumentPipeline/EnrichmentDuration`
  - `DocumentPipeline/EmbeddingDuration`
  - `DocumentPipeline/LoadingDuration`

**Widget 3: ECS Resource Usage**

- Widget type: Line graph
- Metrics:
  - `AWS/ECS/CPUUtilization`
  - `AWS/ECS/MemoryUtilization`
- Dimensions: ClusterName=ray-document-pipeline

**Widget 4: Costs**

- Widget type: Number
- Metrics:
  - Custom metric: `TotalCostUSD`
- Period: Daily

### 2. CloudWatch Alarms

#### Alarm 1: High Failure Rate

**Navigate to:** CloudWatch → Alarms → Create alarm

| Setting | Value |
|---------|-------|
| Metric | `DocumentPipeline/DocumentsFailed` |
| Statistic | Sum |
| Period | 5 minutes |
| Threshold | > 5 |
| Action | SNS topic notification |

#### Alarm 2: Processing Queue Backlog

| Setting | Value |
|---------|-------|
| Metric | `DocumentPipeline/PendingDocuments` |
| Threshold | > 100 |
| Action | SNS + Auto-scale workers |

#### Alarm 3: High Costs

| Setting | Value |
|---------|-------|
| Metric | `DocumentPipeline/TotalCostUSD` |
| Period | 1 day |
| Threshold | > 100 |
| Action | SNS notification |

### 3. Create SNS Topic for Alerts

```bash
# Create SNS topic
aws sns create-topic --name pipeline-alerts

# Subscribe email
aws sns subscribe \
  --topic-arn arn:aws:sns:us-east-1:123456789012:pipeline-alerts \
  --protocol email \
  --notification-endpoint your-email@example.com
```

---

## Troubleshooting

### Issue 1: Lambda Not Triggering

**Symptoms:**
- PDF uploaded to S3
- No DynamoDB record created

**Solutions:**

1. Check S3 event configuration:
```bash
aws s3api get-bucket-notification-configuration \
  --bucket your-document-pipeline
```

2. Verify Lambda has S3 trigger:
```bash
aws lambda get-policy --function-name s3-document-processor
```

3. Check Lambda logs:
```bash
aws logs tail /aws/lambda/s3-document-processor --follow
```

4. Test Lambda manually:
```bash
aws lambda invoke \
  --function-name s3-document-processor \
  --payload file://test_event.json \
  response.json
```

### Issue 2: Ray Workers Not Connecting

**Symptoms:**
- Ray head running
- Workers show as offline in dashboard

**Solutions:**

1. Check security group allows Ray ports:
```bash
aws ec2 describe-security-groups \
  --group-ids sg-xxxxx \
  --query 'SecurityGroups[0].IpPermissions'
```

2. Verify worker task has correct RAY_ADDRESS:
```bash
aws ecs describe-task-definition \
  --task-definition ray-worker-node \
  --query 'taskDefinition.containerDefinitions[0].environment'
```

3. Check worker logs:
```bash
aws logs tail /ecs/ray-worker-node --follow
```

4. Test connectivity from worker:
```bash
# Inside worker container
nc -zv <RAY_HEAD_IP> 6379
```

### Issue 3: DynamoDB Throttling

**Symptoms:**
- Pipeline slowing down
- DynamoDB errors in logs

**Solutions:**

1. Check DynamoDB metrics:
```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name ConsumedReadCapacityUnits \
  --dimensions Name=TableName,Value=document_processing_control \
  --start-time 2025-01-31T00:00:00Z \
  --end-time 2025-01-31T23:59:59Z \
  --period 3600 \
  --statistics Sum
```

2. Enable on-demand capacity if using provisioned

3. Add exponential backoff in code

### Issue 4: High OpenAI Costs

**Symptoms:**
- Unexpected OpenAI bills
- Cost metrics exceeding budget

**Solutions:**

1. Check embedding batch sizes:
```python
# In config.py
EMBEDDING_BATCH_SIZE = 100  # Increase for efficiency
```

2. Implement caching for repeated content

3. Monitor token usage:
```bash
aws dynamodb scan --table-name pipeline_metrics_daily \
  --filter-expression "metric_type = :type" \
  --expression-attribute-values '{":type":{"S":"costs"}}'
```

### Issue 5: Tasks Stuck in PENDING

**Symptoms:**
- Documents stay in PENDING status
- No progress in pipeline

**Solutions:**

1. Check orchestrator is running:
```bash
# List orchestrator tasks
aws ecs list-tasks --cluster ray-document-pipeline \
  --family ray-orchestrator
```

2. Restart orchestrator service

3. Check DynamoDB query limits:
```bash
# Manual poll
python -c "
from dynamodb_manager import DynamoDBManager
db = DynamoDBManager()
pending = db.get_pending_documents(limit=10)
print(f'Found {len(pending)} pending documents')
"
```

---

## Next Steps

After successful deployment:

1. ✅ Monitor pipeline for 24 hours
2. ✅ Tune auto-scaling thresholds
3. ✅ Implement cost alerts
4. ✅ Set up automated testing
5. ✅ Document runbooks for on-call team
6. ✅ Create disaster recovery plan

---

## Additional Resources

- [AWS ECS Documentation](https://docs.aws.amazon.com/ecs/)
- [Ray Documentation](https://docs.ray.io/)
- [Pinecone Documentation](https://docs.pinecone.io/)
- [OpenAI API Reference](https://platform.openai.com/docs/)

---

**Support:** prudhvi@thoughtworks.com  
**Version:** 1.0.0  
**Last Updated:** 2025-01-31
