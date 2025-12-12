"""
Semantic Recall Middleware for Pinecone-backed NL2SQL Agent
Injects relevant schema context before SQL generation
"""

import json
from typing import Dict, Any, Optional

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from logger import logger


def _extract_latest_human_message(messages: list) -> Optional[str]:
    """
    Extract content from the most recent HumanMessage in the message list.

    Args:
        messages: List of LangChain message objects

    Returns:
        Message content string, or None if no HumanMessage found
    """
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg.content
    return None


class NL2SQLSemanticRecallMiddleware(AgentMiddleware):
    """
    Middleware that performs semantic recall from Pinecone vector store.
    - before_agent: Check if we have enough cached context to skip web search
    - before_model: Inject relevant schema context into the prompt
    """

    def __init__(self, store):
        """Initialize middleware with Pinecone store."""
        super().__init__()
        self.store = store
        logger.info(
            "NL2SQLSemanticRecallMiddleware initialized.",
            extra={
                "phase": "middleware",
                "event": "middleware_init",
            }
        )

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Check semantic recall before agent starts. If we find 5+ relevant chunks,
        short-circuit the agent execution and return SQL directly.

        Returns:
            None: Continue with normal agent execution
            Dict: Short-circuit with jump_to="end" to skip agent execution
        """
        logger.info(
            "BEFORE_AGENT CALLED - Checking semantic memory",
            extra={
                "phase": "middleware",
                "event": "before_agent_entry",
                "state_keys": list(state.keys()),
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
                        "message_count": len(messages),
                    }
                )
                return None

            logger.info(
                "Pre-agent semantic recall check initiated.",
                extra={
                    "phase": "middleware",
                    "event": "before_agent_recall_start",
                    "query_preview": query[:120] + "..." if len(query) > 120 else query,
                },
            )

            # Adaptive retrieval based on query complexity
            # Start with higher limits to get comprehensive context
            initial_semantic_limit = 20  # Fetch more to ensure we get all relevant context
            initial_procedural_limit = 10

            # Search both semantic and procedural memory
            semantic_hits = self.store.search(
                namespace_prefix=("semantic",),
                query=query,
                limit=initial_semantic_limit
            )

            procedural_hits = self.store.search(
                namespace_prefix=("procedural",),
                query=query,
                limit=initial_procedural_limit
            )

            # Filter by relevance score (Pinecone score: 0-1, higher is better)
            # Only keep highly relevant results (score > 0.7)
            semantic_hits = [hit for hit in semantic_hits if hit.score > 0.7]
            procedural_hits = [hit for hit in procedural_hits if hit.score > 0.7]

            total_hits = len(semantic_hits) + len(procedural_hits)

            logger.info(
                "Filtered semantic results by relevance.",
                extra={
                    "phase": "middleware",
                    "event": "before_agent_filter_results",
                    "initial_semantic": initial_semantic_limit,
                    "initial_procedural": initial_procedural_limit,
                    "filtered_semantic": len(semantic_hits),
                    "filtered_procedural": len(procedural_hits),
                    "score_threshold": 0.7,
                }
            )

            logger.info(
                "Pre-agent semantic recall completed.",
                extra={
                    "phase": "middleware",
                    "event": "before_agent_recall_done",
                    "semantic_hits": len(semantic_hits),
                    "procedural_hits": len(procedural_hits),
                    "total_hits": total_hits,
                    "threshold": 5,
                    "will_shortcircuit": total_hits >= 5,
                },
            )

            # Short-circuit if we have 5+ relevant chunks
            if total_hits >= 5:
                logger.info(
                    "SHORTCIRCUIT TRIGGERED - Sufficient schema context found",
                    extra={
                        "phase": "middleware",
                        "event": "before_agent_shortcircuit",
                        "total_hits": total_hits,
                    }
                )

                # Build context from retrieved chunks
                context_parts = []

                # Add semantic memory (schema info)
                if semantic_hits:
                    context_parts.append("=== DATABASE SCHEMA CONTEXT ===\n")
                    for hit in semantic_hits:
                        text = hit.value.get('text', '')
                        if text:
                            context_parts.append(text)
                            context_parts.append("\n---\n")

                # Add procedural memory (query examples)
                if procedural_hits:
                    context_parts.append("\n=== QUERY EXAMPLE PATTERNS ===\n")
                    for hit in procedural_hits:
                        text = hit.value.get('text', '')
                        if text:
                            context_parts.append(text)
                            context_parts.append("\n---\n")

                context = "\n".join(context_parts)

                # Add context as system message
                state["messages"].append(
                    SystemMessage(content=f"Relevant schema context retrieved:\n\n{context}")
                )

                logger.info(
                    "SHORTCIRCUIT STATE PREPARED - Context injected",
                    extra={
                        "phase": "middleware",
                        "event": "before_agent_context_injected",
                        "context_length": len(context),
                        "new_message_count": len(state["messages"]),
                    }
                )

                # Return None to continue with agent (now with context)
                # Agent will generate SQL using the injected context
                return None

            else:
                logger.info(
                    "NO SHORTCIRCUIT - Insufficient context, continuing with agent",
                    extra={
                        "phase": "middleware",
                        "event": "before_agent_continue",
                        "total_hits": total_hits,
                    }
                )
                return None

        except Exception as e:
            logger.exception(
                "ERROR in before_agent",
                extra={
                    "phase": "middleware",
                    "event": "before_agent_recall_error",
                    "exception_type": type(e).__name__,
                },
            )
            logger.warning(
                "Error in pre-agent check. Continuing with normal execution.",
                extra={"phase": "middleware", "event": "before_agent_error_recovery"}
            )
            return None

    def before_model(self, state, **kwargs) -> Dict[str, Any]:
        """
        Inject additional context before model processes input.
        This runs during agent execution (if not short-circuited).
        """
        logger.info(
            "BEFORE_MODEL CALLED - Injecting schema context",
            extra={
                "phase": "middleware",
                "event": "before_model_entry",
            }
        )

        try:
            messages = state.get("messages", [])
            query = _extract_latest_human_message(messages)

            if not query:
                logger.warning(
                    "No HumanMessage found. Skipping semantic recall.",
                    extra={
                        "phase": "middleware",
                        "event": "before_model_no_human_message",
                    }
                )
                return state

            logger.info(
                "Before-model semantic recall initiated.",
                extra={
                    "phase": "middleware",
                    "event": "before_model_recall_start",
                    "query_preview": query[:120] + "..." if len(query) > 120 else query,
                },
            )

            # Adaptive retrieval with higher initial limits
            semantic_limit = 15
            procedural_limit = 8

            # Search semantic and procedural memory
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

            # Filter by relevance (score > 0.6 for before_model)
            semantic_hits = [hit for hit in semantic_hits if hit.score > 0.6]
            procedural_hits = [hit for hit in procedural_hits if hit.score > 0.6]

            total_hits = len(semantic_hits) + len(procedural_hits)

            logger.info(
                "Before-model semantic recall completed.",
                extra={
                    "phase": "middleware",
                    "event": "before_model_recall_done",
                    "semantic_hits": len(semantic_hits),
                    "procedural_hits": len(procedural_hits),
                    "total_hits": total_hits,
                },
            )

            # Build and inject context
            if total_hits > 0:
                context_parts = []

                if semantic_hits:
                    context_parts.append("=== DATABASE SCHEMA ===\n")
                    for hit in semantic_hits:
                        table_name = hit.value.get('table_name', 'unknown')
                        entity_type = hit.value.get('entity_type', 'unknown')
                        text_preview = hit.value.get('text', '')[:200]
                        context_parts.append(f"[{entity_type}] {table_name}: {text_preview}...\n")

                if procedural_hits:
                    context_parts.append("\n=== QUERY EXAMPLES ===\n")
                    for hit in procedural_hits:
                        table_name = hit.value.get('table_name', 'unknown')
                        text_preview = hit.value.get('text', '')[:200]
                        context_parts.append(f"Example for {table_name}: {text_preview}...\n")

                context = "\n".join(context_parts)

                state["messages"].append(
                    SystemMessage(content=f"Schema context:\n{context}")
                )

                logger.debug(
                    "Schema context injected into messages.",
                    extra={
                        "phase": "middleware",
                        "event": "before_model_context_injected",
                        "context_length": len(context),
                    }
                )
            else:
                logger.debug(
                    "No semantic recall hits found.",
                    extra={"phase": "middleware", "event": "before_model_recall_empty"},
                )

        except Exception as e:
            logger.exception(
                "Error during semantic recall.",
                extra={
                    "phase": "middleware",
                    "event": "before_model_recall_error",
                    "exception_type": type(e).__name__,
                },
            )
            logger.warning(
                "Continuing without semantic recall context due to error.",
                extra={"phase": "middleware", "event": "before_model_recall_recovery"}
            )

        return state