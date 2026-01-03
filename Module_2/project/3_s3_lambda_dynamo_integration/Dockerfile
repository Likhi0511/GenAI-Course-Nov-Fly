# Use AWS Lambda Python 3.11 base image
FROM public.ecr.aws/lambda/python:3.11

# ------------------------------------------------------------------------------
# Copy requirements and install dependencies
# ------------------------------------------------------------------------------
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# ------------------------------------------------------------------------------
# Copy Lambda handler code
# ------------------------------------------------------------------------------
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/

# ------------------------------------------------------------------------------
# IMPORTANT: Ensure handler file is readable by Lambda runtime
# ------------------------------------------------------------------------------
RUN chmod 755 ${LAMBDA_TASK_ROOT}/lambda_function.py

# ------------------------------------------------------------------------------
# Set Lambda entrypoint
# ------------------------------------------------------------------------------
CMD ["lambda_function.lambda_handler"]