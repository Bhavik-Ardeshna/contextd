"""Graph destination handler for processing graph events.

Stores events in database and returns JSON for UI display.
Includes normalized entity schema data for rich UI rendering.

Two-Phase Commit Architecture:
- Phase 1 (this handler): Store events in PostgreSQL with commit_status='pending'
- Phase 2 (GraphCommitService): Atomic commit to Neo4j after all batches complete
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from contextd.platform.contexts.sync import SyncContext
from contextd.platform.entities._normalized import NormalizedEntity
from contextd.platform.sync.graph import GraphEventBatch
from contextd.schemas.graph_event import GraphEventCreate

logger = logging.getLogger(__name__)


class GraphDestinationHandler:
    """Handles graph event processing and routing.

    Two-Phase Commit Implementation:
    - Phase 1: Store events in graph_events table with commit_status='pending'
    - Phase 2: GraphCommitService commits to Neo4j after all batches complete

    This handler is responsible for Phase 1 only - storing events in PostgreSQL.
    Neo4j writes are handled atomically in Phase 2 by GraphCommitService.
    """

    def __init__(
        self,
        sync_context: SyncContext,
        normalized_entities: Optional[Dict[str, NormalizedEntity]] = None,
    ):
        """Initialize handler.

        Args:
            sync_context: Sync context with all required dependencies
            normalized_entities: Optional dict of entity_id -> NormalizedEntity
        """
        self.sync_context = sync_context
        self.logger = sync_context.logger
        self._normalized_entities = normalized_entities or {}

    async def process_events(
        self, event_batch: GraphEventBatch
    ) -> Dict[str, Any]:
        """Process graph events - Phase 1 of two-phase commit.

        Stores events in PostgreSQL with commit_status='pending'.
        Neo4j commit happens in Phase 2 via GraphCommitService.

        Implementation:
        1. Convert TypedGraphEvent to GraphEventCreate schemas
        2. Extract node_id for deduplication
        3. Store events in graph_events table with commit_status='pending'
        4. Return formatted JSON for frontend display

        Args:
            event_batch: Batch of graph events

        Returns:
            Dictionary with event statistics and data for UI display
        """
        # Get all events
        all_events = event_batch.get_all_events()

        if not all_events:
            self.logger.info("No graph events to process")
            return {
                "status": "success",
                "sync_job_id": str(self.sync_context.sync_job.id),
                "total_events": 0,
                "event_counts": {
                    "node_events": 0,
                    "edge_events": 0,
                    "metadata_events": 0,
                },
                "events": {},
            }

        # Store events in PostgreSQL database (Phase 1)
        # Events are stored with commit_status='pending' for Phase 2 processing
        await self._store_events(event_batch)

        # Format result for frontend
        result = {
            "status": "success",
            "sync_job_id": str(self.sync_context.sync_job.id),
            "total_events": len(all_events),
            "event_counts": {
                "node_events": len(event_batch.node_events),
                "edge_events": len(event_batch.edge_events),
                "metadata_events": len(event_batch.metadata_events),
            },
            "events": event_batch.to_json(),
        }

        self.logger.info(
            f"📊 Processed {result['total_events']} graph events "
            f"(Nodes: {result['event_counts']['node_events']}, "
            f"Edges: {result['event_counts']['edge_events']}, "
            f"Metadata: {result['event_counts']['metadata_events']})"
        )

        return result

    async def _store_events(self, event_batch: GraphEventBatch) -> None:
        """Store events in graph_events table with normalized entity data.

        Phase 1 of Two-Phase Commit:
        - Extracts node_id from event payload for NODE events (used for deduplication)
        - Sets commit_status='pending' for Phase 2 processing
        - Retries on transient connection errors (pool exhaustion, timeouts)

        Args:
            event_batch: Batch of events to store
        """
        event_creates = self._build_event_creates(event_batch)

        # Retry on transient connection errors (pool exhaustion, timeouts)
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                await self._insert_events(event_creates)
                self.logger.debug(
                    f"Stored {len(event_creates)} events in database (pending commit)"
                )
                return
            except Exception as e:
                err_str = str(e).lower()
                is_transient = (
                    isinstance(e, (TimeoutError, asyncio.TimeoutError))
                    or "timeout" in err_str
                    or "pool" in err_str
                    or "connection" in err_str
                    or "cancelled" in err_str
                )
                if is_transient and attempt < max_retries:
                    wait = 0.5 * (2 ** attempt)
                    self.logger.warning(
                        f"Graph event storage attempt {attempt + 1}/{max_retries + 1} failed "
                        f"({type(e).__name__}), retrying in {wait:.1f}s..."
                    )
                    await asyncio.sleep(wait)
                else:
                    raise

    def _build_event_creates(
        self, event_batch: GraphEventBatch
    ) -> list:
        """Convert TypedGraphEvent batch to GraphEventCreate schemas."""
        event_creates = []

        for event in event_batch.get_all_events():
            # Get normalized entity data if available
            normalized_data = self._get_normalized_entity_data(event.entity_id)

            # Convert payload to dict for JSONB storage
            event_data = {
                "event_type": event.event_type,
                "timestamp": event.timestamp.isoformat(),
                "payload": event.payload.model_dump(),
            }

            # Include normalized entity data in event_data for UI rendering
            if normalized_data:
                event_data["normalized_entity"] = normalized_data

            # Extract node_id for deduplication (used in Phase 2)
            node_id = None
            if event.event_type.startswith("NODE"):
                node_id = event.payload.node_id

            event_create = GraphEventCreate(
                entity_id=event.entity_id,
                entity_type=event.entity_type,
                entity_definition_id=event.entity_definition_id,
                sync_id=self.sync_context.sync.id,
                sync_job_id=self.sync_context.sync_job.id,
                organization_id=self.sync_context.organization_id,
                event_type=event.event_type,
                field_name=event.field_name,
                node_id=node_id,
                event_data=event_data,
                commit_status='pending',
            )

            event_creates.append(event_create)

        return event_creates

    async def _insert_events(self, event_creates: list) -> None:
        """Bulk insert events into the database."""
        from contextd import crud
        from contextd.db.session import get_db_context

        async with get_db_context() as db:
            await crud.graph_event.create_batch(
                db=db,
                events=event_creates,
                ctx=self.sync_context.ctx,
            )
            await db.commit()

    def _get_normalized_entity_data(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get normalized entity data for an entity_id.

        Looks up the normalized entity in the cache and returns its serialized form.

        Args:
            entity_id: Entity ID to look up

        Returns:
            Serialized normalized entity data or None if not found
        """
        # Try to get from passed normalized entities cache
        if entity_id in self._normalized_entities:
            normalized = self._normalized_entities[entity_id]
            return normalized.model_dump(mode='json')

        # Try to get from entity pipeline's cache (via sync context)
        if hasattr(self.sync_context, 'entity_pipeline'):
            pipeline = self.sync_context.entity_pipeline
            if hasattr(pipeline, 'get_normalized_entity'):
                normalized = pipeline.get_normalized_entity(entity_id)
                if normalized:
                    return normalized.model_dump(mode='json')

        return None

    def set_normalized_entities(
        self, normalized_entities: Dict[str, NormalizedEntity]
    ) -> None:
        """Set the normalized entities cache.

        Args:
            normalized_entities: Dict mapping entity_id -> NormalizedEntity
        """
        self._normalized_entities = normalized_entities
