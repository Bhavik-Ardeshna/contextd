"""Admin organization endpoints."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.router import TrailingSlashRouter
from contextd.api.v1.endpoints.admin_access import require_admin
from contextd.api.v1.endpoints.admin_organization_helpers import (
    build_sort_subqueries,
    get_sort_column,
    update_or_create_membership,
)
from contextd.core.context_cache_service import context_cache
from contextd.core.exceptions import NotFoundException
from contextd.core.shared_models import FeatureFlag as FeatureFlagEnum
from contextd.integrations.auth0_management import auth0_management_client
from contextd.models.organization import Organization
from contextd.models.organization_billing import OrganizationBilling
from contextd.models.user_organization import UserOrganization

router = TrailingSlashRouter()


@router.get("/organizations", response_model=List[schemas.OrganizationMetrics])
async def list_all_organizations(
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
    skip: int = 0,
    limit: int = Query(1000, le=10000, description="Maximum number of organizations to return"),
    search: Optional[str] = Query(None, description="Search by organization name"),
    sort_by: str = Query("created_at", description="Field to sort by"),
    sort_order: str = Query("desc", description="Sort order (asc or desc)"),
) -> List[schemas.OrganizationMetrics]:
    """List all organizations with comprehensive metrics (admin only).

    This endpoint fetches all organizations with their billing info and usage metrics
    using optimized queries to minimize database round-trips.

    Args:
        db: Database session
        ctx: API context
        skip: Number of organizations to skip
        limit: Maximum number of organizations to return (default 1000, max 10000)
        search: Optional search term to filter by organization name
        sort_by: Field to sort by (name, created_at, billing_plan, user_count,
            source_connection_count, entity_count, query_count, last_active_at)
        sort_order: Sort order (asc or desc)

    Returns:
        List of all organizations with comprehensive metrics

    Raises:
        HTTPException: If user is not an admin
    """
    require_admin(ctx)

    query = select(Organization).outerjoin(
        OrganizationBilling, Organization.id == OrganizationBilling.organization_id
    )
    query, subqueries = build_sort_subqueries(query, sort_by)

    if search:
        query = query.where(Organization.name.ilike(f"%{search}%"))

    sort_column = get_sort_column(sort_by, subqueries)
    if sort_order.lower() == "asc":
        query = query.order_by(sort_column.asc().nullslast())
    else:
        query = query.order_by(sort_column.desc().nullslast())

    result = await db.execute(query.offset(skip).limit(limit))
    orgs = list(result.scalars().all())
    if not orgs:
        return []

    org_ids = [org.id for org in orgs]

    billing_result = await db.execute(
        select(OrganizationBilling).where(OrganizationBilling.organization_id.in_(org_ids))
    )
    billing_map = {b.organization_id: b for b in billing_result.scalars().all()}

    user_count_result = await db.execute(
        select(
            UserOrganization.organization_id,
            func.count(UserOrganization.user_id).label("count"),
        )
        .where(UserOrganization.organization_id.in_(org_ids))
        .group_by(UserOrganization.organization_id)
    )
    user_count_map = {row.organization_id: row.count for row in user_count_result}

    admin_membership_result = await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == ctx.user.id,
            UserOrganization.organization_id.in_(org_ids),
        )
    )
    admin_membership_map = {
        uo.organization_id: uo.role for uo in admin_membership_result.scalars().all()
    }

    from contextd.models.user import User

    last_active_result = await db.execute(
        select(
            UserOrganization.organization_id,
            func.max(User.last_active_at).label("last_active"),
        )
        .join(User, UserOrganization.user_id == User.id)
        .where(UserOrganization.organization_id.in_(org_ids))
        .group_by(UserOrganization.organization_id)
    )
    last_active_map = {row.organization_id: row.last_active for row in last_active_result}

    usage_map = await crud.usage.get_current_usage_for_orgs(db, organization_ids=org_ids)

    from contextd.models.source_connection import SourceConnection

    source_connection_result = await db.execute(
        select(
            SourceConnection.organization_id,
            func.count(SourceConnection.id).label("count"),
        )
        .where(SourceConnection.organization_id.in_(org_ids))
        .group_by(SourceConnection.organization_id)
    )
    source_connection_map = {row.organization_id: row.count for row in source_connection_result}

    org_metrics = []
    for org in orgs:
        billing = billing_map.get(org.id)
        usage_record = usage_map.get(org.id)
        admin_role = admin_membership_map.get(org.id)
        enabled_features = [FeatureFlagEnum(ff.flag) for ff in org.feature_flags if ff.enabled]

        org_metrics.append(
            schemas.OrganizationMetrics(
                id=org.id,
                name=org.name,
                description=org.description,
                created_at=org.created_at,
                modified_at=org.modified_at,
                auth0_org_id=org.auth0_org_id,
                billing_plan=billing.billing_plan if billing else None,
                billing_status=billing.billing_status if billing else None,
                stripe_customer_id=billing.stripe_customer_id if billing else None,
                trial_ends_at=billing.trial_ends_at if billing else None,
                user_count=user_count_map.get(org.id, 0),
                source_connection_count=source_connection_map.get(org.id, 0),
                entity_count=usage_record.entities if usage_record else 0,
                query_count=usage_record.queries if usage_record else 0,
                last_active_at=last_active_map.get(org.id),
                is_member=admin_role is not None,
                member_role=admin_role,
                enabled_features=enabled_features,
            )
        )

    ctx.logger.info(
        f"Admin retrieved {len(org_metrics)} organizations "
        f"(search={search}, sort_by={sort_by}, sort_order={sort_order})"
    )
    return org_metrics


@router.post(
    "/organizations/{organization_id}/add-self",
    response_model=schemas.OrganizationWithRole,
)
async def add_self_to_organization(
    organization_id: UUID,
    role: str = "owner",
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.OrganizationWithRole:
    """Add the admin user to an organization (admin only).

    This allows admins to join any organization for support purposes.

    Args:
        organization_id: The organization to join
        role: Role to assign (owner, admin, or member)
        db: Database session
        ctx: API context

    Returns:
        The organization with the admin's new role

    Raises:
        HTTPException: If user is not an admin or organization doesn't exist
    """
    require_admin(ctx)

    if role not in ["owner", "admin", "member"]:
        raise HTTPException(status_code=400, detail="Invalid role. Must be owner, admin, or member")

    org = await crud.organization.get(db, organization_id, ctx)
    if not org:
        raise NotFoundException(f"Organization {organization_id} not found")

    org_data = {
        "id": org.id,
        "name": org.name,
        "description": org.description,
        "created_at": org.created_at,
        "modified_at": org.modified_at,
        "auth0_org_id": org.auth0_org_id,
        "org_metadata": org.org_metadata,
    }

    membership_changed = await update_or_create_membership(db, ctx, organization_id, role)

    try:
        if org_data["auth0_org_id"] and ctx.user.auth0_id and auth0_management_client:
            await auth0_management_client.add_user_to_organization(
                org_id=org_data["auth0_org_id"],
                user_id=ctx.user.auth0_id,
            )
            ctx.logger.info(f"Added admin {ctx.user.email} to Auth0 org {org_data['auth0_org_id']}")
    except Exception as exc:
        ctx.logger.warning(f"Failed to add admin to Auth0 organization: {exc}")

    if membership_changed and ctx.user and ctx.user.email:
        await context_cache.invalidate_user(ctx.user.email)

    return schemas.OrganizationWithRole(
        id=org_data["id"],
        name=org_data["name"],
        description=org_data["description"],
        created_at=org_data["created_at"],
        modified_at=org_data["modified_at"],
        role=role,
        is_primary=False,
        auth0_org_id=org_data["auth0_org_id"],
        org_metadata=org_data["org_metadata"],
    )
