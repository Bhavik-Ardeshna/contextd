"""Sync connection model."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from contextd.models._base import Base

if TYPE_CHECKING:
    from contextd.models.connection import Connection
    from contextd.models.sync import Sync


class SyncConnection(Base):
    """Sync connection model."""

    __tablename__ = "sync_connection"

    sync_id: Mapped[UUID] = mapped_column(ForeignKey("sync.id", ondelete="CASCADE"), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("connection.id", ondelete="CASCADE"), nullable=False
    )

    # Add relationship back to Sync
    sync: Mapped["Sync"] = relationship("Sync", back_populates="sync_connections")
    connection: Mapped["Connection"] = relationship(
        "Connection",
        back_populates="sync_connections",
        lazy="noload",
    )
