"""
Generic Query Executor Lambda Function
This Lambda function executes SQL queries on RDS PostgreSQL database.
It's called by other Lambda functions to perform database operations.
Credentials are securely retrieved from AWS Secrets Manager.
"""
import json
import os
import boto3
from botocore.exceptions import ClientError
import psycopg2
from psycopg2 import pool
from typing import Dict, Any, List, Optional

# Global variables for connection pool and cached credentials
connection_pool = None
cached_credentials = None

def get_secret(secret_name: str) -> Dict[str, Any]:
    """
    Retrieve secret from AWS Secrets Manager.

    Args:
        secret_name: Name of the secret in Secrets Manager

    Returns:
        Dict containing the secret values
    """
    global cached_credentials

    # Return cached credentials if available
    if cached_credentials:
        return cached_credentials

    # Create Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=os.environ.get('AWS_REGION', 'us-east-1')
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        # Handle specific error cases
        error_code = e.response['Error']['Code']
        if error_code == 'DecryptionFailureException':
            raise Exception(f"Secrets Manager can't decrypt the secret: {e}")
        elif error_code == 'InternalServiceErrorException':
            raise Exception(f"Internal service error from Secrets Manager: {e}")
        elif error_code == 'InvalidParameterException':
            raise Exception(f"Invalid parameter in request: {e}")
        elif error_code == 'InvalidRequestException':
            raise Exception(f"Invalid request to Secrets Manager: {e}")
        elif error_code == 'ResourceNotFoundException':
            raise Exception(f"Secret '{secret_name}' not found: {e}")
        else:
            raise Exception(f"Error retrieving secret: {e}")

    # Parse and cache the secret
    if 'SecretString' in get_secret_value_response:
        secret = json.loads(get_secret_value_response['SecretString'])
        cached_credentials = secret
        return secret
    else:
        raise Exception("Secret is binary, expected JSON string")

def get_db_connection():
    """
    Get database connection from pool or create new one.
    Retrieves credentials from AWS Secrets Manager.
    """
    global connection_pool

    if connection_pool is None:
        # Get secret name from environment variable
        secret_name = os.environ.get('DB_SECRET_NAME')
        if not secret_name:
            raise Exception("DB_SECRET_NAME environment variable not set")

        # Retrieve credentials from Secrets Manager
        credentials = get_secret(secret_name)

        # Create connection pool
        connection_pool = psycopg2.pool.SimpleConnectionPool(
            1, 10,  # min and max connections
            host=credentials.get('host', os.environ.get('DB_HOST')),
            database=credentials.get('dbname', 'postgres'),
            user=credentials.get('username', os.environ.get('DB_USER')),
            password=credentials['password'],  # Password must come from secret
            port=credentials.get('port', os.environ.get('DB_PORT', '5432'))
        )

    return connection_pool.getconn()

def return_db_connection(conn):
    """Return connection to pool"""
    global connection_pool
    if connection_pool:
        connection_pool.putconn(conn)

def execute_query(query: str, params: Optional[tuple] = None, fetch: bool = True) -> Dict[str, Any]:
    """
    Execute SQL query and return results.

    Args:
        query: SQL query to execute
        params: Query parameters (for parameterized queries)
        fetch: Whether to fetch results (True for SELECT, False for INSERT/UPDATE/DELETE)

    Returns:
        Dict with success status, data, and row count
    """
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Execute query with parameters
        cursor.execute(query, params)

        result = {
            'success': True,
            'rowcount': cursor.rowcount
        }

        if fetch and cursor.description:
            # Fetch results for SELECT queries
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

            # Convert to list of dictionaries
            result['data'] = [dict(zip(columns, row)) for row in rows]
        else:
            # For INSERT/UPDATE/DELETE, commit the transaction
            conn.commit()
            result['data'] = None

        return result

    except psycopg2.Error as e:
        if conn:
            conn.rollback()

        return {
            'success': False,
            'error': str(e),
            'error_code': e.pgcode if hasattr(e, 'pgcode') else None
        }

    except Exception as e:
        if conn:
            conn.rollback()

        return {
            'success': False,
            'error': str(e)
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            return_db_connection(conn)

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler function.

    Expected event structure:
    {
        "query": "SELECT * FROM demo.customers WHERE customer_id = %s",
        "params": ["CUST001"],  # Optional
        "fetch": true  # Optional, default true
    }

    Required environment variables:
    - DB_SECRET_NAME: Name of the secret in AWS Secrets Manager
    - AWS_REGION: AWS region (optional, defaults to us-east-1)

    Expected secret structure in Secrets Manager:
    {
        "username": "your_username",
        "password": "your_password",
        "host": "your-rds-endpoint.rds.amazonaws.com",
        "port": "5432",
        "dbname": "your_database"
    }
    """
    try:
        # Parse event (might be from API Gateway or direct invocation)
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event

        # Extract query parameters
        query = body.get('query')
        params = body.get('params')
        fetch = body.get('fetch', True)

        # Validate input
        if not query:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'success': False,
                    'error': 'Query is required'
                })
            }

        # Convert params list to tuple if provided
        if params and isinstance(params, list):
            params = tuple(params)

        # Execute query
        result = execute_query(query, params, fetch)

        # Return response
        return {
            'statusCode': 200 if result['success'] else 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(result, default=str)  # default=str handles datetime serialization
        }

    except json.JSONDecodeError as e:
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': False,
                'error': f'Invalid JSON: {str(e)}'
            })
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': False,
                'error': str(e)
            })
        }