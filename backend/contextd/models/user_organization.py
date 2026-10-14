"""User Organization relationship model."""

from typing import TYPE_CHECKING

from sqlalchemy import UUID, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from contextd.models._base import Base

if TYPE_CHECKING:
    from contextd.models.organization import Organization
    from contextd.models.user import User


class UserOrganization(Base):
    """Many-to-many relationship between users and organizations with roles."""

    __tablename__ = "user_organization"

    user_id: Mapped[UUID] = mapped_column(UUID, ForeignKey("user.id"), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(
        UUID, ForeignKey("organization.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String, default="member", nullable=False
    )  # owner, admin, member
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="user_organizations", lazy="noload")
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="user_organizations", lazy="noload"
    )
