"""Tracking context builder for sync operations.

Builds progress tracking components:
- EntityTracker: Centralized entity state tracking
- SyncStatePublisher: Redis pubsub publishing
- GuardRailService: Rate limiting
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.core.guard_rail_service import GuardRailService
from contextd.platform.contexts.infra import InfraContext
from contextd.platform.contexts.tracking import TrackingContext
from contextd.platform.sync.pipeline.entity_tracker import EntityTracker
from contextd.platform.sync.state.builder import SyncStateBuilder
from contextd.platform.sync.state_publisher import SyncStatePublisher
from contextd.schemas.entity_count import EntityCountWithDefinition


class TrackingContextBuilder:
    """Builds progress tracking context for sync operations."""

    @classmethod
    async def build(
        cls,
        db: AsyncSession,
        sync: schemas.Sync,
        sync_job: schemas.SyncJob,
        infra: InfraContext,
    ) -> TrackingContext:
        """Build complete tracking context.

        Args:
            db: Database session
            sync: Sync configuration
            sync_job: The sync job being tracked
            infra: Infrastructure context (provides ctx and logger)

        Returns:
            TrackingContext with all tracking components.
        """
        ctx = infra.ctx
        logger = infra.logger

        # Load initial entity counts from database. EntityCount rows are the fast
        # path, but dynamic structured connectors can have live normalized rows
        # before count rows are materialized or after an interrupted replay. Seed
        # the tracker with the highest trustworthy per-definition count.
        initial_counts = await cls._load_initial_counts(db, sync.id)

        logger.info(f"🔢 Loaded initial entity counts: {len(initial_counts)} entity types")

        # Log the initial counts for debugging
        for count in initial_counts:
            logger.debug(f"  - {count.entity_definition_name}: {count.count} entities")

        # Create EntityTracker (pure state tracking)
        entity_tracker = EntityTracker(
            job_id=sync_job.id,
            sync_id=sync.id,
            logger=logger,
            initial_counts=initial_counts,
        )

        # Create SyncStatePublisher (handles pubsub publishing)
        state_publisher = SyncStatePublisher(
            job_id=sync_job.id,
            sync_id=sync.id,
            entity_tracker=entity_tracker,
            logger=logger,
        )

        # Create GuardRailService with contextual logger
        guard_rail = GuardRailService(
            organization_id=ctx.organization.id,
            logger=logger.with_context(component="guardrail"),
        )

        # Create SyncStateBuilder for comprehensive state snapshots
        state_builder = SyncStateBuilder()

        logger.info(
            f"✅ Created EntityTracker, SyncStatePublisher, and SyncStateBuilder "
            f"for job {sync_job.id}"
        )

        return TrackingContext(
            entity_tracker=entity_tracker,
            state_publisher=state_publisher,
            state_builder=state_builder,
            guard_rail=guard_rail,
        )

    @classmethod
    async def _load_initial_counts(
        cls,
        db: AsyncSession,
        sync_id,
    ) -> list[EntityCountWithDefinition]:
        from contextd.models.entity import Entity
        from contextd.models.entity_definition import EntityDefinition

        counts_by_definition = {
            count.entity_definition_id: count
            for count in await crud.entity_count.get_counts_per_sync_and_type(db, sync_id)
        }

        live_query = (
            select(
                Entity.entity_definition_id,
                EntityDefinition.name,
                EntityDefinition.type,
                EntityDefinition.description,
                func.count(Entity.id).label("count"),
                func.max(Entity.modified_at).label("modified_at"),
            )
            .join(EntityDefinition, Entity.entity_definition_id == EntityDefinition.id)
            .where(Entity.sync_id == sync_id)
            .group_by(
                Entity.entity_definition_id,
                EntityDefinition.name,
                EntityDefinition.type,
                EntityDefinition.description,
            )
        )
        live_rows = await db.execute(live_query)
        for row in live_rows:
            data = row._mapping
            live_count = int(data["count"] or 0)
            definition_id = data["entity_definition_id"]
            existing = counts_by_definition.get(definition_id)
            if existing and existing.count >= live_count:
                continue
            entity_definition_type = data["type"]
            counts_by_definition[definition_id] = EntityCountWithDefinition(
                count=live_count,
                entity_definition_id=definition_id,
                entity_definition_name=data["name"],
                entity_definition_type=(
                    entity_definition_type.value
                    if hasattr(entity_definition_type, "value")
                    else entity_definition_type
                ),
                entity_definition_description=data["description"],
                modified_at=data["modified_at"],
            )

        return list(counts_by_definition.values())
