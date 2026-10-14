"""Event batching for graph events.

Organizes graph events by type and entity for efficient processing.
"""

from typing import Any, Dict, List
from uuid import uuid4

from contextd.schemas.graph_event import TypedGraphEvent


class GraphEventBatch:
    """Batch of graph events organized by type.

    Provides efficient organization and access to events by type,
    and JSON serialization for frontend display.
    """

    def __init__(self):
        """Initialize empty event batch."""
        self.node_events: List[TypedGraphEvent] = []
        self.edge_events: List[TypedGraphEvent] = []
        self.metadata_events: List[TypedGraphEvent] = []
        self.entity_events_map: Dict[str, List[TypedGraphEvent]] = {}

    def add_events(self, entity_id: str, events: List[TypedGraphEvent]) -> None:
        """Add events for an entity.

        Args:
            entity_id: ID of the entity
            events: List of events to add
        """
        if entity_id not in self.entity_events_map:
            self.entity_events_map[entity_id] = []

        self.entity_events_map[entity_id].extend(events)

        # Categorize by event type
        for event in events:
            if event.event_type.startswith("NODE_"):
                self.node_events.append(event)
            elif event.event_type.startswith("EDGE_"):
                self.edge_events.append(event)
            elif event.event_type.startswith("METADATA_"):
                self.metadata_events.append(event)

    def get_all_events(self) -> List[TypedGraphEvent]:
        """Get all events in batch.

        Returns:
            List of all events
        """
        return self.node_events + self.edge_events + self.metadata_events

    def to_json(self) -> Dict[str, Any]:
        """Serialize batch for frontend display.

        Returns:
            Dictionary with event counts and categorized events
        """
        return {
            "total_events": len(self.get_all_events()),
            "event_counts": {
                "node_events": len(self.node_events),
                "edge_events": len(self.edge_events),
                "metadata_events": len(self.metadata_events),
            },
            "events_by_entity": {
                entity_id: [
                    {
                        "event_id": str(event.event_id if event.event_id else uuid4()),
                        "event_type": event.event_type,
                        "field_name": event.field_name,
                        "timestamp": event.timestamp.isoformat(),
                        "payload": event.payload.model_dump(),
                    }
                    for event in events
                ]
                for entity_id, events in self.entity_events_map.items()
            },
            "events_by_type": {
                "node": [
                    {
                        "event_id": str(event.event_id if event.event_id else uuid4()),
                        "entity_id": event.entity_id,
                        "entity_type": event.entity_type,
                        "field_name": event.field_name,
                        "event_type": event.event_type,
                        "payload": event.payload.model_dump(),
                    }
                    for event in self.node_events
                ],
                "edge": [
                    {
                        "event_id": str(event.event_id if event.event_id else uuid4()),
                        "entity_id": event.entity_id,
                        "entity_type": event.entity_type,
                        "field_name": event.field_name,
                        "event_type": event.event_type,
                        "payload": event.payload.model_dump(),
                    }
                    for event in self.edge_events
                ],
                "metadata": [
                    {
                        "event_id": str(event.event_id if event.event_id else uuid4()),
                        "entity_id": event.entity_id,
                        "entity_type": event.entity_type,
                        "field_name": event.field_name,
                        "event_type": event.event_type,
                        "payload": event.payload.model_dump(),
                    }
                    for event in self.metadata_events
                ],
            },
        }
