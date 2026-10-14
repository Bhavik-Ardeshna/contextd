"""CRUD operations for organization billing."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import schemas
from contextd.crud._base_organization import CRUDBaseOrganization
from contextd.models import OrganizationBilling


class CRUDOrganizationBilling(
    CRUDBaseOrganization[
        OrganizationBilling,
        schemas.OrganizationBillingCreate,
        schemas.OrganizationBillingUpdate,
    ]
):
    """CRUD operations for organization billing."""

    async def get_by_organization(
        self, db: AsyncSession, *, organization_id: UUID
    ) -> Optional[OrganizationBilling]:
        """Get billing record by organization ID.

        Args:
            db: Database session
            organization_id: Organization ID

        Returns:
            OrganizationBilling or None
        """
        query = select(OrganizationBilling).where(
            OrganizationBilling.organization_id == organization_id
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_stripe_customer(
        self, db: AsyncSession, *, stripe_customer_id: str
    ) -> Optional[OrganizationBilling]:
        """Get billing record by Stripe customer ID.

        Args:
            db: Database session
            stripe_customer_id: Stripe customer ID

        Returns:
            OrganizationBilling or None
        """
        query = select(OrganizationBilling).where(
            OrganizationBilling.stripe_customer_id == stripe_customer_id
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_stripe_subscription(
        self, db: AsyncSession, *, stripe_subscription_id: str
    ) -> Optional[OrganizationBilling]:
        """Get billing record by Stripe subscription ID.

        Args:
            db: Database session
            stripe_subscription_id: Stripe subscription ID

        Returns:
            OrganizationBilling or None
        """
        query = select(OrganizationBilling).where(
            OrganizationBilling.stripe_subscription_id == stripe_subscription_id
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()


organization_billing = CRUDOrganizationBilling(OrganizationBilling, track_user=False)
