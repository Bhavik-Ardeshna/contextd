"""Api key model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from contextd.models._base import OrganizationBase, UserMixin

if TYPE_CHECKING:
    pass


class APIKey(OrganizationBase, UserMixin):
    """SQLAlchemy model for the APIKey table."""

    __tablename__ = "api_key"

    encrypted_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    expiration_date: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
