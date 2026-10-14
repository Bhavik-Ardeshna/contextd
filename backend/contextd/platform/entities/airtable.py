"""Airtable entity schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import computed_field

from contextd.platform.entities._base import BaseEntity, FileEntity
from contextd.platform.entities._contextd_field import ContextDField


class AirtableUserEntity(BaseEntity):
    """The authenticated user (from /meta/whoami endpoint)."""

    user_id: str = ContextDField(..., description="Airtable user ID", is_entity_id=True)
    display_name: str = ContextDField(
        ..., description="Display name derived from email or ID", is_name=True, embeddable=True
    )

    email: Optional[str] = ContextDField(None, description="User email address", embeddable=True)
    scopes: Optional[List[str]] = ContextDField(
        default=None, description="OAuth scopes granted to the token", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Account settings page for the authenticated user."""
        return "https://airtable.com/account"


class AirtableBaseEntity(BaseEntity):
    """Metadata for an Airtable base."""

    base_id: str = ContextDField(..., description="Airtable base ID", is_entity_id=True)
    name: str = ContextDField(..., description="Base name", is_name=True, embeddable=True)

    permission_level: Optional[str] = ContextDField(
        None, description="Permission level for this base", embeddable=False
    )
    url: Optional[str] = ContextDField(
        None,
        description="URL to open the base in Airtable (legacy API field)",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Canonical link to open the base in Airtable."""
        return f"https://airtable.com/{self.base_id}"


class AirtableTableEntity(BaseEntity):
    """Metadata for an Airtable table (schema-level info)."""

    table_id: str = ContextDField(..., description="Airtable table ID", is_entity_id=True)
    name: str = ContextDField(..., description="Table name", is_name=True, embeddable=True)

    base_id: str = ContextDField(..., description="Parent base ID", embeddable=False)
    description: Optional[str] = ContextDField(
        None, description="Table description, if any", embeddable=True
    )
    fields_schema: Optional[List[Dict[str, Any]]] = ContextDField(
        default=None, description="List of field definitions from the schema API", embeddable=True
    )
    primary_field_name: Optional[str] = ContextDField(
        None, description="Name of the primary field", embeddable=True
    )
    view_count: Optional[int] = ContextDField(
        None, description="Number of views in this table", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Link back to the table inside the base."""
        return f"https://airtable.com/{self.base_id}/{self.table_id}"


class AirtableRecordEntity(BaseEntity):
    """One Airtable record (row) as a searchable chunk."""

    record_id: str = ContextDField(..., description="Record ID", is_entity_id=True)
    name: str = ContextDField(..., description="Record display name", is_name=True, embeddable=True)
    created_at: Optional[datetime] = ContextDField(
        None, description="Record creation time", is_created_at=True
    )

    base_id: str = ContextDField(..., description="Parent base ID", embeddable=False)
    table_id: str = ContextDField(..., description="Parent table ID", embeddable=False)
    table_name: Optional[str] = ContextDField(
        None, description="Parent table name", embeddable=True
    )
    fields: Dict[str, Any] = ContextDField(
        default_factory=dict, description="Raw Airtable fields map", embeddable=True
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Attempt to deep-link to the record inside its table."""
        return f"https://airtable.com/{self.base_id}/{self.table_id}/{self.record_id}"


class AirtableCommentEntity(BaseEntity):
    """A comment on an Airtable record."""

    comment_id: str = ContextDField(..., description="Comment ID", is_entity_id=True)
    name: str = ContextDField(..., description="Comment preview", is_name=True, embeddable=True)
    created_at: Optional[datetime] = ContextDField(
        None, description="When the comment was created", is_created_at=True
    )
    updated_at: Optional[datetime] = ContextDField(
        None, description="When the comment was last updated", is_updated_at=True
    )

    record_id: str = ContextDField(..., description="Parent record ID", embeddable=False)
    base_id: str = ContextDField(..., description="Parent base ID", embeddable=False)
    table_id: str = ContextDField(..., description="Parent table ID", embeddable=False)
    text: str = ContextDField(..., description="Comment text", embeddable=True)
    author_id: Optional[str] = ContextDField(None, description="Author user ID", embeddable=False)
    author_email: Optional[str] = ContextDField(
        None, description="Author email address", embeddable=True
    )
    author_name: Optional[str] = ContextDField(
        None, description="Author display name", embeddable=True
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Link to the parent record where the comment resides."""
        return f"https://airtable.com/{self.base_id}/{self.table_id}/{self.record_id}"


class AirtableAttachmentEntity(FileEntity):
    """Attachment file from an Airtable record."""

    attachment_id: str = ContextDField(
        ..., description="Attachment ID (or composite key)", is_entity_id=True
    )
    name: str = ContextDField(..., description="Attachment filename", is_name=True, embeddable=True)

    base_id: str = ContextDField(..., description="Base ID", embeddable=False)
    table_id: str = ContextDField(..., description="Table ID", embeddable=False)
    table_name: Optional[str] = ContextDField(None, description="Table name", embeddable=True)
    record_id: str = ContextDField(..., description="Record ID", embeddable=False)
    field_name: str = ContextDField(
        ..., description="Field name that contains this attachment", embeddable=True
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Link to the parent record containing this attachment."""
        return f"https://airtable.com/{self.base_id}/{self.table_id}/{self.record_id}"
