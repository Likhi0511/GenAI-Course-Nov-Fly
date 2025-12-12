"""
NL2SQL LangChain Agent with Pinecone Vector Store
Builds an agent that converts natural language to SQL using semantic memory
"""

from __future__ import annotations

import logging
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from pinecone_store import PineconeStore
from nl2sql_middleware_pinecone import NL2SQLSemanticRecallMiddleware

logger = logging.getLogger(__name__)


# System prompt for SQL generation
SYSTEM_PROMPT = """
You are an expert SQL query generator for an e-commerce database.

Your task is to convert natural language questions into accurate SQL queries.

**Database Schema Context:**
The schema information will be provided in the conversation. Use it to understand:
- Available tables and their purposes
- Column names and data types
- Relationships between tables (foreign keys, joins)
- Common query patterns and examples

**Query Generation Rules:**
1. Always use proper table and column names from the schema
2. Use appropriate joins when querying multiple tables
3. Include WHERE clauses for filtering
4. Use aggregate functions (COUNT, SUM, AVG) when appropriate
5. Add ORDER BY and LIMIT when relevant
6. Follow PostgreSQL syntax

**Output Format:**
Return ONLY the SQL query, no explanations or markdown formatting.
If you need clarification, ask a specific question about the schema.

**Example:**
Question: "Show me all customers in California"
SQL: SELECT * FROM customers WHERE state = 'CA'

Now, generate SQL based on the user's question and the schema context provided.
""".strip()


def create_nl2sql_agent(
    index_name: str = 'nl2sql-semantic-memory',
    model: str = "gpt-4",
    temperature: float = 0
):
    """
    Create NL2SQL agent with Pinecone semantic memory.
    
    Args:
        index_name: Pinecone index name
        model: OpenAI model to use
        temperature: LLM temperature (0 for deterministic)
    
    Returns:
        LangChain Agent ready for .invoke()/.ainvoke()
    """
    
    # Initialize LLM
    llm = ChatOpenAI(model=model, temperature=temperature)
    
    # Initialize embeddings
    embeddings = OpenAIEmbeddings(model='text-embedding-3-small')
    
    # Initialize Pinecone store
    store = PineconeStore(
        index_name=index_name,
        embeddings=embeddings
    )
    
    logger.info(
        "Creating NL2SQL agent with Pinecone store.",
        extra={
            "phase": "agent",
            "event": "agent_creation",
            "index_name": index_name,
            "model": model,
        }
    )
    
    # Create agent with middleware
    agent = create_agent(
        model=llm,
        tools=[],  # No external tools needed - we use semantic memory
        system_prompt=SYSTEM_PROMPT,
        store=store,
        middleware=[
            NL2SQLSemanticRecallMiddleware(store=store)
        ]
    )
    
    logger.info(
        "NL2SQL agent created successfully.",
        extra={
            "phase": "agent",
            "event": "agent_created",
        }
    )
    
    return agent


async def generate_sql(agent, question: str) -> dict:
    """
    Generate SQL query from natural language question.
    
    Args:
        agent: LangChain agent
        question: Natural language question
    
    Returns:
        Dict with sql_query, explanation, and context
    """
    logger.info(
        "Generating SQL query.",
        extra={
            "phase": "agent",
            "event": "sql_generation_start",
            "question": question[:100],
        }
    )
    
    try:
        # Invoke agent
        response = await agent.ainvoke(
            {"messages": [{"role": "user", "content": question}]}
        )
        
        # Extract SQL from response
        messages = response.get("messages", [])
        sql_query = ""
        
        # Get the last AI message
        for msg in reversed(messages):
            if hasattr(msg, 'content') and msg.content:
                sql_query = msg.content
                break
        
        logger.info(
            "SQL generation completed.",
            extra={
                "phase": "agent",
                "event": "sql_generation_done",
                "sql_length": len(sql_query),
            }
        )
        
        return {
            "sql_query": sql_query.strip(),
            "messages": messages,
            "full_response": response
        }
        
    except Exception as e:
        logger.error(
            f"SQL generation failed: {e}",
            extra={
                "phase": "agent",
                "event": "sql_generation_error",
                "exception_type": type(e).__name__,
            }
        )
        raise


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def main():
        # Create agent
        agent = create_nl2sql_agent()
        
        # Test queries
        questions = [
            "Show me all customers in California",
            "What are the top 5 products by revenue?",
            "List orders from last month with their total amounts",
        ]
        
        for question in questions:
            print(f"\nQuestion: {question}")
            print("-" * 70)
            
            result = await generate_sql(agent, question)
            
            print(f"SQL Query:\n{result['sql_query']}")
            print("=" * 70)
    
    # Run
    asyncio.run(main())
