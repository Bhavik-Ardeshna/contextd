"""Zendesk entity schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import computed_field

from contextd.platform.entities._base import BaseEntity, FileEntity
from contextd.platform.entities._contextd_field import ContextDField


class ZendeskTicketEntity(BaseEntity):
    """Schema for Zendesk ticket entities.

    Reference:
        https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/
    """

    ticket_id: int = ContextDField(
        ..., description="Unique identifier of the ticket", embeddable=False, is_entity_id=True
    )
    subject: str = ContextDField(
        ..., description="The subject of the ticket", embeddable=True, is_name=True
    )
    created_time: datetime = ContextDField(
        ..., description="When the ticket was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When the ticket was last updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="UI URL to open the ticket in Zendesk.",
        embeddable=False,
        unhashable=True,
    )

    # API fields
    description: Optional[str] = ContextDField(
        None, description="The description of the ticket (first comment)", embeddable=True
    )
    requester_id: Optional[int] = ContextDField(
        None, description="ID of the user who requested the ticket", embeddable=False
    )
    requester_name: Optional[str] = ContextDField(
        None, description="Name of the user who requested the ticket", embeddable=True
    )
    requester_email: Optional[str] = ContextDField(
        None, description="Email of the user who requested the ticket", embeddable=True
    )
    assignee_id: Optional[int] = ContextDField(
        None, description="ID of the user assigned to the ticket", embeddable=False
    )
    assignee_name: Optional[str] = ContextDField(
        None, description="Name of the user assigned to the ticket", embeddable=True
    )
    assignee_email: Optional[str] = ContextDField(
        None, description="Email of the user assigned to the ticket", embeddable=True
    )
    status: str = ContextDField(..., description="Current status of the ticket", embeddable=True)
    priority: Optional[str] = ContextDField(
        None, description="Priority level of the ticket", embeddable=True
    )
    tags: List[str] = ContextDField(
        default_factory=list, description="Tags associated with the ticket", embeddable=True
    )
    custom_fields: List[Dict[str, Any]] = ContextDField(
        default_factory=list, description="Custom field values for the ticket", embeddable=False
    )
    organization_id: Optional[int] = ContextDField(
        None, description="ID of the organization associated with the ticket", embeddable=False
    )
    organization_name: Optional[str] = ContextDField(
        None, description="Name of the organization associated with the ticket", embeddable=True
    )
    group_id: Optional[int] = ContextDField(
        None, description="ID of the group the ticket belongs to", embeddable=False
    )
    group_name: Optional[str] = ContextDField(
        None, description="Name of the group the ticket belongs to", embeddable=True
    )
    ticket_type: Optional[str] = ContextDField(
        None, description="Type of the ticket (question, incident, problem, task)", embeddable=True
    )
    url: Optional[str] = ContextDField(
        None, description="URL to view the ticket in Zendesk", embeddable=False, unhashable=True
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Return the Zendesk ticket URL."""
        return self.web_url_value or self.url or ""


class ZendeskCommentEntity(BaseEntity):
    """Schema for Zendesk comment entities.

    Reference:
        https://developer.zendesk.com/api-reference/ticketing/tickets/ticket-comments/
    """

    comment_id: int = ContextDField(
        ..., description="Unique identifier of the comment", embeddable=False, is_entity_id=True
    )
    ticket_id: int = ContextDField(
        ..., description="ID of the ticket this comment belongs to", embeddable=False
    )
    ticket_subject: str = ContextDField(
        ..., description="Subject of the ticket this comment belongs to", embeddable=True
    )
    author_id: int = ContextDField(
        ..., description="ID of the user who wrote the comment", embeddable=False
    )
    author_name: str = ContextDField(
        ..., description="Name of the user who wrote the comment", embeddable=True
    )
    author_email: Optional[str] = ContextDField(
        None, description="Email of the user who wrote the comment", embeddable=True
    )
    body: str = ContextDField(
        ..., description="The content of the comment", embeddable=True, is_name=True
    )
    html_body: Optional[str] = ContextDField(
        None, description="HTML formatted content of the comment", embeddable=True
    )
    public: bool = ContextDField(
        False, description="Whether the comment is public or internal", embeddable=False
    )
    attachments: List[Dict[str, Any]] = ContextDField(
        default_factory=list,
        description="Attachments associated with this comment",
        embeddable=False,
    )
    created_time: datetime = ContextDField(
        ..., description="When the comment was created.", is_created_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="URL to view this comment (falls back to ticket).",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Return the Zendesk comment URL."""
        return self.web_url_value or ""


class ZendeskUserEntity(BaseEntity):
    """Schema for Zendesk user entities.

    Reference:
        https://developer.zendesk.com/api-reference/ticketing/users/users/
    """

    user_id: int = ContextDField(
        ..., description="Unique identifier of the user", embeddable=False, is_entity_id=True
    )
    display_name: str = ContextDField(
        ..., description="Display name of the user.", embeddable=True, is_name=True
    )
    created_time: datetime = ContextDField(
        ..., description="When the user was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When the user was last updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="URL to the user's profile in Zendesk.",
        embeddable=False,
        unhashable=True,
    )

    # API fields
    email: str = ContextDField(..., description="Email address of the user", embeddable=True)
    role: str = ContextDField(
        ..., description="Role of the user (end-user, agent, admin)", embeddable=True
    )
    active: bool = ContextDField(
        ..., description="Whether the user account is active", embeddable=False
    )
    last_login_at: Optional[Any] = ContextDField(
        None, description="When the user last logged in", embeddable=False
    )
    organization_id: Optional[int] = ContextDField(
        None, description="ID of the organization the user belongs to", embeddable=False
    )
    organization_name: Optional[str] = ContextDField(
        None,
        description="Name of the organization the user belongs to",
        embeddable=True,
    )
    phone: Optional[str] = ContextDField(
        None, description="Phone number of the user", embeddable=True
    )
    time_zone: Optional[str] = ContextDField(
        None, description="Time zone of the user", embeddable=False
    )
    locale: Optional[str] = ContextDField(None, description="Locale of the user", embeddable=False)
    custom_fields: List[Dict[str, Any]] = ContextDField(
        default_factory=list,
        description="Custom field values for the user",
        embeddable=False,
    )
    tags: List[str] = ContextDField(
        default_factory=list, description="Tags associated with the user", embeddable=True
    )
    user_fields: Dict[str, Any] = ContextDField(
        default_factory=dict, description="User-specific custom fields", embeddable=False
    )
    profile_url: Optional[str] = ContextDField(
        None, description="API URL to the user resource", embeddable=False, unhashable=True
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Return the Zendesk user URL."""
        return self.web_url_value or self.profile_url or ""


class ZendeskOrganizationEntity(BaseEntity):
    """Schema for Zendesk organization entities.

    Reference:
        https://developer.zendesk.com/api-reference/ticketing/organizations/organizations/
    """

    organization_id: int = ContextDField(
        ...,
        description="Unique identifier of the organization",
        embeddable=False,
        is_entity_id=True,
    )
    organization_name: str = ContextDField(
        ..., description="Display name of the organization.", embeddable=True, is_name=True
    )
    created_time: datetime = ContextDField(
        ..., description="When the organization was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When the organization was last updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="URL to view the organization in Zendesk.",
        embeddable=False,
        unhashable=True,
    )

    # API fields
    domain_names: List[str] = ContextDField(
        default_factory=list,
        description="Domain names associated with the organization",
        embeddable=True,
    )
    details: Optional[str] = ContextDField(
        None, description="Details about the organization", embeddable=True
    )
    notes: Optional[str] = ContextDField(
        None, description="Notes about the organization", embeddable=True
    )
    tags: List[str] = ContextDField(
        default_factory=list,
        description="Tags associated with the organization",
        embeddable=True,
    )
    custom_fields: List[Dict[str, Any]] = ContextDField(
        default_factory=list,
        description="Custom field values for the organization",
        embeddable=False,
    )
    organization_fields: Dict[str, Any] = ContextDField(
        default_factory=dict,
        description="Organization-specific custom fields",
        embeddable=False,
    )
    api_url: Optional[str] = ContextDField(
        None,
        description="API URL for this organization resource.",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Return the Zendesk organization URL."""
        return self.web_url_value or self.api_url or ""


class ZendeskAttachmentEntity(FileEntity):
    """Schema for Zendesk attachment entities.

    Reference:
        https://developer.zendesk.com/api-reference/ticketing/tickets/ticket-attachments/
    """

    # Base fields are inherited from BaseEntity:
    # - entity_id (the Zendesk attachment ID)
    # - breadcrumbs (empty - attachments are standalone)
    # - name (from file_name)
    # - created_at (from created_at timestamp)
    # - updated_at (None - attachments don't have update timestamp)

    # File fields are inherited from FileEntity:
    # - url (download URL)
    # - size (file size in bytes)
    # - file_type (determined from mime_type)
    # - mime_type (from content_type)
    # - local_path (set after download)

    # API fields (Zendesk-specific)
    attachment_id: int = ContextDField(
        ..., description="Unique identifier of the attachment", embeddable=False, is_entity_id=True
    )
    ticket_id: Optional[int] = ContextDField(
        None, description="ID of the ticket this attachment belongs to", embeddable=False
    )
    comment_id: Optional[int] = ContextDField(
        None, description="ID of the comment this attachment belongs to", embeddable=False
    )
    ticket_subject: Optional[str] = ContextDField(
        None,
        description="Subject of the ticket this attachment belongs to",
        embeddable=True,
    )
    content_type: str = ContextDField(
        ..., description="MIME type of the attachment", embeddable=False
    )
    file_name: str = ContextDField(
        ..., description="Original filename of the attachment", embeddable=True, is_name=True
    )
    thumbnails: List[Dict[str, Any]] = ContextDField(
        default_factory=list,
        description="Thumbnail information for the attachment",
        embeddable=False,
    )
    created_time: datetime = ContextDField(
        ..., description="When the attachment was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When the attachment metadata was updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="URL to download the attachment.",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Return the Zendesk attachment URL."""
        return self.web_url_value or self.url or ""
