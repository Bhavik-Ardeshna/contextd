"""Attio entity schemas.

Attio is a CRM platform that organizes data into Objects (Companies, People, Deals)
and Lists (custom collections). Each object/list contains Records with custom attributes.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import computed_field

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._contextd_field import ContextDField


class AttioObjectEntity(BaseEntity):
    """Schema for Attio Object (e.g., Companies, People, Deals)."""

    object_id: str = ContextDField(..., description="Attio object ID", is_entity_id=True)
    name: str = ContextDField(
        ..., description="Display name of the object", is_name=True, embeddable=True
    )
    created_at: Optional[datetime] = ContextDField(
        None, description="When the object was created", is_created_at=True
    )

    singular_noun: str = ContextDField(
        ..., description="Singular name of the object (e.g., 'Company')", embeddable=True
    )
    plural_noun: str = ContextDField(
        ..., description="Plural name of the object (e.g., 'Companies')", embeddable=True
    )
    api_slug: str = ContextDField(..., description="API slug for the object", embeddable=False)
    icon: Optional[str] = ContextDField(
        None, description="Icon representing this object", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Link to the object definition inside Attio."""
        return f"https://app.attio.com/objects/{self.api_slug}"


class AttioListEntity(BaseEntity):
    """Schema for Attio List."""

    list_id: str = ContextDField(..., description="Attio list ID", is_entity_id=True)
    name: str = ContextDField(..., description="List name", is_name=True, embeddable=True)
    created_at: Optional[datetime] = ContextDField(
        None, description="When the list was created", is_created_at=True
    )

    workspace_id: str = ContextDField(
        ..., description="ID of the workspace this list belongs to", embeddable=False
    )
    parent_object: Optional[str] = ContextDField(
        None, description="Parent object type if applicable", embeddable=True
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Link to the list inside Attio."""
        return f"https://app.attio.com/lists/{self.list_id}"


class AttioRecordEntity(BaseEntity):
    """Schema for Attio Record."""

    record_id: str = ContextDField(..., description="Attio record ID", is_entity_id=True)
    name: str = ContextDField(..., description="Record display name", is_name=True, embeddable=True)
    created_at: Optional[datetime] = ContextDField(
        None, description="When the record was created", is_created_at=True
    )
    updated_at: Optional[datetime] = ContextDField(
        None, description="When the record was last updated", is_updated_at=True
    )

    object_id: Optional[str] = ContextDField(
        None, description="ID/slug of the object this record belongs to", embeddable=False
    )
    list_id: Optional[str] = ContextDField(
        None, description="ID of the list this record belongs to", embeddable=False
    )
    parent_object_name: Optional[str] = ContextDField(
        None, description="Name of the parent object/list", embeddable=True
    )

    description: Optional[str] = ContextDField(
        None, description="Description of the record", embeddable=True
    )
    email_addresses: List[Dict[str, Any]] = ContextDField(
        default_factory=list,
        description="Email addresses associated with this record",
        embeddable=True,
    )
    phone_numbers: List[Dict[str, Any]] = ContextDField(
        default_factory=list,
        description="Phone numbers associated with this record",
        embeddable=True,
    )
    domains: List[str] = ContextDField(
        default_factory=list, description="Domain names (for company records)", embeddable=True
    )
    categories: List[str] = ContextDField(
        default_factory=list, description="Categories/tags for this record", embeddable=True
    )
    attributes: Dict[str, Any] = ContextDField(
        default_factory=dict,
        description="Custom attributes and their values",
        embeddable=True,
    )
    permalink_url: Optional[str] = ContextDField(
        None,
        description="URL to view this record in Attio (if provided by API)",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=Optional[str])
    def web_url(self) -> Optional[str]:
        """Best-effort link back to the record inside Attio."""
        if self.permalink_url:
            return self.permalink_url
        if self.object_id:
            return f"https://app.attio.com/objects/{self.object_id}/{self.record_id}"
        if self.list_id:
            return f"https://app.attio.com/lists/{self.list_id}/{self.record_id}"
        return None


class AttioNoteEntity(BaseEntity):
    """Schema for Attio Note."""

    note_id: str = ContextDField(..., description="Attio note ID", is_entity_id=True)
    name: str = ContextDField(
        ..., description="Note title or preview", is_name=True, embeddable=True
    )
    created_at: Optional[datetime] = ContextDField(
        None, description="When the note was created", is_created_at=True
    )
    updated_at: Optional[datetime] = ContextDField(
        None, description="When the note was last updated", is_updated_at=True
    )

    parent_record_id: str = ContextDField(
        ..., description="ID of the record this note is attached to", embeddable=False
    )
    parent_object: Optional[str] = ContextDField(
        None, description="Type of parent object", embeddable=False
    )
    title: Optional[str] = ContextDField(None, description="Title of the note", embeddable=True)
    content: str = ContextDField(..., description="Content of the note", embeddable=True)
    format: Optional[str] = ContextDField(
        None, description="Format of the note (plaintext, markdown, etc.)", embeddable=False
    )
    author: Optional[Dict[str, Any]] = ContextDField(
        None, description="User who created this note", embeddable=True
    )
    permalink_url: Optional[str] = ContextDField(
        None,
        description="URL to view this note in Attio (if provided by API)",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=Optional[str])
    def web_url(self) -> Optional[str]:
        """Best-effort link back to the note inside Attio."""
        if self.permalink_url:
            return self.permalink_url
        return f"https://app.attio.com/notes/{self.note_id}"


# Note: AttioCommentEntity was removed because the Attio API does not provide
# a way to fetch comments for notes through their public REST API.
# Comments are visible in the Attio UI but not accessible via /v2/threads or any other endpoint.
