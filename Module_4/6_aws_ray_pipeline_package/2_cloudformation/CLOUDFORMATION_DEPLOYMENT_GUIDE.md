# CloudFormation Deployment Guide
## Deploy Ray Pipeline Infrastructure with One Command

**Author:** Prudhvi  
**Organization:** Thoughtworks  
**Date:** February 2025

---

## Overview

This CloudFormation template creates **all AWS resources** needed for the Ray Document Processing Pipeline in a single deployment:

### Resources Created (40+ resources)

✅ **Networking** (10 resources)
- VPC with public and private subnets
- Internet Gateway
- NAT Gateway with Elastic IP
- Route tables and associations
- Security groups for Ray cluster

✅ **Storage** (1 resource)
- S3 bucket with lifecycle policies
- Folder structure auto-created
- Event notifications configured

✅ **Database** (3 resources)
- DynamoDB control table with GSIs
- DynamoDB audit table
- DynamoDB metrics table
- TTL and point-in-time recovery enabled

✅ **Compute** (8+ resources)
- ECS Fargate cluster
- Ray head task definition
- Ray worker task definition
- CloudWatch log groups
- Auto-scaling configuration

✅ **Security** (5 resources)
- IAM roles (Lambda, ECS Task Execution, Ray Task)
- IAM policies with least privilege
- Secrets Manager (optional)
- Encryption at rest

✅ **Serverless** (2 resources)
- Lambda function for S3 events
- Lambda permissions

✅ **Monitoring** (3+ resources)
- CloudWatch log groups
- CloudWatch alarms
- SNS topic for notifications

✅ **Container Registry** (1 resource)
- ECR repository (optional)

---

## Prerequisites

### 1. AWS CLI Installed and Configured

```bash
# Install AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Configure credentials
aws configure
# Enter your Access Key ID, Secret Access Key, Region (us-east-1), and output format (json)

# Verify
aws sts get-caller-identity
```

### 2. Required Permissions

Your AWS IAM user/role needs permissions to create:
- VPC and networking resources
- S3 buckets
- DynamoDB tables
- IAM roles and policies
- ECS clusters and task definitions
- Lambda functions
- CloudWatch logs and alarms
- Secrets Manager secrets (optional)
- ECR repositories (optional)

Recommended: Use `AdministratorAccess` for initial deployment.

### 3. API Keys Ready

Have these ready:
- **OpenAI API Key** - Get from https://platform.openai.com/
- **Pinecone API Key** - Get from https://www.pinecone.io/

---

## Deployment Options

### Option 1: Quick Deploy (Recommended for First-Time)

**What it does:**
- Creates all infrastructure
- Creates Secrets Manager secrets (you'll update them later)
- Creates ECR repository (you'll push Docker image later)
- Uses default parameters

```bash
# Download the CloudFormation template
# (Assuming you have ray-pipeline-2_cloudformation.yaml)

# Deploy stack
aws 2_cloudformation create-stack \
  --stack-name ray-pipeline-prod \
  --template-body file://ray-pipeline-2_cloudformation.yaml \
  --parameters \
    ParameterKey=S3BucketName,ParameterValue=my-doc-pipeline-$(date +%s) \
    ParameterKey=NotificationEmail,ParameterValue=your-email@example.com \
  --capabilities CAPABILITY_NAMED_IAM

# Monitor 3_deployment
aws 2_cloudformation wait stack-create-complete \
  --stack-name ray-pipeline-prod

# Check status
aws 2_cloudformation describe-stacks \
  --stack-name ray-pipeline-prod \
  --query 'Stacks[0].StackStatus'
```

**Time:** 10-15 minutes

### Option 2: Deploy with Custom Parameters

**What it does:**
- Uses existing Secrets Manager secrets
- Uses existing Docker image from ECR
- Custom VPC CIDR blocks
- Custom resource sizing

```bash
# 1. Edit parameters file
cat > parameters.json << 'EOF'
[
  {
    "ParameterKey": "EnvironmentName",
    "ParameterValue": "production"
  },
  {
    "ParameterKey": "ProjectName",
    "ParameterValue": "ray-doc-pipeline"
  },
  {
    "ParameterKey": "S3BucketName",
    "ParameterValue": "my-unique-bucket-name-12345"
  },
  {
    "ParameterKey": "OpenAIApiKeySecretArn",
    "ParameterValue": "arn:aws:secretsmanager:us-east-1:123456789012:secret:openai-key"
  },
  {
    "ParameterKey": "PineconeApiKeySecretArn",
    "ParameterValue": "arn:aws:secretsmanager:us-east-1:123456789012:secret:pinecone-key"
  },
  {
    "ParameterKey": "RayDockerImageUri",
    "ParameterValue": "123456789012.dkr.ecr.us-east-1.amazonaws.com/ray-pipeline:latest"
  },
  {
    "ParameterKey": "NotificationEmail",
    "ParameterValue": "alerts@yourcompany.com"
  }
]
EOF

# 2. Deploy with parameters
aws 2_cloudformation create-stack \
  --stack-name ray-pipeline-prod \
  --template-body file://ray-pipeline-2_cloudformation.yaml \
  --parameters file://parameters.json \
  --capabilities CAPABILITY_NAMED_IAM

# 3. Monitor
aws 2_cloudformation wait stack-create-complete \
  --stack-name ray-pipeline-prod
```

### Option 3: Deploy via AWS Console (UI)

**Steps:**

1. **Navigate to CloudFormation**
   - AWS Console → CloudFormation → Stacks → Create stack

2. **Upload Template**
   - Choose "Upload a template file"
   - Select `ray-pipeline-cloudformation.yaml`
   - Click "Next"

3. **Specify Stack Details**
   - Stack name: `ray-pipeline-prod`
   - Fill in parameters:
     - **S3BucketName**: Must be globally unique (e.g., `my-doc-pipeline-20250201`)
     - **NotificationEmail**: Your email for alerts
     - Leave other parameters as default (or customize)
   - Click "Next"

4. **Configure Stack Options**
   - Tags (optional): Add `Environment=Production`
   - Permissions: Use default or select existing role
   - Click "Next"

5. **Review**
   - Check "I acknowledge that AWS CloudFormation might create IAM resources with custom names"
   - Click "Create stack"

6. **Monitor Progress**
   - Watch "Events" tab for progress
   - Wait for status: `CREATE_COMPLETE` (10-15 minutes)

7. **View Outputs**
   - Click "Outputs" tab
   - Save important values (ECR URI, table names, etc.)

---

## Post-Deployment Steps

### Step 1: Update Secrets (If Using Auto-Created Secrets)

```bash
# Get secret ARNs from stack outputs
aws 2_cloudformation describe-stacks \
  --stack-name ray-pipeline-prod \
  --query 'Stacks[0].Outputs'

# Update OpenAI secret
aws secretsmanager update-secret \
  --secret-id ray-document-pipeline-openai-api-key \
  --secret-string '{"OPENAI_API_KEY":"sk-your-actual-key-here"}'

# Update Pinecone secret
aws secretsmanager update-secret \
  --secret-id ray-document-pipeline-pinecone-api-key \
  --secret-string '{"PINECONE_API_KEY":"your-actual-key-here"}'
```

### Step 2: Build and Push Docker Image

```bash
# Get ECR repository URI from outputs
ECR_URI=$(aws 2_cloudformation describe-stacks \
  --stack-name ray-pipeline-prod \
  --query 'Stacks[0].Outputs[?OutputKey==`ECRRepositoryUri`].OutputValue' \
  --output text)

# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin $ECR_URI

# Build image (from ray_pipeline_package directory)
cd ray_pipeline_package
docker build -t ray-pipeline:latest .

# Tag for ECR
docker tag ray-pipeline:latest ${ECR_URI}:latest

# Push to ECR
docker push ${ECR_URI}:latest
```

### Step 3: Deploy Ray Head Node Service

```bash
# Get cluster and subnet info
CLUSTER_NAME=$(aws 2_cloudformation describe-stacks \
  --stack-name ray-pipeline-prod \
  --query 'Stacks[0].Outputs[?OutputKey==`ECSClusterName`].OutputValue' \
  --output text)

PUBLIC_SUBNET=$(aws 2_cloudformation describe-stacks \
  --stack-name ray-pipeline-prod \
  --query 'Stacks[0].Outputs[?OutputKey==`PublicSubnetId`].OutputValue' \
  --output text)

SECURITY_GROUP=$(aws 2_cloudformation describe-stacks \
  --stack-name ray-pipeline-prod \
  --query 'Stacks[0].Outputs[?OutputKey==`RayClusterSecurityGroupId`].OutputValue' \
  --output text)

TASK_DEF=$(aws 2_cloudformation describe-stacks \
  --stack-name ray-pipeline-prod \
  --query 'Stacks[0].Outputs[?OutputKey==`RayHeadTaskDefinitionArn`].OutputValue' \
  --output text)

# Create Ray head service
aws ecs create-service \
  --cluster $CLUSTER_NAME \
  --service-name ray-head \
  --task-definition $TASK_DEF \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$PUBLIC_SUBNET],securityGroups=[$SECURITY_GROUP],assignPublicIp=ENABLED}"

# Wait for service to be stable
aws ecs wait services-stable \
  --cluster $CLUSTER_NAME \
  --services ray-head
```

### Step 4: Get Ray Head Public IP

```bash
# Get task ARN
TASK_ARN=$(aws ecs list-tasks \
  --cluster $CLUSTER_NAME \
  --service-name ray-head \
  --query 'taskArns[0]' \
  --output text)

# Get network interface ID
ENI_ID=$(aws ecs describe-tasks \
  --cluster $CLUSTER_NAME \
  --tasks $TASK_ARN \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
  --output text)

# Get public IP
PUBLIC_IP=$(aws ec2 describe-network-interfaces \
  --network-interface-ids $ENI_ID \
  --query 'NetworkInterfaces[0].Association.PublicIp' \
  --output text)

echo "Ray Dashboard: http://${PUBLIC_IP}:8265"
```

### Step 5: Update Worker Task Definition with Ray Head IP

```bash
# Get current worker task definition
aws ecs describe-task-definition \
  --task-definition ray-document-pipeline-ray-worker \
  --query 'taskDefinition' > worker-task-def.json

# Edit worker-task-def.json
# Update the command to use actual Ray head IP:
# ["ray", "start", "--address=<PUBLIC_IP>:6379", "--num-cpus=1", "--block"]

# Register updated task definition
aws ecs register-task-definition \
  --cli-input-json file://worker-task-def.json
```

### Step 6: Deploy Ray Worker Service

```bash
WORKER_TASK_DEF=$(aws 2_cloudformation describe-stacks \
  --stack-name ray-pipeline-prod \
  --query 'Stacks[0].Outputs[?OutputKey==`RayWorkerTaskDefinitionArn`].OutputValue' \
  --output text)

# Create worker service with auto-scaling
aws ecs create-service \
  --cluster $CLUSTER_NAME \
  --service-name ray-workers \
  --task-definition $WORKER_TASK_DEF \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$PUBLIC_SUBNET],securityGroups=[$SECURITY_GROUP],assignPublicIp=ENABLED}"
```

---

## Verification

### 1. Check All Resources Created

```bash
# List all stack resources
aws 2_cloudformation list-stack-resources \
  --stack-name ray-pipeline-prod \
  --query 'StackResourceSummaries[*].[ResourceType,LogicalResourceId,ResourceStatus]' \
  --output table
```

### 2. Verify S3 Bucket

```bash
S3_BUCKET=$(aws 2_cloudformation describe-stacks \
  --stack-name ray-pipeline-prod \
  --query 'Stacks[0].Outputs[?OutputKey==`S3BucketName`].OutputValue' \
  --output text)

# List bucket contents
aws s3 ls s3://${S3_BUCKET}/

# Test upload
echo "test" > test.txt
aws s3 cp test.txt s3://${S3_BUCKET}/input/test.txt
```

### 3. Verify DynamoDB Tables

```bash
# Get table names
CONTROL_TABLE=$(aws 2_cloudformation describe-stacks \
  --stack-name ray-pipeline-prod \
  --query 'Stacks[0].Outputs[?OutputKey==`ControlTableName`].OutputValue' \
  --output text)

# Describe table
aws dynamodb describe-table --table-name $CONTROL_TABLE

# Check for test record (after S3 upload)
aws dynamodb scan --table-name $CONTROL_TABLE --limit 1
```

### 4. Verify Lambda Function

```bash
# Get Lambda ARN
LAMBDA_ARN=$(aws 2_cloudformation describe-stacks \
  --stack-name ray-pipeline-prod \
  --query 'Stacks[0].Outputs[?OutputKey==`LambdaFunctionArn`].OutputValue' \
  --output text)

# Check recent invocations
aws lambda get-function --function-name ${LAMBDA_ARN}

# View logs
aws logs tail /aws/lambda/ray-document-pipeline-s3-event-handler --follow
```

### 5. Verify Ray Cluster

```bash
# Access Ray dashboard
echo "Ray Dashboard: http://${PUBLIC_IP}:8265"

# Check ECS services
aws ecs list-services --cluster $CLUSTER_NAME

# Check running tasks
aws ecs list-tasks --cluster $CLUSTER_NAME
```

---

## Stack Updates

### Update Stack with New Parameters

```bash
aws 2_cloudformation update-stack \
  --stack-name ray-pipeline-prod \
  --template-body file://ray-pipeline-2_cloudformation.yaml \
  --parameters file://updated-parameters.json \
  --capabilities CAPABILITY_NAMED_IAM
```

### Update Just Task Definitions

```bash
# After updating Docker image
aws ecs update-service \
  --cluster $CLUSTER_NAME \
  --service ray-head \
  --force-new-3_deployment

aws ecs update-service \
  --cluster $CLUSTER_NAME \
  --service ray-workers \
  --force-new-3_deployment
```

---

## Cost Estimation

### Monthly Costs (Approximate)

| Service | Usage | Cost |
|---------|-------|------|
| **ECS Fargate** | 1 head (2vCPU, 8GB) + 2 workers (1vCPU, 4GB) running 24/7 | ~$120 |
| **ECS Fargate Spot** | Same as above with Spot (60% discount) | ~$48 |
| **NAT Gateway** | 1 NAT in public subnet | ~$32 |
| **S3 Storage** | 100 GB with lifecycle policies | ~$2 |
| **DynamoDB** | On-demand, 1M reads, 500K writes | ~$5 |
| **CloudWatch Logs** | 10 GB ingested, 7-day retention | ~$5 |
| **Data Transfer** | 100 GB out | ~$9 |
| **Total (On-Demand)** | | **~$173/month** |
| **Total (Spot)** | | **~$101/month** |

**Note:** This is for infrastructure running 24/7. Actual costs depend on:
- Number of documents processed
- OpenAI API usage
- AWS Comprehend usage
- Auto-scaling behavior

### Cost Optimization

1. **Use Fargate Spot for workers** (60% savings)
2. **Stop Ray cluster when not processing** (save ~$100/month)
3. **Use S3 lifecycle policies** (included in template)
4. **Enable DynamoDB on-demand** (included in template)
5. **Clean up old CloudWatch logs** (included in template)

---

## Deletion

### Delete Stack (Careful!)

```bash
# First, empty S3 bucket
S3_BUCKET=$(aws 2_cloudformation describe-stacks \
  --stack-name ray-pipeline-prod \
  --query 'Stacks[0].Outputs[?OutputKey==`S3BucketName`].OutputValue' \
  --output text)

aws s3 rm s3://${S3_BUCKET}/ --recursive

# Delete stack
aws 2_cloudformation delete-stack --stack-name ray-pipeline-prod

# Monitor deletion
aws 2_cloudformation wait stack-delete-complete \
  --stack-name ray-pipeline-prod
```

**Warning:** This will delete:
- All DynamoDB tables (and data)
- All S3 objects (if bucket emptied)
- All CloudWatch logs
- All ECS services and tasks
- All IAM roles

---

## Troubleshooting

### Stack Creation Failed

```bash
# Get failure reason
aws 2_cloudformation describe-stack-events \
  --stack-name ray-pipeline-prod \
  --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`]'

# Common issues:
# 1. S3 bucket name already exists → Use unique name
# 2. IAM permissions insufficient → Add permissions
# 3. Resource limits exceeded → Request limit increase
```

### Can't Access Ray Dashboard

```bash
# Check security group
aws ec2 describe-security-groups \
  --group-ids $SECURITY_GROUP \
  --query 'SecurityGroups[0].IpPermissions'

# Verify port 8265 is open to 0.0.0.0/0
# If not, update security group
```

### Workers Not Connecting

```bash
# Check worker logs
aws logs tail /ecs/ray-document-pipeline-ray-worker --follow

# Verify worker has correct Ray head IP in task definition
aws ecs describe-task-definition \
  --task-definition ray-document-pipeline-ray-worker
```

---

## Advanced Configuration

### Enable Fargate Spot for Cost Savings

Update the ECS service creation to use capacity providers:

```bash
aws ecs put-cluster-capacity-providers \
  --cluster $CLUSTER_NAME \
  --capacity-providers FARGATE FARGATE_SPOT \
  --default-capacity-provider-strategy \
    capacityProvider=FARGATE_SPOT,weight=4 \
    capacityProvider=FARGATE,weight=1
```

### Set Up Auto-Scaling

```bash
# Register scalable target for workers
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --scalable-dimension ecs:service:DesiredCount \
  --resource-id service/${CLUSTER_NAME}/ray-workers \
  --min-capacity 1 \
  --max-capacity 10

# Create scaling policy
aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --scalable-dimension ecs:service:DesiredCount \
  --resource-id service/${CLUSTER_NAME}/ray-workers \
  --policy-name ray-workers-cpu-scaling \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration file://scaling-policy.json
```

---

## Summary

### What You Deployed

✅ Complete VPC with public/private subnets  
✅ S3 bucket with lifecycle policies  
✅ 3 DynamoDB tables with GSIs  
✅ Lambda function for S3 events  
✅ ECS Fargate cluster  
✅ Ray task definitions  
✅ IAM roles and policies  
✅ CloudWatch monitoring  
✅ SNS alerts  

### Next Steps

1. ✅ Update Secrets Manager with real API keys
2. ✅ Build and push Docker image to ECR
3. ✅ Deploy Ray head service
4. ✅ Deploy Ray worker service
5. ✅ Upload test PDF to S3
6. ✅ Monitor pipeline execution

### Resources Created

Total: **40+ AWS resources** created in **10-15 minutes**

### Documentation

- CloudFormation template: `ray-pipeline-cloudformation.yaml`
- Parameters file: `cloudformation-parameters.json`
- Deployment guide: This document

---

**Author:** Prudhvi @ Thoughtworks  
**Version:** 1.0.0  
**Last Updated:** February 2025
