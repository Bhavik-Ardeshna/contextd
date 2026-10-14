"""Organization helper functions for admin endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from contextd.api.context import ApiContext
from contextd.models.organization import Organization
from contextd.models.organization_billing import OrganizationBilling
from contextd.models.user_organization import UserOrganization


def build_sort_subqueries(query, sort_by: str):
    """Build organization-list sort subqueries based on sort field."""
    from datetime import datetime

    from sqlalchemy import select as sa_select

    from contextd.models.billing_period import BillingPeriod
    from contextd.models.source_connection import SourceConnection
    from contextd.models.usage import Usage
    from contextd.models.user import User
    from contextd.schemas.billing_period import BillingPeriodStatus

    subqueries = {}

    if sort_by in ["entity_count", "query_count"]:
        now = datetime.utcnow()
        query = query.outerjoin(
            BillingPeriod,
            and_(
                BillingPeriod.organization_id == Organization.id,
                BillingPeriod.period_start <= now,
                BillingPeriod.period_end > now,
                BillingPeriod.status.in_(
                    [
                        BillingPeriodStatus.ACTIVE,
                        BillingPeriodStatus.TRIAL,
                        BillingPeriodStatus.GRACE,
                    ]
                ),
            ),
        ).outerjoin(Usage, Usage.billing_period_id == BillingPeriod.id)
        subqueries["Usage"] = Usage

    if sort_by == "user_count":
        user_count_subq = (
            sa_select(
                UserOrganization.organization_id,
                func.count(UserOrganization.user_id).label("user_count"),
            )
            .group_by(UserOrganization.organization_id)
            .subquery()
        )
        query = query.outerjoin(
            user_count_subq, Organization.id == user_count_subq.c.organization_id
        )
        subqueries["user_count_subq"] = user_count_subq

    if sort_by == "source_connection_count":
        source_connection_count_subq = (
            sa_select(
                SourceConnection.organization_id,
                func.count(SourceConnection.id).label("source_connection_count"),
            )
            .group_by(SourceConnection.organization_id)
            .subquery()
        )
        query = query.outerjoin(
            source_connection_count_subq,
            Organization.id == source_connection_count_subq.c.organization_id,
        )
        subqueries["source_connection_count_subq"] = source_connection_count_subq

    if sort_by == "last_active_at":
        max_active_subq = (
            sa_select(
                UserOrganization.organization_id,
                func.max(User.last_active_at).label("max_last_active"),
            )
            .join(User, UserOrganization.user_id == User.id)
            .group_by(UserOrganization.organization_id)
            .subquery()
        )
        query = query.outerjoin(
            max_active_subq, Organization.id == max_active_subq.c.organization_id
        )
        subqueries["max_active_subq"] = max_active_subq

    return query, subqueries


def get_sort_column(sort_by: str, subqueries: dict):
    """Get the SQLAlchemy column used for organization-list sorting."""
    from contextd.models.usage import Usage

    column_map = {
        "billing_plan": OrganizationBilling.billing_plan,
        "billing_status": OrganizationBilling.billing_status,
        "entity_count": Usage.entities,
        "query_count": Usage.queries,
        "is_member": Organization.created_at,
    }

    if sort_by in column_map:
        return column_map[sort_by]
    if sort_by == "user_count" and "user_count_subq" in subqueries:
        return subqueries["user_count_subq"].c.user_count
    if sort_by == "source_connection_count" and "source_connection_count_subq" in subqueries:
        return subqueries["source_connection_count_subq"].c.source_connection_count
    if sort_by == "last_active_at" and "max_active_subq" in subqueries:
        return subqueries["max_active_subq"].c.max_last_active
    if hasattr(Organization, sort_by):
        return getattr(Organization, sort_by)
    return Organization.created_at


async def update_or_create_membership(
    db: AsyncSession, ctx: ApiContext, organization_id: UUID, role: str
) -> bool:
    """Update existing membership or create a new one."""
    existing_user_org = None
    for user_org in ctx.user.user_organizations:
        if user_org.organization.id == organization_id:
            existing_user_org = user_org
            break

    if existing_user_org:
        return await update_membership_role(db, ctx, organization_id, role, existing_user_org)

    return await create_new_membership(db, ctx, organization_id, role)


async def update_membership_role(
    db: AsyncSession, ctx: ApiContext, organization_id: UUID, role: str, existing_user_org
) -> bool:
    """Update role if different, return True if changed."""
    if existing_user_org.role == role:
        ctx.logger.info(
            f"Admin {ctx.user.email} already member of org {organization_id} with role {role}"
        )
        return False

    from sqlalchemy import update

    stmt = (
        update(UserOrganization)
        .where(
            UserOrganization.user_id == ctx.user.id,
            UserOrganization.organization_id == organization_id,
        )
        .values(role=role)
    )
    await db.execute(stmt)
    await db.commit()
    ctx.logger.info(f"Admin {ctx.user.email} updated role in org {organization_id} to {role}")
    return True


async def create_new_membership(
    db: AsyncSession, ctx: ApiContext, organization_id: UUID, role: str
) -> bool:
    """Create a new membership, return True if successful."""
    try:
        user_org = UserOrganization(
            user_id=ctx.user.id,
            organization_id=organization_id,
            role=role,
            is_primary=False,
        )
        db.add(user_org)
        await db.commit()
        ctx.logger.info(
            f"Admin {ctx.user.email} added self to org {organization_id} with role {role}"
        )
        return True
    except Exception as exc:
        ctx.logger.error(f"Failed to add admin to organization: {exc}")
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add user to organization: {str(exc)}",
        ) from exc
