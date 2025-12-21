# API Quick Reference Guide

## Base URL
```
https://<API_ID>.execute-api.<REGION>.amazonaws.com/prod
```

---

## Customers API

### 1. Create Customer
**Endpoint**: `POST /customers`

**Request Body**:
```json
{
  "customer_id": "CUST001",
  "customer_name": "John Doe",
  "email": "john@example.com",
  "city": "New York",
  "state": "NY"
}
```

**Response** (201 Created):
```json
{
  "success": true,
  "message": "Customer created successfully",
  "data": {
    "customer_id": "CUST001",
    "customer_name": "John Doe",
    "email": "john@example.com",
    "city": "New York",
    "state": "NY",
    "created_at": "2024-01-15T10:30:00"
  }
}
```

---

### 2. Get All Customers
**Endpoint**: `GET /customers`

**Response** (200 OK):
```json
{
  "success": true,
  "data": [
    {
      "customer_id": "CUST001",
      "customer_name": "John Doe",
      "email": "john@example.com",
      "city": "New York",
      "state": "NY",
      "created_at": "2024-01-15T10:30:00"
    },
    {
      "customer_id": "CUST002",
      "customer_name": "Jane Smith",
      "email": "jane@example.com",
      "city": "Los Angeles",
      "state": "CA",
      "created_at": "2024-01-15T11:00:00"
    }
  ],
  "count": 2
}
```

---

### 3. Get Customer by ID
**Endpoint**: `GET /customers?customer_id=CUST001`

**Response** (200 OK):
```json
{
  "success": true,
  "data": [
    {
      "customer_id": "CUST001",
      "customer_name": "John Doe",
      "email": "john@example.com",
      "city": "New York",
      "state": "NY",
      "created_at": "2024-01-15T10:30:00"
    }
  ],
  "count": 1
}
```

---

### 4. Update Customer
**Endpoint**: `PUT /customers/{customer_id}`

**Example**: `PUT /customers/CUST001`

**Request Body**:
```json
{
  "customer_name": "John Doe Updated",
  "email": "john.updated@example.com",
  "city": "Boston",
  "state": "MA"
}
```

**Response** (200 OK):
```json
{
  "success": true,
  "message": "Customer updated successfully",
  "data": {
    "customer_id": "CUST001",
    "customer_name": "John Doe Updated",
    "email": "john.updated@example.com",
    "city": "Boston",
    "state": "MA",
    "created_at": "2024-01-15T10:30:00"
  }
}
```

---

### 5. Delete Customer
**Endpoint**: `DELETE /customers/{customer_id}`

**Example**: `DELETE /customers/CUST001`

**Response** (200 OK):
```json
{
  "success": true,
  "message": "Customer CUST001 deleted successfully"
}
```

**Error Response** (400 Bad Request) - if customer has orders:
```json
{
  "success": false,
  "error": "Cannot delete customer. 5 orders exist for this customer."
}
```

---

## Orders API

### 1. Create Order
**Endpoint**: `POST /orders`

**Request Body**:
```json
{
  "order_id": "ORD001",
  "customer_id": "CUST001",
  "status": "pending",
  "total_amount": 150.75
}
```

**Response** (201 Created):
```json
{
  "success": true,
  "message": "Order created successfully",
  "data": {
    "order_id": "ORD001",
    "customer_id": "CUST001",
    "order_date": "2024-01-15T12:00:00",
    "status": "pending",
    "total_amount": 150.75
  }
}
```

**Error Response** (400 Bad Request) - invalid customer:
```json
{
  "success": false,
  "error": "Customer CUST999 does not exist"
}
```

---

### 2. Get All Orders
**Endpoint**: `GET /orders`

**Response** (200 OK):
```json
{
  "success": true,
  "data": [
    {
      "order_id": "ORD001",
      "customer_id": "CUST001",
      "order_date": "2024-01-15T12:00:00",
      "status": "pending",
      "total_amount": 150.75,
      "customer_name": "John Doe",
      "email": "john@example.com"
    },
    {
      "order_id": "ORD002",
      "customer_id": "CUST001",
      "order_date": "2024-01-15T13:00:00",
      "status": "shipped",
      "total_amount": 299.99,
      "customer_name": "John Doe",
      "email": "john@example.com"
    }
  ],
  "count": 2
}
```

---

### 3. Get Order by ID
**Endpoint**: `GET /orders?order_id=ORD001`

**Response** (200 OK):
```json
{
  "success": true,
  "data": [
    {
      "order_id": "ORD001",
      "customer_id": "CUST001",
      "order_date": "2024-01-15T12:00:00",
      "status": "pending",
      "total_amount": 150.75,
      "customer_name": "John Doe",
      "email": "john@example.com"
    }
  ],
  "count": 1
}
```

---

### 4. Get Orders by Customer
**Endpoint**: `GET /orders?customer_id=CUST001`

**Response** (200 OK):
```json
{
  "success": true,
  "data": [
    {
      "order_id": "ORD001",
      "customer_id": "CUST001",
      "order_date": "2024-01-15T12:00:00",
      "status": "pending",
      "total_amount": 150.75,
      "customer_name": "John Doe",
      "email": "john@example.com"
    },
    {
      "order_id": "ORD002",
      "customer_id": "CUST001",
      "order_date": "2024-01-15T13:00:00",
      "status": "shipped",
      "total_amount": 299.99,
      "customer_name": "John Doe",
      "email": "john@example.com"
    }
  ],
  "count": 2
}
```

---

### 5. Update Order
**Endpoint**: `PUT /orders/{order_id}`

**Example**: `PUT /orders/ORD001`

**Request Body**:
```json
{
  "status": "shipped",
  "total_amount": 175.99
}
```

**Response** (200 OK):
```json
{
  "success": true,
  "message": "Order updated successfully",
  "data": {
    "order_id": "ORD001",
    "customer_id": "CUST001",
    "order_date": "2024-01-15T12:00:00",
    "status": "shipped",
    "total_amount": 175.99
  }
}
```

---

### 6. Delete Order
**Endpoint**: `DELETE /orders/{order_id}`

**Example**: `DELETE /orders/ORD001`

**Response** (200 OK):
```json
{
  "success": true,
  "message": "Order ORD001 deleted successfully"
}
```

---

## Error Responses

### 400 Bad Request
```json
{
  "success": false,
  "error": "Missing required field: customer_id"
}
```

### 404 Not Found
```json
{
  "success": false,
  "error": "Customer CUST999 not found"
}
```

### 500 Internal Server Error
```json
{
  "success": false,
  "error": "Database connection failed"
}
```

---

## cURL Examples

### Create Customer
```bash
curl -X POST https://abc123.execute-api.us-east-1.amazonaws.com/prod/customers \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "CUST001",
    "customer_name": "John Doe",
    "email": "john@example.com",
    "city": "New York",
    "state": "NY"
  }'
```

### Get All Customers
```bash
curl https://abc123.execute-api.us-east-1.amazonaws.com/prod/customers
```

### Update Customer
```bash
curl -X PUT https://abc123.execute-api.us-east-1.amazonaws.com/prod/customers/CUST001 \
  -H "Content-Type: application/json" \
  -d '{
    "customer_name": "John Doe Updated",
    "city": "Boston"
  }'
```

### Delete Customer
```bash
curl -X DELETE https://abc123.execute-api.us-east-1.amazonaws.com/prod/customers/CUST001
```

### Create Order
```bash
curl -X POST https://abc123.execute-api.us-east-1.amazonaws.com/prod/orders \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORD001",
    "customer_id": "CUST001",
    "status": "pending",
    "total_amount": 150.75
  }'
```

### Get Orders by Customer
```bash
curl "https://abc123.execute-api.us-east-1.amazonaws.com/prod/orders?customer_id=CUST001"
```

---

## Postman Collection

Import this into Postman:

```json
{
  "info": {
    "name": "Customer Orders API",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "item": [
    {
      "name": "Customers",
      "item": [
        {
          "name": "Create Customer",
          "request": {
            "method": "POST",
            "header": [
              {
                "key": "Content-Type",
                "value": "application/json"
              }
            ],
            "body": {
              "mode": "raw",
              "raw": "{\n  \"customer_id\": \"CUST001\",\n  \"customer_name\": \"John Doe\",\n  \"email\": \"john@example.com\",\n  \"city\": \"New York\",\n  \"state\": \"NY\"\n}"
            },
            "url": {
              "raw": "{{base_url}}/customers",
              "host": ["{{base_url}}"],
              "path": ["customers"]
            }
          }
        },
        {
          "name": "Get All Customers",
          "request": {
            "method": "GET",
            "url": {
              "raw": "{{base_url}}/customers",
              "host": ["{{base_url}}"],
              "path": ["customers"]
            }
          }
        },
        {
          "name": "Update Customer",
          "request": {
            "method": "PUT",
            "header": [
              {
                "key": "Content-Type",
                "value": "application/json"
              }
            ],
            "body": {
              "mode": "raw",
              "raw": "{\n  \"customer_name\": \"John Doe Updated\",\n  \"city\": \"Boston\"\n}"
            },
            "url": {
              "raw": "{{base_url}}/customers/CUST001",
              "host": ["{{base_url}}"],
              "path": ["customers", "CUST001"]
            }
          }
        },
        {
          "name": "Delete Customer",
          "request": {
            "method": "DELETE",
            "url": {
              "raw": "{{base_url}}/customers/CUST001",
              "host": ["{{base_url}}"],
              "path": ["customers", "CUST001"]
            }
          }
        }
      ]
    },
    {
      "name": "Orders",
      "item": [
        {
          "name": "Create Order",
          "request": {
            "method": "POST",
            "header": [
              {
                "key": "Content-Type",
                "value": "application/json"
              }
            ],
            "body": {
              "mode": "raw",
              "raw": "{\n  \"order_id\": \"ORD001\",\n  \"customer_id\": \"CUST001\",\n  \"status\": \"pending\",\n  \"total_amount\": 150.75\n}"
            },
            "url": {
              "raw": "{{base_url}}/orders",
              "host": ["{{base_url}}"],
              "path": ["orders"]
            }
          }
        },
        {
          "name": "Get All Orders",
          "request": {
            "method": "GET",
            "url": {
              "raw": "{{base_url}}/orders",
              "host": ["{{base_url}}"],
              "path": ["orders"]
            }
          }
        },
        {
          "name": "Get Orders by Customer",
          "request": {
            "method": "GET",
            "url": {
              "raw": "{{base_url}}/orders?customer_id=CUST001",
              "host": ["{{base_url}}"],
              "path": ["orders"],
              "query": [
                {
                  "key": "customer_id",
                  "value": "CUST001"
                }
              ]
            }
          }
        },
        {
          "name": "Update Order",
          "request": {
            "method": "PUT",
            "header": [
              {
                "key": "Content-Type",
                "value": "application/json"
              }
            ],
            "body": {
              "mode": "raw",
              "raw": "{\n  \"status\": \"shipped\"\n}"
            },
            "url": {
              "raw": "{{base_url}}/orders/ORD001",
              "host": ["{{base_url}}"],
              "path": ["orders", "ORD001"]
            }
          }
        },
        {
          "name": "Delete Order",
          "request": {
            "method": "DELETE",
            "url": {
              "raw": "{{base_url}}/orders/ORD001",
              "host": ["{{base_url}}"],
              "path": ["orders", "ORD001"]
            }
          }
        }
      ]
    }
  ],
  "variable": [
    {
      "key": "base_url",
      "value": "https://abc123.execute-api.us-east-1.amazonaws.com/prod",
      "type": "string"
    }
  ]
}
```

---

## Status Codes

| Code | Description |
|------|-------------|
| 200  | OK - Request successful |
| 201  | Created - Resource created successfully |
| 400  | Bad Request - Invalid input or missing required fields |
| 404  | Not Found - Resource doesn't exist |
| 405  | Method Not Allowed - HTTP method not supported |
| 500  | Internal Server Error - Server/database error |

---

## Valid Order Statuses

- `pending`
- `processing`
- `shipped`
- `delivered`
- `cancelled`

You can use any status, but these are the recommended values.
