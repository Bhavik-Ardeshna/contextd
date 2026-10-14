"""Billing period schemas."""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from contextd.schemas.organization_billing import BillingPlan


class BillingPeriodStatus(str, Enum):
    """Status of a billing period."""

    ACTIVE = "active"  # Currently active period
    COMPLETED = "completed"  # Period ended, successfully paid
    ENDED_UNPAID = "ended_unpaid"  # Period ended, payment failed/pending
    TRIAL = "trial"  # Trial period (no payment required)
    GRACE = "grace"  # Grace period after failed payment


class BillingTransition(str, Enum):
    """How this billing period was created."""

    INITIAL_SIGNUP = "initial_signup"  # First subscription
    RENEWAL = "renewal"  # Automatic renewal
    UPGRADE = "upgrade"  # Plan upgrade (immediate)
    DOWNGRADE = "downgrade"  # Plan downgrade (at period end)
    REACTIVATION = "reactivation"  # Reactivated after cancellation
    TRIAL_CONVERSION = "trial_conversion"  # Trial to paid


class BillingPeriodBase(BaseModel):
    """Base billing period schema."""

    organization_id: UUID = Field(..., description="Organization this period belongs to")
    period_start: datetime = Field(..., description="Period start (inclusive)")
    period_end: datetime = Field(..., description="Period end (exclusive)")
    plan: BillingPlan = Field(..., description="Plan for this period")
    status: BillingPeriodStatus = Field(..., description="Period status")
    created_from: BillingTransition = Field(..., description="How this period was created")


class BillingPeriodCreate(BillingPeriodBase):
    """Schema for creating a billing period."""

    stripe_subscription_id: Optional[str] = Field(None, description="Stripe subscription ID")
    previous_period_id: Optional[UUID] = Field(None, description="Previous period ID")


class BillingPeriodUpdate(BaseModel):
    """Schema for updating a billing period."""

    status: Optional[BillingPeriodStatus] = None
    stripe_invoice_id: Optional[str] = None
    amount_cents: Optional[int] = None
    currency: Optional[str] = None
    paid_at: Optional[datetime] = None
    period_end: Optional[datetime] = Field(
        None, description="Update period end for early termination"
    )


class BillingPeriodInDBBase(BillingPeriodBase):
    """Base schema for billing period in database."""

    model_config = {"from_attributes": True}

    id: UUID
    stripe_subscription_id: Optional[str] = None
    stripe_invoice_id: Optional[str] = None
    amount_cents: Optional[int] = None
    currency: Optional[str] = None
    paid_at: Optional[datetime] = None
    previous_period_id: Optional[UUID] = None
    created_at: datetime
    modified_at: datetime


class BillingPeriod(BillingPeriodInDBBase):
    """Complete billing period representation."""

    pass


class BillingPeriodWithUsage(BillingPeriod):
    """Billing period with usage information."""

    usage: Optional[dict] = Field(None, description="Usage counters for this period")
