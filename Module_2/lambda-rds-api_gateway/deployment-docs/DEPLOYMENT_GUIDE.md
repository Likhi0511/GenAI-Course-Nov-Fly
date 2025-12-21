# AWS Lambda RDS CRUD API - Deployment Guide

## Architecture Overview

This project implements a serverless CRUD API for PostgreSQL RDS using:
- **1 Generic Query Executor Lambda**: Executes SQL queries on RDS
- **2 CRUD API Lambdas**: Customers API and Orders API (each handles POST, GET, PUT, DELETE)
- **API Gateway**: REST API endpoints
- **ECR**: Docker container registry for Lambda images
- **RDS PostgreSQL**: Database with demo.customers and demo.orders tables

### Architecture Flow
```
Client → API Gateway → Customers/Orders Lambda → Generic Query Executor Lambda → RDS PostgreSQL
```

---

## Prerequisites

1. **AWS CLI** installed and configured
   ```bash
   aws configure
   # Enter: Access Key, Secret Key, Region (e.g., us-east-1), Output format (json)
   ```

2. **Docker** installed and running
   ```bash
   docker --version
   ```

3. **AWS Account** with permissions for:
   - Lambda
   - ECR
   - API Gateway
   - RDS
   - IAM
   - VPC (if RDS is in VPC)

4. **RDS PostgreSQL** instance running with:
   - Database: Your database name
   - Schema: `demo`
   - Tables: `customers` and `orders` (already created)
   - Security Group: Allow Lambda access

---

## Step 1: Create ECR Repositories

Create three ECR repositories for Docker images:

```bash
# Set variables
export AWS_REGION="us-east-1"
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Create repositories
aws ecr create-repository --repository-name generic-query-executor --region $AWS_REGION
aws ecr create-repository --repository-name customers-api --region $AWS_REGION
aws ecr create-repository --repository-name orders-api --region $AWS_REGION
```

**Output**: Note the `repositoryUri` for each repository.

---

## Step 2: Authenticate Docker to ECR

```bash
aws ecr get-login-password --region $AWS_REGION | \
docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```

---

## Step 3: Build and Push Docker Images

### 3.1 Build and Push Generic Query Executor

```bash
cd generic-query-executor

# Build Docker image
docker buildx build --platform linux/amd64 --output type=docker --provenance=false -t generic-query-executor:latest --no-cache .

# Tag image for ECR
docker tag generic-query-executor:latest \
$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/generic-query-executor:latest

# Push to ECR
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/generic-query-executor:latest

cd ..
```

### 3.2 Build and Push Customers API

```bash
cd customers-api

# Build Docker image
docker buildx build --platform linux/amd64 --output type=docker --provenance=false -t customers-api:latest --no-cache .


# Tag image for ECR
docker tag customers-api:latest \
$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/customers-api:latest

# Push to ECR
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/customers-api:latest

cd ..
```

### 3.3 Build and Push Orders API

```bash
cd orders-api

# Build Docker image
docker buildx build --platform linux/amd64 --output type=docker --provenance=false -t orders-api:latest --no-cache .


# Tag image for ECR
docker tag orders-api:latest \
$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/orders-api:latest

# Push to ECR
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/orders-api:latest

cd ..
```

---

## Step 4: Create IAM Roles for Lambda Functions

### 4.1 Create Role for Generic Query Executor

Create trust policy file `trust-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

Create the role:

```bash
aws iam create-role \
  --role-name GenericQueryExecutorRole \
  --assume-role-policy-document file://trust-policy.json

# Attach basic Lambda execution policy
aws iam attach-role-policy \
  --role-name GenericQueryExecutorRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

### 4.2 Create VPC Execution Policy (if RDS is in VPC)

Create `vpc-execution-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:CreateNetworkInterface",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DeleteNetworkInterface",
        "ec2:AssignPrivateIpAddresses",
        "ec2:UnassignPrivateIpAddresses"
      ],
      "Resource": "*"
    }
  ]
}
```

Attach VPC policy:

```bash
aws iam put-role-policy \
  --role-name GenericQueryExecutorRole \
  --policy-name VPCExecutionPolicy \
  --policy-document file://vpc-execution-policy.json
```

### 4.3 Create Role for Customers/Orders APIs

```bash
aws iam create-role \
  --role-name CustomersOrdersAPIRole \
  --assume-role-policy-document file://trust-policy.json

# Attach basic Lambda execution policy
aws iam attach-role-policy \
  --role-name CustomersOrdersAPIRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

Create `lambda-invoke-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "lambda:InvokeFunction"
      ],
      "Resource": "arn:aws:lambda:*:*:function:generic-query-executor"
    }
  ]
}
```

Attach invoke policy:

```bash
aws iam put-role-policy \
  --role-name CustomersOrdersAPIRole \
  --policy-name LambdaInvokePolicy \
  --policy-document file://lambda-invoke-policy.json
```

---

## Step 5: Create Lambda Functions

### 5.1 Get IAM Role ARNs

```bash
QUERY_EXECUTOR_ROLE_ARN=$(aws iam get-role --role-name GenericQueryExecutorRole --query 'Role.Arn' --output text)
API_ROLE_ARN=$(aws iam get-role --role-name CustomersOrdersAPIRole --query 'Role.Arn' --output text)
```

### 5.2 Create Generic Query Executor Lambda

Replace these values:
- `<YOUR_RDS_HOST>`: RDS endpoint (e.g., mydb.c9akciq32.us-east-1.rds.amazonaws.com)
- `<YOUR_DB_NAME>`: Database name
- `<YOUR_DB_USER>`: Database username
- `<YOUR_DB_PASSWORD>`: Database password
- `<SUBNET_ID_1>`, `<SUBNET_ID_2>`: Private subnet IDs where RDS is located
- `<SECURITY_GROUP_ID>`: Security group that can access RDS

```bash
aws lambda create-function \
  --function-name generic-query-executor \
  --package-type Image \
  --code ImageUri=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/generic-query-executor:latest \
  --role $QUERY_EXECUTOR_ROLE_ARN \
  --timeout 30 \
  --memory-size 512 \
  --environment Variables="{
      DB_HOST=<YOUR_RDS_HOST>,
      DB_NAME=<YOUR_DB_NAME>,
      DB_USER=<YOUR_DB_USER>,
      DB_PASSWORD=<YOUR_DB_PASSWORD>,
      DB_PORT=5432
    }" \
  --vpc-config SubnetIds=<SUBNET_ID_1>,<SUBNET_ID_2>,SecurityGroupIds=<SECURITY_GROUP_ID> \
  --region $AWS_REGION
```

**Example**:
```bash
aws lambda create-function \
  --function-name generic-query-executor \
  --package-type Image \
  --code ImageUri=123456789012.dkr.ecr.us-east-1.amazonaws.com/generic-query-executor:latest \
  --role arn:aws:iam::123456789012:role/GenericQueryExecutorRole \
  --timeout 30 \
  --memory-size 512 \
  --environment Variables="{
      DB_HOST=mydb.c9akciq32.us-east-1.rds.amazonaws.com,
      DB_NAME=postgres,
      DB_USER=postgres,
      DB_PASSWORD=YourSecurePassword,
      DB_PORT=5432
    }" \
  --vpc-config SubnetIds=subnet-12345,subnet-67890,SecurityGroupIds=sg-abc123 \
  --region us-east-1
```

### 5.3 Create Customers API Lambda

```bash
aws lambda create-function \
  --function-name customers-api \
  --package-type Image \
  --code ImageUri=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/customers-api:latest \
  --role $API_ROLE_ARN \
  --timeout 30 \
  --memory-size 256 \
  --environment Variables="{
      QUERY_EXECUTOR_FUNCTION=generic-query-executor
    }" \
  --region $AWS_REGION
```

### 5.4 Create Orders API Lambda

```bash
aws lambda create-function \
  --function-name orders-api \
  --package-type Image \
  --code ImageUri=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/orders-api:latest \
  --role $API_ROLE_ARN \
  --timeout 30 \
  --memory-size 256 \
  --environment Variables="{
      QUERY_EXECUTOR_FUNCTION=generic-query-executor
    }" \
  --region $AWS_REGION
```

---

## Step 6: Create API Gateway

### 6.1 Create REST API

```bash
API_ID=$(aws apigateway create-rest-api \
  --name "CustomerOrdersAPI" \
  --description "CRUD API for Customers and Orders" \
  --endpoint-configuration types=REGIONAL \
  --region $AWS_REGION \
  --query 'id' \
  --output text)

echo "API ID: $API_ID"

# Get root resource ID
ROOT_ID=$(aws apigateway get-resources \
  --rest-api-id $API_ID \
  --region $AWS_REGION \
  --query 'items[0].id' \
  --output text)
```

### 6.2 Create /customers Resource

```bash
CUSTOMERS_RESOURCE_ID=$(aws apigateway create-resource \
  --rest-api-id $API_ID \
  --parent-id $ROOT_ID \
  --path-part customers \
  --region $AWS_REGION \
  --query 'id' \
  --output text)

echo "Customers Resource ID: $CUSTOMERS_RESOURCE_ID"
```

### 6.3 Create /customers/{customer_id} Resource

```bash
CUSTOMER_ID_RESOURCE=$(aws apigateway create-resource \
  --rest-api-id $API_ID \
  --parent-id $CUSTOMERS_RESOURCE_ID \
  --path-part '{customer_id}' \
  --region $AWS_REGION \
  --query 'id' \
  --output text)

echo "Customer ID Resource: $CUSTOMER_ID_RESOURCE"
```

### 6.4 Create Methods for /customers

```bash
# POST /customers
aws apigateway put-method \
  --rest-api-id $API_ID \
  --resource-id $CUSTOMERS_RESOURCE_ID \
  --http-method POST \
  --authorization-type NONE \
  --region $AWS_REGION

aws apigateway put-integration \
  --rest-api-id $API_ID \
  --resource-id $CUSTOMERS_RESOURCE_ID \
  --http-method POST \
  --type AWS_PROXY \
  --integration-http-method POST \
  --uri arn:aws:apigateway:$AWS_REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:$AWS_REGION:$AWS_ACCOUNT_ID:function:customers-api/invocations \
  --region $AWS_REGION

# GET /customers
aws apigateway put-method \
  --rest-api-id $API_ID \
  --resource-id $CUSTOMERS_RESOURCE_ID \
  --http-method GET \
  --authorization-type NONE \
  --region $AWS_REGION

aws apigateway put-integration \
  --rest-api-id $API_ID \
  --resource-id $CUSTOMERS_RESOURCE_ID \
  --http-method GET \
  --type AWS_PROXY \
  --integration-http-method POST \
  --uri arn:aws:apigateway:$AWS_REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:$AWS_REGION:$AWS_ACCOUNT_ID:function:customers-api/invocations \
  --region $AWS_REGION
```

### 6.5 Create Methods for /customers/{customer_id}

```bash
# GET /customers/{customer_id}
aws apigateway put-method \
  --rest-api-id $API_ID \
  --resource-id $CUSTOMER_ID_RESOURCE \
  --http-method GET \
  --authorization-type NONE \
  --region $AWS_REGION

aws apigateway put-integration \
  --rest-api-id $API_ID \
  --resource-id $CUSTOMER_ID_RESOURCE \
  --http-method GET \
  --type AWS_PROXY \
  --integration-http-method POST \
  --uri arn:aws:apigateway:$AWS_REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:$AWS_REGION:$AWS_ACCOUNT_ID:function:customers-api/invocations \
  --region $AWS_REGION

# PUT /customers/{customer_id}
aws apigateway put-method \
  --rest-api-id $API_ID \
  --resource-id $CUSTOMER_ID_RESOURCE \
  --http-method PUT \
  --authorization-type NONE \
  --region $AWS_REGION

aws apigateway put-integration \
  --rest-api-id $API_ID \
  --resource-id $CUSTOMER_ID_RESOURCE \
  --http-method PUT \
  --type AWS_PROXY \
  --integration-http-method POST \
  --uri arn:aws:apigateway:$AWS_REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:$AWS_REGION:$AWS_ACCOUNT_ID:function:customers-api/invocations \
  --region $AWS_REGION

# DELETE /customers/{customer_id}
aws apigateway put-method \
  --rest-api-id $API_ID \
  --resource-id $CUSTOMER_ID_RESOURCE \
  --http-method DELETE \
  --authorization-type NONE \
  --region $AWS_REGION

aws apigateway put-integration \
  --rest-api-id $API_ID \
  --resource-id $CUSTOMER_ID_RESOURCE \
  --http-method DELETE \
  --type AWS_PROXY \
  --integration-http-method POST \
  --uri arn:aws:apigateway:$AWS_REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:$AWS_REGION:$AWS_ACCOUNT_ID:function:customers-api/invocations \
  --region $AWS_REGION
```

### 6.6 Create /orders Resources (Repeat for Orders)

```bash
# Create /orders resource
ORDERS_RESOURCE_ID=$(aws apigateway create-resource \
  --rest-api-id $API_ID \
  --parent-id $ROOT_ID \
  --path-part orders \
  --region $AWS_REGION \
  --query 'id' \
  --output text)

# Create /orders/{order_id} resource
ORDER_ID_RESOURCE=$(aws apigateway create-resource \
  --rest-api-id $API_ID \
  --parent-id $ORDERS_RESOURCE_ID \
  --path-part '{order_id}' \
  --region $AWS_REGION \
  --query 'id' \
  --output text)
```

### 6.7 Create Methods for Orders (Similar to Customers)

```bash
# POST /orders
aws apigateway put-method \
  --rest-api-id $API_ID \
  --resource-id $ORDERS_RESOURCE_ID \
  --http-method POST \
  --authorization-type NONE \
  --region $AWS_REGION

aws apigateway put-integration \
  --rest-api-id $API_ID \
  --resource-id $ORDERS_RESOURCE_ID \
  --http-method POST \
  --type AWS_PROXY \
  --integration-http-method POST \
  --uri arn:aws:apigateway:$AWS_REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:$AWS_REGION:$AWS_ACCOUNT_ID:function:orders-api/invocations \
  --region $AWS_REGION

# GET /orders
aws apigateway put-method \
  --rest-api-id $API_ID \
  --resource-id $ORDERS_RESOURCE_ID \
  --http-method GET \
  --authorization-type NONE \
  --region $AWS_REGION

aws apigateway put-integration \
  --rest-api-id $API_ID \
  --resource-id $ORDERS_RESOURCE_ID \
  --http-method GET \
  --type AWS_PROXY \
  --integration-http-method POST \
  --uri arn:aws:apigateway:$AWS_REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:$AWS_REGION:$AWS_ACCOUNT_ID:function:orders-api/invocations \
  --region $AWS_REGION

# PUT /orders/{order_id}
aws apigateway put-method \
  --rest-api-id $API_ID \
  --resource-id $ORDER_ID_RESOURCE \
  --http-method PUT \
  --authorization-type NONE \
  --region $AWS_REGION

aws apigateway put-integration \
  --rest-api-id $API_ID \
  --resource-id $ORDER_ID_RESOURCE \
  --http-method PUT \
  --type AWS_PROXY \
  --integration-http-method POST \
  --uri arn:aws:apigateway:$AWS_REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:$AWS_REGION:$AWS_ACCOUNT_ID:function:orders-api/invocations \
  --region $AWS_REGION

# DELETE /orders/{order_id}
aws apigateway put-method \
  --rest-api-id $API_ID \
  --resource-id $ORDER_ID_RESOURCE \
  --http-method DELETE \
  --authorization-type NONE \
  --region $AWS_REGION

aws apigateway put-integration \
  --rest-api-id $API_ID \
  --resource-id $ORDER_ID_RESOURCE \
  --http-method DELETE \
  --type AWS_PROXY \
  --integration-http-method POST \
  --uri arn:aws:apigateway:$AWS_REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:$AWS_REGION:$AWS_ACCOUNT_ID:function:orders-api/invocations \
  --region $AWS_REGION
```

---

## Step 7: Grant API Gateway Permission to Invoke Lambda

```bash
# Grant permission for customers-api
aws lambda add-permission \
  --function-name customers-api \
  --statement-id apigateway-customers \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:$AWS_REGION:$AWS_ACCOUNT_ID:$API_ID/*/*" \
  --region $AWS_REGION

# Grant permission for orders-api
aws lambda add-permission \
  --function-name orders-api \
  --statement-id apigateway-orders \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:$AWS_REGION:$AWS_ACCOUNT_ID:$API_ID/*/*" \
  --region $AWS_REGION
```

---

## Step 8: Deploy API Gateway

```bash
aws apigateway create-deployment \
  --rest-api-id $API_ID \
  --stage-name prod \
  --region $AWS_REGION
```

**Get API Endpoint**:
```bash
echo "API Base URL: https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod"
```

---

## Step 9: Test the APIs

### Test Customers API

#### Create Customer (POST)
```bash
curl -X POST \
  https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod/customers \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "CUST001",
    "customer_name": "John Doe",
    "email": "john@example.com",
    "city": "New York",
    "state": "NY"
  }'
```

#### Get All Customers (GET)
```bash
curl https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod/customers
```

#### Get Specific Customer (GET)
```bash
curl "https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod/customers?customer_id=CUST001"
```

#### Update Customer (PUT)
```bash
curl -X PUT \
  https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod/customers/CUST001 \
  -H "Content-Type: application/json" \
  -d '{
    "customer_name": "John Doe Updated",
    "city": "Boston"
  }'
```

#### Delete Customer (DELETE)
```bash
curl -X DELETE \
  https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod/customers/CUST001
```

### Test Orders API

#### Create Order (POST)
```bash
curl -X POST \
  https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod/orders \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORD001",
    "customer_id": "CUST001",
    "status": "pending",
    "total_amount": 150.75
  }'
```

#### Get All Orders (GET)
```bash
curl https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod/orders
```

#### Get Orders by Customer (GET)
```bash
curl "https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod/orders?customer_id=CUST001"
```

#### Update Order (PUT)
```bash
curl -X PUT \
  https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod/orders/ORD001 \
  -H "Content-Type: application/json" \
  -d '{
    "status": "shipped"
  }'
```

#### Delete Order (DELETE)
```bash
curl -X DELETE \
  https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod/orders/ORD001
```

---

## Step 10: Update Lambda Functions (When Code Changes)

When you update the code:

```bash
# Navigate to the function directory
cd customers-api

# Rebuild Docker image
docker build -t customers-api:latest .

# Retag and push
docker tag customers-api:latest \
$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/customers-api:latest

docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/customers-api:latest

# Update Lambda function
aws lambda update-function-code \
  --function-name customers-api \
  --image-uri $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/customers-api:latest \
  --region $AWS_REGION
```

---

## Monitoring and Logs

### View Lambda Logs

```bash
# View logs for generic-query-executor
aws logs tail /aws/lambda/generic-query-executor --follow

# View logs for customers-api
aws logs tail /aws/lambda/customers-api --follow

# View logs for orders-api
aws logs tail /aws/lambda/orders-api --follow
```

### View API Gateway Logs

Enable CloudWatch Logs for API Gateway:

```bash
aws apigateway update-stage \
  --rest-api-id $API_ID \
  --stage-name prod \
  --patch-operations \
    op=replace,path=/accessLogSettings/destinationArn,value=arn:aws:logs:$AWS_REGION:$AWS_ACCOUNT_ID:log-group:/aws/apigateway/CustomerOrdersAPI
```

---

## Troubleshooting

### Common Issues

1. **Lambda timeout connecting to RDS**
   - Verify Lambda is in same VPC as RDS
   - Check security group allows Lambda security group
   - Verify subnet has route to NAT Gateway (if using private subnet)

2. **Permission denied errors**
   - Check IAM roles have correct policies attached
   - Verify API Gateway has permission to invoke Lambda

3. **Cold start issues**
   - Increase Lambda memory (more memory = more CPU)
   - Consider provisioned concurrency for production

4. **Connection pool exhausted**
   - Increase max connections in RDS parameter group
   - Adjust Lambda concurrency limits

---

## Clean Up

To delete all resources:

```bash
# Delete API Gateway
aws apigateway delete-rest-api --rest-api-id $API_ID --region $AWS_REGION

# Delete Lambda functions
aws lambda delete-function --function-name generic-query-executor --region $AWS_REGION
aws lambda delete-function --function-name customers-api --region $AWS_REGION
aws lambda delete-function --function-name orders-api --region $AWS_REGION

# Delete ECR repositories
aws ecr delete-repository --repository-name generic-query-executor --force --region $AWS_REGION
aws ecr delete-repository --repository-name customers-api --force --region $AWS_REGION
aws ecr delete-repository --repository-name orders-api --force --region $AWS_REGION

# Delete IAM roles
aws iam delete-role --role-name GenericQueryExecutorRole
aws iam delete-role --role-name CustomersOrdersAPIRole
```

---

## Project Structure

```
lambda-rds-project/
├── generic-query-executor/
│   ├── Dockerfile
│   ├── lambda_function.py
│   └── requirements.txt
├── customers-api/
│   ├── Dockerfile
│   ├── lambda_function.py
│   └── requirements.txt
├── orders-api/
│   ├── Dockerfile
│   ├── lambda_function.py
│   └── requirements.txt
└── deployment-docs/
    └── DEPLOYMENT_GUIDE.md (this file)
```

---

## Security Best Practices

1. **Never hardcode credentials** - Use AWS Secrets Manager or Systems Manager Parameter Store
2. **Use VPC** - Deploy Lambda and RDS in private subnets
3. **Enable encryption** - RDS encryption at rest, SSL/TLS for connections
4. **Implement authentication** - Add Cognito or API keys to API Gateway
5. **Use least privilege** - IAM roles should have minimal permissions
6. **Enable CloudWatch Logs** - Monitor all Lambda executions
7. **Input validation** - Validate all user inputs before executing queries
8. **SQL injection protection** - Use parameterized queries (already implemented)

---

## Cost Optimization

1. **Right-size Lambda memory** - Start with 512 MB, adjust based on metrics
2. **Use reserved concurrency** - Prevent runaway costs
3. **Enable RDS autoscaling** - Scale storage automatically
4. **Monitor CloudWatch metrics** - Set billing alarms
5. **Consider Aurora Serverless** - For variable workloads

---

## Next Steps

1. Add authentication (Cognito, API keys)
2. Implement caching (API Gateway cache, ElastiCache)
3. Add input validation and sanitization
4. Implement rate limiting
5. Set up CI/CD pipeline
6. Add automated tests
7. Implement monitoring and alerting
8. Add API documentation (Swagger/OpenAPI)
