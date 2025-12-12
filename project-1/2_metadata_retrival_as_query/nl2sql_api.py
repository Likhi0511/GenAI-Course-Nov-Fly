"""
FastAPI NL2SQL Service
Natural Language to SQL query generation using S3 Vectors and OpenAI
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, List, Optional
import logging

from langchain_openai import ChatOpenAI
from s3_vector_retriever import S3VectorRetriever

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="NL2SQL API",
    description="Natural Language to SQL Query Generation API",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
SEMANTIC_BUCKET = 'nl2sql-semantic-memory'
PROCEDURAL_BUCKET = 'nl2sql-procedural-memory'
AWS_REGION = 'us-east-1'

# Initialize retriever (lazy loading)
retriever = None

# Initialize OpenAI
llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
    max_tokens=2000
)


class QueryRequest(BaseModel):
    """Request model for NL2SQL query"""
    question: str
    database: Optional[str] = "ecommerce"
    max_results: Optional[int] = None


class QueryResponse(BaseModel):
    """Response model for NL2SQL query"""
    question: str
    sql_query: str
    explanation: str
    relevant_tables: List[str]
    confidence: str
    context_used: Optional[Dict] = None  # Add context details


def get_retriever():
    """Lazy load retriever"""
    global retriever
    if retriever is None:
        retriever = S3VectorRetriever(
            semantic_bucket=SEMANTIC_BUCKET,
            procedural_bucket=PROCEDURAL_BUCKET,
            aws_region=AWS_REGION
        )
    return retriever


def extract_context_details(semantic_results: List[Dict], procedural_results: List[Dict]) -> Dict:
    """Extract detailed context information from retrieved vectors"""

    details = {
        "tables": {},
        "columns": [],
        "relationships": [],
        "example_queries": []
    }

    # Process semantic results
    for vec in semantic_results:
        metadata = vec.get('metadata', {})
        # Text is stored in metadata since S3 Vectors only returns metadata
        text = metadata.get('text', '')
        distance = vec.get('distance', 0)

        table_name = metadata.get('table_name', 'unknown')
        entity_type = metadata.get('entity_type', 'unknown')
        column_name = metadata.get('column_name', '')

        # Initialize table if not exists
        if table_name not in details['tables']:
            details['tables'][table_name] = {
                'columns': [],
                'relationships': [],
                'description': ''
            }

        # Extract columns
        if entity_type == 'column' and column_name:
            details['columns'].append({
                'table': table_name,
                'column': column_name,
                'description': text[:200] + '...' if len(text) > 200 else text,
                'full_text': text,
                'relevance_score': round(1 - distance, 3)
            })
            if column_name not in details['tables'][table_name]['columns']:
                details['tables'][table_name]['columns'].append(column_name)

        # Extract relationships
        elif entity_type == 'relationship':
            # Extract key information from text
            join_condition = ''
            if 'JOIN_CONDITION:' in text:
                join_start = text.find('JOIN_CONDITION:')
                join_end = text.find('\n', join_start)
                if join_end != -1:
                    join_condition = text[join_start:join_end].replace('JOIN_CONDITION:', '').strip()

            details['relationships'].append({
                'description': text[:300] + '...' if len(text) > 300 else text,
                'join_condition': join_condition,
                'full_text': text,
                'relevance_score': round(1 - distance, 3)
            })

            # Add to table relationships
            if text not in details['tables'][table_name]['relationships']:
                details['tables'][table_name]['relationships'].append(text[:150])

        # Extract table info
        elif entity_type == 'table':
            if not details['tables'][table_name]['description']:
                details['tables'][table_name]['description'] = text[:200] + '...' if len(text) > 200 else text

    # Process procedural results (query examples)
    for vec in procedural_results:
        metadata = vec.get('metadata', {})
        # Text is stored in metadata since S3 Vectors only returns metadata
        text = metadata.get('text', '')
        distance = vec.get('distance', 0)

        # Extract SQL examples from text
        sql_examples = []
        if 'EXAMPLES:' in text:
            examples_section = text.split('EXAMPLES:')[1]
            # Split by bullet points or dashes
            example_lines = [line.strip() for line in examples_section.split('\n') if line.strip().startswith('-')]
            sql_examples = [line.lstrip('- ').strip() for line in example_lines if 'SELECT' in line.upper()]

        # Extract use case description
        use_case = ''
        if 'DESCRIPTION:' in text:
            desc_start = text.find('DESCRIPTION:')
            desc_end = text.find('\n\n', desc_start)
            if desc_end != -1:
                use_case = text[desc_start:desc_end].replace('DESCRIPTION:', '').strip()

        details['example_queries'].append({
            'summary': text[:200] + '...' if len(text) > 200 else text,
            'use_case': use_case,
            'sql_examples': sql_examples,
            'table': metadata.get('table_name', 'unknown'),
            'full_text': text,
            'relevance_score': round(1 - distance, 3)
        })

    return details


def build_context(semantic_results: List[Dict], procedural_results: List[Dict]) -> str:
    """Build context string from retrieved vectors"""

    context_parts = []

    # Add semantic memory (schema information)
    if semantic_results:
        context_parts.append("=== DATABASE SCHEMA ===\n")
        for vec in semantic_results:
            text = vec.get('text', '')
            metadata = vec.get('metadata', {})
            table = metadata.get('table_name', 'unknown')
            entity = metadata.get('entity_type', 'unknown')

            context_parts.append(f"[{table}.{entity}]")
            context_parts.append(text)
            context_parts.append("")

    # Add procedural memory (query examples)
    if procedural_results:
        context_parts.append("\n=== SIMILAR QUERY EXAMPLES ===\n")
        for vec in procedural_results:
            text = vec.get('text', '')
            context_parts.append(text)
            context_parts.append("")

    return "\n".join(context_parts)


def generate_sql_query(question: str, context: str) -> Dict:
    """Generate SQL query using OpenAI"""

    prompt = f"""You are an expert SQL query generator for an e-commerce database.

Given the database schema and example queries below, generate a SQL query to answer the user's question.

{context}

User Question: {question}

Requirements:
1. Generate ONLY valid SQL (PostgreSQL syntax)
2. Use proper JOIN conditions based on the schema
3. Include appropriate WHERE clauses
4. Use meaningful column aliases
5. Consider the query examples for patterns

Respond in this exact JSON format:
{{
    "sql_query": "your SQL query here",
    "explanation": "brief explanation of what the query does",
    "relevant_tables": ["table1", "table2"],
    "confidence": "high/medium/low"
}}

Do not include any markdown formatting or code blocks - just the raw JSON."""

    try:
        # Call OpenAI
        response = llm.invoke(prompt)
        result_text = response.content

        # Parse JSON response
        import json
        result = json.loads(result_text)

        return result

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response: {e}")
        logger.error(f"Response text: {result_text}")
        raise HTTPException(status_code=500, detail="Failed to parse LLM response")
    except Exception as e:
        logger.error(f"Query generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query generation failed: {str(e)}")


@app.get("/")
def read_root():
    """Health check endpoint"""
    return {
        "status": "running",
        "service": "NL2SQL API",
        "version": "1.0.0"
    }


@app.get("/health")
def health_check():
    """Detailed health check"""
    try:
        # Test retriever connection
        r = get_retriever()
        return {
            "status": "healthy",
            "retriever": "connected",
            "llm": "ready"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


@app.post("/query", response_model=QueryResponse)
def generate_query(request: QueryRequest):
    """
    Generate SQL query from natural language question

    Example request:
    ```json
    {
        "question": "Show me all customers in California who ordered last month",
        "database": "ecommerce"
    }
    ```
    """

    try:
        logger.info(f"Received query: {request.question}")

        # Step 1: Retrieve relevant context from S3 Vectors
        r = get_retriever()
        results = r.search_both(request.question, semantic_k=8, procedural_k=3)

        semantic_results = results['semantic']
        procedural_results = results['procedural']

        logger.info(f"Retrieved {len(semantic_results)} semantic + {len(procedural_results)} procedural vectors")

        # Step 2: Extract context details
        context_details = extract_context_details(semantic_results, procedural_results)

        # Step 3: Build context for LLM
        context = build_context(semantic_results, procedural_results)

        # Step 4: Generate SQL query using OpenAI
        result = generate_sql_query(request.question, context)

        # Step 5: Return response with context details
        return QueryResponse(
            question=request.question,
            sql_query=result['sql_query'],
            explanation=result['explanation'],
            relevant_tables=result['relevant_tables'],
            confidence=result['confidence'],
            context_used=context_details
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Query processing failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/query/explain")
def explain_query(request: QueryRequest):
    """
    Generate SQL query with detailed explanation
    """

    try:
        # Get the query first
        query_result = generate_query(request)

        # Add retrieval details
        r = get_retriever()
        results = r.search_both(request.question, semantic_k=8, procedural_k=3)

        return {
            "query": query_result.dict(),
            "retrieval_details": {
                "semantic_chunks": len(results['semantic']),
                "procedural_chunks": len(results['procedural']),
                "top_tables": list(set([
                    vec.get('metadata', {}).get('table_name', 'unknown')
                    for vec in results['semantic'][:5]
                ]))
            }
        }

    except Exception as e:
        logger.exception("Explain query failed")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    # Run server
    uvicorn.run(
        "nl2sql_api:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info"
    )