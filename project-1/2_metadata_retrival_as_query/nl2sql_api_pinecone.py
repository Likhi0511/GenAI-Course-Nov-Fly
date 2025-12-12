"""
FastAPI NL2SQL Service with Pinecone
Natural Language to SQL query generation using Pinecone vector database
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
import logging
import json

from openai import OpenAI
from pinecone_retriever import PineconeRetriever

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="NL2SQL API with Pinecone",
    description="Convert natural language to SQL queries using Pinecone semantic memory",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global retriever (lazy loaded)
retriever = None


def get_retriever() -> PineconeRetriever:
    """Lazy load retriever"""
    global retriever
    if retriever is None:
        retriever = PineconeRetriever(index_name='nl2sql-semantic-memory')
    return retriever


# Request/Response Models
class QueryRequest(BaseModel):
    question: str
    database: Optional[str] = "ecommerce"
    max_results: Optional[int] = None


class QueryResponse(BaseModel):
    question: str
    sql_query: str
    explanation: str
    relevant_tables: List[str]
    confidence: str
    context_used: Optional[Dict] = None


def extract_context_details(semantic_results: List[Dict], procedural_results: List[Dict]) -> Dict:
    """Extract detailed context information from retrieved vectors"""
    
    details = {
        "tables": {},
        "columns": [],
        "relationships": [],
        "example_queries": []
    }
    
    # Process semantic results (Pinecone uses 'score' instead of 'distance')
    for vec in semantic_results:
        metadata = vec.get('metadata', {})
        text = metadata.get('text', '')
        score = vec.get('score', 0)  # Pinecone score (0-1, higher is better)
        
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
                'relevance_score': round(score, 3)  # Use score directly
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
                'relevance_score': round(score, 3)
            })
            
            if text not in details['tables'][table_name]['relationships']:
                details['tables'][table_name]['relationships'].append(text[:150])
        
        # Extract table info
        elif entity_type == 'table':
            if not details['tables'][table_name]['description']:
                details['tables'][table_name]['description'] = text[:200] + '...' if len(text) > 200 else text
    
    # Process procedural results (query examples)
    for vec in procedural_results:
        metadata = vec.get('metadata', {})
        text = metadata.get('text', '')
        score = vec.get('score', 0)
        
        # Extract SQL examples from text
        sql_examples = []
        if 'EXAMPLES:' in text:
            examples_section = text.split('EXAMPLES:')[1]
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
            'relevance_score': round(score, 3)
        })
    
    return details


def build_context(semantic_results: List[Dict], procedural_results: List[Dict]) -> str:
    """Build context string for LLM from retrieved vectors"""
    
    context_parts = []
    
    # Add semantic memory (schema info)
    if semantic_results:
        context_parts.append("=== DATABASE SCHEMA CONTEXT ===\n")
        for vec in semantic_results:
            metadata = vec.get('metadata', {})
            text = metadata.get('text', '')
            if text:
                context_parts.append(text)
                context_parts.append("\n---\n")
    
    # Add procedural memory (query examples)
    if procedural_results:
        context_parts.append("\n=== QUERY EXAMPLE PATTERNS ===\n")
        for vec in procedural_results:
            metadata = vec.get('metadata', {})
            text = metadata.get('text', '')
            if text:
                context_parts.append(text)
                context_parts.append("\n---\n")
    
    return "\n".join(context_parts)


def generate_sql_query(question: str, context: str) -> Dict:
    """Generate SQL query using OpenAI"""
    
    client = OpenAI()
    
    prompt = f"""You are an expert SQL query generator. Given a natural language question and database schema context, generate an accurate SQL query.

DATABASE CONTEXT:
{context}

USER QUESTION: {question}

Generate a SQL query that answers this question. Return your response as JSON with these fields:
- sql_query: The complete SQL query
- explanation: Brief explanation of what the query does
- relevant_tables: List of tables used
- confidence: "high", "medium", or "low" based on how well the question matches the schema

Return ONLY valid JSON, no markdown formatting."""

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a SQL expert. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        
        result = response.choices[0].message.content.strip()
        
        # Clean up markdown if present
        if result.startswith('```json'):
            result = result.replace('```json', '').replace('```', '').strip()
        elif result.startswith('```'):
            result = result.replace('```', '').strip()
        
        return json.loads(result)
        
    except Exception as e:
        logger.error(f"SQL generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate SQL: {str(e)}")


@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "nl2sql-api-pinecone",
        "version": "1.0.0"
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
        
        # Step 1: Retrieve relevant context from Pinecone
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
    Generate SQL query with detailed retrieval information
    """
    
    try:
        r = get_retriever()
        results = r.search_both(request.question, semantic_k=8, procedural_k=3)
        
        context_details = extract_context_details(results['semantic'], results['procedural'])
        context = build_context(results['semantic'], results['procedural'])
        
        sql_result = generate_sql_query(request.question, context)
        
        return {
            "question": request.question,
            "sql_query": sql_result['sql_query'],
            "explanation": sql_result['explanation'],
            "relevant_tables": sql_result['relevant_tables'],
            "confidence": sql_result['confidence'],
            "retrieval_info": {
                "semantic_results": len(results['semantic']),
                "procedural_results": len(results['procedural']),
                "context_length": len(context)
            },
            "context_used": context_details
        }
        
    except Exception as e:
        logger.exception("Query explanation failed")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    # Pass the app as an import string so --reload works correctly.
    # Use "nl2sql_api_pinecone:app" if this file is located in the current working directory.
    uvicorn.run(
        "nl2sql_api_pinecone:app",
        host="0.0.0.0",
        port=8002,
        reload=True,
    )