"""
Customers API Lambda Function
=============================

This Lambda function exposes a REST-style API for managing customers.
It supports CRUD operations (Create, Read, Update, Delete) by delegating
all database access to a generic query executor Lambda.

Architecture Pattern
--------------------
API Gateway
    -> Customers API Lambda (this file)
        -> Generic Query Executor Lambda
            -> Database (Postgres / Aurora / RDS etc.)

Why this design?
----------------
- Keeps DB logic centralized and reusable
- Simplifies security (single DB-access Lambda)
- Enables consistent logging, retries, and monitoring
"""

import json
import os
import boto3
from typing import Dict, Any
from datetime import datetime

# ---------------------------------------------------------
# AWS Clients
# ---------------------------------------------------------

# Lambda client used to invoke the generic query executor
lambda_client = boto3.client('lambda')

# Name of the query executor Lambda
# Can be overridden via environment variables
QUERY_EXECUTOR_FUNCTION = os.environ.get(
    'QUERY_EXECUTOR_FUNCTION',
    'generic-query-executor'
)

# ---------------------------------------------------------
# Helper: Invoke Generic Query Executor
# ---------------------------------------------------------

def invoke_query_executor(
    query: str,
    params: list = None,
    fetch: bool = True
) -> Dict[str, Any]:
    """
    Invokes the generic query executor Lambda.

    Parameters
    ----------
    query : str
        SQL query to execute (parameterized).
    params : list, optional
        Query parameters corresponding to %s placeholders.
    fetch : bool
        If True, returns query results (SELECT / RETURNING).
        If False, executes without fetching data (DELETE).

    Returns
    -------
    Dict[str, Any]
        Normalized response from query executor:
        {
            "success": bool,
            "data": list (optional),
            "rowcount": int (optional),
            "error": str (optional)
        }
    """

    # Payload expected by the query executor Lambda
    payload = {
        "query": query,
        "params": params or [],
        "fetch": fetch
    }

    # Synchronous Lambda invocation
    response = lambda_client.invoke(
        FunctionName=QUERY_EXECUTOR_FUNCTION,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload)
    )

    # Read raw payload
    response_payload = json.loads(response["Payload"].read())

    # Handle API Gateway–style responses (body is a string)
    if isinstance(response_payload.get("body"), str):
        return json.loads(response_payload["body"])

    return response_payload


# ---------------------------------------------------------
# POST /customers
# ---------------------------------------------------------

def create_customer(event_body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Creates a new customer record.

    Endpoint
    --------
    POST /customers

    Expected Request Body
    ---------------------
    {
        "customer_id": "CUST001",
        "customer_name": "John Doe",
        "email": "john@example.com",
        "city": "New York",
        "state": "NY"
    }

    Returns
    -------
    201 Created
        Customer record if successful
    400 Bad Request
        Missing required fields
    500 Internal Server Error
        DB or execution error
    """

    # Required fields validation
    required_fields = ["customer_id", "customer_name", "email"]
    for field in required_fields:
        if field not in event_body:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "success": False,
                    "error": f"Missing required field: {field}"
                })
            }

    # SQL INSERT with RETURNING to fetch created record
    query = """
    INSERT INTO demo.customers
    (customer_id, customer_name, email, city, state, created_at)
    VALUES (%s, %s, %s, %s, %s, %s)
    RETURNING customer_id, customer_name, email, city, state, created_at
    """

    # Parameter order must match query placeholders
    params = [
        event_body["customer_id"],
        event_body["customer_name"],
        event_body["email"],
        event_body.get("city"),
        event_body.get("state"),
        datetime.utcnow()  # Server-side timestamp
    ]

    result = invoke_query_executor(query, params, fetch=True)

    if result.get("success"):
        return {
            "statusCode": 201,
            "body": json.dumps({
                "success": True,
                "message": "Customer created successfully",
                "data": result.get("data", [])[0] if result.get("data") else None
            }, default=str)
        }

    return {
        "statusCode": 500,
        "body": json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error")
        })
    }


# ---------------------------------------------------------
# GET /customers
# ---------------------------------------------------------

def get_customers(query_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fetches customers.

    Endpoint
    --------
    GET /customers
    GET /customers?customer_id=CUST001

    Behavior
    --------
    - If customer_id is provided → fetch single customer
    - Else → fetch all customers ordered by creation date
    """

    customer_id = query_params.get("customer_id")

    if customer_id:
        query = """
        SELECT customer_id, customer_name, email, city, state, created_at
        FROM demo.customers
        WHERE customer_id = %s
        """
        params = [customer_id]
    else:
        query = """
        SELECT customer_id, customer_name, email, city, state, created_at
        FROM demo.customers
        ORDER BY created_at DESC
        """
        params = []

    result = invoke_query_executor(query, params, fetch=True)

    if result.get("success"):
        data = result.get("data", [])
        return {
            "statusCode": 200,
            "body": json.dumps({
                "success": True,
                "data": data,
                "count": len(data)
            }, default=str)
        }

    return {
        "statusCode": 500,
        "body": json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error")
        })
    }


# ---------------------------------------------------------
# PUT /customers/{customer_id}
# ---------------------------------------------------------

def update_customer(customer_id: str, event_body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Updates an existing customer.

    Endpoint
    --------
    PUT /customers/{customer_id}

    Notes
    -----
    - Only provided fields are updated
    - Dynamic SQL is constructed safely using placeholders
    """

    if not customer_id:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "success": False,
                "error": "customer_id is required"
            })
        }

    update_fields = []
    params = []

    # Build update fields dynamically
    for field in ["customer_name", "email", "city", "state"]:
        if field in event_body:
            update_fields.append(f"{field} = %s")
            params.append(event_body[field])

    if not update_fields:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "success": False,
                "error": "No fields to update"
            })
        }

    # customer_id is always last param
    params.append(customer_id)

    query = f"""
    UPDATE demo.customers
    SET {', '.join(update_fields)}
    WHERE customer_id = %s
    RETURNING customer_id, customer_name, email, city, state, created_at
    """

    result = invoke_query_executor(query, params, fetch=True)

    if result.get("success"):
        if result.get("rowcount", 0) == 0:
            return {
                "statusCode": 404,
                "body": json.dumps({
                    "success": False,
                    "error": f"Customer {customer_id} not found"
                })
            }

        return {
            "statusCode": 200,
            "body": json.dumps({
                "success": True,
                "message": "Customer updated successfully",
                "data": result.get("data", [])[0] if result.get("data") else None
            }, default=str)
        }

    return {
        "statusCode": 500,
        "body": json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error")
        })
    }


# ---------------------------------------------------------
# DELETE /customers/{customer_id}
# ---------------------------------------------------------

def delete_customer(customer_id: str) -> Dict[str, Any]:
    """
    Deletes a customer.

    Safety Checks
    -------------
    - Prevents deletion if customer has existing orders
    """

    if not customer_id:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "success": False,
                "error": "customer_id is required"
            })
        }

    # Referential integrity check
    check_query = """
    SELECT COUNT(*) AS order_count
    FROM demo.orders
    WHERE customer_id = %s
    """

    check_result = invoke_query_executor(check_query, [customer_id], fetch=True)

    if check_result.get("success") and check_result.get("data"):
        if check_result["data"][0].get("order_count", 0) > 0:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "success": False,
                    "error": "Cannot delete customer with existing orders"
                })
            }

    delete_query = """
    DELETE FROM demo.customers
    WHERE customer_id = %s
    """

    result = invoke_query_executor(delete_query, [customer_id], fetch=False)

    if result.get("success"):
        return {
            "statusCode": 200,
            "body": json.dumps({
                "success": True,
                "message": f"Customer {customer_id} deleted successfully"
            })
        }

    return {
        "statusCode": 500,
        "body": json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error")
        })
    }


# ---------------------------------------------------------
# Lambda Entry Point
# ---------------------------------------------------------

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda entry point.

    Responsibilities
    ----------------
    - Parse API Gateway request
    - Route based on HTTP method
    - Attach CORS headers
    - Handle unexpected exceptions safely
    """

    try:
        http_method = event.get(
            "httpMethod",
            event.get("requestContext", {}).get("http", {}).get("method")
        )

        path_parameters = event.get("pathParameters") or {}
        query_parameters = event.get("queryStringParameters") or {}

        body = {}
        if event.get("body"):
            body = json.loads(event["body"])

        # Route requests
        if http_method == "POST":
            response = create_customer(body)
        elif http_method == "GET":
            response = get_customers(query_parameters)
        elif http_method == "PUT":
            response = update_customer(
                path_parameters.get("customer_id") or path_parameters.get("id"),
                body
            )
        elif http_method == "DELETE":
            response = delete_customer(
                path_parameters.get("customer_id") or path_parameters.get("id")
            )
        else:
            response = {
                "statusCode": 405,
                "body": json.dumps({
                    "success": False,
                    "error": f"Method {http_method} not allowed"
                })
            }

        # Add standard CORS headers
        response.setdefault("headers", {})
        response["headers"].update({
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"
        })

        return response

    except Exception as e:
        # Fail-safe error handling
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