# CloudFormation Template — Explained

## What This Stack Creates

The `1_ray-pipeline-cloudformation-public.yaml` template provisions the entire
RAG document processing infrastructure in a single deployment. It creates
**30+ AWS resources** across 8 service categories.

**Total deployment time:** ~10–15 minutes
**Monthly cost (idle):** ~$5–10 (ECS tasks + Secrets Manager)
**Monthly cost (active, 20 docs):** ~$15–30

---

## Architecture at a Glance

```
Internet
   │
   ▼
┌──────────────────────── VPC (10.0.0.0/16) ────────────────────────┐
│                                                                     │
│  ┌─────────────── Public Subnet (10.0.1.0/24) ──────────────────┐  │
│  │                                                                │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐  │  │
│  │  │  Ray Head    │  │  Ray Worker  │  │  Ray Worker (auto)   │  │  │
│  │  │  (ECS Task)  │──│  (ECS Task)  │  │  scales 1→10         │  │  │
│  │  │  Orchestrator│  │  5 Stages    │  │  based on queue      │  │  │
│  │  └──────┬───────┘  └──────────────┘  └──────────────────────┘  │  │
│  │         │                                                       │  │
│  └─────────┼───────────────────────────────────────────────────────┘  │
│            │  VPC Endpoints (free internal routing)                    │
│     ┌──────┴──────┬────────────────┐                                  │
│     ▼             ▼                ▼                                   │
│  ┌──────┐  ┌──────────┐  ┌──────────────┐                            │
│  │  S3  │  │ DynamoDB  │  │ CloudWatch   │                            │
│  │Bucket│  │ 3 Tables  │  │ Logs+Alarms  │                            │
│  └──┬───┘  └──────────┘  └──────────────┘                            │
│     │                                                                  │
│     ▼  S3 Event Notification                                          │
│  ┌──────────┐                                                         │
│  │  Lambda   │  Creates PENDING record in DynamoDB                    │
│  │  Trigger  │  when PDF lands in s3://bucket/input/                  │
│  └──────────┘                                                         │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Parameters (cloudformation-parameters.json)

| Parameter | Default | What It Controls |
|-----------|---------|-----------------|
| `VpcCIDR` | `10.0.0.0/16` | VPC IP range (65,536 addresses) |
| `PublicSubnetCIDR` | `10.0.1.0/24` | Subnet IP range (256 addresses) |
| `S3BucketName` | `ray-ingestion-prudhvi-...` | Base name; AccountId appended for uniqueness |
| `RayHeadCPU` | `2048` (2 vCPU) | Head node CPU (runs orchestrator) |
| `RayHeadMemory` | `8192` (8 GB) | Head node memory |
| `RayWorkerCPU` | `2048` (2 vCPU) | Worker node CPU (runs pipeline stages) |
| `RayWorkerMemory` | `16384` (16 GB) | Worker memory (Docling needs ~8 GB) |
| `MinWorkers` | `1` | Minimum Ray workers always running |
| `MaxWorkers` | `10` | Maximum workers during scale-out |
| `ECRImageUri` | `<account>.dkr.ecr...` | Docker image URI (set by prerequisites check) |
| `OpenAISecretArn` | `arn:aws:secretsmanager:...` | Secrets Manager ARN for OpenAI key |
| `PineconeSecretArn` | `arn:aws:secretsmanager:...` | Secrets Manager ARN for Pinecone key |
| `AlertEmail` | (your email) | SNS alerts for pipeline issues |
| `Environment` | `production` | Tag for resource identification |
| `UseFargateSpot` | `false` | Enable Fargate Spot (70% cheaper, can be interrupted) |

---

## Resources Breakdown

### 1. Networking (VPC)

**Resources:** VPC, InternetGateway, PublicSubnet, RouteTable, SecurityGroup

**Why public subnet instead of private + NAT?**
A NAT Gateway costs ~$32/month just to exist. For a teaching/demo environment
processing 10–20 documents, that's unnecessary. ECS tasks get public IPs
directly via the Internet Gateway. This is the entire networking cost: **$0**.

**VPC Endpoints** for S3 and DynamoDB route traffic internally — these calls
never leave the AWS network, so there are no data transfer charges.

The **Security Group** allows all traffic within the cluster (Ray nodes need
to communicate freely) and exposes port 8265 for the Ray Dashboard.

### 2. Storage (S3)

**Resources:** DocumentBucket, DocumentBucketPolicy

The bucket stores all pipeline artifacts in a structured prefix layout:

```
s3://bucket/
├── input/           ← PDFs uploaded here (triggers Lambda)
├── extracted/       ← Stage 1: Markdown pages, tables, images
├── chunks/          ← Stage 2: Semantic chunks JSON
├── enriched/        ← Stage 3: Enriched chunks with NER/PII
├── embeddings/      ← Stage 4: Vectors JSON (1536-dim)
└── pipeline-logs/   ← Processing metadata and audit trails
```

**Bucket Policy** enforces TLS (HTTPS-only access) — rejects any `s3:*`
call that arrives over plain HTTP.

### 3. Database (DynamoDB)

**Resources:** ControlTable, AuditTable, MetricsTable

Three tables with distinct purposes:

| Table | Pattern | Purpose |
|-------|---------|---------|
| **Control** | 1 record per document | Current status (PENDING → IN_PROGRESS → COMPLETED/FAILED). GSI on `status + updated_at` for the orchestrator's polling query. |
| **Audit** | Append-only, many per document | Immutable history of every status transition. 180-day TTL auto-deletes old records. |
| **Metrics** | Aggregated stats | Processing times, costs, error rates for dashboards. |

All tables use **PAY_PER_REQUEST** billing — you pay per read/write with no
minimum. For 20 documents, the cost is effectively $0.

### 4. Compute (ECS Fargate)

**Resources:** ECSCluster, RayHeadTaskDefinition, RayWorkerTaskDefinition,
RayHeadService, RayWorkerService, CapacityProviders

Two ECS services run the Ray cluster:

**Ray Head** (1 task, always running):
- Runs `ray start --head` + the orchestrator polling loop
- 2 vCPU / 8 GB memory
- Polls DynamoDB for PENDING documents
- Submits `@ray.remote` tasks to workers

**Ray Workers** (1–10 tasks, auto-scaled):
- Run `ray start --address=ray-head.local:6379`
- 2 vCPU / 16 GB memory (Docling extraction needs ~8 GB)
- Execute the 5 pipeline stages as Ray remote functions
- Scale out when documents are queued, scale in when idle

**Service Discovery** uses AWS Cloud Map (`ray-head.local`) so workers
can find the head node by DNS name instead of IP address.

### 5. Serverless (Lambda)

**Resources:** S3EventLambda, S3TriggerLambdaPermission, S3NotificationCustomResource

When a PDF lands in `s3://bucket/input/`, S3 fires an event notification.
The Lambda function creates a PENDING record in the DynamoDB Control table.
The orchestrator picks it up on its next polling cycle.

The **Custom Resource** is needed because CloudFormation can't natively
configure S3 event notifications on a bucket it creates in the same stack
(circular dependency). The custom resource Lambda runs once during stack
creation to wire up the S3 → Lambda trigger.

### 6. IAM (Roles & Policies)

**Resources:** ECSTaskExecutionRole, ECSTaskRole, S3EventLambdaRole,
S3NotificationCustomResourceRole

| Role | Who Uses It | What It Can Do |
|------|-------------|----------------|
| **TaskExecutionRole** | ECS agent | Pull images from ECR, read Secrets Manager, write CloudWatch Logs |
| **TaskRole** | Application code | Full S3 access, DynamoDB read/write, Secrets Manager read |
| **LambdaRole** | S3 event Lambda | DynamoDB write (create PENDING record), CloudWatch Logs |
| **CustomResourceRole** | Setup Lambda | Configure S3 bucket notifications (runs once) |

### 7. Monitoring (CloudWatch + SNS)

**Resources:** LogGroups, Alarms (5), AlertTopic, MetricPublisherLambda, EventsRule

**Log Groups:** Separate streams for Ray Head and Ray Workers — easy to filter
in CloudWatch Logs console.

**Alarms** (sent to SNS → email):

| Alarm | Triggers When |
|-------|---------------|
| **HeadServiceDown** | Ray head has 0 running tasks |
| **PendingButNoWorkers** | Documents pending but no workers processing |
| **LongPendingDocuments** | Documents stuck PENDING for 30+ minutes |
| **WorkersAtCapacity** | Workers at max count (may need to increase MaxWorkers) |
| **ScaleOut** | Documents queued → add workers |

The **MetricPublisherLambda** runs every 60 seconds (EventBridge rule),
queries DynamoDB for PENDING document count, and publishes it as a
CloudWatch custom metric. This metric drives the auto-scaling alarms.

### 8. Auto-Scaling

**Resources:** ScalableTarget, ScaleOutPolicy, ScaleInPolicy

Worker count scales between `MinWorkers` and `MaxWorkers` based on
CloudWatch alarms:

- **Scale out:** PENDING documents detected → add 1 worker (cooldown: 120s)
- **Scale in:** Queue empty for 5 consecutive minutes → remove 1 worker (cooldown: 300s)

The asymmetric cooldowns are intentional: scale out fast (don't let
documents wait), scale in slow (avoid thrashing if new documents arrive).

---

## Cost Summary

| Resource | Idle Cost | Active Cost (20 docs) |
|----------|-----------|----------------------|
| ECS Fargate (head) | ~$3/month | ~$3/month |
| ECS Fargate (workers) | ~$1.50/month (1 min worker) | ~$5–15/month |
| S3 | < $0.10/month | < $0.50/month |
| DynamoDB | $0 (PAY_PER_REQUEST) | < $0.01 |
| Secrets Manager | $0.80/month (2 secrets) | $0.80/month |
| CloudWatch Logs | < $0.50/month | < $1/month |
| Lambda | $0 (free tier) | $0 |
| NAT Gateway | **$0** (public subnet) | **$0** |
| **Total** | **~$5–6/month** | **~$10–20/month** |

---

## Deployment Commands

```bash
# From deploy/steps/
python orchestrator.py          # Runs all 3 steps

# Or individually:
python step1_deploy_stack.py    # Create/update CloudFormation stack
python step2_download_pdfs.py   # Download clinical trial PDFs
python step3_upload_to_s3.py    # Upload PDFs → S3 → Lambda → DynamoDB

# Monitor:
aws cloudformation describe-stacks --stack-name ray-document-pipeline \
    --query 'Stacks[0].StackStatus'

# Tear down:
aws cloudformation delete-stack --stack-name ray-document-pipeline
```

---

## Common Modifications

**Change region:** Update `REGION` in step1/step2/step3 and re-run prerequisites.

**Increase worker memory:** Edit `RayWorkerMemory` in parameters.json. Valid
Fargate values: 8192, 16384, 30720 (MB).

**Enable Fargate Spot:** Set `UseFargateSpot` to `true` in parameters.json.
Workers run at 70% discount but can be interrupted with 2-minute warning.
Head node always uses on-demand (never interrupted).

**Add private subnet + NAT:** For production with sensitive data, add a private
subnet, NAT Gateway, and move ECS tasks to the private subnet. Cost: +$32/month.
