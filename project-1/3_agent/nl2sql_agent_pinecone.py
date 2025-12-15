"""
NL2SQL Agent Builder
Follows the pattern from your example - imports config, builds agent async
"""

from __future__ import annotations

import logging
from langchain.agents import create_agent

from nl2sql_config import llm, store
from nl2sql_semantic_recall import NL2SQLSemanticRecallMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Enhanced system prompt
SYSTEM_PROMPT = """You are an expert PostgreSQL query generator for an e-commerce database.

**Your Task:**
Convert natural language questions into accurate, executable SQL queries.

**Database Schema:**
You will receive detailed schema information including:
• Table definitions and purposes
• Column names, data types, and constraints  
• Foreign key relationships and join patterns
• Real-world query examples and patterns

**SQL Generation Rules:**

1. **Accuracy First**
   - Use exact table and column names from the schema
   - Respect data types and constraints
   - Include all necessary JOINs

2. **Query Structure**
   - Start with SELECT for retrieval queries
   - Use WHERE for filtering conditions
   - Apply JOINs for multi-table queries
   - Add GROUP BY for aggregations
   - Include ORDER BY for sorting
   - Use LIMIT for pagination

3. **PostgreSQL Syntax**
   - Use PostgreSQL-specific functions when needed
   - Date arithmetic: CURRENT_DATE, INTERVAL '1 month'
   - String matching: ILIKE for case-insensitive
   - Type casting: ::integer, ::date
   - Array operations when appropriate

4. **Performance Considerations**
   - Avoid SELECT * when specific columns suffice
   - Use indexes (mentioned in schema) wisely
   - Prefer JOINs over subqueries when possible
   - Use LIMIT for large result sets

5. **Common Patterns**
   - Aggregations: COUNT(*), SUM(), AVG(), MAX(), MIN()
   - Time filters: WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
   - String search: WHERE name ILIKE '%keyword%'
   - Top N: ORDER BY column DESC LIMIT N
   - Grouping: GROUP BY x, y HAVING COUNT(*) > n

**Output Format:**
Return ONLY the SQL query. No explanations, no markdown, no comments.

**Example:**
Question: "Show top 10 customers by total spending"
Response: SELECT c.customer_id, c.first_name, c.last_name, SUM(o.total_amount) AS total_spending FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id, c.first_name, c.last_name ORDER BY total_spending DESC LIMIT 10

**When Uncertain:**
If the schema context doesn't contain enough information, respond with:
"CLARIFICATION NEEDED: [specific question about schema]"

Now, generate the SQL query based on the user's question and the provided schema context.
""".strip()


async def build_agent():
    """
    Build NL2SQL agent with semantic recall middleware.
    Follows the pattern from your example.

    Returns:
        LangChain Agent (Runnable) ready for .invoke/.ainvoke
    """

    logger.info("=" * 70)
    logger.info("Building NL2SQL Agent")
    logger.info("=" * 70)

    # Create agent (following your example pattern)
    agent = create_agent(
        model=llm,
        tools=[],  # No external tools needed
        system_prompt=SYSTEM_PROMPT,
        store=store,  # Imported from config
        middleware=[
            NL2SQLSemanticRecallMiddleware()  # No parameters - imports store internally
        ]
    )

    logger.info("✓ NL2SQL Agent created successfully")
    logger.info("=" * 70)
    logger.info("")

    return agent


async def generate_sql(question: str) -> dict:
    """
    Generate SQL query from natural language question.

    Args:
        question: Natural language question

    Returns:
        Dict with sql_query and metadata
    """
    logger.info("")
    logger.info("=" * 70)
    logger.info(f"GENERATING SQL FOR: {question}")
    logger.info("=" * 70)

    try:
        # Build agent
        agent = await build_agent()

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

        logger.info("")
        logger.info("=" * 70)
        logger.info("SQL GENERATION COMPLETED")
        logger.info("=" * 70)
        logger.info(f"Generated SQL:")
        logger.info(sql_query)
        logger.info("=" * 70)
        logger.info("")

        return {
            "sql_query": sql_query.strip(),
            "messages": messages,
            "full_response": response
        }

    except Exception as e:
        logger.error("")
        logger.error("=" * 70)
        logger.error(f"❌ SQL GENERATION FAILED: {type(e).__name__}")
        logger.error(f"   {str(e)}")
        logger.error("=" * 70)
        logger.exception("Full traceback:")
        raise


# Example usage
if __name__ == "__main__":
    import asyncio

    async def main():
        # Test queries
        questions = [
            "Show me all customers in California",
            "What are the top 5 products by revenue?",
            "Find customers who ordered Electronics products last month",
        ]

        for question in questions:
            print(f"\n{'='*70}")
            print(f"Question: {question}")
            print('='*70)

            result = await generate_sql(question)

            print(f"\nGenerated SQL:")
            print(result['sql_query'])
            print("=" * 70)

    # Run
    asyncio.run(main())