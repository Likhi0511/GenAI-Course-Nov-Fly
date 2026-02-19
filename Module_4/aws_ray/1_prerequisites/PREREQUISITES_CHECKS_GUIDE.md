# Ray Document Pipeline — Prerequisites Checks Guide

**Complete documentation of all 10 prerequisite checks performed before CloudFormation deployment**

---

## Table of Contents

1. [Overview](#overview)
2. [Check Details](#check-details)
   - [Check 1: AWS CLI](#check-1-aws-cli)
   - [Check 2: AWS Credentials](#check-2-aws-credentials)
   - [Check 3: AWS Region](#check-3-aws-region)
   - [Check 4: Docker](#check-4-docker)
   - [Check 5: AWS Permissions](#check-5-aws-permissions)
   - [Check 6: API Keys → Secrets Manager](#check-6-api-keys--secrets-manager)
   - [Check 7: S3 Bucket Name](#check-7-s3-bucket-name)
   - [Check 8: Docker Image Build & Push](#check-8-docker-image-build--push)
   - [Check 9: AWS Service Quotas](#check-9-aws-service-quotas)
   - [Check 10: CloudFormation Template Validation](#check-10-cloudformation-template-validation)
3. [Common Issues & Fixes](#common-issues--fixes)
4. [Cost Implications](#cost-implications)
5. [Advanced Configuration](#advanced-configuration)

---

## Overview

The `check_prerequisites.py` script performs **10 comprehensive checks** to ensure your AWS environment is ready for deploying the Ray Document Processing Pipeline. These checks prevent common deployment failures and save time by catching issues early.

### What Gets Validated

| Category | Checks | Purpose |
|----------|--------|---------|
| **Local Environment** | AWS CLI, Docker, Python | Ensure tools are installed |
| **AWS Authentication** | Credentials, Region, Permissions | Verify access to AWS services |
| **Resource Provisioning** | Secrets Manager, ECR, S3 | Auto-create required resources |
| **Capacity Planning** | Service Quotas, Template Validation | Prevent deployment failures |

### Execution Time

- **First run**: 8-12 minutes (includes Docker build + ECR push)
- **Subsequent runs**: 1-2 minutes (Docker layers cached)

---

## Check Details

### Check 1: AWS CLI

**What it checks**: Verifies AWS Command Line Interface is installed and accessible

**Requirements**:
- AWS CLI version 2.x or higher
- Available in system PATH

**Validation method**:
```bash
aws --version
```

**Expected output**:
```
aws-cli/2.x.x Python/3.x.x Darwin/23.x.x
```

**Common failures**:

| Issue | Fix |
|-------|-----|
| `aws: command not found` | Install AWS CLI from [official docs](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) |
| Version 1.x detected | Upgrade to CLI v2 for latest features |

**Platform-specific installation**:

```bash
# macOS
brew install awscli

# Linux (apt)
sudo apt install awscli

# Linux (yum)
sudo yum install awscli

# Windows
# Download .msi installer from AWS documentation
```

---

### Check 2: AWS Credentials

**What it checks**: Validates AWS access credentials are configured and active

**Requirements**:
- Valid AWS Access Key ID
- Valid AWS Secret Access Key
- Credentials have not expired
- IAM user/role has active permissions

**Validation method**:
```bash
aws sts get-caller-identity
```

**Expected output**:
```json
{
  "UserId": "AIDAI...",
  "Account": "123456789012",
  "Arn": "arn:aws:iam::123456789012:user/your-username"
}
```

**Information captured**:
- AWS Account ID (used for ECR image tagging)
- IAM identity ARN (logged for audit purposes)

**Common failures**:

| Issue | Fix |
|-------|-----|
| `Unable to locate credentials` | Run `aws configure` and enter credentials |
| `The security token is expired` | Refresh credentials (SSO: `aws sso login`) |
| `Access Denied` | Verify IAM user has required permissions |

**Configuration**:
```bash
aws configure
# Enter:
# - AWS Access Key ID
# - AWS Secret Access Key  
# - Default region (e.g., us-east-1)
# - Default output format (json recommended)
```

**Credential locations** (checked in order):
1. Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
2. AWS credentials file (`~/.aws/credentials`)
3. AWS config file (`~/.aws/config`)
4. IAM role (if running on EC2/ECS)

---

### Check 3: AWS Region

**What it checks**: Verifies AWS region is configured and valid

**Requirements**:
- Region must be set (not defaulting to None)
- Region must be a valid AWS region identifier

**Validation method**:
```bash
aws configure get region
```

**Expected output**:
```
us-east-1
```

**Supported regions** (for this pipeline):
- `us-east-1` (N. Virginia) — Default, recommended
- `us-west-2` (Oregon)
- `eu-west-1` (Ireland)
- Any region supporting ECS Fargate + ECR

**Common failures**:

| Issue | Fix |
|-------|-----|
| No region configured | Run `aws configure` and set default region |
| Invalid region code | Use standard region identifier (e.g., `us-east-1`) |

**Region considerations**:
- **Latency**: Choose region closest to your data sources
- **Pricing**: Fargate pricing varies by region (~10% difference)
- **Availability**: Not all regions support all EC2 instance types

---

### Check 4: Docker

**What it checks**: Ensures Docker is installed, running, and accessible

**Requirements**:
- Docker Engine installed (20.10.x or higher)
- Docker daemon is running
- Current user has Docker permissions (no `sudo` required)

**Validation method**:
```bash
docker --version
docker info
```

**Expected output**:
```
Docker version 24.x.x, build xxxxx
Server: Docker Engine - Community
```

**Common failures**:

| Issue | Fix |
|-------|-----|
| `docker: command not found` | Install Docker Desktop or Docker Engine |
| `Cannot connect to Docker daemon` | Start Docker Desktop / `sudo systemctl start docker` |
| `permission denied` | Add user to `docker` group: `sudo usermod -aG docker $USER` |

**Platform-specific setup**:

```bash
# macOS
# Install Docker Desktop from docker.com
# Launch Docker Desktop app

# Linux
sudo apt install docker.io
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER
# Log out and back in

# Windows
# Install Docker Desktop (WSL2 backend recommended)
```

**Docker daemon verification**:
```bash
docker ps  # Should list running containers (or empty list)
docker images  # Should list local images
```

---

### Check 5: AWS Permissions

**What it checks**: Validates IAM permissions for 7 required AWS services

**Services verified**:
1. **CloudFormation** — Stack creation/updates
2. **ECR** — Docker image registry
3. **ECS** — Fargate task management
4. **S3** — Document storage
5. **DynamoDB** — Metadata storage
6. **Secrets Manager** — API key storage
7. **Lambda** — Optional processing functions

**Validation method**:
```bash
# For each service, runs a read-only operation:
aws cloudformation list-stacks --max-results 1
aws ecr describe-repositories --max-results 1
aws ecs list-clusters --max-results 1
aws s3 ls
aws dynamodb list-tables --max-results 1
aws secretsmanager list-secrets --max-results 1
aws lambda list-functions --max-results 1
```

**Required IAM permissions**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "cloudformation:*",
        "ecr:*",
        "ecs:*",
        "s3:*",
        "dynamodb:*",
        "secretsmanager:*",
        "lambda:*",
        "ec2:Describe*",
        "ec2:CreateVpc",
        "ec2:CreateSubnet",
        "ec2:CreateInternetGateway",
        "ec2:CreateNatGateway",
        "ec2:AllocateAddress",
        "iam:CreateRole",
        "iam:AttachRolePolicy",
        "iam:PassRole",
        "logs:*"
      ],
      "Resource": "*"
    }
  ]
}
```

**Common failures**:

| Issue | Fix |
|-------|-----|
| `Access Denied` on multiple services | Attach `PowerUserAccess` policy to IAM user |
| `Access Denied` on specific service | Add missing permissions to IAM policy |
| IAM PassRole error | Add `iam:PassRole` permission |

**Minimal policy** (least privilege):
- See the full IAM policy printed by the script on permission failures
- Recommended: Use AWS managed policy `PowerUserAccess` for POC/dev

---

### Check 6: API Keys → Secrets Manager

**What it checks**: Provisions OpenAI and Pinecone API keys in AWS Secrets Manager

**Requirements**:
- `OPENAI_API_KEY` environment variable set
- `PINECONE_API_KEY` environment variable set
- Secrets Manager write permissions

**What it does**:
1. **Checks** if secrets already exist in AWS Secrets Manager
2. **Reads** API keys from local environment variables
3. **Creates** secrets in Secrets Manager if missing
4. **Validates** secret ARNs are accessible
5. **Writes** secret ARNs to `cloudformation-parameters.json`

**Validation method**:
```bash
aws secretsmanager describe-secret \
  --secret-id ray-pipeline-openai
  
aws secretsmanager describe-secret \
  --secret-id ray-pipeline-pinecone
```

**Created secrets**:

| Secret Name | Environment Variable | Used For |
|-------------|---------------------|----------|
| `ray-pipeline-openai` | `OPENAI_API_KEY` | GPT-4 Vision, embeddings |
| `ray-pipeline-pinecone` | `PINECONE_API_KEY` | Vector database storage |

**Setting environment variables**:

```bash
# macOS/Linux - Add to ~/.bashrc or ~/.zshrc
export OPENAI_API_KEY="sk-..."
export PINECONE_API_KEY="pk-..."

# Windows PowerShell
$env:OPENAI_API_KEY="sk-..."
$env:PINECONE_API_KEY="pk-..."

# Windows CMD
set OPENAI_API_KEY=sk-...
set PINECONE_API_KEY=pk-...
```

**Common failures**:

| Issue | Fix |
|-------|-----|
| Environment variables not set | Export keys in terminal before running script |
| Invalid API key format | Verify key starts with `sk-` (OpenAI) or correct format |
| Secrets Manager quota exceeded | Delete old unused secrets |
| Secret already exists with different value | Script will preserve existing value |

**Security notes**:
- Secrets are encrypted at rest with AWS KMS
- CloudFormation references secrets via ARN (no plaintext in template)
- Secrets are injected into ECS tasks as environment variables at runtime

**Cost**: $0.40/month per secret (first 30 days free)

---

### Check 7: S3 Bucket Name

**What it checks**: Validates S3 bucket name is configured in CloudFormation parameters

**Requirements**:
- Bucket name must be globally unique across all AWS accounts
- Must follow S3 naming rules:
  - 3-63 characters
  - Lowercase letters, numbers, hyphens only
  - No underscores, spaces, or uppercase
  - Must start with letter or number

**What it does**:
1. **Reads** `cloudformation-parameters.json`
2. **Checks** if `S3BucketName` is still the placeholder value
3. **Validates** naming rules if custom name provided
4. **Does NOT create** the bucket (CloudFormation will create it)

**Validation method**:
```python
# Checks parameter file for placeholder
if bucket_name == "your-unique-bucket-name-here":
    FAIL
```

**Example valid names**:
```
ray-pipeline-prudhvi-2026
document-pipeline-prod-us-east-1
my-company-ray-docs-feb18
```

**Example invalid names**:
```
Ray_Pipeline_Bucket          # Contains uppercase and underscores
my bucket name               # Contains spaces
prudhvi@company.com          # Contains @ symbol
ab                           # Too short (<3 chars)
```

**How to fix**:

```bash
# Edit cloudformation-parameters.json
{
  "Parameters": {
    "S3BucketName": "ray-pipeline-prudhvi-2026"  # Change this
  }
}
```

**Common failures**:

| Issue | Fix |
|-------|-----|
| Still using placeholder | Edit parameters file with unique name |
| Name already taken globally | Try different name with timestamp/region |
| Invalid characters | Use only lowercase, numbers, hyphens |

**Naming strategy**:
```
{project}-{owner}-{environment}-{region}-{date}

Examples:
ray-pipeline-prudhvi-dev-useast1-feb2026
doc-processing-acmecorp-prod-20260218
```

---

### Check 8: Docker Image Build & Push

**What it checks**: Builds Ray pipeline Docker image and pushes to ECR

**What it does**:
1. **Creates** ECR repository (if doesn't exist)
2. **Authenticates** Docker to ECR
3. **Builds** Docker image for `linux/amd64` platform
4. **Tags** image with 3 tags: `latest`, `head`, `worker`
5. **Pushes** all tags to ECR
6. **Updates** `cloudformation-parameters.json` with ECR URI

**Build details**:

```dockerfile
Base image:  rayproject/ray:2.53.0-py312
Python:      3.12
Platform:    linux/amd64 (required for ECS Fargate)
Size:        ~3.2 GB (includes PyTorch + CUDA libraries)
Build time:  4-8 minutes (first build)
             30-60 seconds (cached rebuild)
```

**Created tags**:

| Tag | Purpose | Used By |
|-----|---------|---------|
| `latest` | Default reference | CloudFormation parameter |
| `head` | Ray head node | ECS task definition |
| `worker` | Ray worker nodes | ECS task definition |

**Build process**:

```bash
# 1. Create/verify ECR repo
aws ecr create-repository --repository-name ray-document-pipeline-ray

# 2. Authenticate Docker to ECR
aws ecr get-login-password | docker login --username AWS --password-stdin

# 3. Build image
docker buildx build --platform linux/amd64 \
  -t ray-document-pipeline-ray:latest \
  3_deployment/

# 4. Tag for ECR
docker tag ray-document-pipeline-ray:latest \
  {account}.dkr.ecr.{region}.amazonaws.com/ray-document-pipeline-ray:latest

# 5. Push to ECR (3 tags)
docker push {ecr_uri}:latest
docker push {ecr_uri}:head
docker push {ecr_uri}:worker
```

**Common failures**:

| Issue | Fix |
|-------|-----|
| Docker daemon not running | Start Docker Desktop |
| Platform mismatch (ARM Mac) | Script auto-detects and uses `--platform linux/amd64` |
| ECR authentication expired | Re-run script (auto-authenticates) |
| Disk space full | Free up 5GB, prune old images: `docker system prune -a` |
| Network timeout during push | Check internet connection, retry |

**Performance notes**:
- First build downloads 915MB PyTorch + dependencies
- Subsequent builds reuse cached layers (much faster)
- ECR push uploads ~3.2GB (takes 3-5 minutes on typical connection)

**Cost implications**:
- ECR storage: $0.10/GB-month = ~$0.32/month for 3.2GB image
- Data transfer: First 100GB/month free (outbound to internet)
- No charge for data transfer to ECS Fargate in same region

---

### Check 9: AWS Service Quotas

**What it checks**: Validates AWS account has capacity for CloudFormation resource creation

**What it does**:
1. **Checks VPC quota** — CloudFormation creates a new VPC
2. **Checks Elastic IP quota** — NAT Gateway requires 1 EIP
3. **Informs about ECS task quota** — For large Ray clusters

**Quota validation**:

```bash
# VPC count
aws ec2 describe-vpcs --query "Vpcs[*].VpcId"

# Elastic IP count
aws ec2 describe-addresses --query "Addresses[*].PublicIp"
```

**Default AWS quotas**:

| Resource | Default Limit | Used By | Impact if Exceeded |
|----------|---------------|---------|-------------------|
| VPCs per region | 5 | CloudFormation creates 1 VPC | Stack creation fails |
| Elastic IPs per region | 5 | NAT Gateway needs 1 EIP | NAT Gateway creation fails |
| ECS tasks per service | 500 | Ray worker scaling | Cannot scale beyond limit |
| Fargate vCPUs | 2000 | Ray cluster size | Cannot launch new tasks |

**Check results**:

✅ **PASS**: Below quota limits
```
[PASS] VPC quota OK: 2/5 used
[PASS] Elastic IP quota OK: 1/5 used (NAT needs 1)
```

❌ **FAIL**: At or near quota limit
```
[FAIL] VPC limit reached: 5/5 VPCs in us-east-1
[FIX ] CloudFormation will create a new VPC and may fail
[FIX ] Delete unused VPCs or request limit increase
```

**Common failures**:

| Issue | Fix |
|-------|-----|
| 5/5 VPCs used | Delete unused VPCs in AWS Console → VPC Dashboard |
| 5/5 Elastic IPs used | Release unattached EIPs in EC2 Console |
| Need higher limits | Request quota increase via Service Quotas console |

**How to request quota increases**:

1. Go to [AWS Service Quotas Console](https://console.aws.amazon.com/servicequotas/)
2. Select service (VPC, EC2, ECS)
3. Find quota (e.g., "VPCs per Region")
4. Click "Request quota increase"
5. Enter new limit (typically 2x current)
6. Submit (approval takes 1-2 business days)

**Quota increase links**:
- VPCs: https://console.aws.amazon.com/servicequotas/home/services/vpc/quotas
- Elastic IPs: https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas/L-0263D0A3
- ECS Tasks: https://console.aws.amazon.com/servicequotas/home/services/ecs/quotas

**Why this matters**:
- CloudFormation fails silently if quotas exceeded
- Saves 20 minutes waiting for failed stack creation
- Prevents partial resource creation (cleanup required)

---

### Check 10: CloudFormation Template Validation

**What it checks**: Validates CloudFormation template syntax before deployment

**What it does**:
1. **Locates** template file: `2_cloudformation/ray-pipeline-cloudformation.yaml`
2. **Runs** AWS CloudFormation validation
3. **Reports** syntax errors, parameter issues, or invalid references
4. **Shows** required IAM capabilities

**Validation method**:
```bash
aws cloudformation validate-template \
  --template-body file://ray-pipeline-cloudformation.yaml
```

**What gets validated**:

| Validation Type | Checks For |
|-----------------|------------|
| **Syntax** | Valid YAML/JSON structure |
| **Resources** | Valid resource types and properties |
| **Parameters** | Correct parameter definitions |
| **References** | Valid `!Ref` and `!GetAtt` |
| **Outputs** | Valid output definitions |
| **Capabilities** | Required IAM permissions |

**Success output**:
```
[PASS] Template syntax valid
[INFO] Template has 12 parameters
[INFO] Requires capabilities: CAPABILITY_IAM
```

**Common failures**:

| Issue | Fix |
|-------|-----|
| YAML syntax error | Check indentation, colons, quotes |
| Invalid resource type | Verify resource type exists in AWS |
| Invalid property | Check CloudFormation resource documentation |
| Unresolved reference | Ensure referenced resource exists in template |
| Missing parameter | Add required parameter to template |

**Example validation errors**:

```yaml
# ❌ Invalid YAML
Resources:
  MyBucket
    Type: AWS::S3::Bucket  # Missing colon after MyBucket

# ✅ Valid YAML  
Resources:
  MyBucket:
    Type: AWS::S3::Bucket
```

```yaml
# ❌ Invalid reference
Properties:
  VpcId: !Ref MyVPC  # MyVPC doesn't exist

# ✅ Valid reference
Resources:
  MyVPC:
    Type: AWS::EC2::VPC
  MySubnet:
    Properties:
      VpcId: !Ref MyVPC  # MyVPC defined above
```

**Why this matters**:
- Catches template bugs in 2 seconds
- Prevents 20-minute failed CloudFormation deployments
- Saves AWS CloudFormation API calls (rate limited)
- Identifies missing IAM capabilities before deployment

**What validation does NOT catch**:
- ❌ Resource quota limits (use Check 9)
- ❌ Parameter value validity (e.g., invalid CIDR block)
- ❌ Cross-stack references that don't exist
- ❌ IAM permission issues (use Check 5)

**Template structure** (for reference):
```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: Ray Document Processing Pipeline

Parameters:     # User inputs
  S3BucketName:
    Type: String
  
Resources:      # AWS resources to create
  VPC:
    Type: AWS::EC2::VPC
  
Outputs:        # Values to export
  VPCId:
    Value: !Ref VPC
```

---

## Common Issues & Fixes

### Issue: "Docker build fails with platform mismatch"

**Symptom**:
```
WARNING: The requested image's platform (linux/amd64) 
does not match the detected host platform (linux/arm64/v8)
```

**Root cause**: Building on Apple Silicon (M1/M2/M3) Mac

**Fix**: Script auto-detects and uses `--platform linux/amd64` flag

**Manual verification**:
```bash
docker buildx build --platform linux/amd64 .
```

---

### Issue: "ECR push hangs at 'Waiting'"

**Symptom**:
```
0b9a666cf5d5: Waiting
6fa06ccd11d2: Waiting
a078dcb0fee4: Waiting
```

**Root cause**: Pushing 3.2GB image over slow internet connection

**Fix**: 
1. **Be patient** — upload takes 3-10 minutes depending on connection
2. Check upload progress: each layer shows "Pushed" when complete
3. If truly stuck (>15 min), Ctrl+C and re-run script

**Progress indicators**:
```
0b9a666cf5d5: Pushed      # ✅ Complete
6fa06ccd11d2: Pushing     # 🔄 In progress  
a078dcb0fee4: Waiting     # ⏳ Queued
```

---

### Issue: "S3 bucket name already taken"

**Symptom**:
```
[FAIL] Bucket name 'my-bucket' already exists globally
```

**Root cause**: S3 bucket names are globally unique across ALL AWS accounts

**Fix**: Choose a more unique name with timestamp/identifier
```
my-bucket                          # ❌ Too generic
ray-pipeline-prudhvi-feb2026       # ✅ Unique
doc-processing-acmecorp-20260218   # ✅ Unique
```

---

### Issue: "VPC quota exceeded"

**Symptom**:
```
[FAIL] VPC limit reached: 5/5 VPCs in us-east-1
```

**Root cause**: AWS default limit is 5 VPCs per region

**Fix Option 1** — Delete unused VPCs:
```bash
# List VPCs
aws ec2 describe-vpcs --query "Vpcs[*].[VpcId,Tags[?Key=='Name'].Value|[0]]"

# Delete unused VPC (remove dependencies first)
aws ec2 delete-vpc --vpc-id vpc-xxxxx
```

**Fix Option 2** — Request quota increase:
1. AWS Console → Service Quotas
2. Search "VPC"
3. Request increase to 10-20 VPCs

---

### Issue: "Permission denied while connecting to Docker daemon"

**Symptom**:
```
permission denied while trying to connect to the Docker daemon socket
```

**Root cause**: User not in `docker` group (Linux)

**Fix**:
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Log out and back in (or reboot)
newgrp docker

# Verify
docker ps
```

---

### Issue: "Secrets Manager quota exceeded"

**Symptom**:
```
LimitExceededException: You have reached the maximum number of secrets
```

**Root cause**: Default limit is 500 secrets per region

**Fix**:
```bash
# List secrets
aws secretsmanager list-secrets --query "SecretList[*].Name"

# Delete unused secrets
aws secretsmanager delete-secret --secret-id old-secret --force-delete-without-recovery
```

---

## Cost Implications

### Infrastructure Costs (Monthly)

| Resource | Unit Cost | This Pipeline | Monthly Cost |
|----------|-----------|---------------|--------------|
| **ECR Storage** | $0.10/GB-month | 3.2 GB image | $0.32 |
| **Secrets Manager** | $0.40/secret | 2 secrets | $0.80 |
| **S3 Storage** | $0.023/GB-month | Varies | $0.50 - $50 |
| **DynamoDB** | Free tier 25 GB | <1 GB | $0.00 |
| **CloudWatch Logs** | $0.50/GB ingested | 1-5 GB/month | $0.50 - $2.50 |
| | | **Subtotal** | **~$2-54/month** |

### Runtime Costs (Pay-per-use)

| Resource | Unit Cost | Usage Pattern | Estimated Cost |
|----------|-----------|---------------|----------------|
| **ECS Fargate (Head)** | $0.04048/vCPU-hour<br>$0.004445/GB-hour | 2 vCPU, 4GB RAM<br>24/7 | ~$32/month |
| **ECS Fargate (Workers)** | $0.04048/vCPU-hour<br>$0.004445/GB-hour | 4 vCPU, 8GB RAM<br>On-demand | $0.18/hour<br>$130/month (24/7) |
| **NAT Gateway** | $0.045/hour<br>$0.045/GB processed | 24/7 operation | ~$32/month + data transfer |
| **Data Transfer** | $0.09/GB (out to internet) | 100GB/month | $9.00 |

### Cost Optimization Tips

**Development/POC**:
- ✅ Stop Ray cluster when not in use (saves $32/month)
- ✅ Use on-demand workers (only pay when processing)
- ✅ Set CloudWatch log retention to 7 days
- ✅ Enable S3 lifecycle policies (delete old processed docs)

**Production**:
- ✅ Use Fargate Spot for workers (70% discount)
- ✅ Enable S3 Intelligent-Tiering
- ✅ Use VPC endpoints (avoid NAT Gateway data charges)
- ✅ Implement auto-scaling based on queue depth

**Estimated Total Costs**:
- **POC (on-demand, 8 hours/day)**: $15-20/month
- **Dev (always-on, low volume)**: $70-100/month
- **Production (auto-scaled)**: $200-500/month

---

## Advanced Configuration

### Multi-Region Deployment

To deploy in multiple regions:

1. **Run prerequisites in each region**:
```bash
export AWS_DEFAULT_REGION=us-west-2
python check_prerequisites.py

export AWS_DEFAULT_REGION=eu-west-1  
python check_prerequisites.py
```

2. **Use region-specific parameter files**:
```
cloudformation-parameters-us-east-1.json
cloudformation-parameters-us-west-2.json
cloudformation-parameters-eu-west-1.json
```

3. **Replicate Docker image**:
```bash
# Pull from source region
docker pull 123456789012.dkr.ecr.us-east-1.amazonaws.com/ray-pipeline:latest

# Tag for destination region
docker tag 123456789012.dkr.ecr.us-east-1.amazonaws.com/ray-pipeline:latest \
           123456789012.dkr.ecr.eu-west-1.amazonaws.com/ray-pipeline:latest

# Push to destination
docker push 123456789012.dkr.ecr.eu-west-1.amazonaws.com/ray-pipeline:latest
```

### Custom Docker Image Optimization

**Reduce image size** (3.2GB → 800MB):

1. **Remove PyTorch/CUDA** (if not using GPU):
```dockerfile
# Install docling without ML dependencies
RUN pip install --no-deps docling && \
    pip install docling-core docling-parse pypdfium2
```

2. **Use multi-stage build**:
```dockerfile
FROM python:3.12-slim as builder
RUN pip install --user ray boto3 openai pinecone

FROM python:3.12-slim
COPY --from=builder /root/.local /root/.local
```

3. **Minimize layers**:
```dockerfile
RUN apt-get update && apt-get install -y \
    poppler-utils && \
    rm -rf /var/lib/apt/lists/*
```

### Environment-Specific Secrets

**Use different API keys per environment**:

```bash
# Development
export OPENAI_API_KEY="sk-dev-..."
export PINECONE_API_KEY="pk-dev-..."
python check_prerequisites.py  # Creates dev secrets

# Production  
export OPENAI_API_KEY="sk-prod-..."
export PINECONE_API_KEY="pk-prod-..."
# Manually create with different names:
aws secretsmanager create-secret \
  --name ray-pipeline-openai-prod \
  --secret-string "$OPENAI_API_KEY"
```

### CI/CD Integration

**Run prerequisites in GitHub Actions**:

```yaml
name: Deploy Ray Pipeline
on: [push]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1
      
      - name: Run prerequisites
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          PINECONE_API_KEY: ${{ secrets.PINECONE_API_KEY }}
        run: python 1_prerequisites/check_prerequisites.py
      
      - name: Deploy CloudFormation
        run: |
          aws cloudformation deploy \
            --template-file 2_cloudformation/ray-pipeline-cloudformation.yaml \
            --stack-name ray-pipeline-prod \
            --parameter-overrides file://2_cloudformation/cloudformation-parameters.json
```

---

## Summary

The prerequisite checks ensure:

✅ **Local environment** ready (AWS CLI, Docker)  
✅ **AWS access** configured (credentials, permissions)  
✅ **Resources provisioned** (ECR, Secrets Manager)  
✅ **Capacity available** (VPC quota, EIP quota)  
✅ **Template validated** (syntax, resources, parameters)  

**Total time**: 8-12 minutes first run, 1-2 minutes subsequent runs

**Next step**: Deploy CloudFormation stack  
**Guide**: See `2_cloudformation/CLOUDFORMATION_DEPLOYMENT_GUIDE.md`

---

**Last updated**: February 18, 2026  
**Version**: 1.0.0  
**Checks**: 10 comprehensive validations
