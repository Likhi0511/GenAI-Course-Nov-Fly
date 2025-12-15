"""
Semantic Recall Middleware for NL2SQL
Imports store from config module (does NOT take store as parameter)
"""

import json
from typing import Dict, Any, Optional
import logging

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from nl2sql_config import store  # Import store from config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _extract_latest_human_message(messages: list) -> Optional[str]:
    """Extract content from the most recent HumanMessage."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg.content
    return None


def _format_retrieved_context(semantic_hits, procedural_hits) -> str:
    """Format retrieved context with clear structure"""
    
    parts = []
    
    # Group semantic hits by type
    tables = []
    columns = []
    relationships = []
    
    for hit in semantic_hits:
        entity_type = hit.value.get('entity_type', 'unknown')
        if entity_type == 'table':
            tables.append(hit)
        elif entity_type == 'column':
            columns.append(hit)
        elif entity_type == 'relationship':
            relationships.append(hit)
    
    # Format tables
    if tables:
        parts.append("=== AVAILABLE TABLES ===")
        for hit in tables:
            table_name = hit.value.get('table_name', 'unknown')
            text = hit.value.get('text', '')
            score = hit.score
            parts.append(f"\nTable: {table_name} (relevance: {score:.3f})")
            parts.append(text)
            parts.append("-" * 50)
    
    # Format columns
    if columns:
        parts.append("\n=== TABLE COLUMNS ===")
        for hit in columns:
            table_name = hit.value.get('table_name', 'unknown')
            column_name = hit.value.get('column_name', 'unknown')
            text = hit.value.get('text', '')
            score = hit.score
            parts.append(f"\n{table_name}.{column_name} (relevance: {score:.3f})")
            parts.append(text)
            parts.append("-" * 50)
    
    # Format relationships
    if relationships:
        parts.append("\n=== TABLE RELATIONSHIPS ===")
        for hit in relationships:
            text = hit.value.get('text', '')
            score = hit.score
            parts.append(f"\nRelationship (relevance: {score:.3f})")
            parts.append(text)
            parts.append("-" * 50)
    
    # Format query examples
    if procedural_hits:
        parts.append("\n=== QUERY EXAMPLES ===")
        for hit in procedural_hits:
            table_name = hit.value.get('table_name', 'unknown')
            text = hit.value.get('text', '')
            score = hit.score
            parts.append(f"\nExample for {table_name} (relevance: {score:.3f})")
            parts.append(text)
            parts.append("-" * 50)
    
    return "\n".join(parts)


class NL2SQLSemanticRecallMiddleware(AgentMiddleware):
    """
    Middleware for NL2SQL semantic recall.
    Uses store imported from config module (like the example you provided).
    """

    def __init__(self):
        """Initialize middleware WITHOUT store parameter (imports from config)"""
        super().__init__()
        logger.info("=" * 70)
        logger.info("NL2SQLSemanticRecallMiddleware initialized")
        logger.info("  Store imported from nl2sql_config module")
        logger.info("=" * 70)

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Retrieve relevant schema context before agent execution.
        """
        logger.info("")
        logger.info("=" * 70)
        logger.info("BEFORE_AGENT: Starting semantic recall")
        logger.info("=" * 70)

        try:
            messages = state.get("messages", [])
            query = _extract_latest_human_message(messages)

            if not query:
                logger.warning("⚠️  No HumanMessage found - skipping semantic recall")
                return None

            logger.info(f"📝 User Query: {query}")
            logger.info("")
            
            # Configuration
            semantic_limit = 25
            procedural_limit = 10
            score_threshold = 0.65
            
            # === SEMANTIC MEMORY SEARCH ===
            logger.info(f"🔍 Searching semantic memory (limit={semantic_limit})...")
            semantic_hits = store.search(
                ("semantic",),  # namespace as positional arg
                query=query,
                limit=semantic_limit
            )
            logger.info(f"   Retrieved {len(semantic_hits)} semantic chunks")
            
            # Log top semantic results
            if semantic_hits:
                logger.info("   Top 5 semantic results:")
                for i, hit in enumerate(semantic_hits[:5], 1):
                    entity_type = hit.value.get('entity_type', 'unknown')
                    table_name = hit.value.get('table_name', 'unknown')
                    column_name = hit.value.get('column_name', '')
                    score = hit.score
                    
                    if column_name:
                        logger.info(f"     {i}. [{entity_type}] {table_name}.{column_name} (score: {score:.3f})")
                    else:
                        logger.info(f"     {i}. [{entity_type}] {table_name} (score: {score:.3f})")
            
            # === PROCEDURAL MEMORY SEARCH ===
            logger.info("")
            logger.info(f"🔍 Searching procedural memory (limit={procedural_limit})...")
            procedural_hits = store.search(
                ("procedural",),  # namespace as positional arg
                query=query,
                limit=procedural_limit
            )
            logger.info(f"   Retrieved {len(procedural_hits)} procedural chunks")
            
            # Log top procedural results
            if procedural_hits:
                logger.info("   Top 3 procedural results:")
                for i, hit in enumerate(procedural_hits[:3], 1):
                    table_name = hit.value.get('table_name', 'unknown')
                    score = hit.score
                    use_case = hit.value.get('text', '')[:80]
                    logger.info(f"     {i}. {table_name} (score: {score:.3f})")
                    logger.info(f"        {use_case}...")
            
            # === FILTERING BY SCORE ===
            logger.info("")
            logger.info(f"🎯 Filtering by score threshold: {score_threshold}")
            
            semantic_filtered = [hit for hit in semantic_hits if hit.score >= score_threshold]
            procedural_filtered = [hit for hit in procedural_hits if hit.score >= score_threshold]
            
            logger.info(f"   Semantic: {len(semantic_hits)} → {len(semantic_filtered)} (after filtering)")
            logger.info(f"   Procedural: {len(procedural_hits)} → {len(procedural_filtered)} (after filtering)")
            
            total_hits = len(semantic_filtered) + len(procedural_filtered)
            logger.info(f"   Total relevant chunks: {total_hits}")
            
            # === BUILD CONTEXT ===
            if total_hits > 0:
                logger.info("")
                logger.info("📦 Building context for LLM...")
                
                context = _format_retrieved_context(semantic_filtered, procedural_filtered)
                
                logger.info(f"   Context length: {len(context)} characters")
                logger.info(f"   Context contains:")
                
                # Count entity types
                tables = sum(1 for h in semantic_filtered if h.value.get('entity_type') == 'table')
                columns = sum(1 for h in semantic_filtered if h.value.get('entity_type') == 'column')
                relationships = sum(1 for h in semantic_filtered if h.value.get('entity_type') == 'relationship')
                
                logger.info(f"     - {tables} tables")
                logger.info(f"     - {columns} columns")
                logger.info(f"     - {relationships} relationships")
                logger.info(f"     - {len(procedural_filtered)} query examples")
                
                # === INJECT CONTEXT ===
                logger.info("")
                logger.info("💉 Injecting context into agent state...")
                
                state["messages"].append(
                    SystemMessage(content=f"Database schema context:\n\n{context}")
                )
                
                logger.info("   ✓ Context injected as SystemMessage")
                logger.info(f"   Total messages in state: {len(state['messages'])}")
                
                # Log sample of context (first 500 chars)
                logger.info("")
                logger.info("📄 Context preview (first 500 chars):")
                logger.info("-" * 70)
                logger.info(context[:500] + "...")
                logger.info("-" * 70)
                
            else:
                logger.warning("")
                logger.warning("⚠️  No relevant context found (all scores below threshold)")
                logger.warning("   Agent will proceed without schema context")
            
            logger.info("")
            logger.info("✓ Semantic recall completed - continuing with agent")
            logger.info("=" * 70)
            logger.info("")
            
            return None

        except Exception as e:
            logger.error("")
            logger.error("=" * 70)
            logger.error(f"❌ ERROR in before_agent: {type(e).__name__}")
            logger.error(f"   {str(e)}")
            logger.error("=" * 70)
            logger.exception("Full traceback:")
            logger.warning("Continuing with agent execution (without context)")
            return None