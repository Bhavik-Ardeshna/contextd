"""CRUD operations for sync state."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from contextd.api.context import ApiContext
from contextd.crud._base_organization import CRUDBaseOrganization
from contextd.models.sync_state import SyncState
from contextd.schemas.sync_state import SyncStateCreate, SyncStateUpdate


class CRUDSyncState(CRUDBaseOrganization[SyncState, SyncStateCreate, SyncStateUpdate]):
    """CRUD operations for sync state.

    Provides database operations for storing and retrieving comprehensive
    state snapshots created during sync execution.
    """

    async def get_by_sync_job_id(
        self,
        db: AsyncSession,
        sync_job_id: UUID,
        ctx: ApiContext,
    ) -> Optional[SyncState]:
        """Get state snapshot for a specific sync job.

        Args:
            db: Database session
            sync_job_id: Sync job ID
            ctx: API context for access control

        Returns:
            SyncState if found, None otherwise
        """
        stmt = select(SyncState).where(
            SyncState.sync_job_id == sync_job_id,
            SyncState.organization_id == ctx.organization.id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_by_sync_id(
        self,
        db: AsyncSession,
        sync_id: UUID,
        ctx: ApiContext,
    ) -> Optional[SyncState]:
        """Get the most recent state snapshot for a sync.

        This is useful for Phase 2 comparison logic - comparing current
        entities against the previous sync's state.

        Args:
            db: Database session
            sync_id: Sync configuration ID
            ctx: API context for access control

        Returns:
            Most recent SyncState if found, None otherwise
        """
        stmt = (
            select(SyncState)
            .where(
                SyncState.sync_id == sync_id,
                SyncState.organization_id == ctx.organization.id,
            )
            .order_by(SyncState.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_by_sync_id(
        self,
        db: AsyncSession,
        sync_id: UUID,
        ctx: ApiContext,
        skip: int = 0,
        limit: int = 100,
    ) -> list[SyncState]:
        """Get all state snapshots for a sync, ordered by creation time.

        Useful for viewing state history and debugging.

        Args:
            db: Database session
            sync_id: Sync configuration ID
            ctx: API context for access control
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            List of SyncState objects
        """
        stmt = (
            select(SyncState)
            .where(
                SyncState.sync_id == sync_id,
                SyncState.organization_id == ctx.organization.id,
            )
            .order_by(SyncState.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_sync_id(
        self,
        db: AsyncSession,
        sync_id: UUID,
        ctx: ApiContext,
    ) -> int:
        """Count total state snapshots for a sync.

        Args:
            db: Database session
            sync_id: Sync configuration ID
            ctx: API context for access control

        Returns:
            Count of state snapshots
        """
        from sqlalchemy import func

        stmt = select(func.count(SyncState.id)).where(
            SyncState.sync_id == sync_id,
            SyncState.organization_id == ctx.organization.id,
        )
        result = await db.execute(stmt)
        return result.scalar_one()


# Singleton instance
sync_state = CRUDSyncState(SyncState)
