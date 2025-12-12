"""
Advanced Semantic Recall Middleware with Adaptive Retrieval
Analyzes query complexity and retrieves appropriate amount of context
"""

import json
import re
from typing import Dict, Any, Optional

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from logger import logger


def _extract_latest_human_message(messages: list) -> Optional[str]:
    """Extract content from the most recent HumanMessage."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg.content
    return None


def _analyze_query_complexity(query: str) -> Dict[str, Any]:
    """
    Analyze query to determine optimal retrieval strategy.
    
    Returns:
        Dict with complexity metrics and suggested limits
    """
    query_lower = query.lower()
    
    # Count indicators of complexity
    complexity_score = 0
    
    # Multi-table indicators
    joins_keywords = ['join', 'with', 'and', 'related', 'connected']
    if any(kw in query_lower for kw in joins_keywords):
        complexity_score += 2
    
    # Aggregation indicators
    agg_keywords = ['total', 'sum', 'count', 'average', 'top', 'most', 'least']
    if any(kw in query_lower for kw in agg_keywords):
        complexity_score += 1
    
    # Time-based indicators
    time_keywords = ['last', 'recent', 'month', 'year', 'today', 'yesterday']
    if any(kw in query_lower for kw in time_keywords):
        complexity_score += 1
    
    # Multiple conditions
    condition_keywords = ['where', 'filter', 'only', 'exclude']
    condition_count = sum(1 for kw in condition_keywords if kw in query_lower)
    complexity_score += condition_count
    
    # Count number of table mentions (rough estimate)
    potential_tables = re.findall(r'\b(customer|product|order|payment|review|inventory|warehouse|category|address)\w*\b', query_lower)
    table_count = len(set(potential_tables))
    complexity_score += table_count
    
    # Determine retrieval strategy
    if complexity_score >= 6:
        strategy = "comprehensive"
        semantic_limit = 30
        procedural_limit = 15
        score_threshold = 0.6  # Lower threshold for complex queries
    elif complexity_score >= 3:
        strategy = "moderate"
        semantic_limit = 20
        procedural_limit = 10
        score_threshold = 0.65
    else:
        strategy = "focused"
        semantic_limit = 12
        procedural_limit = 6
        score_threshold = 0.7  # Higher threshold for simple queries
    
    return {
        "complexity_score": complexity_score,
        "strategy": strategy,
        "semantic_limit": semantic_limit,
        "procedural_limit": procedural_limit,
        "score_threshold": score_threshold,
        "estimated_tables": table_count
    }


class AdaptiveNL2SQLMiddleware(AgentMiddleware):
    """
    Advanced middleware with adaptive retrieval based on query complexity.
    """

    def __init__(self, store, config: Optional[Dict] = None):
        """
        Initialize middleware with Pinecone store and optional config.
        
        Args:
            store: Pinecone BaseStore instance
            config: Optional configuration dict with:
                - max_semantic_limit: Maximum semantic chunks to retrieve (default: 50)
                - max_procedural_limit: Maximum procedural chunks (default: 20)
                - min_score: Minimum relevance score (default: 0.5)
                - enable_query_analysis: Use adaptive retrieval (default: True)
        """
        super().__init__()
        self.store = store
        self.config = config or {}
        
        # Configuration
        self.max_semantic_limit = self.config.get('max_semantic_limit', 50)
        self.max_procedural_limit = self.config.get('max_procedural_limit', 20)
        self.min_score = self.config.get('min_score', 0.5)
        self.enable_query_analysis = self.config.get('enable_query_analysis', True)
        
        logger.info(
            "AdaptiveNL2SQLMiddleware initialized.",
            extra={
                "phase": "middleware",
                "event": "middleware_init",
                "config": self.config,
            }
        )

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Adaptive semantic recall before agent execution.
        Analyzes query complexity and retrieves appropriate context.
        """
        logger.info(
            "BEFORE_AGENT - Adaptive retrieval starting",
            extra={
                "phase": "middleware",
                "event": "before_agent_entry",
            }
        )

        try:
            messages = state.get("messages", [])
            query = _extract_latest_human_message(messages)

            if not query:
                logger.warning(
                    "No HumanMessage found. Cannot perform semantic recall.",
                    extra={
                        "phase": "middleware",
                        "event": "before_agent_no_human_message",
                    }
                )
                return None

            # Analyze query complexity
            if self.enable_query_analysis:
                analysis = _analyze_query_complexity(query)
                semantic_limit = min(analysis['semantic_limit'], self.max_semantic_limit)
                procedural_limit = min(analysis['procedural_limit'], self.max_procedural_limit)
                score_threshold = max(analysis['score_threshold'], self.min_score)
                
                logger.info(
                    "Query complexity analysis completed.",
                    extra={
                        "phase": "middleware",
                        "event": "query_analysis",
                        "analysis": analysis,
                        "adjusted_limits": {
                            "semantic": semantic_limit,
                            "procedural": procedural_limit,
                            "threshold": score_threshold
                        }
                    }
                )
            else:
                # Use default limits
                semantic_limit = 20
                procedural_limit = 10
                score_threshold = 0.65
                
                logger.info(
                    "Using default retrieval limits (query analysis disabled).",
                    extra={
                        "phase": "middleware",
                        "event": "default_limits",
                        "semantic_limit": semantic_limit,
                        "procedural_limit": procedural_limit,
                    }
                )

            logger.info(
                "Searching semantic memory.",
                extra={
                    "phase": "middleware",
                    "event": "before_agent_search_start",
                    "query_preview": query[:120],
                    "semantic_limit": semantic_limit,
                    "procedural_limit": procedural_limit,
                },
            )

            # Search with determined limits
            semantic_hits = self.store.search(
                namespace_prefix=("semantic",),
                query=query,
                limit=semantic_limit
            )
            
            procedural_hits = self.store.search(
                namespace_prefix=("procedural",), 
                query=query,
                limit=procedural_limit
            )

            # Filter by relevance score
            semantic_hits_filtered = [hit for hit in semantic_hits if hit.score >= score_threshold]
            procedural_hits_filtered = [hit for hit in procedural_hits if hit.score >= score_threshold]
            
            logger.info(
                "Search and filtering completed.",
                extra={
                    "phase": "middleware",
                    "event": "before_agent_search_done",
                    "semantic_retrieved": len(semantic_hits),
                    "semantic_filtered": len(semantic_hits_filtered),
                    "procedural_retrieved": len(procedural_hits),
                    "procedural_filtered": len(procedural_hits_filtered),
                    "score_threshold": score_threshold,
                }
            )

            total_hits = len(semantic_hits_filtered) + len(procedural_hits_filtered)

            # Proceed if we have sufficient context
            if total_hits >= 3:  # Lower threshold - we want to use context when available
                logger.info(
                    "Sufficient context found - injecting into state",
                    extra={
                        "phase": "middleware",
                        "event": "before_agent_context_injection",
                        "total_hits": total_hits,
                    }
                )

                # Build comprehensive context
                context_parts = []
                
                # Group semantic hits by entity type
                columns = [hit for hit in semantic_hits_filtered if hit.value.get('entity_type') == 'column']
                relationships = [hit for hit in semantic_hits_filtered if hit.value.get('entity_type') == 'relationship']
                tables = [hit for hit in semantic_hits_filtered if hit.value.get('entity_type') == 'table']
                
                # Add table info
                if tables:
                    context_parts.append("=== TABLES ===")
                    for hit in tables[:5]:  # Top 5 tables
                        context_parts.append(hit.value.get('text', ''))
                        context_parts.append("---")
                
                # Add column info
                if columns:
                    context_parts.append("\n=== COLUMNS ===")
                    for hit in columns[:15]:  # Top 15 columns
                        context_parts.append(hit.value.get('text', ''))
                        context_parts.append("---")
                
                # Add relationships
                if relationships:
                    context_parts.append("\n=== RELATIONSHIPS ===")
                    for hit in relationships[:8]:  # Top 8 relationships
                        context_parts.append(hit.value.get('text', ''))
                        context_parts.append("---")
                
                # Add query examples
                if procedural_hits_filtered:
                    context_parts.append("\n=== QUERY EXAMPLES ===")
                    for hit in procedural_hits_filtered[:5]:  # Top 5 examples
                        context_parts.append(hit.value.get('text', ''))
                        context_parts.append("---")
                
                context = "\n".join(context_parts)

                # Inject as system message
                state["messages"].append(
                    SystemMessage(content=f"Relevant database schema context:\n\n{context}")
                )

                logger.info(
                    "Context injected successfully.",
                    extra={
                        "phase": "middleware",
                        "event": "before_agent_context_ready",
                        "context_length": len(context),
                        "tables_count": len(tables),
                        "columns_count": len(columns),
                        "relationships_count": len(relationships),
                        "examples_count": len(procedural_hits_filtered),
                    }
                )

                # Continue with agent execution (return None)
                return None
                
            else:
                logger.info(
                    "Insufficient relevant context - continuing with agent",
                    extra={
                        "phase": "middleware",
                        "event": "before_agent_insufficient_context",
                        "total_hits": total_hits,
                    }
                )
                return None

        except Exception as e:
            logger.exception(
                "ERROR in before_agent",
                extra={
                    "phase": "middleware",
                    "event": "before_agent_error",
                    "exception_type": type(e).__name__,
                },
            )
            return None

    def before_model(self, state, **kwargs) -> Dict[str, Any]:
        """
        Light context injection before model call.
        Adds high-level summary without full context.
        """
        logger.info(
            "BEFORE_MODEL - Adding summary context",
            extra={"phase": "middleware", "event": "before_model_entry"}
        )

        try:
            messages = state.get("messages", [])
            query = _extract_latest_human_message(messages)

            if not query:
                return state

            # Quick search for top results only
            semantic_hits = self.store.search(
                namespace_prefix=("semantic",),
                query=query,
                limit=5
            )

            if semantic_hits:
                # Build quick summary
                tables = set()
                for hit in semantic_hits:
                    table = hit.value.get('table_name')
                    if table:
                        tables.add(table)
                
                if tables:
                    summary = f"Available tables: {', '.join(sorted(tables))}"
                    state["messages"].append(SystemMessage(content=summary))
                    
                    logger.debug(
                        "Summary context added.",
                        extra={
                            "phase": "middleware",
                            "event": "before_model_summary_added",
                            "tables": list(tables),
                        }
                    )

        except Exception as e:
            logger.warning(
                f"before_model context injection failed: {e}",
                extra={
                    "phase": "middleware",
                    "event": "before_model_error",
                }
            )

        return state
