#!/bin/bash

################################################################################
# E-Commerce Product Onboarding System - Automated Deployment Script
################################################################################
#
# This script automates the complete 3_deployment of the product onboarding system
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh
#
# Prerequisites:
#   - AWS CLI configured with admin credentials
#   - Docker installed and running
#   - PostgreSQL client (psql) installed
#
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI not found. Please install: https://aws.amazon.com/cli/"
        exit 1
    fi
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker not found. Please install: https://www.docker.com/"
        exit 1
    fi
    
    # Check PostgreSQL client
    if ! command -v psql &> /dev/null; then
        log_warn "PostgreSQL client not found. RDS testing will be limited."
    fi
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not configured. Run: aws configure"
        exit 1
    fi
    
    log_success "All prerequisites met"
}

# Set environment variables
setup_environment() {
    log_info "Setting up environment variables..."
    
    export AWS_REGION=${AWS_REGION:-us-east-1}
    export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    export PROJECT_NAME="ecommerce-product-onboarding"
    export S3_BUCKET_NAME="ecommerce-product-uploads-${ACCOUNT_ID}"
    
    log_success "Environment configured"
    log_info "  Region: ${AWS_REGION}"
    log_info "  Account: ${ACCOUNT_ID}"
    log_info "  S3 Bucket: ${S3_BUCKET_NAME}"
}

# Prompt for database password
get_db_password() {
    log_info "Setting database password..."
    
    if [ -z "$DB_PASSWORD" ]; then
        read -s -p "Enter RDS password (min 8 chars): " DB_PASSWORD
        echo
        
        if [ ${#DB_PASSWORD} -lt 8 ]; then
            log_error "Password must be at least 8 characters"
            exit 1
        fi
    fi
    
    export DB_PASSWORD
    log_success "Database password set"
}

# Prompt for vendor email
get_vendor_email() {
    log_info "Setting notification email..."
    
    if [ -z "$VENDOR_EMAIL" ]; then
        read -p "Enter email for notifications: " VENDOR_EMAIL
        
        if [[ ! "$VENDOR_EMAIL" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
            log_error "Invalid email format"
            exit 1
        fi
    fi
    
    export VENDOR_EMAIL
    log_success "Email configured: ${VENDOR_EMAIL}"
}

# Create S3 bucket
create_s3_bucket() {
    log_info "Creating S3 bucket..."
    
    if aws s3 ls "s3://${S3_BUCKET_NAME}" 2>&1 | grep -q 'NoSuchBucket'; then
        aws s3api create-bucket \
            --bucket ${S3_BUCKET_NAME} \
            --region ${AWS_REGION} \
            --create-bucket-configuration LocationConstraint=${AWS_REGION}
        
        aws s3api put-bucket-versioning \
            --bucket ${S3_BUCKET_NAME} \
            --versioning-configuration Status=Enabled
        
        aws s3api put-bucket-encryption \
            --bucket ${S3_BUCKET_NAME} \
            --server-side-encryption-configuration '{
                "Rules": [{
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "AES256"
                    }
                }]
            }'
        
        log_success "S3 bucket created: ${S3_BUCKET_NAME}"
    else
        log_warn "S3 bucket already exists: ${S3_BUCKET_NAME}"
    fi
}

# Create DynamoDB table
create_dynamodb_table() {
    log_info "Creating DynamoDB table..."
    
    if ! aws dynamodb describe-table --table-name UploadRecords &> /dev/null; then
        aws dynamodb create-table \
            --table-name UploadRecords \
            --attribute-definitions \
                AttributeName=upload_id,AttributeType=S \
                AttributeName=record_id,AttributeType=S \
                AttributeName=vendor_id,AttributeType=S \
            --key-schema \
                AttributeName=upload_id,KeyType=HASH \
                AttributeName=record_id,KeyType=RANGE \
            --billing-mode PAY_PER_REQUEST \
            --stream-specification StreamEnabled=true,StreamViewType=NEW_IMAGE \
            --global-secondary-indexes \
                "[{
                    \"IndexName\": \"VendorIndex\",
                    \"KeySchema\": [{\"AttributeName\":\"vendor_id\",\"KeyType\":\"HASH\"}],
                    \"Projection\": {\"ProjectionType\":\"ALL\"}
                }]" \
            --tags Key=Project,Value=${PROJECT_NAME}
        
        aws dynamodb wait table-exists --table-name UploadRecords
        
        export DYNAMODB_STREAM_ARN=$(aws dynamodb describe-table \
            --table-name UploadRecords \
            --query 'Table.LatestStreamArn' \
            --output text)
        
        log_success "DynamoDB table created with Streams"
    else
        log_warn "DynamoDB table already exists"
        
        export DYNAMODB_STREAM_ARN=$(aws dynamodb describe-table \
            --table-name UploadRecords \
            --query 'Table.LatestStreamArn' \
            --output text)
    fi
}

# Create SQS queues
create_sqs_queues() {
    log_info "Creating SQS queues..."
    
    # Create DLQ
    if ! aws sqs get-queue-url --queue-name product-validation-errors-dlq &> /dev/null; then
        aws sqs create-queue \
            --queue-name product-validation-errors-dlq \
            --attributes VisibilityTimeout=300,MessageRetentionPeriod=1209600
        
        log_success "DLQ created"
    else
        log_warn "DLQ already exists"
    fi
    
    export DLQ_ARN=$(aws sqs get-queue-attributes \
        --queue-url $(aws sqs get-queue-url --queue-name product-validation-errors-dlq --query 'QueueUrl' --output text) \
        --attribute-names QueueArn \
        --query 'Attributes.QueueArn' \
        --output text)
    
    # Create main queue
    if ! aws sqs get-queue-url --queue-name product-validation-errors &> /dev/null; then
        aws sqs create-queue \
            --queue-name product-validation-errors \
            --attributes "{
                \"VisibilityTimeout\": \"300\",
                \"MessageRetentionPeriod\": \"345600\",
                \"RedrivePolicy\": \"{\\\"deadLetterTargetArn\\\":\\\"${DLQ_ARN}\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"
            }"
        
        log_success "SQS queue created"
    else
        log_warn "SQS queue already exists"
    fi
    
    export SQS_QUEUE_URL=$(aws sqs get-queue-url \
        --queue-name product-validation-errors \
        --query 'QueueUrl' \
        --output text)
    
    export SQS_QUEUE_ARN=$(aws sqs get-queue-attributes \
        --queue-url ${SQS_QUEUE_URL} \
        --attribute-names QueueArn \
        --query 'Attributes.QueueArn' \
        --output text)
}

# Create SNS topic
create_sns_topic() {
    log_info "Creating SNS topic..."
    
    if ! aws sns list-topics | grep -q "product-upload-notifications"; then
        aws sns create-topic \
            --name product-upload-notifications \
            --tags Key=Project,Value=${PROJECT_NAME}
        
        log_success "SNS topic created"
    else
        log_warn "SNS topic already exists"
    fi
    
    export SNS_TOPIC_ARN=$(aws sns list-topics \
        --query 'Topics[?contains(TopicArn, `product-upload-notifications`)].TopicArn' \
        --output text)
    
    # Subscribe email
    log_info "Subscribing email to SNS topic..."
    aws sns subscribe \
        --topic-arn ${SNS_TOPIC_ARN} \
        --protocol email \
        --notification-endpoint ${VENDOR_EMAIL}
    
    log_warn "Check your email (${VENDOR_EMAIL}) and confirm the SNS subscription!"
}

# Create Secrets Manager secret
create_secret() {
    log_info "Creating Secrets Manager secret..."
    
    if ! aws secretsmanager describe-secret --secret-id ecommerce/rds/credentials &> /dev/null; then
        aws secretsmanager create-secret \
            --name ecommerce/rds/credentials \
            --secret-string "{
                \"username\": \"postgres\",
                \"password\": \"${DB_PASSWORD}\",
                \"host\": \"${RDS_ENDPOINT}\",
                \"port\": 5432,
                \"dbname\": \"ecommerce_platform\"
            }" \
            --tags Key=Project,Value=${PROJECT_NAME}
        
        log_success "Secret created"
    else
        log_warn "Secret already exists - updating..."
        
        aws secretsmanager update-secret \
            --secret-id ecommerce/rds/credentials \
            --secret-string "{
                \"username\": \"postgres\",
                \"password\": \"${DB_PASSWORD}\",
                \"host\": \"${RDS_ENDPOINT}\",
                \"port\": 5432,
                \"dbname\": \"ecommerce_platform\"
            }"
        
        log_success "Secret updated"
    fi
}

# Build and push Docker images
build_and_push_images() {
    log_info "Building and pushing Docker images..."
    
    # Create ECR repositories
    for REPO in csv-parser-lambda product-validator-lambda error-processor-lambda; do
        if ! aws ecr describe-repositories --repository-names ${REPO} &> /dev/null; then
            aws ecr create-repository \
                --repository-name ${REPO} \
                --image-scanning-configuration scanOnPush=true \
                --tags Key=Project,Value=${PROJECT_NAME}
            
            log_success "ECR repository created: ${REPO}"
        else
            log_warn "ECR repository already exists: ${REPO}"
        fi
    done
    
    # Authenticate to ECR
    log_info "Authenticating to ECR..."
    aws ecr get-login-password --region ${AWS_REGION} | \
        docker login --username AWS --password-stdin \
        ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com
    
    # Build and push images
    for LAMBDA in csv-parser product-validator error-processor; do
        log_info "Building ${LAMBDA}..."
        
        cd lambda_${LAMBDA//-/_}/
        
        docker build -t ${LAMBDA}-lambda:latest .
        docker tag ${LAMBDA}-lambda:latest \
            ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${LAMBDA}-lambda:latest
        docker push ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${LAMBDA}-lambda:latest
        
        cd ..
        
        log_success "Image pushed: ${LAMBDA}-lambda"
    done
}

# Create Lambda functions
create_lambda_functions() {
    log_info "Creating Lambda functions..."
    
    # CSV Parser
    if ! aws lambda get-function --function-name csv-parser &> /dev/null; then
        aws lambda create-function \
            --function-name csv-parser \
            --package-type Image \
            --code ImageUri=${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/csv-parser-lambda:latest \
            --role ${CSV_PARSER_ROLE_ARN} \
            --timeout 300 \
            --memory-size 512 \
            --environment Variables="{
                DYNAMODB_TABLE=UploadRecords,
                RDS_SECRET_NAME=ecommerce/rds/credentials,
                AWS_REGION=${AWS_REGION}
            }"
        
        log_success "CSV Parser Lambda created"
    else
        log_warn "CSV Parser Lambda already exists"
    fi
    
    # Similar for other Lambdas...
}

# Main 3_deployment
main() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║  E-Commerce Product Onboarding System - Automated Deployment  ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    
    check_prerequisites
    setup_environment
    get_db_password
    get_vendor_email
    
    echo ""
    log_info "Starting deployment..."
    echo ""
    
    create_s3_bucket
    create_dynamodb_table
    create_sqs_queues
    create_sns_topic
    
    log_info "Skipping RDS creation (manual step required)"
    log_warn "Please create RDS manually and set RDS_ENDPOINT environment variable"
    
    if [ -z "$RDS_ENDPOINT" ]; then
        read -p "Enter RDS endpoint: " RDS_ENDPOINT
        export RDS_ENDPOINT
    fi
    
    create_secret
    build_and_push_images
    
    echo ""
    log_success "Deployment complete!"
    echo ""
    log_info "Next steps:"
    log_info "  1. Confirm SNS email subscription"
    log_info "  2. Create Lambda IAM roles (see MASTER_DEPLOYMENT_GUIDE.md)"
    log_info "  3. Create Lambda functions"
    log_info "  4. Configure event triggers"
    log_info "  5. Upload test CSV"
    echo ""
}

# Run main
main "$@"
