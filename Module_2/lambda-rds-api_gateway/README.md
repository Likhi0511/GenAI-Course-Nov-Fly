# AWS Lambda RDS CRUD API Project

Serverless CRUD API for PostgreSQL RDS using AWS Lambda (Docker/ECR), API Gateway, and generic query executor pattern.

## 📋 Project Overview

This project implements a complete serverless REST API with:
- **3 Lambda Functions** (Docker-based, deployed via ECR)
  - 1 Generic Query Executor (database access layer)
  - 2 CRUD APIs (Customers and Orders)
- **API Gateway** REST API with full CRUD operations
- **PostgreSQL RDS** database backend
- **Clean Architecture** with separation of concerns

## 🏗️ Architecture

```
┌─────────┐      ┌──────────────┐      ┌────────────┐      ┌──────────────┐      ┌──────────┐
│ Client  │─────▶│ API Gateway  │─────▶│ Customers  │─────▶│   Generic    │─────▶│   RDS    │
│ (Browser│      │ REST API     │      │   Lambda   │      │    Query     │      │PostgreSQL│
│  /curl) │      │              │      │            │      │  Executor    │      │          │
└─────────┘      └──────────────┘      └────────────┘      │   Lambda     │      └──────────┘
                         │                                   └──────────────┘             
                         │                                          ▲
                         │              ┌────────────┐             │
                         └─────────────▶│   Orders   │─────────────┘
                                        │   Lambda   │
                                        └────────────┘
```

## 🔥 Key Features

### Generic Query Executor Pattern
- **Single database access point** - All SQL executions go through one Lambda
- **Connection pooling** - Efficient database connection management
- **Parameterized queries** - SQL injection protection
- **Error handling** - Comprehensive error management

### CRUD API Lambdas
- **RESTful design** - Standard HTTP methods (GET, POST, PUT, DELETE)
- **Input validation** - Required field checking
- **Foreign key validation** - Ensures data integrity
- **CORS enabled** - Ready for web applications
- **JSON responses** - Consistent API format

### Docker-based Deployment
- **ECR images** - Container-based Lambda functions
- **Easy updates** - Docker build & push workflow
- **Dependency management** - No zip file size limits
- **Reproducible builds** - Consistent environments

## 📁 Project Structure

```
lambda-rds-project/
├── generic-query-executor/       # Database access layer
│   ├── Dockerfile
│   ├── lambda_function.py
│   └── requirements.txt          # psycopg2-binary
│
├── customers-api/                # Customers CRUD API
│   ├── Dockerfile
│   ├── lambda_function.py
│   └── requirements.txt          # boto3
│
├── orders-api/                   # Orders CRUD API
│   ├── Dockerfile
│   ├── lambda_function.py
│   └── requirements.txt          # boto3
│
└── deployment-docs/
    ├── DEPLOYMENT_GUIDE.md       # Complete deployment instructions
    ├── API_REFERENCE.md          # API endpoints and examples
    └── README.md                 # This file
```

## 🚀 Quick Start

### Prerequisites
- AWS CLI configured
- Docker installed
- RDS PostgreSQL instance running
- Tables created (demo.customers, demo.orders)

### Deploy in 3 Steps

1. **Create ECR Repositories**
```bash
aws ecr create-repository --repository-name generic-query-executor
aws ecr create-repository --repository-name customers-api
aws ecr create-repository --repository-name orders-api
```

2. **Build and Push Docker Images**
```bash
# Generic Query Executor
cd generic-query-executor
docker build -t generic-query-executor:latest .
docker tag generic-query-executor:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/generic-query-executor:latest
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/generic-query-executor:latest

# Repeat for customers-api and orders-api
```

3. **Create Lambda Functions**
```bash
aws lambda create-function \
  --function-name generic-query-executor \
  --package-type Image \
  --code ImageUri=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/generic-query-executor:latest \
  --role <LAMBDA_EXECUTION_ROLE_ARN> \
  --environment Variables="{DB_HOST=<RDS_HOST>,DB_NAME=<DB_NAME>,DB_USER=<DB_USER>,DB_PASSWORD=<DB_PASSWORD>}"
```

**For complete step-by-step instructions**, see [DEPLOYMENT_GUIDE.md](deployment-docs/DEPLOYMENT_GUIDE.md)

## 📚 Documentation

- **[Deployment Guide](deployment-docs/DEPLOYMENT_GUIDE.md)** - Complete deployment instructions
- **[API Reference](deployment-docs/API_REFERENCE.md)** - API endpoints, request/response examples

## 🔌 API Endpoints

### Customers API
- `POST /customers` - Create customer
- `GET /customers` - Get all customers
- `GET /customers?customer_id=X` - Get specific customer
- `PUT /customers/{customer_id}` - Update customer
- `DELETE /customers/{customer_id}` - Delete customer

### Orders API
- `POST /orders` - Create order
- `GET /orders` - Get all orders
- `GET /orders?customer_id=X` - Get orders by customer
- `GET /orders?order_id=X` - Get specific order
- `PUT /orders/{order_id}` - Update order
- `DELETE /orders/{order_id}` - Delete order

## 🧪 Testing

### Create a Customer
```bash
curl -X POST https://your-api.execute-api.us-east-1.amazonaws.com/prod/customers \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "CUST001",
    "customer_name": "John Doe",
    "email": "john@example.com",
    "city": "New York",
    "state": "NY"
  }'
```

### Create an Order
```bash
curl -X POST https://your-api.execute-api.us-east-1.amazonaws.com/prod/orders \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORD001",
    "customer_id": "CUST001",
    "status": "pending",
    "total_amount": 150.75
  }'
```

See [API_REFERENCE.md](deployment-docs/API_REFERENCE.md) for complete examples.

## 🛡️ Security Features

- **Parameterized queries** - Prevents SQL injection
- **Connection pooling** - Efficient resource usage
- **IAM roles** - No hardcoded credentials
- **VPC integration** - Lambda can access private RDS
- **Foreign key validation** - Data integrity checks
- **CORS enabled** - Secure cross-origin requests

## 💰 Cost Estimation

### Monthly costs for moderate usage (10,000 requests/day):

| Service | Usage | Monthly Cost |
|---------|-------|--------------|
| API Gateway | 300K requests | ~$1.05 |
| Lambda (3 functions) | 600K invocations, 256-512 MB | ~$2.50 |
| RDS PostgreSQL (db.t3.micro) | 730 hours | ~$13.14 |
| Data Transfer | 10 GB OUT | ~$0.90 |
| **Total** | | **~$17.59** |

*Free tier covers most of Lambda and API Gateway for first 12 months*

## 🔧 Troubleshooting

### Lambda can't connect to RDS
- ✅ Check Lambda is in same VPC as RDS
- ✅ Verify security group rules allow Lambda → RDS
- ✅ Confirm subnet has NAT Gateway route

### API Gateway returns 500 error
- ✅ Check CloudWatch Logs for Lambda errors
- ✅ Verify IAM role has correct permissions
- ✅ Test Lambda function directly

### Cold start latency
- ✅ Increase Lambda memory (more CPU)
- ✅ Consider Provisioned Concurrency
- ✅ Keep functions warm with scheduled pings

## 📈 Performance Optimization

1. **Connection Pooling** - Generic executor maintains connection pool
2. **Right-size Memory** - Start with 512 MB, monitor CloudWatch
3. **Minimize Package Size** - Use slim Docker base images
4. **Enable X-Ray** - Trace requests across services
5. **API Gateway Caching** - Cache GET requests (optional)

## 🔄 Update Workflow

When code changes:

```bash
# 1. Rebuild Docker image
docker build -t customers-api:latest .

# 2. Retag and push to ECR
docker tag customers-api:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/customers-api:latest
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/customers-api:latest

# 3. Update Lambda function
aws lambda update-function-code \
  --function-name customers-api \
  --image-uri $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/customers-api:latest
```

## 📊 Monitoring

### CloudWatch Logs
```bash
# View Lambda logs
aws logs tail /aws/lambda/customers-api --follow

# View API Gateway logs
aws logs tail /aws/apigateway/CustomerOrdersAPI --follow
```

### Metrics to Monitor
- Lambda duration (p50, p99)
- Lambda errors and throttles
- API Gateway 4xx/5xx errors
- RDS CPU and connections
- Lambda concurrent executions

## 🤝 Contributing

This is a reference implementation. Feel free to:
- Add authentication (Cognito, API keys)
- Implement caching (Redis, DynamoDB)
- Add pagination for large datasets
- Implement soft deletes
- Add audit logging

## 📝 License

MIT License - Feel free to use for your projects!

## 🙋 Support

For issues or questions:
1. Check [DEPLOYMENT_GUIDE.md](deployment-docs/DEPLOYMENT_GUIDE.md)
2. Review CloudWatch Logs
3. Verify IAM permissions
4. Check VPC/Security Group configuration

## 🎯 Next Steps

1. ✅ Deploy infrastructure
2. ✅ Test all endpoints
3. ⬜ Add authentication
4. ⬜ Implement caching
5. ⬜ Set up CI/CD pipeline
6. ⬜ Add automated tests
7. ⬜ Configure monitoring alerts
8. ⬜ Add API documentation (Swagger)

---

**Built with** ❤️ **using AWS Lambda, API Gateway, ECR, and RDS PostgreSQL**
