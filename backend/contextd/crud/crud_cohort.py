"""CRUD for saved cohorts."""

from typing import List
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from contextd.api.context import ApiContext
from contextd.core.exceptions import NotFoundException
from contextd.crud._base_organization import CRUDBaseOrganization
from contextd.models.cohort import Cohort
from contextd.schemas.cohort import CohortCreate, CohortUpdate


class CRUDCohort(CRUDBaseOrganization[Cohort, CohortCreate, CohortUpdate]):
    """Organization-scoped cohorts, filtered by collection."""

    async def get_multi_for_collection(
        self,
        db: AsyncSession,
        *,
        collection_id: UUID,
        ctx: ApiContext,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Cohort]:
        """List cohorts for a collection."""
        q = (
            select(Cohort)
            .where(
                and_(
                    Cohort.organization_id == ctx.organization.id,
                    Cohort.collection_id == collection_id,
                )
            )
            .order_by(Cohort.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(q)
        rows = list(result.unique().scalars().all())
        for obj in rows:
            await self._validate_organization_access(ctx, obj.organization_id)
        return rows

    async def get_for_collection(
        self,
        db: AsyncSession,
        *,
        cohort_id: UUID,
        collection_id: UUID,
        ctx: ApiContext,
    ) -> Cohort:
        """Get one cohort scoped to collection."""
        q = select(Cohort).where(
            and_(
                Cohort.id == cohort_id,
                Cohort.organization_id == ctx.organization.id,
                Cohort.collection_id == collection_id,
            )
        )
        result = await db.execute(q)
        obj = result.unique().scalar_one_or_none()
        if obj is None:
            raise NotFoundException("Cohort not found")
        await self._validate_organization_access(ctx, obj.organization_id)
        return obj


cohort = CRUDCohort(Cohort)
