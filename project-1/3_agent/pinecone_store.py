"""
Pinecone-backed Store implementation compatible with LangGraph BaseStore.
"""

from __future__ import annotations

import json
import os
import logging
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple
from collections.abc import Iterable
from datetime import datetime

from pinecone import Pinecone
from langgraph.store.base import (
    BaseStore,
    Item,
    SearchItem,
    Op,
    GetOp,
    PutOp,
    SearchOp,
    ListNamespacesOp,
    Result,
)

logger = logging.getLogger(__name__)


_METADATA_SOFT_LIMIT = 40000  # Pinecone's metadata limit (40KB)


def _json_len_bytes(obj: dict) -> int:
    """Rough-but-safe UTF-8 size estimate"""
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _compact_metadata(value: dict, *, text: str | None) -> dict:
    """
    Produce a metadata dict that respects Pinecone's 40KB metadata limit.
    For NL2SQL, we NEED full text in metadata for context injection.
    """
    # Start with full metadata including text
    meta = {
        "table_name": value.get("table_name"),
        "entity_type": value.get("entity_type"),
        "column_name": value.get("column_name"),
        "keywords": value.get("keywords"),
        "memory_type": value.get("memory_type", "semantic"),
        "text": text or "",  # KEEP full text - needed for NL2SQL context
        "text_len": len(text or "") if isinstance(text, str) else None,
    }

    # If over limit, truncate text progressively
    if _json_len_bytes(meta) > _METADATA_SOFT_LIMIT:
        text_len = len(text or "")
        # Progressively reduce text
        for cut in [text_len * 3 // 4, text_len // 2, text_len // 4, 1000, 500, 0]:
            meta["text"] = (text or "")[:cut]
            if _json_len_bytes(meta) <= _METADATA_SOFT_LIMIT:
                break

    return meta


def _ns_to_str(namespace: Tuple[str, ...]) -> str:
    """Convert namespace tuple to string representation"""
    return "/".join(namespace)


def _redact_key(k: str, keep: int = 6) -> str:
    """Redact key for logging, keeping only last N characters"""
    if not k:
        return "<empty>"
    return k if len(k) <= keep else f"{k[:keep]}…"


class PineconeStore(BaseStore):
    """
    Store backed by Pinecone for long-term semantic and episodic memory.
    """

    def __init__(
        self,
        index_name: str,
        embeddings: Optional[Any] = None,
    ) -> None:
        self.index_name = index_name
        self.embed = embeddings

        # Initialize Pinecone
        api_key = os.getenv('PINECONE_API_KEY')
        if not api_key:
            raise ValueError("PINECONE_API_KEY environment variable not set")

        self.pc = Pinecone(api_key=api_key)
        self.index = self.pc.Index(index_name)

        logger.info(
            "PineconeStore initialized.",
            extra={
                "phase": "store",
                "event": "init",
                "index": index_name,
                "embeddings_present": bool(embeddings),
            },
        )

    # ----------------------------------------------------------------------
    # Internal Operations
    # ----------------------------------------------------------------------
    def _do_put(self, op: PutOp) -> None:
        """Execute a single put operation."""
        ns = _ns_to_str(op.namespace)
        t0 = time.monotonic()
        vector_id = f"{ns}:{op.key}"

        try:
            # Delete operation (value is None)
            if op.value is None:
                self.index.delete(ids=[vector_id])
                logger.info(
                    "Delete completed.",
                    extra={
                        "phase": "store",
                        "event": "delete_ok",
                        "namespace": ns,
                        "key": _redact_key(op.key),
                        "duration_ms": int((time.monotonic() - t0) * 1000),
                    },
                )
                return

            # Put operation - extract text for embedding
            if "text" in op.value:
                text = op.value["text"]
            elif "content" in op.value:
                text = op.value["content"]
            else:
                text = json.dumps(op.value, ensure_ascii=False)

            logger.debug(
                "Embedding text for storage.",
                extra={
                    "phase": "store",
                    "event": "put_embed",
                    "text_preview": text[:100] if text else None,
                    "text_len": len(text) if text else 0,
                }
            )

            # Compute vector embedding
            vec = self.embed.embed_query(text) if self.embed else [0.0] * 1536

            # Build compact metadata
            metadata = _compact_metadata(op.value, text=text)
            metadata["namespace"] = ns

            # Upsert to Pinecone
            self.index.upsert(vectors=[{
                'id': vector_id,
                'values': vec,
                'metadata': metadata
            }])

            logger.info(
                "Put completed.",
                extra={
                    "phase": "store",
                    "event": "put_ok",
                    "namespace": ns,
                    "key": _redact_key(op.key),
                    "text_len": len(text) if isinstance(text, str) else None,
                    "vector_dim": len(vec) if isinstance(vec, list) else None,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                },
            )
        except Exception as e:
            logger.error(
                f"Put failed. {traceback.format_exc()}",
                extra={
                    "phase": "store",
                    "event": "put_error",
                    "namespace": ns,
                    "key": _redact_key(op.key),
                    "exception_type": type(e).__name__,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                }
            )
            raise

    def _do_get(self, op: GetOp) -> Optional[Item]:
        """Execute a single get operation."""
        ns = _ns_to_str(op.namespace)
        t0 = time.monotonic()
        vector_id = f"{ns}:{op.key}"

        try:
            result = self.index.fetch(ids=[vector_id])
            vectors = result.get('vectors', {})

            if vector_id not in vectors:
                logger.info(
                    "Get completed - not found.",
                    extra={
                        "phase": "store",
                        "event": "get_ok",
                        "namespace": ns,
                        "key": _redact_key(op.key),
                        "found": False,
                        "duration_ms": int((time.monotonic() - t0) * 1000),
                    },
                )
                return None

            metadata = vectors[vector_id].get('metadata', {})
            accessed_at = metadata.get("accessed_at")

            # Parse timestamp
            if isinstance(accessed_at, (int, float)):
                created_at = datetime.fromtimestamp(accessed_at)
            elif isinstance(accessed_at, str):
                created_at = datetime.fromisoformat(accessed_at)
            else:
                created_at = datetime.now()

            item = Item(
                value=metadata,
                key=op.key,
                namespace=op.namespace,
                created_at=created_at,
                updated_at=created_at,
            )

            logger.info(
                "Get completed.",
                extra={
                    "phase": "store",
                    "event": "get_ok",
                    "namespace": ns,
                    "key": _redact_key(op.key),
                    "found": True,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                },
            )
            return item

        except Exception as e:
            logger.warning(
                f"Get failed. {traceback.format_exc()}",
                extra={
                    "phase": "store",
                    "event": "get_error",
                    "namespace": ns,
                    "key": _redact_key(op.key),
                    "exception_type": type(e).__name__,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                },
            )
            return None

    def _do_search(self, op: SearchOp) -> List[SearchItem]:
        """Execute a single search operation."""
        ns = _ns_to_str(op.namespace_prefix)
        t0 = time.monotonic()

        if not op.query:
            logger.warning(
                "Search skipped: no query provided.",
                extra={"phase": "store", "event": "search_no_query", "namespace": ns},
            )
            return []

        if not self.embed:
            logger.warning(
                "Search skipped: no embedding model configured.",
                extra={"phase": "store", "event": "search_no_embeddings", "namespace": ns},
            )
            return []

        try:
            qvec = self.embed.embed_query(op.query)

            # Fetch more results to account for namespace filtering and offset
            fetch_limit = (op.limit + op.offset) * 3

            # Query Pinecone
            response = self.index.query(
                vector=qvec,
                top_k=min(fetch_limit, 10000),  # Pinecone max
                include_metadata=True
            )

            matches = response.get('matches', [])

            # Filter by namespace prefix
            namespace_prefix_str = f"{ns}:"
            filtered_results = []

            for match in matches:
                vector_id = match.get('id', '')
                if vector_id.startswith(namespace_prefix_str):
                    # Extract actual key without namespace prefix
                    actual_key = vector_id[len(namespace_prefix_str):]
                    metadata = match.get('metadata', {})
                    accessed_at = metadata.get("accessed_at")

                    # Parse timestamp
                    if isinstance(accessed_at, (int, float)):
                        created_at = datetime.fromtimestamp(accessed_at)
                    elif isinstance(accessed_at, str):
                        created_at = datetime.fromisoformat(accessed_at)
                    else:
                        created_at = datetime.now()

                    item = SearchItem(
                        namespace=op.namespace_prefix,
                        key=actual_key,
                        value=metadata,
                        created_at=created_at,
                        updated_at=created_at,
                        score=match.get('score'),  # Pinecone score (0-1, higher is better)
                    )
                    filtered_results.append(item)

                    if len(filtered_results) >= op.limit + op.offset:
                        break

            # Apply offset
            final_results = filtered_results[op.offset:op.offset + op.limit]

            logger.info(
                "Search completed.",
                extra={
                    "phase": "store",
                    "event": "search_ok",
                    "namespace": ns,
                    "limit": op.limit,
                    "offset": op.offset,
                    "fetched": len(matches),
                    "filtered": len(filtered_results),
                    "returned": len(final_results),
                    "query_len": len(op.query),
                    "vector_dim": len(qvec),
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                },
            )

            return final_results

        except Exception as e:
            logger.error(
                f"Search failed. {traceback.format_exc()}",
                extra={
                    "phase": "store",
                    "event": "search_error",
                    "namespace": ns,
                    "limit": op.limit,
                    "exception_type": type(e).__name__,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                },
            )
            return []

    def _do_list_namespaces(self, op: ListNamespacesOp) -> List[Tuple[str, ...]]:
        """Execute a list namespaces operation."""
        t0 = time.monotonic()

        try:
            # Pinecone doesn't have native namespace listing
            # We need to query and extract unique namespaces from metadata
            # This is an expensive operation, so we'll return a limited set

            logger.warning(
                "List namespaces is expensive in Pinecone - returning empty list.",
                extra={
                    "phase": "store",
                    "event": "list_namespaces_limited",
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                },
            )
            return []

        except Exception as e:
            logger.error(
                f"List namespaces failed. {traceback.format_exc()}",
                extra={
                    "phase": "store",
                    "event": "list_namespaces_error",
                    "exception_type": type(e).__name__,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                },
            )
            return []

    # ----------------------------------------------------------------------
    # BaseStore Interface Implementation
    # ----------------------------------------------------------------------
    def batch(self, ops: Iterable[Op]) -> list[Result]:
        """Execute multiple operations synchronously in a single batch."""
        t0 = time.monotonic()
        ops_list = list(ops)

        logger.info(
            "Batch started.",
            extra={"phase": "store", "event": "batch_start", "ops_count": len(ops_list)},
        )

        results: list[Result] = []

        for op in ops_list:
            try:
                if isinstance(op, PutOp):
                    self._do_put(op)
                    results.append(None)
                elif isinstance(op, GetOp):
                    results.append(self._do_get(op))
                elif isinstance(op, SearchOp):
                    results.append(self._do_search(op))
                elif isinstance(op, ListNamespacesOp):
                    results.append(self._do_list_namespaces(op))
                else:
                    logger.warning(
                        "Unknown batch op.",
                        extra={"phase": "store", "event": "batch_unknown_op", "op": type(op).__name__},
                    )
                    results.append(None)
            except Exception as e:
                logger.error(
                    f"Batch op failed. {traceback.format_exc()}",
                    extra={
                        "phase": "store",
                        "event": "batch_op_error",
                        "op": type(op).__name__,
                        "exception_type": type(e).__name__,
                    },
                )
                results.append(None)

        logger.info(
            "Batch completed.",
            extra={
                "phase": "store",
                "event": "batch_done",
                "ops_count": len(ops_list),
                "duration_ms": int((time.monotonic() - t0) * 1000),
            },
        )

        return results

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        """Execute multiple operations asynchronously in a single batch."""
        import asyncio
        t0 = time.monotonic()
        ops_list = list(ops)

        logger.info(
            "Async batch dispatch.",
            extra={"phase": "store", "event": "abatch_start", "ops_count": len(ops_list)},
        )

        try:
            out = await asyncio.to_thread(self.batch, ops_list)
            logger.info(
                "Async batch completed.",
                extra={
                    "phase": "store",
                    "event": "abatch_done",
                    "ops_count": len(ops_list),
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                },
            )
            return out
        except Exception as e:
            logger.error(
                f"Async batch failed. {traceback.format_exc()}",
                extra={
                    "phase": "store",
                    "event": "abatch_error",
                    "ops_count": len(ops_list),
                    "exception_type": type(e).__name__,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                },
            )
            raise