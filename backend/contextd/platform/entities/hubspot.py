"""HubSpot entity schemas.

Based on the HubSpot CRM API reference, we define entity schemas for common
HubSpot objects like Contacts, Companies, Deals, and Tickets.
"""

from datetime import datetime
from typing import Any, ClassVar, Dict, Optional

from pydantic import computed_field, field_validator

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._contextd_field import ContextDField
from contextd.platform.entities._metadata import (
    EntityIndexConfig,
    EntityMetadata,
    FieldMetadata,
    LLMExtractionConfig,
    SearchConfig,
)


def parse_hubspot_datetime(value: Any) -> Optional[datetime]:
    """Parse HubSpot datetime value, handling empty strings and various formats.

    Args:
        value: The datetime value from HubSpot API (could be string, datetime, or None)

    Returns:
        Parsed datetime object or None if empty/invalid
    """
    if not value or value == "":
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        try:
            # HubSpot typically returns ISO format datetime strings
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    return None


class HubspotContactEntity(BaseEntity):
    """Schema for HubSpot contact entities with flexible property handling.

    Reference:
        https://developers.hubspot.com/docs/api/crm/contacts
    """

    contact_id: str = ContextDField(..., description="The HubSpot contact ID.", is_entity_id=True)
    display_name: str = ContextDField(
        ...,
        description="Display name derived from first/last name or email.",
        embeddable=True,
        is_name=True,
    )
    created_time: datetime = ContextDField(
        ..., description="When the contact was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When the contact was last updated.", is_updated_at=True
    )
    first_name: Optional[str] = ContextDField(
        default=None, description="The contact's first name", embeddable=True
    )
    last_name: Optional[str] = ContextDField(
        default=None, description="The contact's last name", embeddable=True
    )
    email: Optional[str] = ContextDField(
        default=None, description="The contact's email address", embeddable=True
    )
    properties: Dict[str, Any] = ContextDField(
        default_factory=dict,
        description="All properties from HubSpot contact object",
        embeddable=True,
    )
    archived: bool = ContextDField(
        default=False, description="Whether the contact is archived", embeddable=False
    )
    web_url_value: Optional[str] = ContextDField(
        None, description="URL to view this contact in HubSpot.", embeddable=False, unhashable=True
    )

    @field_validator("created_time", "updated_time", mode="before")
    @classmethod
    def parse_datetime_fields(cls, value: Any) -> Optional[datetime]:
        """Normalize HubSpot datetime inputs to timezone-aware datetimes."""
        return parse_hubspot_datetime(value)

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Link to the HubSpot contact UI."""
        return self.web_url_value or ""


class HubspotCompanyEntity(BaseEntity):
    """Schema for HubSpot company entities with flexible property handling.

    Reference:
        https://developers.hubspot.com/docs/api/crm/companies
    """

    company_id: str = ContextDField(..., description="The HubSpot company ID.", is_entity_id=True)
    company_name: str = ContextDField(
        ..., description="Display name of the company.", embeddable=True, is_name=True
    )
    created_time: datetime = ContextDField(
        ..., description="When the company was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When the company was last updated.", is_updated_at=True
    )
    domain: Optional[str] = ContextDField(
        default=None, description="The company's domain name", embeddable=True
    )
    properties: Dict[str, Any] = ContextDField(
        default_factory=dict,
        description="All properties from HubSpot company object",
        embeddable=True,
    )
    archived: bool = ContextDField(
        default=False, description="Whether the company is archived", embeddable=False
    )
    web_url_value: Optional[str] = ContextDField(
        None, description="URL to view this company in HubSpot.", embeddable=False, unhashable=True
    )

    @field_validator("created_time", "updated_time", mode="before")
    @classmethod
    def parse_datetime_fields(cls, value: Any) -> Optional[datetime]:
        """Normalize HubSpot datetime inputs to timezone-aware datetimes."""
        return parse_hubspot_datetime(value)

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Link to the HubSpot company UI."""
        return self.web_url_value or ""


class HubspotDealEntity(BaseEntity):
    """Schema for HubSpot deal entities with flexible property handling.

    Reference:
        https://developers.hubspot.com/docs/api/crm/deals
    """

    deal_id: str = ContextDField(..., description="The HubSpot deal ID.", is_entity_id=True)
    deal_name: str = ContextDField(
        ..., description="The name of the deal.", embeddable=True, is_name=True
    )
    created_time: datetime = ContextDField(
        ..., description="When the deal was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When the deal was last updated.", is_updated_at=True
    )
    amount: Optional[float] = ContextDField(
        default=None, description="The monetary value of the deal", embeddable=True
    )
    properties: Dict[str, Any] = ContextDField(
        default_factory=dict, description="All properties from HubSpot deal object", embeddable=True
    )
    archived: bool = ContextDField(
        default=False, description="Whether the deal is archived", embeddable=False
    )
    web_url_value: Optional[str] = ContextDField(
        None, description="URL to view this deal in HubSpot.", embeddable=False, unhashable=True
    )

    @field_validator("created_time", "updated_time", mode="before")
    @classmethod
    def parse_datetime_fields(cls, value: Any) -> Optional[datetime]:
        """Normalize HubSpot datetime inputs to timezone-aware datetimes."""
        return parse_hubspot_datetime(value)

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Link to the HubSpot deal UI."""
        return self.web_url_value or ""


class HubspotTicketEntity(BaseEntity):
    """Schema for HubSpot ticket entities with flexible property handling.

    Reference:
        https://developers.hubspot.com/docs/api/crm/tickets
    """

    _entity_metadata: ClassVar[EntityMetadata] = EntityMetadata(
        default_graph_node_type="HubspotTicketNode",
        create_entity_node=True,
        enable_llm_enrichment=True,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["ticket_name", "subject", "content"],
        ),
        fields={
            "ticket_name": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                is_name=True,
            ),
            "subject": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.5),
            ),
            "content": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.25),
                llm=LLMExtractionConfig(
                    enabled=True,
                    base_node_type="EmailExtract",
                    custom_entity_types=[
                        "Person",
                        "Task",
                        "Project",
                        "Decision",
                        "Company",
                        "Team",
                        "Product",
                    ],
                    content_template="""Ticket: {ticket_name}
Subject: {subject}
Content:
{content}""",
                    content_fields=["ticket_name", "subject", "content"],
                    extraction_hint="""Analyze this HubSpot ticket and extract only these graph-worthy entity types:
- Person: a person important enough to track across tickets, emails, and documents as their own reusable node
- Task: a concrete follow-up, remediation step, or action item worth tracking
- Project: a named initiative, implementation, migration, rollout, or workstream
- Decision: an explicit decision, approval, or committed support/product direction
- Company: a customer, prospect, partner, vendor, or organization worth linking across systems
- Team: a named team, org unit, queue, squad, or working group
- Product: a named product, feature area, platform, plan, integration, or service

Do not invent any other node types.
Do not create standalone time/date nodes. Dates should only appear as properties on richer nodes such as Task or Decision.
Only extract things that deserve reusable nodes in the knowledge graph rather than remaining as plain text in the ticket.
For Person entities, include email when available.
If an extracted entity relates to a specific person, include that person's email in fields like assigned_to, owner, or related_to.
Person must be a real human—never a product, portal, or bot name mistaken for a person; use Product or Company instead when appropriate. Every type must represent a concrete real-world entity, not placeholder or misclassified text.""",
                    confidence_threshold=0.65,
                ),
            ),
        },
    )

    ticket_id: str = ContextDField(..., description="The HubSpot ticket ID.", is_entity_id=True)
    ticket_name: str = ContextDField(
        ..., description="Display name for the ticket.", embeddable=True, is_name=True
    )
    created_time: datetime = ContextDField(
        ..., description="When the ticket was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When the ticket was last updated.", is_updated_at=True
    )
    subject: Optional[str] = ContextDField(
        default=None, description="The subject of the support ticket", embeddable=True
    )
    content: Optional[str] = ContextDField(
        default=None, description="The content or description of the ticket", embeddable=True
    )
    properties: Dict[str, Any] = ContextDField(
        default_factory=dict,
        description="All properties from HubSpot ticket object",
        embeddable=True,
    )
    archived: bool = ContextDField(
        default=False, description="Whether the ticket is archived", embeddable=False
    )
    web_url_value: Optional[str] = ContextDField(
        None, description="URL to view this ticket in HubSpot.", embeddable=False, unhashable=True
    )

    @field_validator("created_time", "updated_time", mode="before")
    @classmethod
    def parse_datetime_fields(cls, value: Any) -> Optional[datetime]:
        """Normalize HubSpot datetime inputs to timezone-aware datetimes."""
        return parse_hubspot_datetime(value)

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Link to the HubSpot ticket UI."""
        return self.web_url_value or ""
