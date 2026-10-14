"""Organization feature flag model."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from contextd.models._base import Base

if TYPE_CHECKING:
    from contextd.models.organization import Organization


class FeatureFlag(Base):
    """Organization-specific feature flag assignments.

    N-to-1 relationship: Multiple flags per organization.
    Ensures each flag can only be assigned once per organization.
    """

    __tablename__ = "feature_flag"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), nullable=False, index=True
    )
    flag: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="feature_flags", lazy="noload"
    )

    __table_args__ = (UniqueConstraint("organization_id", "flag", name="uq_org_flag"),)
