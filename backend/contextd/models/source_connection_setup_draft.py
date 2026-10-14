"""Source setup draft model."""

from typing import Optional
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from contextd.models._base import OrganizationBase, UserMixin


class SourceConnectionSetupDraft(OrganizationBase, UserMixin):
    """Persisted source-setup wizard state before a source connection is finalized."""

    __tablename__ = "source_connection_setup_draft"

    provider_short_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_collection_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("collection.readable_id", ondelete="SET NULL"), nullable=True, index=True
    )
    connection_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    current_step: Mapped[str] = mapped_column(String, nullable=False, default="auth")
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    auth_method: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Never store raw secrets here. Secret values are accepted by test endpoints,
    # summarized, then persisted only in IntegrationCredential on final connection create.
    auth_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    test_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    discovery_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    scope: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    schedule: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    finalized_source_connection_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("source_connection.id", ondelete="SET NULL"), nullable=True
    )
