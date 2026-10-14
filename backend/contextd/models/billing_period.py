"""Billing period model for tracking subscription periods."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import CheckConstraint, Index

from contextd.models._base import Base

if TYPE_CHECKING:
    from contextd.models.organization import Organization
    from contextd.models.usage import Usage


class BillingPeriod(Base):
    """Represents a discrete billing period for an organization."""

    __tablename__ = "billing_period"

    # Foreign key to organization
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), nullable=False
    )

    # Period boundaries (inclusive start, exclusive end)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    # Billing details at time of period
    plan: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)

    # Stripe references
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    stripe_invoice_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Payment tracking
    amount_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)

    # State transition metadata
    created_from: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_period_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("billing_period.id"), nullable=True
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="billing_periods"
    )
    usage: Mapped[Optional["Usage"]] = relationship(
        "Usage", back_populates="billing_period", uselist=False
    )
    previous_period: Mapped[Optional["BillingPeriod"]] = relationship(
        "BillingPeriod",
        remote_side="BillingPeriod.id",
        foreign_keys=[previous_period_id],
    )

    __table_args__ = (
        # Ensure period_end is after period_start
        CheckConstraint("period_end > period_start", name="check_period_end_after_start"),
        # Index for efficient queries
        Index("ix_billing_period_org_dates", "organization_id", "period_start", "period_end"),
        Index("ix_billing_period_org_status", "organization_id", "status"),
    )
