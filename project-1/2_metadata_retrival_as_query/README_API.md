# NL2SQL FastAPI Service

Natural Language to SQL query generation using S3 Vectors and OpenAI GPT-4.

## Architecture

```
User Question
    ↓
FastAPI Service
    ↓
S3 Vector Retrieval (Semantic + Procedural Memory)
    ↓
Context Building
    ↓
OpenAI GPT-4 (SQL Generation)
    ↓
SQL Query + Explanation
```

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements_api.txt
```

### 2. Set Environment Variables

```bash
export OPENAI_API_KEY="your-openai-key"
export AWS_ACCESS_KEY_ID="your-aws-key"
export AWS_SECRET_ACCESS_KEY="your-aws-secret"
export AWS_DEFAULT_REGION="us-east-1"
```

### 3. Ensure S3 Vectors are Ingested

Make sure you've run the ingestion script first:
```bash
python ingest_s3_vectors_corrected.py
```

## Running the API

### Start the Server

```bash
python nl2sql_api.py
```

Or with uvicorn directly:
```bash
uvicorn nl2sql_api:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at: http://localhost:8000

### API Documentation

Interactive docs: http://localhost:8000/docs

## Usage

### 1. Health Check

```bash
curl http://localhost:8000/health
```

### 2. Generate SQL Query

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Show me all customers in California"
  }'
```

Response:
```json
{
  "question": "Show me all customers in California",
  "sql_query": "SELECT * FROM customers WHERE state = 'CA'",
  "explanation": "This query retrieves all customer records where the state is California",
  "relevant_tables": ["customers"],
  "confidence": "high"
}
```

### 3. Using Python Client

```python
from test_nl2sql_api import NL2SQLClient

client = NL2SQLClient()

result = client.generate_query("Show me top 10 products by sales")
print(result['sql_query'])
```

### 4. Test with Multiple Queries

```bash
python test_nl2sql_api.py
```

## API Endpoints

### POST /query
Generate SQL query from natural language

**Request:**
```json
{
  "question": "your natural language question",
  "database": "ecommerce"
}
```

**Response:**
```json
{
  "question": "...",
  "sql_query": "...",
  "explanation": "...",
  "relevant_tables": ["table1", "table2"],
  "confidence": "high"
}
```

### POST /query/explain
Get SQL query with detailed retrieval information

**Response includes:**
- Generated SQL query
- Explanation
- Number of semantic chunks retrieved
- Number of procedural chunks retrieved
- Top tables used

### GET /health
Check service health

## Example Questions

```
"Show me all customers in California"
"What are the top 5 products by revenue?"
"List orders from last month"
"Find customers who ordered more than $1000"
"Show me products with low inventory"
"Get all orders for customer ID 123"
"What's the average order value by state?"
```

## How It Works

1. **Question Received**: FastAPI receives natural language question

2. **Vector Search**: 
   - Retrieves 8 semantic chunks (schema info: tables, columns, relationships)
   - Retrieves 3 procedural chunks (query examples)

3. **Context Building**:
   - Combines schema information
   - Adds similar query examples
   - Formats for LLM

4. **SQL Generation**:
   - Sends context + question to GPT-4
   - GPT-4 generates SQL with explanation
   - Returns structured response

5. **Response**: Returns SQL query, explanation, tables used, confidence level

## Configuration

Edit these variables in `nl2sql_api.py`:

```python
SEMANTIC_BUCKET = 'nl2sql-semantic-memory'
PROCEDURAL_BUCKET = 'nl2sql-procedural-memory'
AWS_REGION = 'us-east-1'
```

## Troubleshooting

**Error: "retriever not connected"**
- Ensure S3 vectors are ingested
- Check AWS credentials
- Verify bucket names exist

**Error: "Query generation failed"**
- Check OPENAI_API_KEY is set
- Verify OpenAI API quota
- Check logs for details

**Slow responses**
- First query takes longer (initializing retriever)
- Subsequent queries are faster
- Consider caching retriever globally

## Production Considerations

1. **Authentication**: Add API key authentication
2. **Rate Limiting**: Add rate limits per user
3. **Caching**: Cache frequent queries
4. **Database Connection**: Add actual DB execution
5. **Monitoring**: Add logging and metrics
6. **Error Handling**: More detailed error responses
