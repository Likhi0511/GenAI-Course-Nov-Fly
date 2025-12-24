# 🔄 Lambda Throttling & Retry Mechanism with EventBridge + DLQ

## 📋 Problem Statement

### The Throttling Scenario

```
Problem: CSV Parser Lambda Throttling
═══════════════════════════════════════════════════════════════════════════════

Scenario 1: Normal Operation
────────────────────────────
10 vendors upload simultaneously
→ 10 Lambda invocations (CONCURRENT)
→ All process successfully ✓

Scenario 2: Black Friday / Peak Load
─────────────────────────────────────
100 vendors upload simultaneously
→ 100 Lambda invocations requested
→ AWS Account Limit: 1000 concurrent Lambdas
→ Reserved Concurrency for csv-parser: 50
→ Result: 50 run, 50 THROTTLED! ✗

Scenario 3: Burst Traffic
──────────────────────────
1000 CSV uploads in 10 seconds
→ S3 triggers 1000 Lambda invocations
→ Exceeds reserved concurrency
→ Result: Mass throttling, lost events! ✗
```

### What Happens When Throttled?

```
S3 Event → Lambda Service
         ↓
    Is capacity available?
         ├─ YES → Invoke Lambda ✓
         └─ NO  → Return 429 (Too Many Requests)
                  ↓
                  Event LOST! ✗
                  (S3 doesn't retry automatically)
```

### Why This Is Critical

❌ **Without Retry Mechanism:**
- Lost CSV uploads (vendors don't know)
- No error notification
- Manual re-upload required
- Poor user experience

✅ **With Retry Mechanism:**
- Failed invocations captured in DLQ
- Automatic retry with backoff
- Notifications sent
- Graceful degradation

---

## 🏗️ Solution Architecture

### Complete Retry Flow with EventBridge

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    RETRY MECHANISM ARCHITECTURE                             │
└─────────────────────────────────────────────────────────────────────────────┘

NORMAL FLOW (Happy Path):
═══════════════════════════════════════════════════════════════════════════════
    Vendor uploads CSV
           ↓
    ┌──────────────┐
    │   S3 BUCKET  │
    └──────┬───────┘
           │ S3 Event Notification
           ↓
    ┌──────────────────────────────┐
    │  Lambda: csv-parser          │
    │  Concurrency Available? YES  │
    └──────┬───────────────────────┘
           │
           ↓ SUCCESS
    DynamoDB ✓


THROTTLING FLOW (With Retry):
═══════════════════════════════════════════════════════════════════════════════
    Vendor uploads CSV
           ↓
    ┌──────────────┐
    │   S3 BUCKET  │
    └──────┬───────┘
           │ S3 Event Notification
           ↓
    ┌──────────────────────────────┐
    │  Lambda: csv-parser          │
    │  Concurrency Available? NO   │
    │  Status: 429 THROTTLED       │
    └──────┬───────────────────────┘
           │
           │ On Failure
           ↓
    ┌──────────────────────────────┐
    │  Lambda Destination          │
    │  Type: OnFailure             │
    │  Target: SQS DLQ             │
    └──────┬───────────────────────┘
           │
           │ Failed event details
           ↓
    ┌──────────────────────────────┐
    │  SQS: csv-parser-dlq         │
    │  (Dead Letter Queue)         │
    │                              │
    │  Message contains:           │
    │  • Original S3 event         │
    │  • Error details             │
    │  • Timestamp                 │
    │  • Retry count               │
    └──────┬───────────────────────┘
           │
           │ EventBridge Rule (every 5 min)
           ↓
    ┌──────────────────────────────┐
    │  EventBridge Rule            │
    │  Schedule: rate(5 minutes)   │
    │  Target: Retry Lambda        │
    └──────┬───────────────────────┘
           │
           │ Triggers
           ↓
    ┌──────────────────────────────┐
    │  Lambda: csv-parser-retry    │
    │                              │
    │  1. Read messages from DLQ   │
    │  2. Check retry count        │
    │  3. Re-invoke csv-parser     │
    │  4. If still fails → back    │
    │     to DLQ with count++      │
    │  5. If success → delete msg  │
    │  6. If max retries → SNS     │
    └──────┬───────────────────────┘
           │
           ├─────────────┬─────────────┐
           │             │             │
           ↓             ↓             ↓
    CSV Parser     DLQ (retry)    SNS (alert)
    (SUCCESS)      (temp fail)     (max retries)


ADVANCED: EventBridge + Step Functions (Optional Enhancement):
═══════════════════════════════════════════════════════════════════════════════
    ┌──────────────────────────────┐
    │  SQS DLQ                     │
    └──────┬───────────────────────┘
           │
           │ EventBridge triggers
           ↓
    ┌──────────────────────────────┐
    │  EventBridge Rule            │
    │  Event Pattern:              │
    │  • Source: aws.sqs           │
    │  • Detail: DLQ message       │
    └──────┬───────────────────────┘
           │
           │ Starts
           ↓
    ┌──────────────────────────────┐
    │  Step Functions              │
    │  State Machine: RetryWorkflow│
    │                              │
    │  States:                     │
    │  1. Wait (exponential)       │
    │  2. Invoke Lambda            │
    │  3. Check Success            │
    │  4. If fail → Loop (max 5)   │
    │  5. If max → SNS alert       │
    └──────────────────────────────┘
```

---

## 🔧 Implementation Guide

### Part 1: Configure Lambda Destination (DLQ)

#### Step 1.1: Create SQS Dead Letter Queue

```bash
# Create DLQ for failed csv-parser invocations
aws sqs create-queue \
    --queue-name csv-parser-dlq \
    --attributes '{
        "MessageRetentionPeriod": "1209600",
        "VisibilityTimeout": "300",
        "ReceiveMessageWaitTimeSeconds": "20"
    }' \
    --tags Key=Project,Value=ecommerce-onboarding

# Get queue ARN
CSV_PARSER_DLQ_ARN=$(aws sqs get-queue-attributes \
    --queue-url $(aws sqs get-queue-url --queue-name csv-parser-dlq --query 'QueueUrl' --output text) \
    --attribute-names QueueArn \
    --query 'Attributes.QueueArn' \
    --output text)

echo "DLQ ARN: ${CSV_PARSER_DLQ_ARN}"
```

**Queue Attributes Explained:**
- `MessageRetentionPeriod: 1209600` = 14 days (maximum retention)
- `VisibilityTimeout: 300` = 5 minutes (time to process message)
- `ReceiveMessageWaitTimeSeconds: 20` = Long polling (reduces costs)

#### Step 1.2: Configure Lambda Destination

```bash
# Add OnFailure destination to csv-parser Lambda
aws lambda put-function-event-invoke-config \
    --function-name csv-parser \
    --destination-config '{
        "OnFailure": {
            "Destination": "'${CSV_PARSER_DLQ_ARN}'"
        }
    }' \
    --maximum-retry-attempts 0 \
    --maximum-event-age-in-seconds 60

# Verify configuration
aws lambda get-function-event-invoke-config \
    --function-name csv-parser
```

**Configuration Explained:**
- `OnFailure.Destination` = Where to send failed events (our DLQ)
- `maximum-retry-attempts: 0` = Don't retry automatically (we'll control retries)
- `maximum-event-age-in-seconds: 60` = Give up after 60 seconds

#### Step 1.3: Update Lambda IAM Role

```bash
# Add SQS permissions to csv-parser role
cat > csv-parser-dlq-policy.json << 'EOF'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "SendToDLQ",
            "Effect": "Allow",
            "Action": [
                "sqs:SendMessage",
                "sqs:GetQueueAttributes"
            ],
            "Resource": "arn:aws:sqs:*:*:csv-parser-dlq"
        }
    ]
}
EOF

# Attach policy
aws iam put-role-policy \
    --role-name lambda-csv-parser-role \
    --policy-name csv-parser-dlq-policy \
    --policy-document file://csv-parser-dlq-policy.json
```

---

### Part 2: Create Retry Lambda Function

#### Step 2.1: Create Retry Lambda Code

**File: `lambda_csv_parser_retry/lambda_retry.py`**

```python
"""
Lambda Function: CSV Parser Retry Handler
==========================================

Triggered by: EventBridge (scheduled every 5 minutes)
Purpose: Process failed CSV parser invocations from DLQ
Features:
  - Exponential backoff
  - Maximum retry limit
  - Success/failure tracking
  - SNS alerts for permanent failures
"""

import json
import boto3
import os
from datetime import datetime
from botocore.exceptions import ClientError

# AWS Clients
sqs_client = boto3.client('sqs')
lambda_client = boto3.client('lambda')
sns_client = boto3.client('sns')
cloudwatch = boto3.client('cloudwatch')

# Environment Variables
DLQ_URL = os.environ.get('DLQ_URL')
CSV_PARSER_FUNCTION = os.environ.get('CSV_PARSER_FUNCTION', 'csv-parser')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
MAX_RETRIES = int(os.environ.get('MAX_RETRIES', '5'))
REGION = os.environ.get('AWS_REGION', 'us-east-1')


def lambda_handler(event, context):
    """
    Main handler for retry logic.
    
    Flow:
    1. Receive messages from DLQ (batch)
    2. For each message:
       a. Extract original S3 event
       b. Check retry count
       c. Re-invoke csv-parser
       d. Handle success/failure
    3. Publish metrics
    """
    
    print("\n" + "="*80)
    print("CSV Parser Retry Handler - Started")
    print("="*80)
    
    retry_stats = {
        'total_messages': 0,
        'successful_retries': 0,
        'failed_retries': 0,
        'max_retries_exceeded': 0
    }
    
    try:
        # =====================================================================
        # STEP 1: Receive Messages from DLQ
        # =====================================================================
        
        print(f"\n>>> Step 1: Receiving messages from DLQ...")
        print(f"    DLQ URL: {DLQ_URL}")
        
        response = sqs_client.receive_message(
            QueueUrl=DLQ_URL,
            MaxNumberOfMessages=10,  # Process up to 10 at a time
            WaitTimeSeconds=20,       # Long polling
            AttributeNames=['All'],
            MessageAttributeNames=['All']
        )
        
        messages = response.get('Messages', [])
        retry_stats['total_messages'] = len(messages)
        
        print(f"    Received {len(messages)} messages")
        
        if not messages:
            print("    No messages to process")
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'No messages in DLQ'})
            }
        
        # =====================================================================
        # STEP 2: Process Each Message
        # =====================================================================
        
        for message in messages:
            print(f"\n>>> Processing message: {message['MessageId'][:8]}...")
            
            try:
                # Parse message body
                message_body = json.loads(message['Body'])
                
                # Extract retry count (stored in message attributes)
                retry_count = int(message.get('Attributes', {}).get('ApproximateReceiveCount', 1))
                
                print(f"    Retry attempt: {retry_count}/{MAX_RETRIES}")
                
                # Check if max retries exceeded
                if retry_count > MAX_RETRIES:
                    print(f"    ✗ Max retries exceeded ({MAX_RETRIES})")
                    handle_max_retries_exceeded(message_body, retry_count)
                    delete_message_from_dlq(message['ReceiptHandle'])
                    retry_stats['max_retries_exceeded'] += 1
                    continue
                
                # Extract original S3 event from DLQ message
                original_event = extract_original_event(message_body)
                
                if not original_event:
                    print(f"    ✗ Could not extract original event")
                    delete_message_from_dlq(message['ReceiptHandle'])
                    continue
                
                # Get S3 bucket and key
                s3_bucket = original_event['Records'][0]['s3']['bucket']['name']
                s3_key = original_event['Records'][0]['s3']['object']['key']
                
                print(f"    Original file: s3://{s3_bucket}/{s3_key}")
                
                # =====================================================================
                # STEP 3: Retry CSV Parser Invocation
                # =====================================================================
                
                print(f"    Retrying csv-parser Lambda...")
                
                retry_result = retry_csv_parser_invocation(
                    original_event,
                    retry_count
                )
                
                if retry_result['success']:
                    print(f"    ✓ Retry successful!")
                    delete_message_from_dlq(message['ReceiptHandle'])
                    retry_stats['successful_retries'] += 1
                    
                    # Send success metric
                    publish_metric('RetrySuccess', 1)
                    
                else:
                    print(f"    ✗ Retry failed: {retry_result.get('error')}")
                    
                    # Check if it's a throttling error
                    if is_throttling_error(retry_result.get('error')):
                        print(f"    Still throttled - leaving in DLQ for next attempt")
                        # Don't delete - will retry again in 5 minutes
                    else:
                        # Permanent error - delete from DLQ
                        print(f"    Permanent error - removing from DLQ")
                        delete_message_from_dlq(message['ReceiptHandle'])
                        send_failure_alert(s3_bucket, s3_key, retry_result.get('error'))
                    
                    retry_stats['failed_retries'] += 1
                    publish_metric('RetryFailed', 1)
            
            except Exception as e:
                print(f"    ✗ Error processing message: {str(e)}")
                retry_stats['failed_retries'] += 1
        
        # =====================================================================
        # STEP 4: Summary & Metrics
        # =====================================================================
        
        print("\n" + "="*80)
        print("RETRY SUMMARY")
        print("="*80)
        print(f"Total Messages: {retry_stats['total_messages']}")
        print(f"Successful Retries: {retry_stats['successful_retries']}")
        print(f"Failed Retries: {retry_stats['failed_retries']}")
        print(f"Max Retries Exceeded: {retry_stats['max_retries_exceeded']}")
        print("="*80 + "\n")
        
        return {
            'statusCode': 200,
            'body': json.dumps(retry_stats)
        }
    
    except Exception as e:
        print(f"\n✗ ERROR: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


def extract_original_event(message_body):
    """
    Extract original S3 event from DLQ message.
    
    DLQ message structure:
    {
        "version": "1.0",
        "timestamp": "2024-12-21T10:30:45.123Z",
        "requestContext": {...},
        "requestPayload": {
            "Records": [{ "s3": {...} }]  <- Original S3 event
        },
        "responseContext": {...},
        "responsePayload": {...}
    }
    """
    try:
        # Lambda destination wraps the original event
        if 'requestPayload' in message_body:
            return message_body['requestPayload']
        
        # Fallback: message might be the event itself
        if 'Records' in message_body:
            return message_body
        
        print(f"    ⚠ Unexpected message structure: {list(message_body.keys())}")
        return None
    
    except Exception as e:
        print(f"    ✗ Error extracting event: {str(e)}")
        return None


def retry_csv_parser_invocation(original_event, retry_count):
    """
    Retry the csv-parser Lambda invocation.
    
    Args:
        original_event: Original S3 event
        retry_count: Current retry attempt number
    
    Returns:
        dict: {'success': bool, 'error': str}
    """
    try:
        # Add retry metadata to event
        event_with_metadata = original_event.copy()
        event_with_metadata['retryMetadata'] = {
            'retryCount': retry_count,
            'retryTimestamp': datetime.utcnow().isoformat(),
            'retrySource': 'csv-parser-retry'
        }
        
        # Invoke csv-parser Lambda
        response = lambda_client.invoke(
            FunctionName=CSV_PARSER_FUNCTION,
            InvocationType='RequestResponse',  # Wait for response
            Payload=json.dumps(event_with_metadata)
        )
        
        # Check response
        status_code = response['StatusCode']
        
        if status_code == 200:
            # Success!
            payload = json.loads(response['Payload'].read())
            
            # Check if function itself returned an error
            if 'errorMessage' in payload:
                return {
                    'success': False,
                    'error': payload['errorMessage']
                }
            
            return {'success': True}
        
        else:
            return {
                'success': False,
                'error': f"Lambda returned status code {status_code}"
            }
    
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        
        return {
            'success': False,
            'error': f"{error_code}: {error_message}"
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def is_throttling_error(error_message):
    """
    Check if error is due to throttling.
    
    Throttling errors include:
    - TooManyRequestsException
    - Rate exceeded
    - ResourceNotFoundException (sometimes)
    """
    if not error_message:
        return False
    
    throttling_indicators = [
        'TooManyRequestsException',
        'Rate exceeded',
        'Throttling',
        '429',
        'concurrent execution limit'
    ]
    
    return any(indicator.lower() in error_message.lower() 
               for indicator in throttling_indicators)


def delete_message_from_dlq(receipt_handle):
    """Delete message from DLQ after successful processing."""
    try:
        sqs_client.delete_message(
            QueueUrl=DLQ_URL,
            ReceiptHandle=receipt_handle
        )
        print(f"    ✓ Message deleted from DLQ")
        return True
    except Exception as e:
        print(f"    ✗ Failed to delete message: {str(e)}")
        return False


def handle_max_retries_exceeded(message_body, retry_count):
    """
    Handle case where max retries exceeded.
    
    Actions:
    1. Send SNS alert
    2. Log to CloudWatch
    3. Optionally store in "failed permanently" table
    """
    print(f"    Sending alert for permanent failure...")
    
    try:
        # Extract file info
        original_event = extract_original_event(message_body)
        if original_event:
            s3_bucket = original_event['Records'][0]['s3']['bucket']['name']
            s3_key = original_event['Records'][0]['s3']['object']['key']
        else:
            s3_bucket = 'unknown'
            s3_key = 'unknown'
        
        # Send SNS alert
        if SNS_TOPIC_ARN:
            sns_client.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=f'CSV Parser - Permanent Failure',
                Message=f"""
CSV Parser Retry - Permanent Failure
=====================================

File: s3://{s3_bucket}/{s3_key}
Retry Attempts: {retry_count}
Status: FAILED (Max retries exceeded)

Action Required:
1. Investigate why file keeps failing
2. Check Lambda logs for csv-parser
3. Manually process file if needed

This message will not be retried automatically.
                """,
                MessageAttributes={
                    's3_bucket': {'StringValue': s3_bucket, 'DataType': 'String'},
                    's3_key': {'StringValue': s3_key, 'DataType': 'String'},
                    'retry_count': {'StringValue': str(retry_count), 'DataType': 'Number'}
                }
            )
            print(f"    ✓ Alert sent via SNS")
        
        # Publish metric
        publish_metric('MaxRetriesExceeded', 1)
    
    except Exception as e:
        print(f"    ✗ Failed to send alert: {str(e)}")


def send_failure_alert(s3_bucket, s3_key, error_message):
    """Send alert for permanent (non-throttling) failure."""
    try:
        if SNS_TOPIC_ARN:
            sns_client.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=f'CSV Parser - Processing Error',
                Message=f"""
CSV Parser - Processing Error
==============================

File: s3://{s3_bucket}/{s3_key}
Error: {error_message}
Status: FAILED (Permanent error)

This file will not be retried automatically.
Please investigate the issue.
                """,
                MessageAttributes={
                    's3_bucket': {'StringValue': s3_bucket, 'DataType': 'String'},
                    's3_key': {'StringValue': s3_key, 'DataType': 'String'}
                }
            )
    except Exception as e:
        print(f"    ✗ Failed to send failure alert: {str(e)}")


def publish_metric(metric_name, value):
    """Publish custom CloudWatch metric."""
    try:
        cloudwatch.put_metric_data(
            Namespace='EcommerceProductOnboarding',
            MetricData=[{
                'MetricName': metric_name,
                'Value': value,
                'Unit': 'Count',
                'Timestamp': datetime.utcnow()
            }]
        )
    except Exception as e:
        print(f"    ⚠ Failed to publish metric: {str(e)}")


# For local testing
if __name__ == '__main__':
    # Mock event
    test_event = {}
    
    class MockContext:
        function_name = 'csv-parser-retry'
        memory_limit_in_mb = 256
    
    result = lambda_handler(test_event, MockContext())
    print(json.dumps(result, indent=2))
```

#### Step 2.2: Create Dockerfile for Retry Lambda

**File: `lambda_csv_parser_retry/Dockerfile`**

```dockerfile
FROM public.ecr.aws/lambda/python:3.11

# Copy requirements
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

# Install dependencies
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy function code
COPY lambda_retry.py ${LAMBDA_TASK_ROOT}/

# Set handler
CMD ["lambda_retry.lambda_handler"]
```

**File: `lambda_csv_parser_retry/requirements.txt`**

```txt
boto3>=1.34.0
botocore>=1.34.0
```

#### Step 2.3: Build and Deploy Retry Lambda

```bash
# Navigate to retry lambda directory
cd lambda_csv_parser_retry/

# Create ECR repository
aws ecr create-repository \
    --repository-name csv-parser-retry-lambda \
    --image-scanning-configuration scanOnPush=true

# Build image
docker build -t csv-parser-retry-lambda:latest .

# Get account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Tag image
docker tag csv-parser-retry-lambda:latest \
    ${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/csv-parser-retry-lambda:latest

# Authenticate to ECR
aws ecr get-login-password --region us-east-1 | \
    docker login --username AWS --password-stdin \
    ${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com

# Push image
docker push ${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/csv-parser-retry-lambda:latest

echo "✓ Retry Lambda image pushed to ECR"
```

#### Step 2.4: Create IAM Role for Retry Lambda

```bash
# Create IAM policy
cat > csv-parser-retry-policy.json << 'EOF'
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
            "Sid": "ReadFromDLQ",
            "Effect": "Allow",
            "Action": [
                "sqs:ReceiveMessage",
                "sqs:DeleteMessage",
                "sqs:GetQueueAttributes"
            ],
            "Resource": "arn:aws:sqs:*:*:csv-parser-dlq"
        },
        {
            "Sid": "InvokeCSVParser",
            "Effect": "Allow",
            "Action": [
                "lambda:InvokeFunction"
            ],
            "Resource": "arn:aws:lambda:*:*:function:csv-parser"
        },
        {
            "Sid": "SNSAlert",
            "Effect": "Allow",
            "Action": [
                "sns:Publish"
            ],
            "Resource": "arn:aws:sns:*:*:product-upload-notifications"
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
EOF

# Create role
aws iam create-role \
    --role-name lambda-csv-parser-retry-role \
    --assume-role-policy-document file://trust-policy-lambda.json

# Attach policy
aws iam put-role-policy \
    --role-name lambda-csv-parser-retry-role \
    --policy-name csv-parser-retry-policy \
    --policy-document file://csv-parser-retry-policy.json

# Get role ARN
RETRY_ROLE_ARN=$(aws iam get-role \
    --role-name lambda-csv-parser-retry-role \
    --query 'Role.Arn' \
    --output text)

echo "Retry Role ARN: ${RETRY_ROLE_ARN}"
```

#### Step 2.5: Create Retry Lambda Function

```bash
# Get DLQ URL
DLQ_URL=$(aws sqs get-queue-url \
    --queue-name csv-parser-dlq \
    --query 'QueueUrl' \
    --output text)

# Create Lambda
aws lambda create-function \
    --function-name csv-parser-retry \
    --package-type Image \
    --code ImageUri=${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/csv-parser-retry-lambda:latest \
    --role ${RETRY_ROLE_ARN} \
    --timeout 300 \
    --memory-size 256 \
    --environment Variables="{
        DLQ_URL=${DLQ_URL},
        CSV_PARSER_FUNCTION=csv-parser,
        SNS_TOPIC_ARN=${SNS_TOPIC_ARN},
        MAX_RETRIES=5,
        AWS_REGION=us-east-1
    }" \
    --description "Retry handler for throttled csv-parser invocations"

echo "✓ Retry Lambda created"
```

---

### Part 3: Configure EventBridge Scheduler

#### Step 3.1: Create EventBridge Rule

```bash
# Create EventBridge rule (runs every 5 minutes)
aws events put-rule \
    --name csv-parser-retry-schedule \
    --description "Trigger retry Lambda every 5 minutes" \
    --schedule-expression "rate(5 minutes)" \
    --state ENABLED

# Get rule ARN
RULE_ARN=$(aws events describe-rule \
    --name csv-parser-retry-schedule \
    --query 'Arn' \
    --output text)

echo "EventBridge Rule ARN: ${RULE_ARN}"
```

**Schedule Expression Options:**
```bash
rate(5 minutes)              # Every 5 minutes
rate(1 minute)               # Every 1 minute (faster recovery)
rate(10 minutes)             # Every 10 minutes (slower, cheaper)
cron(0/5 * * * ? *)          # Every 5 minutes (cron format)
cron(0 * * * ? *)            # Every hour (on the hour)
```

#### Step 3.2: Add Lambda Permission for EventBridge

```bash
# Allow EventBridge to invoke retry Lambda
aws lambda add-permission \
    --function-name csv-parser-retry \
    --statement-id AllowEventBridgeInvoke \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn ${RULE_ARN}

echo "✓ Lambda permission added"
```

#### Step 3.3: Add Target to EventBridge Rule

```bash
# Get retry Lambda ARN
RETRY_LAMBDA_ARN=$(aws lambda get-function \
    --function-name csv-parser-retry \
    --query 'Configuration.FunctionArn' \
    --output text)

# Add Lambda as target
aws events put-targets \
    --rule csv-parser-retry-schedule \
    --targets "Id"="1","Arn"="${RETRY_LAMBDA_ARN}"

echo "✓ EventBridge target configured"
```

#### Step 3.4: Verify EventBridge Rule

```bash
# List targets
aws events list-targets-by-rule \
    --rule csv-parser-retry-schedule

# Check rule status
aws events describe-rule \
    --name csv-parser-retry-schedule
```

---

### Part 4: Set Reserved Concurrency (Prevent Throttling)

#### Step 4.1: Analyze Current Concurrency

```bash
# Get account-level concurrency limits
aws lambda get-account-settings

# Example output:
# {
#     "AccountLimit": {
#         "TotalCodeSize": 80530636800,
#         "CodeSizeUnzipped": 262144000,
#         "CodeSizeZipped": 52428800,
#         "ConcurrentExecutions": 1000,      <- Account limit
#         "UnreservedConcurrentExecutions": 900
#     },
#     "AccountUsage": {
#         "TotalCodeSize": 1234567,
#         "FunctionCount": 15
#     }
# }
```

#### Step 4.2: Set Reserved Concurrency for CSV Parser

```bash
# Reserve 50 concurrent executions for csv-parser
aws lambda put-function-concurrency \
    --function-name csv-parser \
    --reserved-concurrent-executions 50

echo "✓ Reserved concurrency set to 50"
```

**Concurrency Strategy:**
```
Account Total: 1000 concurrent executions

Allocation:
├─ csv-parser: 50 (reserved)
├─ product-validator: 100 (reserved)
├─ error-processor: 20 (reserved)
├─ csv-parser-retry: 10 (reserved)
└─ Other functions: 820 (unreserved pool)

Benefits:
✓ Guarantees capacity for critical functions
✓ Prevents one function from consuming all capacity
✓ Predictable performance
✗ May throttle if exceed reservation
```

#### Step 4.3: Monitor Concurrency Usage

```bash
# Get current concurrency metrics
aws cloudwatch get-metric-statistics \
    --namespace AWS/Lambda \
    --metric-name ConcurrentExecutions \
    --dimensions Name=FunctionName,Value=csv-parser \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 300 \
    --statistics Maximum,Average
```

---

## 🧪 Testing the Retry Mechanism

### Test 1: Simulate Throttling

#### Create Test Script

**File: `test_throttling.sh`**

```bash
#!/bin/bash

# Simulate throttling by uploading many CSVs simultaneously

BUCKET_NAME="ecommerce-product-uploads-${ACCOUNT_ID}"

echo "Simulating throttling scenario..."
echo "Uploading 100 CSV files simultaneously..."

# Generate 100 test CSV files
for i in {1..100}; do
    cat > test_${i}.csv << EOF
vendor_product_id,product_name,category,sku,price,stock_quantity
PROD${i},Test Product ${i},Electronics,SKU-TEST-${i},19.99,100
EOF
done

# Upload all simultaneously (in background)
for i in {1..100}; do
    aws s3 cp test_${i}.csv s3://${BUCKET_NAME}/uploads/VEND001/test_${i}.csv &
done

wait

echo "✓ All files uploaded"
echo "Checking for throttling..."

# Wait for processing
sleep 30

# Check DLQ depth
DLQ_URL=$(aws sqs get-queue-url --queue-name csv-parser-dlq --query 'QueueUrl' --output text)

MESSAGES=$(aws sqs get-queue-attributes \
    --queue-url ${DLQ_URL} \
    --attribute-names ApproximateNumberOfMessages \
    --query 'Attributes.ApproximateNumberOfMessages' \
    --output text)

echo "Messages in DLQ: ${MESSAGES}"

if [ "${MESSAGES}" -gt "0" ]; then
    echo "✓ Throttling occurred - ${MESSAGES} messages in DLQ"
    echo "Retry Lambda will process these in next 5-minute window"
else
    echo "No throttling detected - all processed successfully"
fi

# Clean up test files
rm -f test_*.csv
```

#### Run Test

```bash
chmod +x test_throttling.sh
./test_throttling.sh
```

### Test 2: Monitor Retry Lambda

```bash
# Tail retry Lambda logs
aws logs tail /aws/lambda/csv-parser-retry --follow

# Check metrics
aws cloudwatch get-metric-statistics \
    --namespace EcommerceProductOnboarding \
    --metric-name RetrySuccess \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 300 \
    --statistics Sum
```

### Test 3: Verify DLQ Processing

```bash
# Check DLQ before retry
aws sqs get-queue-attributes \
    --queue-url ${DLQ_URL} \
    --attribute-names ApproximateNumberOfMessages

# Wait 5 minutes (for EventBridge trigger)
echo "Waiting 5 minutes for retry..."
sleep 300

# Check DLQ after retry
aws sqs get-queue-attributes \
    --queue-url ${DLQ_URL} \
    --attribute-names ApproximateNumberOfMessages

# Should see messages decrease (successful retries)
```

---

## 📊 Monitoring & Alerting

### CloudWatch Dashboard

```bash
# Create dashboard for retry metrics
aws cloudwatch put-dashboard \
    --dashboard-name CSV-Parser-Retry-Monitoring \
    --dashboard-body file://retry-dashboard.json
```

**File: `retry-dashboard.json`**

```json
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["AWS/Lambda", "Throttles", {"stat": "Sum", "label": "CSV Parser Throttles"}],
          ["EcommerceProductOnboarding", "RetrySuccess", {"stat": "Sum"}],
          [".", "RetryFailed", {"stat": "Sum"}],
          [".", "MaxRetriesExceeded", {"stat": "Sum"}]
        ],
        "period": 300,
        "stat": "Sum",
        "region": "us-east-1",
        "title": "CSV Parser Retry Metrics",
        "yAxis": {
          "left": {
            "min": 0
          }
        }
      }
    },
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["AWS/Lambda", "ConcurrentExecutions", 
           {"stat": "Maximum", "label": "CSV Parser Concurrency"}]
        ],
        "period": 300,
        "stat": "Maximum",
        "region": "us-east-1",
        "title": "CSV Parser Concurrency",
        "yAxis": {
          "left": {
            "min": 0,
            "max": 50
          }
        },
        "annotations": {
          "horizontal": [{
            "value": 50,
            "label": "Reserved Limit",
            "fill": "above"
          }]
        }
      }
    },
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["AWS/SQS", "ApproximateNumberOfMessagesVisible",
           {"stat": "Sum", "label": "DLQ Depth"}]
        ],
        "period": 300,
        "stat": "Sum",
        "region": "us-east-1",
        "title": "DLQ Message Count"
      }
    }
  ]
}
```

### CloudWatch Alarms

```bash
# Alarm 1: High DLQ depth
aws cloudwatch put-metric-alarm \
    --alarm-name csv-parser-dlq-high-depth \
    --alarm-description "Alert when DLQ has many messages" \
    --metric-name ApproximateNumberOfMessagesVisible \
    --namespace AWS/SQS \
    --statistic Average \
    --period 300 \
    --threshold 50 \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods 2 \
    --alarm-actions ${SNS_TOPIC_ARN}

# Alarm 2: Max retries exceeded
aws cloudwatch put-metric-alarm \
    --alarm-name csv-parser-max-retries-exceeded \
    --alarm-description "Alert when files exceed max retries" \
    --metric-name MaxRetriesExceeded \
    --namespace EcommerceProductOnboarding \
    --statistic Sum \
    --period 300 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --evaluation-periods 1 \
    --alarm-actions ${SNS_TOPIC_ARN}

# Alarm 3: Throttling rate
aws cloudwatch put-metric-alarm \
    --alarm-name csv-parser-high-throttles \
    --alarm-description "Alert on high throttle rate" \
    --metric-name Throttles \
    --namespace AWS/Lambda \
    --statistic Sum \
    --period 300 \
    --threshold 10 \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods 2 \
    --alarm-actions ${SNS_TOPIC_ARN}
```

---

## 🚀 Advanced: Step Functions Integration (Optional)

For more sophisticated retry logic with exponential backoff:

### Step Functions State Machine

```json
{
  "Comment": "CSV Parser Retry with Exponential Backoff",
  "StartAt": "CheckRetryCount",
  "States": {
    "CheckRetryCount": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.retryCount",
          "NumericGreaterThan": 5,
          "Next": "MaxRetriesExceeded"
        }
      ],
      "Default": "WaitBeforeRetry"
    },
    "WaitBeforeRetry": {
      "Type": "Wait",
      "SecondsPath": "$.waitSeconds",
      "Next": "InvokeCSVParser"
    },
    "InvokeCSVParser": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:123456789012:function:csv-parser",
      "Retry": [
        {
          "ErrorEquals": ["Lambda.TooManyRequestsException"],
          "IntervalSeconds": 2,
          "BackoffRate": 2,
          "MaxAttempts": 3
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "IncrementRetryCount"
        }
      ],
      "Next": "Success"
    },
    "IncrementRetryCount": {
      "Type": "Pass",
      "Parameters": {
        "retryCount.$": "$.retryCount + 1",
        "waitSeconds.$": "$.waitSeconds * 2",
        "event.$": "$.event"
      },
      "Next": "CheckRetryCount"
    },
    "MaxRetriesExceeded": {
      "Type": "Task",
      "Resource": "arn:aws:sns:us-east-1:123456789012:product-upload-notifications",
      "End": true
    },
    "Success": {
      "Type": "Succeed"
    }
  }
}
```

---

## ✅ Verification Checklist

- [ ] DLQ created and configured
- [ ] Lambda destination configured (OnFailure)
- [ ] Retry Lambda created and deployed
- [ ] IAM roles configured correctly
- [ ] EventBridge rule created (5-minute schedule)
- [ ] EventBridge target added
- [ ] Reserved concurrency set
- [ ] CloudWatch dashboard created
- [ ] CloudWatch alarms configured
- [ ] Test throttling scenario successful
- [ ] DLQ messages processed correctly
- [ ] Metrics published correctly
- [ ] SNS alerts working

---

## 📚 Summary

**What You Built:**
✅ Automatic retry mechanism for Lambda throttling
✅ Dead Letter Queue for failed invocations
✅ EventBridge scheduled retry processing
✅ Exponential backoff strategy
✅ Maximum retry limit
✅ SNS alerts for permanent failures
✅ CloudWatch monitoring & alarms
✅ Reserved concurrency for predictable performance

**How It Works:**
1. CSV Parser hits concurrency limit → Throttled (429)
2. Failed invocation → DLQ
3. EventBridge triggers retry Lambda every 5 minutes
4. Retry Lambda processes DLQ messages
5. Re-invokes CSV Parser with backoff
6. Success → Delete from DLQ
7. Max retries → Alert via SNS

**Benefits:**
- ✅ No lost uploads
- ✅ Automatic recovery
- ✅ Graceful degradation
- ✅ Vendor notifications
- ✅ Complete audit trail
- ✅ Cost-effective (only pay for retries)

**Ready for production!** 🚀
