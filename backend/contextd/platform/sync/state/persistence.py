"""Persistence service for sync state objects.

Handles storing and retrieving comprehensive state snapshots to/from the database.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud
from contextd.api.context import ApiContext
from contextd.db.unit_of_work import UnitOfWork
from contextd.models.sync_state import SyncState
from contextd.schemas.sync_state import SyncStateCreate, SyncStateData


class SyncStatePersistence:
    """Handles state object persistence to database.

    This service provides a high-level interface for storing and retrieving
    sync state snapshots, abstracting away the CRUD layer details.

    Example:
        >>> persistence = SyncStatePersistence()
        >>> # Save state after sync completion
        >>> state = await persistence.save_state(
        ...     db=db,
        ...     sync_job_id=job_id,
        ...     sync_id=sync_id,
        ...     state_data=state_data,
        ...     ctx=ctx
        ... )
        >>> # Retrieve latest state for comparison
        >>> prev_state = await persistence.get_latest_state(db, sync_id, ctx)
    """

    async def save_state(
        self,
        db: AsyncSession,
        sync_job_id: UUID,
        sync_id: UUID,
        state_data: SyncStateData,
        ctx: ApiContext,
        uow: Optional[UnitOfWork] = None,
    ) -> SyncState:
        """Persist state object to database.

        Creates a new sync_state record containing the comprehensive
        state snapshot for this sync job.

        Args:
            db: Database session
            sync_job_id: Sync job ID that created this state
            sync_id: Sync configuration ID
            state_data: Complete state data object
            ctx: API context for access control and audit tracking
            uow: Optional unit of work for transaction management

        Returns:
            Created SyncState model instance

        Example:
            >>> state_data = await builder.build_state(sync_context)
            >>> state = await persistence.save_state(
            ...     db=db,
            ...     sync_job_id=sync_context.sync_job.id,
            ...     sync_id=sync_context.sync.id,
            ...     state_data=state_data,
            ...     ctx=sync_context.ctx
            ... )
        """
        # Extract entity count from statistics
        entity_count = state_data.statistics.total_entities

        # Serialize state_data to dict for JSONB storage
        # This ensures datetime objects and nested Pydantic models are properly serialized
        state_data_dict = state_data.model_dump(mode="json")

        # Create state record
        state_create = SyncStateCreate(
            sync_job_id=sync_job_id,
            sync_id=sync_id,
            state_data=state_data_dict,
            entity_count=entity_count,
            state_version=state_data.version,
        )

        # Use UoW if provided, otherwise create one
        if uow:
            state = await crud.sync_state.create(
                db=uow.session,
                obj_in=state_create,
                ctx=ctx,
                uow=uow,
            )
        else:
            async with UnitOfWork(db) as new_uow:
                state = await crud.sync_state.create(
                    db=new_uow.session,
                    obj_in=state_create,
                    ctx=ctx,
                    uow=new_uow,
                )
                await new_uow.commit()

        ctx.logger.info(
            f"Saved sync state for job {sync_job_id}: "
            f"{entity_count} entities, version {state_data.version}"
        )

        return state

    async def get_latest_state(
        self,
        db: AsyncSession,
        sync_id: UUID,
        ctx: ApiContext,
    ) -> Optional[SyncState]:
        """Retrieve the most recent state for a sync.

        This is the primary method for Phase 2 comparison logic - it retrieves
        the previous sync's state to compare against current entities.

        Args:
            db: Database session
            sync_id: Sync configuration ID
            ctx: API context for access control

        Returns:
            Most recent SyncState if found, None if no previous state exists

        Example:
            >>> # During sync, get previous state for comparison
            >>> prev_state = await persistence.get_latest_state(
            ...     db=db,
            ...     sync_id=sync_context.sync.id,
            ...     ctx=sync_context.ctx
            ... )
            >>> if prev_state:
            ...     # Compare current entities against prev_state.state_data
            ...     pass
        """
        return await crud.sync_state.get_latest_by_sync_id(
            db=db,
            sync_id=sync_id,
            ctx=ctx,
        )

    async def get_state_for_job(
        self,
        db: AsyncSession,
        sync_job_id: UUID,
        ctx: ApiContext,
    ) -> Optional[SyncState]:
        """Retrieve state for specific sync job.

        Useful for debugging and viewing historical state snapshots.

        Args:
            db: Database session
            sync_job_id: Sync job ID
            ctx: API context for access control

        Returns:
            SyncState if found, None otherwise

        Example:
            >>> # Get state for a specific job
            >>> state = await persistence.get_state_for_job(
            ...     db=db,
            ...     sync_job_id=job_id,
            ...     ctx=ctx
            ... )
        """
        return await crud.sync_state.get_by_sync_job_id(
            db=db,
            sync_job_id=sync_job_id,
            ctx=ctx,
        )

    async def get_state_history(
        self,
        db: AsyncSession,
        sync_id: UUID,
        ctx: ApiContext,
        limit: int = 10,
    ) -> list[SyncState]:
        """Get recent state history for a sync.

        Returns the most recent N state snapshots, ordered by creation time.
        Useful for viewing state evolution over time.

        Args:
            db: Database session
            sync_id: Sync configuration ID
            ctx: API context for access control
            limit: Maximum number of states to return

        Returns:
            List of SyncState objects, newest first

        Example:
            >>> # Get last 5 states for debugging
            >>> history = await persistence.get_state_history(
            ...     db=db,
            ...     sync_id=sync_id,
            ...     ctx=ctx,
            ...     limit=5
            ... )
        """
        return await crud.sync_state.get_all_by_sync_id(
            db=db,
            sync_id=sync_id,
            ctx=ctx,
            skip=0,
            limit=limit,
        )


# Singleton instance for convenience
sync_state_persistence = SyncStatePersistence()
