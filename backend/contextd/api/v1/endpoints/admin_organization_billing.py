"""Admin organization billing endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.router import TrailingSlashRouter
from contextd.api.v1.endpoints.admin_access import require_admin
from contextd.billing.service import billing_service
from contextd.core.context_cache_service import context_cache
from contextd.core.exceptions import InvalidStateError, NotFoundException
from contextd.core.organization_service import organization_service
from contextd.crud.crud_organization_billing import organization_billing
from contextd.db.unit_of_work import UnitOfWork
from contextd.integrations.auth0_management import auth0_management_client
from contextd.integrations.stripe_client import stripe_client
from contextd.models.organization import Organization
from contextd.models.organization_billing import OrganizationBilling
from contextd.models.user_organization import UserOrganization
from contextd.schemas.organization_billing import BillingPlan, BillingStatus

router = TrailingSlashRouter()


@router.post("/organizations/{organization_id}/upgrade-to-enterprise")
async def upgrade_organization_to_enterprise(  # noqa: C901
    organization_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.Organization:
    """Upgrade an organization to enterprise plan (admin only).

    Uses the existing billing service infrastructure to properly handle
    enterprise upgrades with Stripe customer and $0 subscription management.

    For new billing: Creates Stripe customer + $0 enterprise subscription.
    For existing billing: Upgrades plan using billing service.

    Args:
        organization_id: The organization to upgrade
        db: Database session
        ctx: API context

    Returns:
        The updated organization

    Raises:
        HTTPException: If user is not an admin or organization doesn't exist
    """
    require_admin(ctx)

    org = await crud.organization.get(db, organization_id, ctx, enrich=False)
    if not org:
        raise NotFoundException(f"Organization {organization_id} not found")

    org_schema = schemas.Organization.model_validate(org, from_attributes=True)
    billing = await organization_billing.get_by_organization(db, organization_id=organization_id)

    if not billing:
        ctx.logger.info(f"Creating enterprise billing for org {organization_id}")

        owner_email = ctx.user.email if ctx.user else "admin@contextd.local"
        result = await db.execute(
            select(UserOrganization).where(
                UserOrganization.organization_id == organization_id,
                UserOrganization.role == "owner",
            )
        )
        owner_user_org = result.scalar_one_or_none()

        if owner_user_org:
            from contextd.models.user import User

            result = await db.execute(select(User).where(User.id == owner_user_org.user_id))
            owner_user = result.scalar_one_or_none()
            if owner_user:
                owner_email = owner_user.email

        if not org.org_metadata:
            org.org_metadata = {}
        org.org_metadata["plan"] = "enterprise"
        await db.flush()

        internal_ctx = billing_service._create_system_context(org_schema, "admin_upgrade")

        if not stripe_client:
            raise InvalidStateError("Stripe is not enabled")

        customer = await stripe_client.create_customer(
            email=owner_email,
            name=org.name,
            metadata={
                "organization_id": str(organization_id),
                "plan": "enterprise",
            },
        )

        async with UnitOfWork(db) as uow:
            await billing_service.create_billing_record(
                db=db,
                organization=org,
                stripe_customer_id=customer.id,
                billing_email=owner_email,
                ctx=internal_ctx,
                uow=uow,
                contextual_logger=ctx.logger,
            )
            await uow.commit()

        ctx.logger.info(f"Created enterprise billing for org {organization_id}")
    else:
        ctx.logger.info(f"Upgrading org {organization_id} to enterprise")

        if billing.stripe_subscription_id:
            try:
                await stripe_client.cancel_subscription(
                    billing.stripe_subscription_id, at_period_end=False
                )
                ctx.logger.info(f"Cancelled subscription {billing.stripe_subscription_id}")
            except Exception as exc:
                ctx.logger.warning(f"Failed to cancel subscription: {exc}")

        if stripe_client:
            price_id = stripe_client.get_price_for_plan(BillingPlan.ENTERPRISE)
            if price_id:
                sub = await stripe_client.create_subscription(
                    customer_id=billing.stripe_customer_id,
                    price_id=price_id,
                    metadata={
                        "organization_id": str(organization_id),
                        "plan": "enterprise",
                    },
                )
                ctx.logger.info(
                    f"Created $0 enterprise subscription {sub.id}, "
                    f"webhook will update billing record"
                )
            else:
                raise InvalidStateError("Enterprise price ID not configured")
        else:
            raise InvalidStateError("Stripe is not enabled")

        await db.commit()
        ctx.logger.info(f"Enterprise subscription created for org {organization_id}")

    await db.refresh(org)
    await context_cache.invalidate_organization(organization_id)
    return schemas.Organization.model_validate(org)


@router.post("/organizations/create-enterprise", response_model=schemas.Organization)
async def create_enterprise_organization(
    organization_data: schemas.OrganizationCreate,
    owner_email: str,
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.Organization:
    """Create a new enterprise organization (admin only).

    This creates an organization directly on the enterprise plan.

    Args:
        organization_data: The organization data
        owner_email: Email of the user who will own this organization
        db: Database session
        ctx: API context

    Returns:
        The created organization

    Raises:
        HTTPException: If user is not an admin or owner user doesn't exist
    """
    require_admin(ctx)

    try:
        owner_user = await crud.user.get_by_email(db, email=owner_email)
    except NotFoundException:
        raise HTTPException(status_code=404, detail=f"User with email {owner_email} not found")

    async with UnitOfWork(db) as uow:
        from contextd.core.datetime_utils import utc_now_naive

        org = Organization(
            name=organization_data.name,
            description=organization_data.description,
            created_by_email=ctx.user.email,
            modified_by_email=ctx.user.email,
        )
        uow.session.add(org)
        await uow.session.flush()

        user_org = UserOrganization(
            user_id=owner_user.id,
            organization_id=org.id,
            role="owner",
            is_primary=len(owner_user.user_organizations) == 0,
        )
        uow.session.add(user_org)

        try:
            customer = await stripe_client.create_customer(
                email=owner_email,
                name=org.name,
                metadata={"organization_id": str(org.id), "plan": "enterprise"},
            )

            billing = OrganizationBilling(
                organization_id=org.id,
                stripe_customer_id=customer.id,
                stripe_subscription_id=None,
                billing_plan="enterprise",
                billing_status=BillingStatus.ACTIVE,
                billing_email=owner_email,
                payment_method_added=True,
                current_period_start=utc_now_naive(),
                current_period_end=None,
            )
            uow.session.add(billing)
        except Exception as exc:
            ctx.logger.error(f"Failed to create Stripe customer for enterprise org: {exc}")
            raise HTTPException(status_code=500, detail=f"Failed to create billing: {str(exc)}")

        await uow.session.commit()
        await uow.session.refresh(org)

        ctx.logger.info(f"Created enterprise organization {org.id} for {owner_email}")

    try:
        if owner_user.auth0_id and auth0_management_client:
            auth0_org_name = organization_service._create_org_name(
                schemas.OrganizationCreate(name=org.name, description=org.description)
            )

            auth0_org = await auth0_management_client.create_organization(
                name=auth0_org_name,
                display_name=org.name,
            )

            org.auth0_org_id = auth0_org["id"]
            await db.commit()
            await db.refresh(org)

            await auth0_management_client.add_user_to_organization(
                org_id=auth0_org["id"],
                user_id=owner_user.auth0_id,
            )

            ctx.logger.info(f"Created Auth0 organization for {org.id}")
    except Exception as exc:
        ctx.logger.warning(f"Failed to create Auth0 organization: {exc}")

    await context_cache.invalidate_user(owner_user.email)

    return schemas.Organization.model_validate(org)
