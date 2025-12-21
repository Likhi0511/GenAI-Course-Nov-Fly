"""
Orders API Lambda Function
=========================

This Lambda function exposes REST-style endpoints for managing orders.
It performs CRUD operations on the `demo.orders` table by delegating
all database access to a shared Generic Query Executor Lambda.

Architecture Pattern
--------------------
API Gateway
    -> Orders API Lambda (this file)
        -> Generic Query Executor Lambda
            -> RDS PostgreSQL

Why this design?
----------------
- Keeps business logic separate from database access
- Ensures consistent DB access patterns across services
- Centralizes security, secrets, and connection pooling
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
lambda_client = boto3.client("lambda")

# Name of the generic query executor Lambda
# Can be overridden using environment variables
QUERY_EXECUTOR_FUNCTION = os.environ.get(
    "QUERY_EXECUTOR_FUNCTION",
    "generic-query-executor"
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
    Invoke the Generic Query Executor Lambda.

    Parameters
    ----------
    query : str
        Parameterized SQL query (%s placeholders).
    params : list, optional
        Parameters for the SQL query.
    fetch : bool
        Whether results should be fetched and returned.

    Returns
    -------
    Dict[str, Any]
        Normalized response containing:
        - success
        - data (optional)
        - rowcount (optional)
        - error (optional)
    """

    payload = {
        "query": query,
        "params": params or [],
        "fetch": fetch
    }

    # Synchronous invocation so caller waits for DB result
    response = lambda_client.invoke(
        FunctionName=QUERY_EXECUTOR_FUNCTION,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload)
    )

    response_payload = json.loads(response["Payload"].read())

    # Handle API Gateway-style responses
    if isinstance(response_payload.get("body"), str):
        return json.loads(response_payload["body"])

    return response_payload


# ---------------------------------------------------------
# POST /orders
# ---------------------------------------------------------

def create_order(event_body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new order.

    Endpoint
    --------
    POST /orders

    Expected Request Body
    ---------------------
    {
        "order_id": "ORD001",
        "customer_id": "CUST001",
        "status": "pending",
        "total_amount": 150.75
    }

    Business Rules
    --------------
    - customer_id must exist in customers table
    - status defaults to 'pending' if not provided
    """

    # Validate required fields
    required_fields = ["order_id", "customer_id", "total_amount"]
    for field in required_fields:
        if field not in event_body:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "success": False,
                    "error": f"Missing required field: {field}"
                })
            }

    # Ensure referenced customer exists (FK-style validation)
    check_query = """
    SELECT customer_id
    FROM demo.customers
    WHERE customer_id = %s
    """

    check_result = invoke_query_executor(
        check_query,
        [event_body["customer_id"]],
        fetch=True
    )

    if not check_result.get("success") or not check_result.get("data"):
        return {
            "statusCode": 400,
            "body": json.dumps({
                "success": False,
                "error": f"Customer {event_body['customer_id']} does not exist"
            })
        }

    # Insert new order
    query = """
    INSERT INTO demo.orders
    (order_id, customer_id, order_date, status, total_amount)
    VALUES (%s, %s, %s, %s, %s)
    RETURNING order_id, customer_id, order_date, status, total_amount
    """

    params = [
        event_body["order_id"],
        event_body["customer_id"],
        datetime.utcnow(),                       # Order creation timestamp
        event_body.get("status", "pending"),     # Default order status
        event_body["total_amount"]
    ]

    result = invoke_query_executor(query, params, fetch=True)

    if result.get("success"):
        return {
            "statusCode": 201,
            "body": json.dumps({
                "success": True,
                "message": "Order created successfully",
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
# GET /orders
# ---------------------------------------------------------

def get_orders(query_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retrieve orders.

    Endpoint
    --------
    GET /orders
    GET /orders?order_id=ORD001
    GET /orders?customer_id=CUST001

    Behavior
    --------
    - order_id → fetch specific order
    - customer_id → fetch all orders for a customer
    - no filters → fetch all orders
    """

    order_id = query_params.get("order_id")
    customer_id = query_params.get("customer_id")

    if order_id:
        query = """
        SELECT o.order_id, o.customer_id, o.order_date, o.status, o.total_amount,
               c.customer_name, c.email
        FROM demo.orders o
        JOIN demo.customers c ON o.customer_id = c.customer_id
        WHERE o.order_id = %s
        """
        params = [order_id]

    elif customer_id:
        query = """
        SELECT o.order_id, o.customer_id, o.order_date, o.status, o.total_amount,
               c.customer_name, c.email
        FROM demo.orders o
        JOIN demo.customers c ON o.customer_id = c.customer_id
        WHERE o.customer_id = %s
        ORDER BY o.order_date DESC
        """
        params = [customer_id]

    else:
        query = """
        SELECT o.order_id, o.customer_id, o.order_date, o.status, o.total_amount,
               c.customer_name, c.email
        FROM demo.orders o
        JOIN demo.customers c ON o.customer_id = c.customer_id
        ORDER BY o.order_date DESC
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
# PUT /orders/{order_id}
# ---------------------------------------------------------

def update_order(order_id: str, event_body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update an existing order.

    Endpoint
    --------
    PUT /orders/{order_id}

    Updatable Fields
    ----------------
    - status
    - total_amount
    """

    if not order_id:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "success": False,
                "error": "order_id is required"
            })
        }

    update_fields = []
    params = []

    # Build dynamic update query safely
    if "status" in event_body:
        update_fields.append("status = %s")
        params.append(event_body["status"])

    if "total_amount" in event_body:
        update_fields.append("total_amount = %s")
        params.append(event_body["total_amount"])

    if not update_fields:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "success": False,
                "error": "No fields to update"
            })
        }

    # order_id used in WHERE clause
    params.append(order_id)

    query = f"""
    UPDATE demo.orders
    SET {', '.join(update_fields)}
    WHERE order_id = %s
    RETURNING order_id, customer_id, order_date, status, total_amount
    """

    result = invoke_query_executor(query, params, fetch=True)

    if result.get("success"):
        if result.get("rowcount", 0) == 0:
            return {
                "statusCode": 404,
                "body": json.dumps({
                    "success": False,
                    "error": f"Order {order_id} not found"
                })
            }

        return {
            "statusCode": 200,
            "body": json.dumps({
                "success": True,
                "message": "Order updated successfully",
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
# DELETE /orders/{order_id}
# ---------------------------------------------------------

def delete_order(order_id: str) -> Dict[str, Any]:
    """
    Delete an order.

    Endpoint
    --------
    DELETE /orders/{order_id}
    """

    if not order_id:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "success": False,
                "error": "order_id is required"
            })
        }

    query = """
    DELETE FROM demo.orders
    WHERE order_id = %s
    """

    result = invoke_query_executor(query, [order_id], fetch=False)

    if result.get("success"):
        if result.get("rowcount", 0) == 0:
            return {
                "statusCode": 404,
                "body": json.dumps({
                    "success": False,
                    "error": f"Order {order_id} not found"
                })
            }

        return {
            "statusCode": 200,
            "body": json.dumps({
                "success": True,
                "message": f"Order {order_id} deleted successfully"
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
    - Handle unexpected failures safely
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
            body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]

        # Route request
        if http_method == "POST":
            response = create_order(body)
        elif http_method == "GET":
            response = get_orders(query_parameters)
        elif http_method == "PUT":
            response = update_order(
                path_parameters.get("order_id") or path_parameters.get("id"),
                body
            )
        elif http_method == "DELETE":
            response = delete_order(
                path_parameters.get("order_id") or path_parameters.get("id")
            )
        else:
            response = {
                "statusCode": 405,
                "body": json.dumps({
                    "success": False,
                    "error": f"Method {http_method} not allowed"
                })
            }

        # Standard CORS headers
        response.setdefault("headers", {})
        response["headers"].update({
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"
        })

        return response

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