# Deployment Guide — ECS + CloudFormation

Deploy the full Ray RAG pipeline to AWS ECS Fargate with a single CloudFormation stack.

**Total time:** ~20–25 minutes (first run) | ~5 minutes (subsequent)
**Monthly cost:** ~$10–20 for 20 documents | $0 when torn down

---

## Overview

Deployment has 3 phases, each with its own script:

| Phase | Script | Time | What It Does |
|-------|--------|------|-------------|
| **Prerequisites** | `deploy/prerequisites/check.py` | 8–12 min (first) | Validates tools, provisions secrets, builds Docker image |
| **Infrastructure** | `deploy/steps/orchestrator.py` | 10–15 min | Creates VPC, ECS, S3, DynamoDB, Lambda via CloudFormation |
| **Data** | (included in orchestrator) | 1–2 min | Downloads PDFs, uploads to S3, triggers Lambda |

---

## Phase 1: Prerequisites

Run once per AWS account. Validates your environment and provisions resources.

```bash
cd deploy/prerequisites

# macOS / Linux
python3 check.py

# Windows (recommended — includes charmap fix)
python check_windows.py
```

**What it does (10 checks):**

1. AWS CLI installed
2. AWS credentials valid
3. Default region set
4. Docker running
5. IAM permissions for 7 services
6. API keys stored in Secrets Manager ($0.80/month)
7. S3 bucket name validated
8. Docker image built and pushed to ECR (3 tags: latest, head, worker)
9. VPC quota checked
10. CloudFormation template syntax validated

**After success:** `deploy/cloudformation/cloudformation-parameters.json` is
fully populated with ECR URI and Secrets Manager ARNs.

---

## Phase 2: Deploy Infrastructure

```bash
cd deploy/steps

# Run all 3 steps automatically
python orchestrator.py

# Or run individually:
python step1_deploy_stack.py     # CloudFormation (~10-15 min)
python step2_download_pdfs.py    # Download clinical trial PDFs
python step3_upload_to_s3.py     # Upload PDFs → S3 → triggers Lambda
```

**What CloudFormation creates (30+ resources):**

- **VPC** with public subnet, Internet Gateway, VPC endpoints for S3/DynamoDB
- **ECS Cluster** with Ray Head service + auto-scaling Ray Worker service
- **S3 Bucket** with prefix structure (input/, extracted/, chunks/, etc.)
- **DynamoDB** tables (control, audit, metrics) with PAY_PER_REQUEST billing
- **Lambda** trigger: S3 event → creates PENDING record in DynamoDB
- **CloudWatch** alarms (head down, workers at capacity, stalled documents)
- **SNS** alerts to your email

See `deploy/cloudformation/EXPLAINED.md` for a detailed resource walkthrough.

---

## Phase 3: Verify

### Check Stack Status

```bash
aws cloudformation describe-stacks \
    --stack-name ray-document-pipeline \
    --query 'Stacks[0].StackStatus'
# Expected: "CREATE_COMPLETE"
```

### Check ECS Services

```bash
# Ray head should have 1 running task
aws ecs describe-services \
    --cluster ray-document-pipeline \
    --services ray-head-service \
    --query 'services[0].runningCount'

# Ray workers should have ≥1 running task
aws ecs describe-services \
    --cluster ray-document-pipeline \
    --services ray-worker-service \
    --query 'services[0].runningCount'
```

### Watch Document Processing

```bash
# DynamoDB: check document statuses
aws dynamodb scan \
    --table-name ray-document-pipeline-control \
    --projection-expression "document_id, #s, current_stage" \
    --expression-attribute-names '{"#s": "status"}'

# CloudWatch Logs: tail the orchestrator
aws logs tail /ecs/ray-document-pipeline/ray-head --follow

# CloudWatch Logs: tail a worker
aws logs tail /ecs/ray-document-pipeline/ray-worker --follow
```

### Verify Pinecone Vectors

```bash
python -c "
from pinecone import Pinecone
import os
pc = Pinecone(api_key=os.environ['PINECONE_API_KEY'])
idx = pc.Index('clinical-trials-index')
stats = idx.describe_index_stats()
print(f'Total vectors: {stats.total_vector_count}')
print(f'Namespaces: {list(stats.namespaces.keys())}')
"
```

---

## Updating the Pipeline

### Code Changes Only (No Infrastructure)

```bash
# Rebuild and push Docker image
cd deploy/prerequisites
python check.py    # Re-runs Check 8 (Docker build + ECR push)

# Force ECS to pull new image
aws ecs update-service \
    --cluster ray-document-pipeline \
    --service ray-head-service \
    --force-new-deployment

aws ecs update-service \
    --cluster ray-document-pipeline \
    --service ray-worker-service \
    --force-new-deployment
```

### Infrastructure Changes

```bash
# Edit parameters or template, then:
cd deploy/steps
python step1_deploy_stack.py   # Detects existing stack, runs update-stack
```

---

## Tear Down

```bash
# Delete the CloudFormation stack (removes all resources)
aws cloudformation delete-stack --stack-name ray-document-pipeline

# Monitor deletion (~5 min)
aws cloudformation wait stack-delete-complete \
    --stack-name ray-document-pipeline

# Optional: clean up ECR images and Secrets Manager
aws ecr delete-repository \
    --repository-name ray-document-pipeline-ray --force

aws secretsmanager delete-secret \
    --secret-id ray-pipeline-openai --force-delete-without-recovery
aws secretsmanager delete-secret \
    --secret-id ray-pipeline-pinecone --force-delete-without-recovery
```

**Important:** The S3 bucket must be empty before CloudFormation can delete it.
If deletion fails, empty the bucket first:

```bash
aws s3 rm s3://ray-ingestion-prudhvi-2026-<account-id> --recursive
```

---

## Cost Control

| Resource | Idle Cost | How to Reduce |
|----------|-----------|---------------|
| ECS Head (always on) | ~$3/month | Stop when not processing |
| ECS Workers | ~$1.50/month (min=1) | Set MinWorkers=0 in parameters |
| Secrets Manager | $0.80/month fixed | Cannot reduce |
| ECR Storage | ~$0.32/month | Delete old images |
| NAT Gateway | **$0** | Public subnet design |

**Cheapest idle state:** Set `MinWorkers=0` and stop the head service.
Cost drops to ~$1.12/month (Secrets Manager + ECR storage).

**Fargate Spot:** Set `UseFargateSpot=true` in parameters for 70% cheaper
workers (can be interrupted with 2-min warning — safe because stages are
idempotent and documents retry automatically).

---

## Troubleshooting Deployment

| Issue | Fix |
|-------|-----|
| Stack stuck in `CREATE_IN_PROGRESS` | Wait — first deploy takes 10–15 min |
| `ROLLBACK_COMPLETE` | Check CloudFormation Events tab for the failed resource |
| ECS task keeps restarting | Check CloudWatch Logs for the failing service |
| "No updates to perform" | Stack is already current — this is success |
| Workers not scaling | Check CloudWatch alarm `PendingDocumentsAlarm` |
| Documents stuck PENDING | Verify head task is running, check orchestrator logs |

For more, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
