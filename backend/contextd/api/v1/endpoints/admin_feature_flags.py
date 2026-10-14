"""Admin feature flag endpoints."""

from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud
from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.router import TrailingSlashRouter
from contextd.api.v1.endpoints.admin_access import require_admin
from contextd.core.context_cache_service import context_cache
from contextd.core.exceptions import NotFoundException
from contextd.core.shared_models import FeatureFlag as FeatureFlagEnum

router = TrailingSlashRouter()


@router.get("/feature-flags", response_model=List[dict])
async def list_available_feature_flags(
    ctx: ApiContext = Depends(deps.get_context),
) -> List[dict]:
    """Get all available feature flags in the system."""
    require_admin(ctx)
    return serialize_available_feature_flags()


@router.post("/organizations/{organization_id}/feature-flags/{flag}/enable")
async def enable_feature_flag(
    organization_id: UUID,
    flag: str,
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> dict:
    """Enable a feature flag for an organization."""
    require_admin(ctx)

    org = await crud.organization.get(db, organization_id, ctx, skip_access_validation=True)
    if not org:
        raise NotFoundException(f"Organization {organization_id} not found")

    try:
        feature_flag = FeatureFlagEnum(flag)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid feature flag: {flag}") from exc

    await crud.organization.enable_feature(db, organization_id, feature_flag)
    await context_cache.invalidate_organization(organization_id)

    ctx.logger.info(f"Admin enabled feature flag {flag} for org {organization_id}")
    return {"message": f"Feature flag '{flag}' enabled", "organization_id": str(organization_id)}


@router.post("/organizations/{organization_id}/feature-flags/{flag}/disable")
async def disable_feature_flag(
    organization_id: UUID,
    flag: str,
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> dict:
    """Disable a feature flag for an organization."""
    require_admin(ctx)

    org = await crud.organization.get(db, organization_id, ctx, skip_access_validation=True)
    if not org:
        raise NotFoundException(f"Organization {organization_id} not found")

    try:
        feature_flag = FeatureFlagEnum(flag)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid feature flag: {flag}") from exc

    await crud.organization.disable_feature(db, organization_id, feature_flag)
    await context_cache.invalidate_organization(organization_id)

    ctx.logger.info(f"Admin disabled feature flag {flag} for org {organization_id}")
    return {"message": f"Feature flag '{flag}' disabled", "organization_id": str(organization_id)}


def serialize_available_feature_flags() -> List[dict]:
    return [{"name": flag.name, "value": flag.value} for flag in FeatureFlagEnum]
