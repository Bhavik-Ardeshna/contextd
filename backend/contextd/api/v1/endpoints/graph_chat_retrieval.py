"""Deterministic graph-search retrieval helpers for graph chat endpoints."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from contextd import crud
from contextd.api.context import ApiContext
from contextd.api.v1.endpoints.graph_chat_schemas import strip_context_tool_mentions
from contextd.db.session import get_db_context

logger = logging.getLogger(__name__)


def _parse_connector_ignoring_search(message: str) -> Optional[str]:
    """Parse first @connector from message, ignoring reserved ContextD tool mentions."""
    if not message or not message.strip():
        return None
    message_without_search = strip_context_tool_mentions(
        re.sub(r"\s*@search\s*", " ", message, flags=re.IGNORECASE).strip()
    )
    from contextd.platform.agent_orchestration.business_logic import (
        parse_connector_filter_from_message,
    )

    return parse_connector_filter_from_message(message_without_search)


async def _run_graph_search_retrieval(
    readable_id: str,
    query: str,
    ctx: ApiContext,
    *,
    search_limit: int = 10,
    max_depth: int = 2,
    source_type_filter: Optional[str] = None,
    collection: Any = None,
) -> Tuple[Any, List[Dict[str, Any]]]:
    """Run deterministic path (seed search + PPR/traversal)."""
    from contextd.platform.agent_orchestration.runtime.traversal import (
        run_deterministic_graph_retrieval,
    )

    if collection is None:
        async with get_db_context() as db:
            collection = await crud.collection.get_by_readable_id(
                db, readable_id=readable_id, ctx=ctx
            )
        if not collection:
            return (None, [])

    try:
        traversal_result, search_results = await run_deterministic_graph_retrieval(
            query=query,
            organization_id=ctx.organization.id,
            collection_id=collection.id,
            readable_id=readable_id,
            ctx=ctx,
            vector_size=collection.vector_size,
            search_limit=search_limit,
            max_depth=max_depth,
            node_limit=100,
            source_type_filter=source_type_filter,
        )
        return (traversal_result, search_results or [])
    except Exception as exc:
        logger.warning("Graph search retrieval failed: %s", exc)
        return (None, [])
