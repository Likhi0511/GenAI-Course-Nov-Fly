"""
Generic Query Executor Lambda
=============================

This Lambda function acts as a **database access layer** for all application
Lambdas. It executes parameterized SQL queries against an RDS PostgreSQL
database using credentials stored securely in AWS Secrets Manager.

Architecture Role
-----------------
Business Lambda (Customers, Orders, etc.)
    -> Generic Query Executor Lambda (this file)
        -> RDS PostgreSQL

Why this design?
----------------
- Centralized database access & security
- Reusable query execution logic
- Simplified IAM and secrets handling
- Connection pooling for performance optimization
"""

import json
import os
import boto3
from botocore.exceptions import ClientError
import psycopg2
from psycopg2 import pool
from typing import Dict, Any, Optional

# ---------------------------------------------------------
# Global State (Reused Across Lambda Invocations)
# ---------------------------------------------------------

# PostgreSQL connection pool (created once per warm Lambda)
connection_pool = None

# Cached DB credentials to avoid repeated Secrets Manager calls
cached_credentials = None


# ---------------------------------------------------------
# Secrets Manager Integration
# ---------------------------------------------------------

def get_secret(secret_name: str) -> Dict[str, Any]:
    """
    Retrieve database credentials from AWS Secrets Manager.

    This function:
    - Fetches credentials only once per Lambda container
    - Caches them in memory for subsequent invocations

    Args
    ----
    secret_name : str
        Name of the secret in AWS Secrets Manager

    Returns
    -------
    Dict[str, Any]
        Parsed JSON secret containing DB credentials

    Raises
    ------
    Exception
        If secret retrieval or parsing fails
    """
    global cached_credentials

    # Return cached credentials if already loaded
    if cached_credentials:
        return cached_credentials

    # Create Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name="secretsmanager",
        region_name=os.environ.get("AWS_REGION", "us-east-1")
    )

    try:
        response = client.get_secret_value(SecretId=secret_name)

    except ClientError as e:
        # Explicit handling of Secrets Manager failure scenarios
        error_code = e.response["Error"]["Code"]

        if error_code == "DecryptionFailureException":
            raise Exception("Secrets Manager cannot decrypt the secret")
        elif error_code == "InternalServiceErrorException":
            raise Exception("Secrets Manager internal service error")
        elif error_code == "InvalidParameterException":
            raise Exception("Invalid parameter while fetching secret")
        elif error_code == "InvalidRequestException":
            raise Exception("Invalid request to Secrets Manager")
        elif error_code == "ResourceNotFoundException":
            raise Exception(f"Secret '{secret_name}' not found")
        else:
            raise Exception(f"Unexpected Secrets Manager error: {str(e)}")

    # Secrets Manager returns secrets either as string or binary
    if "SecretString" in response:
        secret = json.loads(response["SecretString"])
        cached_credentials = secret  # Cache for reuse
        return secret

    raise Exception("Unsupported secret format (binary secret)")


# ---------------------------------------------------------
# Database Connection Pool Management
# ---------------------------------------------------------

def get_db_connection():
    """
    Acquire a database connection from the pool.

    Behavior
    --------
    - Initializes a PostgreSQL connection pool on first invocation
    - Reuses pooled connections for subsequent calls

    Returns
    -------
    psycopg2.connection
        Active database connection
    """
    global connection_pool

    if connection_pool is None:
        # Secret name must be provided via environment variable
        secret_name = os.environ.get("DB_SECRET_NAME")
        if not secret_name:
            raise Exception("DB_SECRET_NAME environment variable is not set")

        # Fetch DB credentials securely
        credentials = get_secret(secret_name)

        # Initialize PostgreSQL connection pool
        connection_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            host=credentials.get("host", os.environ.get("DB_HOST")),
            database=credentials.get("dbname", "postgres"),
            user=credentials.get("username", os.environ.get("DB_USER")),
            password=credentials["password"],  # MUST come from secret
            port=credentials.get("port", os.environ.get("DB_PORT", "5432"))
        )

    return connection_pool.getconn()


def return_db_connection(conn):
    """
    Return a database connection back to the pool.

    This ensures connections are reused efficiently and
    prevents connection leaks.
    """
    global connection_pool
    if connection_pool:
        connection_pool.putconn(conn)


# ---------------------------------------------------------
# Core Query Execution Logic
# ---------------------------------------------------------

def execute_query(
    query: str,
    params: Optional[tuple] = None,
    fetch: bool = True
) -> Dict[str, Any]:
    """
    Execute a SQL query against PostgreSQL.

    Supports:
    - SELECT queries (fetch=True)
    - INSERT / UPDATE / DELETE (fetch=False or RETURNING)

    Args
    ----
    query : str
        SQL query with parameter placeholders (%s)
    params : tuple, optional
        Query parameters
    fetch : bool
        Whether to fetch and return query results

    Returns
    -------
    Dict[str, Any]
        {
            "success": bool,
            "rowcount": int,
            "data": list | None,
            "error": str (optional)
        }
    """
    conn = None
    cursor = None

    try:
        # Acquire DB connection
        conn = get_db_connection()
        cursor = conn.cursor()

        # Execute parameterized query (prevents SQL injection)
        cursor.execute(query, params)

        result = {
            "success": True,
            "rowcount": cursor.rowcount
        }

        # Handle SELECT / RETURNING queries
        if fetch and cursor.description:
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

            # Convert rows into list of dictionaries
            result["data"] = [dict(zip(columns, row)) for row in rows]
        else:
            # Commit transactional queries
            conn.commit()
            result["data"] = None

        return result

    except psycopg2.Error as e:
        # Roll back transaction on DB errors
        if conn:
            conn.rollback()

        return {
            "success": False,
            "error": str(e),
            "error_code": getattr(e, "pgcode", None)
        }

    except Exception as e:
        if conn:
            conn.rollback()

        return {
            "success": False,
            "error": str(e)
        }

    finally:
        # Always clean up resources
        if cursor:
            cursor.close()
        if conn:
            return_db_connection(conn)


# ---------------------------------------------------------
# Lambda Entry Point
# ---------------------------------------------------------

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda entry point.

    Expected Event Payload
    ----------------------
    {
        "query": "SELECT * FROM demo.customers WHERE customer_id = %s",
        "params": ["CUST001"],
        "fetch": true
    }

    Environment Variables
    ---------------------
    - DB_SECRET_NAME : Secrets Manager secret name
    - AWS_REGION     : AWS region (optional)

    Returns
    -------
    API Gateway–compatible HTTP response
    """
    try:
        # Support both API Gateway and direct Lambda invocation
        body = json.loads(event["body"]) if isinstance(event.get("body"), str) else event

        query = body.get("query")
        params = body.get("params")
        fetch = body.get("fetch", True)

        # Input validation
        if not query:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*"
                },
                "body": json.dumps({
                    "success": False,
                    "error": "Query is required"
                })
            }

        # Convert params list to tuple for psycopg2
        if params and isinstance(params, list):
            params = tuple(params)

        # Execute SQL query
        result = execute_query(query, params, fetch)

        return {
            "statusCode": 200 if result["success"] else 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps(result, default=str)
        }

    except json.JSONDecodeError as e:
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "success": False,
                "error": f"Invalid JSON payload: {str(e)}"
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "success": False,
                "error": str(e)
            })
        }