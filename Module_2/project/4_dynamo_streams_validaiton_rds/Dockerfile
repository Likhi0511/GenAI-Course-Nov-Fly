# Dockerfile for Product Validator Lambda
# =========================================
# Uses AWS Lambda Python 3.11 base image
# Includes psycopg2 for PostgreSQL connectivity

FROM public.ecr.aws/lambda/python:3.11

# Install system dependencies for psycopg2
RUN yum install -y \
    postgresql-devel \
    gcc \
    python3-devel \
    && yum clean all

# Copy requirements file
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

# Install Python dependencies
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy Lambda function code
COPY lambda_product_validator.py ${LAMBDA_TASK_ROOT}/

# Set the CMD to your handler
CMD ["lambda_product_validator.lambda_handler"]
