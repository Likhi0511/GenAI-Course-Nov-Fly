# Ray Document Processing Pipeline

A production-ready distributed RAG (Retrieval-Augmented Generation) pipeline built on **AWS ECS Fargate** + **Ray**, designed to ingest clinical trial PDFs at scale and make them semantically searchable via Pinecone.

Built as a teaching module for the **Applied GenAI** course at Vidya Sankalp — the architecture is intentionally explained step by step so students can understand every design decision, not just run the code.

---

## What This Pipeline Does

Upload a PDF → get it fully searchable in Pinecone within minutes.

Every document goes through 5 automated stages running as Ray remote tasks on ECS:

```
PDF (S3)
  │
  ▼  Stage 1 — Extract
     Docling converts PDF → Markdown pages with <!-- BOUNDARY --> markers
     GPT-4o describes every image/table inline
  │
  ▼  Stage 2 — Chunk
     Boundary-aware chunker splits into ~1500-char semantic units
     Never splits mid-table or mid-paragraph
  │
  ▼  Stage 3 — Enrich
     Single GPT-4o-mini call per chunk handles 3 tasks at once:
       • PII redaction  (emails, phone numbers, SSNs → [REDACTED])
       • Named Entity Recognition  (people, orgs, medications)
       • Key phrase extraction  (improves search recall)
  │
  ▼  Stage 4 — Embed
     OpenAI text-embedding-3-small → 1536-dimensional vectors
     Exponential backoff for rate limits, token cost tracked per doc
  │
  ▼  Stage 5 — Load
     Vectors upserted into Pinecone with full metadata
     MD5-based IDs make re-runs idempotent
  │
  ▼
Pinecone index — document is now fully searchable
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          AWS ECS Fargate                             │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                     Ray Head Container                        │   │
│  │   • Starts Ray cluster  (--head, port 6379)                  │   │
│  │   • Runs ray_orchestrator.py  (polling loop)                 │   │
│  │   • Hosts Ray Dashboard  (port 8265)                         │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                          ▲  Service Discovery: ray-head.local        │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐   │
│  │Ray Worker 1│  │Ray Worker 2│  │Ray Worker 3│  │   ...      │   │
│  │ ray_tasks  │  │ ray_tasks  │  │ ray_tasks  │  │ (auto-     │   │
│  │ Stages 1-5 │  │ Stages 1-5 │  │ Stages 1-5 │  │  scale)    │   │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘   │
│                  1–10 workers, Fargate Spot (70% cheaper)            │
└─────────────────────────────────────────────────────────────────────┘
         │                │                │                │
         ▼                ▼                ▼                ▼
       S3 Bucket      DynamoDB         Secrets          Pinecone
    (PDF storage,   (Control +       Manager           (vector
     stage outputs)  Audit tables)  (API keys)          index)
```

**Key design decisions:**

| Decision | Reason |
|---|---|
| Public subnet (no NAT Gateway) | Saves ~$32/month — fine for teaching demos |
| Ray functions not classes | Simpler, stateless, easier to test |
| Head runs orchestrator | Avoids a 3rd ECS service; head CPU is reserved (`--num-cpus=0`) |
| Fargate Spot for workers | 70% cost saving; workers are stateless so interruption is safe |
| VPC Gateway Endpoints for S3 + DynamoDB | Free — traffic stays inside AWS network |
| DynamoDB conditional updates | Prevents duplicate processing if 2 orchestrators run simultaneously |

---

## Project Structure

```
ray-document-pipeline/
│
├── 1_prerequisites/
│   └── check_prerequisites.py      # Validates environment + provisions AWS resources
│
├── 2_cloudformation/
│   ├── 1_ray-pipeline-cloudformation-public.yaml   # Full infrastructure-as-code
│   └── cloudformation-parameters.json             # Stack parameters (edit before deploy)
│
└── 3_deployment/
    ├── Dockerfile                  # Pipeline container image
    ├── requirements.txt            # Python dependencies
    ├── config.py                   # Central config (reads env vars / Secrets Manager)
    ├── ray_orchestrator.py         # Polling loop — drives all 5 stages per document
    ├── ray_tasks.py                # @ray.remote functions for Stages 1–5
    ├── docling_bounded_extractor.py # Stage 1: PDF → Markdown with boundary markers
    ├── comprehensive_chunker.py    # Stage 2: Semantic chunking
    ├── enrich_pipeline_openai.py   # Stage 3: PII + NER + key phrases
    ├── openai_embeddings.py        # Stage 4: Vector generation
    ├── load_embeddings_to_pinecone.py # Stage 5: Pinecone upsert
    ├── dynamodb_manager.py         # DynamoDB helpers
    ├── s3_event_lambda.py          # Lambda: S3 upload → DynamoDB PENDING record
    ├── utils.py                    # S3Helper, LocalFileManager, format_duration
    │
    ├── orchestrator.py             # Run all 3 deployment steps in sequence
    ├── step1_deploy_cloudformation.py  # Deploy stack + wait for CREATE_COMPLETE
    ├── step2_download_clinical_trials.py  # Download 10 PDFs from ClinicalTrials.gov
    └── step3_upload_to_s3.py           # Upload PDFs → triggers pipeline automatically
```

---

## Prerequisites

### Local tools required

| Tool | Version | Check |
|---|---|---|
| Python | 3.9+ | `python --version` |
| AWS CLI | v2.x | `aws --version` |
| Docker | Any recent | `docker --version` |

### AWS account requirements

- IAM user with **PowerUserAccess** (or the scoped policy in `check_prerequisites.py`)
- Region: `us-east-1` (default — change in `cloudformation-parameters.json` if needed)

### API keys required

| Key | Where to get it | Environment variable |
|---|---|---|
| OpenAI API key | [platform.openai.com](https://platform.openai.com/api-keys) | `OPENAI_API_KEY` |
| Pinecone API key | [app.pinecone.io](https://app.pinecone.io) | `PINECONE_API_KEY` |

Set them before running anything:

```bash
export OPENAI_API_KEY="sk-..."
export PINECONE_API_KEY="pcsk_..."
```

---

## Deployment

### Step 0 — Run the prerequisites checker

This is the most important step. It validates your environment, stores API keys in Secrets Manager, builds your Docker image, pushes it to ECR, and updates `cloudformation-parameters.json` — all automatically.

```bash
cd 1_prerequisites
python check_prerequisites.py
```

**First run takes 8–12 minutes** (Docker image build + ECR push). Subsequent runs take 1–2 minutes because Docker layers are cached.

What it checks:
1. AWS CLI installed
2. AWS credentials valid
3. AWS region configured
4. Docker installed and running
5. IAM permissions for all 7 required services
6. OpenAI + Pinecone keys → created in Secrets Manager
7. S3 bucket name set in parameters file
8. Docker image built and pushed to ECR
9. VPC quota not exceeded
10. CloudFormation template syntax valid

Only proceed to Step 1 once all 10 checks show `[PASS]`.

---

### Step 1 — Edit parameters (if needed)

Open `2_cloudformation/cloudformation-parameters.json` and verify these values:

```json
{
  "ParameterKey": "S3BucketName",
  "ParameterValue": "ray-pipeline-yourname-2026"   ← must be globally unique
},
{
  "ParameterKey": "AlertEmail",
  "ParameterValue": "your-email@example.com"       ← for CloudWatch alarm emails
},
{
  "ParameterKey": "UseFargateSpot",
  "ParameterValue": "true"                          ← keep true for cost savings
}
```

The prerequisites checker auto-fills `ECRImageUri`, `OpenAISecretArn`, and `PineconeSecretArn` — you don't need to touch those.

---

### Step 2 — Deploy everything (one command)

```bash
cd 3_deployment
python orchestrator.py
```

This runs 3 steps in sequence:

| Step | Script | What it does | Time |
|---|---|---|---|
| 1 | `step1_deploy_cloudformation.py` | Deploys CloudFormation stack, waits for `CREATE_COMPLETE` | ~12 min |
| 2 | `step2_download_clinical_trials.py` | Downloads 10 clinical trial PDFs from ClinicalTrials.gov | ~1 min |
| 3 | `step3_upload_to_s3.py` | Uploads PDFs to S3 — Lambda auto-queues them in DynamoDB | ~30 sec |

> **Note:** Step 1 blocks until the entire stack is ready before proceeding. No more "NoSuchBucket" errors from uploading too early.

You can also run steps individually if needed:

```bash
python step1_deploy_cloudformation.py   # Deploy or update stack
python step2_download_clinical_trials.py
python step3_upload_to_s3.py
```

---

### Step 3 — Find the Ray Dashboard

Once the stack is deployed, get the Ray head node's public IP:

```bash
CLUSTER=$(aws cloudformation describe-stacks \
  --stack-name ray-document-pipeline \
  --query 'Stacks[0].Outputs[?OutputKey==`ECSClusterName`].OutputValue' \
  --output text)

SERVICE=$(aws cloudformation describe-stacks \
  --stack-name ray-document-pipeline \
  --query 'Stacks[0].Outputs[?OutputKey==`RayHeadServiceName`].OutputValue' \
  --output text)

TASK=$(aws ecs list-tasks --cluster $CLUSTER \
  --service-name $SERVICE --query 'taskArns[0]' --output text)

aws ecs describe-tasks --cluster $CLUSTER --tasks $TASK \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
  --output text | xargs -I {} \
  aws ec2 describe-network-interfaces \
  --network-interface-ids {} \
  --query 'NetworkInterfaces[0].Association.PublicIp' \
  --output text
```

Open `http://<PUBLIC_IP>:8265` in your browser to see the Ray Dashboard.

---

## How a Document Gets Processed

When you upload a PDF to `s3://<bucket>/input/`, this chain fires automatically:

```
1. S3 ObjectCreated event fires
2. Lambda (s3_event_lambda.py) creates a PENDING record in DynamoDB
   └── document_id = MD5 hash of S3 key (idempotent — no duplicates on retry)
3. Orchestrator polling loop picks up the PENDING record
4. Orchestrator claims the document atomically (PENDING → IN_PROGRESS)
   └── DynamoDB ConditionExpression prevents two orchestrators from claiming the same doc
5. Stage 1 runs on a Ray worker → extracts PDF → saves to S3
6. Stage 2 runs on a Ray worker → chunks markdown → saves to S3
7. Stage 3 runs on a Ray worker → enriches chunks → saves to S3
8. Stage 4 runs on a Ray worker → generates embeddings → saves to S3
9. Stage 5 runs on a Ray worker → loads vectors into Pinecone
10. DynamoDB record updated to COMPLETED
```

---

## Monitoring

### Watch documents being processed

```bash
# DynamoDB control table — shows status of every document
aws dynamodb scan \
  --table-name ray-document-pipeline-control \
  --query 'Items[*].{id:document_id.S,status:status.S,stage:current_stage.S}'

# Ray head logs (orchestrator output)
aws logs tail /ecs/ray-document-pipeline/ray-head --follow

# Ray worker logs (stage execution output)
aws logs tail /ecs/ray-document-pipeline/ray-worker --follow
```

### Document status values

| Status | Meaning |
|---|---|
| `PENDING` | Queued by Lambda, waiting for orchestrator |
| `IN_PROGRESS` | Claimed by orchestrator, pipeline running |
| `COMPLETED` | All 5 stages done, vectors in Pinecone |
| `FAILED` | One stage failed — check logs for details |

### Re-process a failed document

```bash
aws dynamodb update-item \
  --table-name ray-document-pipeline-control \
  --key '{"document_id":{"S":"doc_xxx"},"processing_version":{"S":"v1"}}' \
  --update-expression "SET #s = :pending" \
  --expression-attribute-names '{"#s":"status"}' \
  --expression-attribute-values '{":pending":{"S":"PENDING"}}'
```

---

## Infrastructure Created by CloudFormation

| Resource | Details |
|---|---|
| VPC | `10.0.0.0/16`, single public subnet (no NAT Gateway needed) |
| ECS Cluster | Container Insights enabled |
| ECS Service: Ray Head | 1 task, `2 vCPU / 8 GB`, always FARGATE (not Spot) |
| ECS Service: Ray Workers | 1–10 tasks, `1 vCPU / 4 GB`, 80% Fargate Spot + 20% on-demand |
| S3 Bucket | `<name>-<AccountId>`, encrypted, versioned, lifecycle rules per folder |
| DynamoDB: Control Table | Pipeline state, GSI for PENDING polling, PITR enabled |
| DynamoDB: Audit Table | Full event history per document, 180-day TTL |
| DynamoDB: Metrics Table | Daily aggregates for dashboard reporting |
| Lambda | S3 → DynamoDB ingestion trigger, Python 3.12 |
| Secrets Manager | OpenAI key + Pinecone key (referenced by ARN — no plaintext) |
| VPC Endpoints | S3 + DynamoDB Gateway endpoints (free, traffic stays inside AWS) |
| CloudWatch Alarms | Ray head down, no workers running, workers at max capacity |
| SNS Topic | Email alerts when alarms trigger |
| Service Discovery | `ray-head.local` DNS — workers find head node automatically |
| Auto Scaling | CPU target 70%, memory target 80%, scale-in cooldown 5 min |

---

## S3 Folder Structure

```
s3://<bucket>/
├── input/          ← Upload PDFs here to trigger processing (auto-deleted after 180 days)
├── extracted/      ← Stage 1 output: Markdown pages + images (auto-deleted after 30 days)
├── chunks/         ← Stage 2 output: Semantic chunks JSON (auto-deleted after 30 days)
├── enriched/       ← Stage 3 output: PII-redacted + NER + key phrases (auto-deleted after 30 days)
└── embeddings/     ← Stage 4 output: 1536-dim vectors JSON (auto-deleted after 90 days)
```

---

## Cost Estimate (Teaching / Demo Setup)

### Fixed monthly costs (always running)

| Resource | Cost |
|---|---|
| Ray Head (2 vCPU / 8 GB, always on) | ~$28/month |
| 1 min worker (1 vCPU / 4 GB, Fargate Spot) | ~$8/month |
| DynamoDB (pay-per-request, light usage) | ~$1–2/month |
| S3 (10 PDFs + intermediate files) | < $1/month |
| Secrets Manager (2 secrets) | $0.80/month |
| CloudWatch Logs | ~$1/month |
| **Total fixed** | **~$40/month** |

### Per-document processing costs (OpenAI API)

| Stage | Model | Typical cost per PDF |
|---|---|---|
| Stage 1 — Image descriptions | GPT-4o | $0.01–$0.05 per image |
| Stage 3 — PII + NER + phrases | GPT-4o-mini | ~$0.002 per chunk |
| Stage 4 — Embeddings | text-embedding-3-small | ~$0.001 per doc |
| **Total per 10-page PDF** | | **~$0.10–$0.30** |

### Cost saving tips

- Set `UseFargateSpot: true` in parameters (already the default) — saves 70% on workers
- Stop the ECS services between classes: `aws ecs update-service --desired-count 0`
- Delete the stack after the course: see [Cleanup](#cleanup) below

---

## Cleanup

**Delete all AWS resources when done:**

```bash
# 1. Empty the S3 bucket first (CloudFormation cannot delete a non-empty bucket)
BUCKET=$(aws cloudformation describe-stacks \
  --stack-name ray-document-pipeline \
  --query 'Stacks[0].Outputs[?OutputKey==`S3BucketName`].OutputValue' \
  --output text)
aws s3 rm s3://$BUCKET --recursive

# 2. Delete the CloudFormation stack (deletes everything else)
aws cloudformation delete-stack --stack-name ray-document-pipeline

# 3. Wait for deletion to complete
aws cloudformation wait stack-delete-complete \
  --stack-name ray-document-pipeline

echo "Stack deleted"

# 4. (Optional) Delete Secrets Manager secrets
aws secretsmanager delete-secret \
  --secret-id ray-pipeline-openai --force-delete-without-recovery
aws secretsmanager delete-secret \
  --secret-id ray-pipeline-pinecone --force-delete-without-recovery

# 5. (Optional) Delete ECR repository
aws ecr delete-repository \
  --repository-name ray-document-pipeline-ray --force
```

---

## Troubleshooting

### Ray workers can't connect to the head node

```bash
# Check that service discovery is resolving correctly
aws servicediscovery list-services
# Expected: a service named 'ray-head' in namespace 'local'

# Check worker logs for the connection attempt
aws logs tail /ecs/ray-document-pipeline/ray-worker --follow
# Expected: "Connected to Ray cluster"
```

### Documents stuck in PENDING

```bash
# Check orchestrator is running
aws ecs list-tasks \
  --cluster ray-document-pipeline-cluster \
  --service-name ray-document-pipeline-ray-head

# Check orchestrator logs
aws logs tail /ecs/ray-document-pipeline/ray-head --follow
# Look for: "POLL #N" lines — confirms it is actively polling
```

### Documents stuck in IN_PROGRESS after a crash

The orchestrator crashed mid-pipeline. Reset the document to PENDING:

```bash
aws dynamodb update-item \
  --table-name ray-document-pipeline-control \
  --key '{"document_id":{"S":"doc_xxx"},"processing_version":{"S":"v1"}}' \
  --update-expression "SET #s = :p, retry_count = retry_count + :one" \
  --expression-attribute-names '{"#s":"status"}' \
  --expression-attribute-values '{":p":{"S":"PENDING"},":one":{"N":"1"}}'
```

### Stack creation fails

```bash
# See exactly what went wrong
aws cloudformation describe-stack-events \
  --stack-name ray-document-pipeline \
  --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`].[LogicalResourceId,ResourceStatusReason]' \
  --output table
```

Common causes: VPC limit reached (delete an unused VPC), invalid ECR image URI (re-run `check_prerequisites.py`), Secrets Manager ARN mismatch (check that `check_prerequisites.py` ran to completion).

### Auto-scaling not triggering

```bash
# Check current CPU utilisation
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ServiceName,Value=ray-document-pipeline-ray-worker \
               Name=ClusterName,Value=ray-document-pipeline-cluster \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 \
  --statistics Average
```

---

## Key Files Reference

| File | Purpose | When to edit |
|---|---|---|
| `cloudformation-parameters.json` | Stack parameters | Before first deploy — set bucket name, alert email |
| `config.py` | Runtime configuration | To change polling interval, chunk sizes, Pinecone index name |
| `ray_tasks.py` | Stage 1–5 pipeline logic | To change extraction, chunking, or enrichment behaviour |
| `ray_orchestrator.py` | Document processing loop | To change retry logic, DynamoDB schema, polling frequency |
| `s3_event_lambda.py` | S3 → DynamoDB trigger | To change how documents are named or filtered on upload |
| `check_prerequisites.py` | Pre-deploy validation | If you add new AWS services or change parameter key names |

---

## Learning Objectives

Students completing this module will be able to:

- Explain the difference between **Ray head nodes** and **worker nodes** and why the orchestrator runs on the head
- Describe why **`@ray.remote` functions** are used instead of classes in this pipeline
- Explain the **5-stage RAG pipeline** and what each stage produces
- Understand why **DynamoDB conditional updates** prevent duplicate processing in distributed systems
- Describe the **public subnet tradeoff** — lower cost vs. production security considerations
- Read and interpret **CloudFormation templates** for ECS Fargate deployments
- Use **AWS CloudWatch Logs** and **DynamoDB** to monitor a running pipeline
- Calculate approximate **API costs per document** for OpenAI models

---

## Author

**Prudhvi Akella**  
Lead Data & AI Engineer, Thoughtworks  
Instructor, Applied GenAI — Vidya Sankalp  

---

*Course: Applied GenAI | Module: Distributed RAG Pipelines with Ray on AWS ECS*
