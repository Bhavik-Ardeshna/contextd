"""Shared access helpers for admin endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import schemas
from contextd.api.context import ApiContext
from contextd.core.exceptions import NotFoundException
from contextd.core.shared_models import FeatureFlag as FeatureFlagEnum
from contextd.models.organization import Organization


def require_admin(ctx: ApiContext) -> None:
    """Validate that the caller is an admin or superuser."""
    if not ctx.has_user_context or not (ctx.user.is_admin or ctx.user.is_superuser):
        raise HTTPException(status_code=403, detail="Admin access required")


def require_admin_permission(ctx: ApiContext, permission: FeatureFlagEnum) -> None:
    """Validate admin access with scoped API key permission support."""
    if ctx.has_user_context and (ctx.user.is_admin or ctx.user.is_superuser):
        ctx.logger.debug(f"Admin access granted via user: {ctx.user.email}")
        return

    if ctx.is_api_key_auth and ctx.has_feature(permission):
        ctx.logger.info(
            f"Admin access granted via API key with permission: {permission.value}",
            extra={
                "permission": permission.value,
                "organization_id": str(ctx.organization.id),
                "auth_method": ctx.auth_method.value,
            },
        )
        return

    if ctx.is_api_key_auth:
        raise HTTPException(
            status_code=403,
            detail=f"API key requires '{permission.value}' feature flag for admin access",
        )
    raise HTTPException(status_code=403, detail="Admin access required")


async def build_org_context(
    db: AsyncSession,
    target_org_id: UUID,
    admin_ctx: ApiContext,
) -> ApiContext:
    """Build an ApiContext for a target organization during cross-org admin operations."""
    from sqlalchemy import select as sa_select

    from contextd.core.logging import LoggerConfigurator

    org_result = await db.execute(sa_select(Organization).where(Organization.id == target_org_id))
    org_obj = org_result.scalar_one_or_none()
    if not org_obj:
        raise NotFoundException(f"Organization {target_org_id} not found")

    target_org = schemas.Organization.model_validate(org_obj, from_attributes=True)
    return ApiContext(
        request_id=admin_ctx.request_id,
        organization=target_org,
        user=admin_ctx.user,
        auth_method=admin_ctx.auth_method,
        auth_metadata=admin_ctx.auth_metadata,
        logger=LoggerConfigurator.configure_logger(
            "contextd.admin.cross_org",
            dimensions={
                "request_id": admin_ctx.request_id,
                "organization_id": str(target_org.id),
                "organization_name": target_org.name,
                "admin_org_id": str(admin_ctx.organization.id),
                "auth_method": admin_ctx.auth_method.value,
            },
        ),
    )
