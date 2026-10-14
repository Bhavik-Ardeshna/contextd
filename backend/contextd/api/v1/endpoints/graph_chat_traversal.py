"""Graph traversal endpoint service."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from contextd import crud
from contextd.api.context import ApiContext
from contextd.api.v1.endpoints.graph_chat_schemas import TraverseRequest, TraverseResponse
from contextd.core.logging import LoggerConfigurator
from contextd.db.session import get_db_context
from contextd.platform.graph.traversal import (
    TraversalConfig,
    TraversalDirection,
    TraversalService,
)

logger = LoggerConfigurator.configure_logger(__name__)


async def traverse_graph_for_request(
    readable_id: str,
    request: TraverseRequest,
    ctx: ApiContext,
) -> TraverseResponse:
    """Traverse graph from starting nodes."""
    async with get_db_context() as db:
        collection = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")

    if not request.node_ids:
        raise HTTPException(status_code=400, detail="At least one node_id is required")

    config = build_traversal_config(request)

    try:
        service = await TraversalService.create()

        try:
            result = await service.traverse(
                node_ids=request.node_ids,
                organization_id=ctx.organization.id,
                config=config,
                readable_collection_id=readable_id,
            )
            return build_traverse_response(result)
        finally:
            await service.close()

    except Exception as exc:
        logger.error("Graph traversal failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Traversal failed: {str(exc)}") from exc


def resolve_traversal_direction(direction: str) -> TraversalDirection:
    direction_map = {
        "outgoing": TraversalDirection.OUTGOING,
        "incoming": TraversalDirection.INCOMING,
        "both": TraversalDirection.BOTH,
    }
    return direction_map.get(direction.lower(), TraversalDirection.BOTH)


def build_traversal_config(request: TraverseRequest) -> TraversalConfig:
    return TraversalConfig(
        max_depth=request.max_depth,
        direction=resolve_traversal_direction(request.direction),
        relationship_types=request.relationship_types,
        node_limit=request.node_limit,
        include_properties=request.include_properties,
    )


def build_traverse_response(result: Any) -> TraverseResponse:
    return TraverseResponse(
        nodes=[
            {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "name": node.name,
                "properties": node.properties,
                "depth": node.depth,
            }
            for node in result.nodes
        ],
        edges=[
            {
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "relationship_type": edge.relationship_type,
                "properties": edge.properties,
            }
            for edge in result.edges
        ],
        start_node_ids=result.start_node_ids,
        stats=result.stats,
    )
