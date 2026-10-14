"""CRUD operations for graph events."""

from datetime import datetime
from typing import List
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from contextd.api.context import ApiContext
from contextd.crud._base_organization import CRUDBaseOrganization
from contextd.models.graph_event import GraphEvent
from contextd.schemas.graph_event import GraphEventCreate, GraphEventUpdate


class CRUDGraphEvent(CRUDBaseOrganization[GraphEvent, GraphEventCreate, GraphEventUpdate]):
    """CRUD operations for graph events.

    Provides database operations for storing and retrieving graph events
    generated during sync execution.
    """

    async def create_batch(
        self,
        db: AsyncSession,
        events: List[GraphEventCreate],
        ctx: ApiContext,
    ) -> List[GraphEvent]:
        """Bulk insert graph events.

        Args:
            db: Database session
            events: List of events to create
            ctx: API context

        Returns:
            List of created GraphEvent models
        """
        if not events:
            return []

        # Create model instances
        db_events = [
            GraphEvent(**event.model_dump())
            for event in events
        ]

        # Add all to session
        db.add_all(db_events)
        await db.flush()

        return db_events

    async def get_by_entity(
        self,
        db: AsyncSession,
        entity_id: str,
        entity_definition_id: UUID,
        ctx: ApiContext,
    ) -> List[GraphEvent]:
        """Get all events for a specific entity.

        Args:
            db: Database session
            entity_id: Entity ID
            entity_definition_id: Entity definition ID
            ctx: API context

        Returns:
            List of GraphEvent models
        """
        stmt = (
            select(GraphEvent)
            .where(
                GraphEvent.entity_id == entity_id,
                GraphEvent.entity_definition_id == entity_definition_id,
                GraphEvent.organization_id == ctx.organization.id,
            )
            .order_by(GraphEvent.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_sync_job(
        self,
        db: AsyncSession,
        sync_job_id: UUID,
        ctx: ApiContext,
    ) -> List[GraphEvent]:
        """Get all events generated during a sync job.

        Args:
            db: Database session
            sync_job_id: Sync job ID
            ctx: API context

        Returns:
            List of GraphEvent models
        """
        stmt = (
            select(GraphEvent)
            .where(
                GraphEvent.sync_job_id == sync_job_id,
                GraphEvent.organization_id == ctx.organization.id,
            )
            .order_by(GraphEvent.created_at.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_event_type(
        self,
        db: AsyncSession,
        event_type: str,
        ctx: ApiContext,
        limit: int = 100,
    ) -> List[GraphEvent]:
        """Get events by type.

        Args:
            db: Database session
            event_type: Type of event (e.g., "NODE_CREATE")
            ctx: API context
            limit: Maximum number of events to return

        Returns:
            List of GraphEvent models
        """
        stmt = (
            select(GraphEvent)
            .where(
                GraphEvent.event_type == event_type,
                GraphEvent.organization_id == ctx.organization.id,
            )
            .order_by(GraphEvent.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_unprocessed(
        self,
        db: AsyncSession,
        ctx: ApiContext,
        limit: int = 1000,
    ) -> List[GraphEvent]:
        """Get unprocessed events.

        Args:
            db: Database session
            ctx: API context
            limit: Maximum number of events to return

        Returns:
            List of unprocessed GraphEvent models
        """
        stmt = (
            select(GraphEvent)
            .where(
                GraphEvent.processed is False,
                GraphEvent.organization_id == ctx.organization.id,
            )
            .order_by(GraphEvent.created_at.asc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # -------------------------------------------------------------------------
    # Two-Phase Commit Methods
    # -------------------------------------------------------------------------

    async def get_pending_by_sync(
        self,
        db: AsyncSession,
        sync_id: UUID,
        ctx: ApiContext,
    ) -> List[GraphEvent]:
        """Get all pending events for a sync.

        Args:
            db: Database session
            sync_id: Sync ID
            ctx: API context

        Returns:
            List of pending GraphEvent models
        """
        stmt = (
            select(GraphEvent)
            .where(
                GraphEvent.sync_id == sync_id,
                GraphEvent.commit_status == "pending",
                GraphEvent.organization_id == ctx.organization.id,
            )
            .order_by(GraphEvent.created_at.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_nodes_deduplicated(
        self,
        db: AsyncSession,
        sync_id: UUID,
        ctx: ApiContext,
    ) -> List[GraphEvent]:
        """Get deduplicated pending node events for a sync.

        Uses SQL DISTINCT ON for database-level deduplication.

        Args:
            db: Database session
            sync_id: Sync ID
            ctx: API context

        Returns:
            List of deduplicated node GraphEvent models
        """
        # Use raw SQL for DISTINCT ON which isn't directly supported in SQLAlchemy ORM
        query = text("""
            SELECT DISTINCT ON (node_id) *
            FROM graph_events
            WHERE sync_id = :sync_id
              AND event_type LIKE 'NODE%'
              AND commit_status = 'pending'
              AND organization_id = :organization_id
              AND node_id IS NOT NULL
            ORDER BY node_id, created_at DESC
        """)

        result = await db.execute(query, {
            "sync_id": str(sync_id),
            "organization_id": str(ctx.organization.id),
        })
        rows = result.fetchall()

        # Convert to GraphEvent models
        return [GraphEvent(**dict(row._mapping)) for row in rows]

    async def get_pending_edges_deduplicated(
        self,
        db: AsyncSession,
        sync_id: UUID,
        ctx: ApiContext,
    ) -> List[GraphEvent]:
        """Get deduplicated pending edge events for a sync.

        Uses SQL DISTINCT ON for database-level deduplication based on
        (from_node, to_node, edge_type) extracted from JSONB event_data.

        Args:
            db: Database session
            sync_id: Sync ID
            ctx: API context

        Returns:
            List of deduplicated edge GraphEvent models
        """
        query = text("""
            SELECT DISTINCT ON (
                event_data->'payload'->'from_node'->>'node_id',
                event_data->'payload'->'to_node'->>'node_id',
                event_data->'payload'->>'edge_type'
            ) *
            FROM graph_events
            WHERE sync_id = :sync_id
              AND event_type LIKE 'EDGE%'
              AND commit_status = 'pending'
              AND organization_id = :organization_id
            ORDER BY
                event_data->'payload'->'from_node'->>'node_id',
                event_data->'payload'->'to_node'->>'node_id',
                event_data->'payload'->>'edge_type',
                created_at DESC
        """)

        result = await db.execute(query, {
            "sync_id": str(sync_id),
            "organization_id": str(ctx.organization.id),
        })
        rows = result.fetchall()

        return [GraphEvent(**dict(row._mapping)) for row in rows]

    async def mark_committed(
        self,
        db: AsyncSession,
        sync_id: UUID,
        ctx: ApiContext,
    ) -> int:
        """Mark all pending events for a sync as committed.

        Args:
            db: Database session
            sync_id: Sync ID
            ctx: API context

        Returns:
            Number of events updated
        """
        stmt = (
            update(GraphEvent)
            .where(
                GraphEvent.sync_id == sync_id,
                GraphEvent.commit_status == "pending",
                GraphEvent.organization_id == ctx.organization.id,
            )
            .values(
                commit_status="committed",
                committed_at=datetime.utcnow(),
            )
        )
        result = await db.execute(stmt)
        return result.rowcount

    async def mark_failed(
        self,
        db: AsyncSession,
        sync_id: UUID,
        error: str,
        ctx: ApiContext,
    ) -> int:
        """Mark all pending events for a sync as failed.

        Args:
            db: Database session
            sync_id: Sync ID
            error: Error message to record
            ctx: API context

        Returns:
            Number of events updated
        """
        stmt = (
            update(GraphEvent)
            .where(
                GraphEvent.sync_id == sync_id,
                GraphEvent.commit_status == "pending",
                GraphEvent.organization_id == ctx.organization.id,
            )
            .values(
                commit_status="failed",
                commit_error=error[:1000] if error else None,
            )
        )
        result = await db.execute(stmt)
        return result.rowcount

    async def get_commit_status_counts(
        self,
        db: AsyncSession,
        sync_id: UUID,
        ctx: ApiContext,
    ) -> dict:
        """Get counts of events by commit status for a sync.

        Args:
            db: Database session
            sync_id: Sync ID
            ctx: API context

        Returns:
            Dict with status counts: {pending: N, committed: N, failed: N, skipped: N}
        """
        query = text("""
            SELECT commit_status, COUNT(*) as count
            FROM graph_events
            WHERE sync_id = :sync_id
              AND organization_id = :organization_id
            GROUP BY commit_status
        """)

        result = await db.execute(query, {
            "sync_id": str(sync_id),
            "organization_id": str(ctx.organization.id),
        })
        rows = result.fetchall()

        counts = {"pending": 0, "committed": 0, "failed": 0, "skipped": 0}
        for row in rows:
            status = row[0]
            count = row[1]
            if status in counts:
                counts[status] = count

        return counts

    async def reset_failed_to_pending(
        self,
        db: AsyncSession,
        sync_id: UUID,
        ctx: ApiContext,
    ) -> int:
        """Reset failed events to pending for retry.

        Args:
            db: Database session
            sync_id: Sync ID
            ctx: API context

        Returns:
            Number of events reset
        """
        stmt = (
            update(GraphEvent)
            .where(
                GraphEvent.sync_id == sync_id,
                GraphEvent.commit_status == "failed",
                GraphEvent.organization_id == ctx.organization.id,
            )
            .values(
                commit_status="pending",
                commit_error=None,
                committed_at=None,
            )
        )
        result = await db.execute(stmt)
        return result.rowcount


# Singleton instance
graph_event = CRUDGraphEvent(GraphEvent)
