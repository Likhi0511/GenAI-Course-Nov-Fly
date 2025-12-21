"""
S3 CSV Customer Ingestion Lambda
================================

This Lambda function is triggered by an S3 event (or invoked manually)
to process a CSV file containing customer records.

Primary Responsibilities
------------------------
- Read a CSV file from S3
- Parse customer records
- Log customer details for auditing / debugging
- Return processing summary

Trigger Sources
---------------
1. S3 Object Created event
2. Direct invocation (bucket + key passed explicitly)

Typical Use Cases
-----------------
- Initial data ingestion / validation
- File-based integration from external systems
- Lightweight preprocessing before downstream pipelines
"""

import json
import logging
import boto3
import csv
from io import StringIO
from datetime import datetime
from botocore.exceptions import ClientError

# ---------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------
# AWS Clients
# ---------------------------------------------------------

# S3 client reused across invocations
s3_client = boto3.client("s3")


# ---------------------------------------------------------
# Lambda Entry Point
# ---------------------------------------------------------

def lambda_handler(event, context):
    """
    AWS Lambda entry point.

    Event Formats Supported
    -----------------------
    1. S3 Event Notification:
       {
         "Records": [
           {
             "s3": {
               "bucket": {"name": "my-bucket"},
               "object": {"key": "customers.csv"}
             }
           }
         ]
       }

    2. Direct Invocation:
       {
         "bucket": "my-bucket",
         "key": "customers.csv"
       }

    Returns
    -------
    {
        "statusCode": 200,
        "body": {
            "processed": <number_of_customers>
        }
    }
    """

    logger.info("Lambda execution started")

    try:
        # -------------------------------------------------
        # Identify S3 bucket and object key
        # -------------------------------------------------

        if "Records" in event:
            # Event triggered via S3 notification
            bucket = event["Records"][0]["s3"]["bucket"]["name"]
            key = event["Records"][0]["s3"]["object"]["key"]
            logger.info(f"S3 trigger detected: s3://{bucket}/{key}")
        else:
            # Direct Lambda invocation (useful for testing)
            bucket = event["bucket"]
            key = event["key"]
            logger.info(f"Manual invocation: s3://{bucket}/{key}")

        # -------------------------------------------------
        # Download CSV file from S3
        # -------------------------------------------------

        obj = s3_client.get_object(Bucket=bucket, Key=key)

        # Read file content as UTF-8 string
        content = obj["Body"].read().decode("utf-8")

        logger.info("CSV file successfully downloaded from S3")

        # -------------------------------------------------
        # Parse CSV Content
        # -------------------------------------------------

        reader = csv.DictReader(StringIO(content))

        # Filter out rows without customer_id (basic validation)
        customers = [
            row for row in reader
            if row.get("customer_id")
        ]

        # -------------------------------------------------
        # Structured Logging for Observability
        # -------------------------------------------------

        logger.info("=" * 80)
        logger.info("Parsed Customer Records")

        for index, customer in enumerate(customers, start=1):
            logger.info(f"\n[Customer {index}]")
            logger.info(f"  ID: {customer.get('customer_id')}")
            logger.info(f"  Name: {customer.get('customer_name')}")
            logger.info(f"  Email: {customer.get('email')}")
            logger.info(
                f"  Location: {customer.get('city')}, {customer.get('state')}"
            )

        logger.info(f"\nTotal customers processed: {len(customers)}")
        logger.info("=" * 80)

        # -------------------------------------------------
        # Success Response
        # -------------------------------------------------

        return {
            "statusCode": 200,
            "body": json.dumps({
                "processed": len(customers),
                "timestamp": datetime.utcnow().isoformat()
            })
        }

    except ClientError as e:
        # AWS-specific errors (S3 permissions, missing file, etc.)
        logger.error(f"AWS ClientError: {e}")

        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Failed to access S3 object",
                "details": str(e)
            })
        }

    except Exception as e:
        # Catch-all for unexpected failures
        logger.error(f"Unhandled exception: {e}", exc_info=True)

        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e)
            })
        }