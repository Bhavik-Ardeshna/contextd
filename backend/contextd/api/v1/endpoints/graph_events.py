"""API endpoints for graph events with normalized entity data."""

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud
from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.router import TrailingSlashRouter

router = TrailingSlashRouter()


def _extract_normalized_data(event_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract normalized entity data from event_data if present.

    Args:
        event_data: The event data dictionary

    Returns:
        Normalized entity data or None
    """
    return event_data.get("normalized_entity") if event_data else None


def _format_event_with_normalized(event) -> Dict[str, Any]:
    """Format an event with normalized data surfaced for easy access.

    Args:
        event: The GraphEvent model instance

    Returns:
        Event dictionary with normalized data
    """
    event_dict = {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "entity_id": event.entity_id,
        "entity_type": event.entity_type,
        "field_name": event.field_name,
        "created_at": event.created_at.isoformat(),
        "event_data": event.event_data,
    }

    # Surface normalized entity data for easier frontend access
    normalized_data = _extract_normalized_data(event.event_data)
    if normalized_data:
        event_dict["normalized_entity"] = normalized_data

        # Extract key normalized fields for quick display
        event_dict["entity_name"] = normalized_data.get("name")
        event_dict["entity_description"] = normalized_data.get("description")
        event_dict["people"] = normalized_data.get("people", [])
        event_dict["tags"] = normalized_data.get("tags", [])
        event_dict["status"] = normalized_data.get("status")
        event_dict["priority"] = normalized_data.get("priority")
        event_dict["web_url"] = normalized_data.get("web_url")

    return event_dict


@router.get("/sync-jobs/{sync_job_id}/graph-events")
async def get_graph_events_by_sync_job(
    *,
    db: AsyncSession = Depends(deps.get_db),
    sync_job_id: UUID,
    include_normalized: bool = Query(True, description="Include normalized entity data"),
    ctx: ApiContext = Depends(deps.get_context),
) -> Dict[str, Any]:
    """Get all graph events generated during a sync job.

    Returns events grouped by entity and type for UI display.
    Includes normalized entity data (people, tags, status, etc.) for rich display.

    Args:
        db: Database session
        sync_job_id: Sync job ID
        include_normalized: Whether to include normalized data (default: True)
        ctx: API context

    Returns:
        Dictionary with event counts, categorized events, and normalized data
    """
    # Get events from database
    events = await crud.graph_event.get_by_sync_job(
        db=db,
        sync_job_id=sync_job_id,
        ctx=ctx,
    )

    if not events:
        return {
            "sync_job_id": str(sync_job_id),
            "total_events": 0,
            "event_counts": {
                "node_events": 0,
                "edge_events": 0,
                "metadata_events": 0,
            },
            "events_by_entity": {},
            "events_by_type": {
                "node": [],
                "edge": [],
                "metadata": [],
            },
            "normalized_entities": {},
        }

    # Organize events
    events_by_entity = {}
    events_by_type = {
        "node": [],
        "edge": [],
        "metadata": [],
    }
    normalized_entities = {}  # Cache normalized data per entity

    for event in events:
        # Add to entity grouping
        if event.entity_id not in events_by_entity:
            events_by_entity[event.entity_id] = []

        event_dict = _format_event_with_normalized(event)
        events_by_entity[event.entity_id].append(event_dict)

        # Cache normalized entity data (dedup by entity_id)
        if include_normalized and event.entity_id not in normalized_entities:
            normalized_data = _extract_normalized_data(event.event_data)
            if normalized_data:
                normalized_entities[event.entity_id] = normalized_data

        # Add to type grouping
        if event.event_type.startswith("NODE_"):
            events_by_type["node"].append(event_dict)
        elif event.event_type.startswith("EDGE_"):
            events_by_type["edge"].append(event_dict)
        elif event.event_type.startswith("METADATA_"):
            events_by_type["metadata"].append(event_dict)

    # Count by type
    event_counts = {
        "node_events": len(events_by_type["node"]),
        "edge_events": len(events_by_type["edge"]),
        "metadata_events": len(events_by_type["metadata"]),
    }

    return {
        "sync_job_id": str(sync_job_id),
        "total_events": len(events),
        "event_counts": event_counts,
        "events_by_entity": events_by_entity,
        "events_by_type": events_by_type,
        "normalized_entities": normalized_entities if include_normalized else {},
    }


@router.get("/entities/{entity_id}/graph-events")
async def get_graph_events_by_entity(
    *,
    db: AsyncSession = Depends(deps.get_db),
    entity_id: str,
    entity_definition_id: UUID,
    include_normalized: bool = Query(True, description="Include normalized entity data"),
    ctx: ApiContext = Depends(deps.get_context),
) -> Dict[str, Any]:
    """Get all graph events for a specific entity.

    Returns events with normalized entity data for rich UI display.

    Args:
        db: Database session
        entity_id: Entity ID
        entity_definition_id: Entity definition ID
        include_normalized: Whether to include normalized data (default: True)
        ctx: API context

    Returns:
        Dictionary with events and normalized data for the entity
    """
    events = await crud.graph_event.get_by_entity(
        db=db,
        entity_id=entity_id,
        entity_definition_id=entity_definition_id,
        ctx=ctx,
    )

    if not events:
        return {
            "entity_id": entity_id,
            "total_events": 0,
            "events": [],
            "normalized_entity": None,
        }

    event_list = []
    normalized_entity = None

    for event in events:
        event_dict = {
            "event_id": str(event.id),
            "event_type": event.event_type,
            "field_name": event.field_name,
            "created_at": event.created_at.isoformat(),
            "sync_job_id": str(event.sync_job_id),
            "event_data": event.event_data,
        }

        # Extract normalized data from first event that has it
        if include_normalized and normalized_entity is None:
            normalized_data = _extract_normalized_data(event.event_data)
            if normalized_data:
                normalized_entity = normalized_data
                event_dict["normalized_entity"] = normalized_data

        event_list.append(event_dict)

    response = {
        "entity_id": entity_id,
        "total_events": len(events),
        "events": event_list,
    }

    # Include normalized entity data at top level for easy access
    if include_normalized and normalized_entity:
        response["normalized_entity"] = normalized_entity
        response["entity_name"] = normalized_entity.get("name")
        response["people"] = normalized_entity.get("people", [])
        response["tags"] = normalized_entity.get("tags", [])
        response["status"] = normalized_entity.get("status")
        response["priority"] = normalized_entity.get("priority")

    return response
