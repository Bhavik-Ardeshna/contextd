"""Google Calendar entity schemas.

Based on the Google Calendar API reference (readonly scope),
we define entity schemas for:
 - Calendar objects
 - CalendarList objects
 - Event objects
 - FreeBusy responses

Each entity includes:
- Graph configuration for building knowledge graph relationships
- Index configuration for vector and fulltext search
- LLM enrichment configuration for extracting entities from calendar content

Reference:
    https://developers.google.com/calendar/api/v3/reference
"""

import urllib.parse
from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import computed_field

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._contextd_field import ContextDField
from contextd.platform.entities._metadata import (
    EntityIndexConfig,
    EntityMetadata,
    EntityRelationConfig,
    FieldMetadata,
    GraphEdgeConfig,
    LLMExtractionConfig,
    SearchConfig,
)


class GoogleCalendarCalendarEntity(BaseEntity):
    """Schema for a Google Calendar object (the underlying calendar resource).

    See: https://developers.google.com/calendar/api/v3/reference/calendars

    Graph Configuration:
    - Creates GoogleCalendarNode in the knowledge graph
    - Owner (authenticated user) connected via OWNED_BY edge (static)

    Index Configuration:
    - Display name and description are embeddable for semantic search

    LLM Enrichment:
    - DISABLED: Calendar data is fully structured, no unstructured content to extract
    """

    # Unified metadata configuration (ClassVar tells Pydantic this is a class attribute, not a model field)
    _entity_metadata: ClassVar[EntityMetadata] = EntityMetadata(
        default_graph_node_type="GoogleCalendarNode",
        create_entity_node=True,
        enable_llm_enrichment=False,  # DISABLED: All calendar data is structured
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["display_name", "summary", "description"],
        ),
        fields={
            "display_name": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                is_name=True,
            ),
            "summary": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.5),
            ),
            "description": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.0),
                # No LLM extraction - calendar descriptions are typically structured
            ),
            "location": FieldMetadata(
                search=SearchConfig(embeddable=True),
            ),
            "owner_email": FieldMetadata(
                search=SearchConfig(embeddable=True),
                graph=GraphEdgeConfig(
                    edge_type="OWNED_BY",
                    to_node_type="PersonNode",
                    create_reverse_edge=True,
                    reverse_edge_type="OWNS",
                    is_list=False,
                ),
            ),
        },
    )

    calendar_key: str = ContextDField(
        ...,
        description="Stable calendar identifier (matches Google calendar ID).",
        is_entity_id=True,
    )
    display_name: str = ContextDField(
        ...,
        description="Display name for the calendar.",
        is_name=True,
        embeddable=True,
    )
    summary: Optional[str] = ContextDField(
        None, description="Title of the calendar.", embeddable=True
    )
    description: Optional[str] = ContextDField(
        None, description="Description of the calendar.", embeddable=True
    )
    location: Optional[str] = ContextDField(
        None, description="Geographic location of the calendar.", embeddable=True
    )
    time_zone: Optional[str] = ContextDField(
        None, description="The time zone of the calendar.", embeddable=False
    )
    owner_email: Optional[str] = ContextDField(
        None,
        description="Email address of the calendar owner (authenticated user).",
        embeddable=True,
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="Direct link to the calendar in Google Calendar.",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Clickable calendar URL."""
        if self.web_url_value:
            return self.web_url_value
        encoded = urllib.parse.quote(self.calendar_key)
        return f"https://calendar.google.com/calendar/u/0/r?cid={encoded}"


class GoogleCalendarListEntity(BaseEntity):
    """Schema for a CalendarList entry, i.e., how the user sees a calendar.

    See: https://developers.google.com/calendar/api/v3/reference/calendarList

    Graph Configuration:
    - Creates GoogleCalendarListNode in the knowledge graph
    - Owner (authenticated user) connected via OWNED_BY edge

    Index Configuration:
    - Display name and summary are embeddable for semantic search
    """

    # Unified metadata configuration (ClassVar tells Pydantic this is a class attribute, not a model field)
    _entity_metadata: ClassVar[EntityMetadata] = EntityMetadata(
        default_graph_node_type="GoogleCalendarListNode",
        create_entity_node=True,
        enable_llm_enrichment=False,  # List entries don't have much content
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["display_name", "summary"],
        ),
        fields={
            "display_name": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                is_name=True,
            ),
            "summary": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.5),
            ),
            "owner_email": FieldMetadata(
                search=SearchConfig(embeddable=True),
                graph=GraphEdgeConfig(
                    edge_type="OWNED_BY",
                    to_node_type="PersonNode",
                    create_reverse_edge=True,
                    reverse_edge_type="OWNS",
                    is_list=False,
                ),
            ),
        },
    )

    calendar_key: str = ContextDField(
        ...,
        description="Calendar ID for this list entry.",
        is_entity_id=True,
    )
    display_name: str = ContextDField(
        ...,
        description="Display name used by the user.",
        is_name=True,
        embeddable=True,
    )
    summary: Optional[str] = ContextDField(
        None, description="Title of the calendar.", embeddable=True
    )
    summary_override: Optional[str] = ContextDField(
        None, description="User-defined name for the calendar, if set.", embeddable=True
    )
    color_id: Optional[str] = ContextDField(
        None, description="Color ID reference for the calendar.", embeddable=False
    )
    background_color: Optional[str] = ContextDField(
        None, description="Background color in HEX.", embeddable=False
    )
    foreground_color: Optional[str] = ContextDField(
        None, description="Foreground color in HEX.", embeddable=False
    )
    hidden: bool = ContextDField(
        False, description="Whether the calendar is hidden from the UI.", embeddable=False
    )
    selected: bool = ContextDField(
        False, description="Indicates if the calendar is selected in the UI.", embeddable=False
    )
    access_role: Optional[str] = ContextDField(
        None,
        description=(
            "The effective access role that the authenticated user has on the calendar."
            " E.g., 'owner', 'reader', 'writer'."
        ),
        embeddable=False,
    )
    primary: bool = ContextDField(
        False, description="Flag to indicate if this is the primary calendar.", embeddable=False
    )
    deleted: bool = ContextDField(
        False, description="Flag to indicate if this calendar has been deleted.", embeddable=False
    )
    owner_email: Optional[str] = ContextDField(
        None,
        description="Email address of the calendar owner (authenticated user).",
        embeddable=True,
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="Direct link to the calendar in Google Calendar.",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Clickable calendar URL."""
        if self.web_url_value:
            return self.web_url_value
        encoded = urllib.parse.quote(self.calendar_key)
        return f"https://calendar.google.com/calendar/u/0/r?cid={encoded}"


class GoogleCalendarEventEntity(BaseEntity):
    """Schema for a Google Calendar Event.

    See: https://developers.google.com/calendar/api/v3/reference/events

    Graph Configuration:
    - Creates GoogleCalendarEventNode in the knowledge graph
    - Organizer connected as PersonNode with ORGANIZED_BY edge (static)
    - Creator connected as PersonNode with CREATED_BY edge (static)
    - Attendees connected as PersonNode with HAS_ATTENDEE edge (static)
    - Owner (authenticated user) connected via OWNED_BY edge (static)
    - Related to parent calendar via PART_OF edge (static)

    LLM Enrichment:
    - ENABLED for limited, graph-worthy concepts embedded in event text
    - The event entity itself is already the meeting node, so we do NOT extract Meeting
    - Organizer, creator, attendees are still extracted from structured fields

    Index Configuration:
    - Title, summary, description are embeddable for semantic search
    """

    # Unified metadata configuration (ClassVar tells Pydantic this is a class attribute, not a model field)
    _entity_metadata: ClassVar[EntityMetadata] = EntityMetadata(
        default_graph_node_type="GoogleCalendarEventNode",
        create_entity_node=True,
        enable_llm_enrichment=True,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["title", "summary", "description", "location"],
        ),
        fields={
            "title": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                is_name=True,
            ),
            "summary": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.5),
            ),
            "description": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.0),
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
                    ],
                    content_template="""Title: {title}
Summary: {summary}
Start: {start_datetime}
Start Date: {start_date}
End: {end_datetime}
End Date: {end_date}
Location: {location}
Organizer: {organizer_email}
Attendees: {attendee_emails}
Description:
{description}""",
                    content_fields=[
                        "title",
                        "summary",
                        "start_datetime",
                        "start_date",
                        "end_datetime",
                        "end_date",
                        "location",
                        "organizer_email",
                        "attendee_emails",
                        "description",
                    ],
                    extraction_hint="""Analyze this calendar event and extract only these graph-worthy entity types:
- Person: a person important enough to track across event notes, emails, and documents as their own reusable node
- Task: a concrete follow-up, preparation item, or action item connected to the event
- Project: a named initiative, workstream, or program discussed by the event
- Decision: an explicit decision, approval, or committed direction captured in the event details
- Company: a company, customer, partner, vendor, or organization worth linking across tools
- Team: a named team, org unit, squad, or working group

Do not invent any other node types.
Do not extract a Meeting node from calendar events. The calendar event itself already represents the meeting.
Do not create standalone time/date nodes. Dates should only appear as properties on richer nodes such as Task or Decision.
Only extract things that deserve reusable nodes in the knowledge graph rather than remaining as plain text in the event.
For Person entities, include email when available.
If an extracted entity relates to a specific person, include that person's email in fields like assigned_to, owner, or related_to.
Person must be a real human—never a conferencing product (Google Meet, Zoom, Teams, etc.), room resource, or automated system. Use Product or Company for products/orgs. Other types must also refer to real, specific things worth tracking, not boilerplate.""",
                    confidence_threshold=0.65,
                ),
            ),
            "location": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.0),
            ),
            "organizer_email": FieldMetadata(
                search=SearchConfig(embeddable=True),
                graph=GraphEdgeConfig(
                    edge_type="ORGANIZED_BY",
                    to_node_type="PersonNode",
                    create_reverse_edge=True,
                    reverse_edge_type="ORGANIZES",
                    is_list=False,
                ),
            ),
            "creator_email": FieldMetadata(
                search=SearchConfig(embeddable=True),
                graph=GraphEdgeConfig(
                    edge_type="CREATED_BY",
                    to_node_type="PersonNode",
                    create_reverse_edge=True,
                    reverse_edge_type="CREATED",
                    is_list=False,
                ),
            ),
            "attendee_emails": FieldMetadata(
                search=SearchConfig(embeddable=True),
                graph=GraphEdgeConfig(
                    edge_type="HAS_ATTENDEE",
                    to_node_type="PersonNode",
                    create_reverse_edge=True,
                    reverse_edge_type="ATTENDS",
                    is_list=True,
                ),
            ),
            "owner_email": FieldMetadata(
                search=SearchConfig(embeddable=True),
                graph=GraphEdgeConfig(
                    edge_type="OWNED_BY",
                    to_node_type="PersonNode",
                    create_reverse_edge=True,
                    reverse_edge_type="OWNS",
                    is_list=False,
                ),
            ),
        },
        entity_relations=[
            EntityRelationConfig(
                edge_type="PART_OF",
                to_entity_type="GoogleCalendarListEntity",
                to_id_field="calendar_key",
                create_reverse_edge=True,
                reverse_edge_type="CONTAINS",
            ),
        ],
    )

    event_key: str = ContextDField(
        ...,
        description="Stable event identifier.",
        is_entity_id=True,
    )
    calendar_key: str = ContextDField(
        ..., description="Calendar ID for this event.", embeddable=False
    )
    title: str = ContextDField(
        ...,
        description="Display title of the event.",
        is_name=True,
        embeddable=True,
    )
    created_time: datetime = ContextDField(
        ...,
        description="Creation timestamp for the event.",
        is_created_at=True,
    )
    updated_time: datetime = ContextDField(
        ...,
        description="Last modification timestamp for the event.",
        is_updated_at=True,
    )
    status: Optional[str] = ContextDField(
        None, description="Status of the event (e.g., 'confirmed').", embeddable=False
    )
    html_link: Optional[str] = ContextDField(
        None,
        description="An absolute link to the event in the Google Calendar UI.",
        embeddable=False,
    )
    summary: Optional[str] = ContextDField(None, description="Title of the event.", embeddable=True)
    description: Optional[str] = ContextDField(
        None, description="Description of the event.", embeddable=True
    )
    location: Optional[str] = ContextDField(
        None, description="Geographic location of the event.", embeddable=True
    )
    color_id: Optional[str] = ContextDField(
        None, description="Color ID for this event.", embeddable=False
    )
    start_datetime: Optional[datetime] = ContextDField(
        None,
        description=(
            "Start datetime if the event has a specific datetime. "
            "(DateTime from 'start' if 'dateTime' is present.)"
        ),
        embeddable=True,
    )
    start_date: Optional[str] = ContextDField(
        None,
        description=(
            "Start date if the event is an all-day event. (Date from 'start' if 'date' is present.)"
        ),
        embeddable=True,
    )
    end_datetime: Optional[datetime] = ContextDField(
        None,
        description=(
            "End datetime if the event has a specific datetime. "
            "(DateTime from 'end' if 'dateTime' is present.)"
        ),
        embeddable=True,
    )
    end_date: Optional[str] = ContextDField(
        None,
        description=(
            "End date if the event is an all-day event. (Date from 'end' if 'date' is present.)"
        ),
        embeddable=True,
    )
    recurrence: Optional[List[str]] = ContextDField(
        None,
        description="List of RRULE, EXRULE, RDATE, EXDATE lines for recurring events.",
        embeddable=False,
    )
    recurring_event_id: Optional[str] = ContextDField(
        None,
        description="For recurring events, identifies the event ID of the recurring series.",
        embeddable=False,
    )
    organizer: Optional[Dict[str, Any]] = ContextDField(
        None,
        description="The organizer of the event. Usually contains 'email' and 'displayName'.",
        embeddable=True,
    )
    organizer_email: Optional[str] = ContextDField(
        None,
        description="Email address of the event organizer.",
        embeddable=True,
    )
    creator: Optional[Dict[str, Any]] = ContextDField(
        None,
        description="The creator of the event. Usually contains 'email' and 'displayName'.",
        embeddable=True,
    )
    creator_email: Optional[str] = ContextDField(
        None,
        description="Email address of the event creator.",
        embeddable=True,
    )
    attendees: Optional[List[Dict[str, Any]]] = ContextDField(
        None,
        description=(
            "The attendees of the event (each dict typically has 'email', 'responseStatus', etc.)."
        ),
        embeddable=True,
    )
    attendee_emails: List[str] = ContextDField(
        default_factory=list,
        description="List of attendee email addresses for graph edges.",
        embeddable=True,
    )
    owner_email: Optional[str] = ContextDField(
        None,
        description="Email address of the calendar owner (authenticated user).",
        embeddable=True,
    )
    transparency: Optional[str] = ContextDField(
        None,
        description=(
            "Specifies whether the event blocks time on the calendar ('opaque') or not "
            "('transparent')."
        ),
        embeddable=False,
    )
    visibility: Optional[str] = ContextDField(
        None, description="Visibility of the event (e.g., 'default', 'public').", embeddable=False
    )
    conference_data: Optional[Dict[str, Any]] = ContextDField(
        None,
        description="Conference data associated with the event, e.g., hangout or meet link.",
        embeddable=True,
    )
    event_type: Optional[str] = ContextDField(
        None, description="Event type. E.g., 'default' or 'focus'.", embeddable=False
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="Direct link to the event in Google Calendar.",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Clickable event URL."""
        if self.web_url_value:
            return self.web_url_value
        return f"https://calendar.google.com/calendar/u/0/r/eventedit/{self.event_key}"


class GoogleCalendarFreeBusyEntity(BaseEntity):
    """Schema for a FreeBusy response entity for a given calendar.

    See: https://developers.google.com/calendar/api/v3/reference/freebusy

    Graph Configuration:
    - Creates GoogleCalendarFreeBusyNode in the knowledge graph
    - Related to parent calendar via PART_OF edge
    - Owner (authenticated user) connected via OWNED_BY edge

    Index Configuration:
    - Label is embeddable for semantic search
    """

    # Unified metadata configuration (ClassVar tells Pydantic this is a class attribute, not a model field)
    _entity_metadata: ClassVar[EntityMetadata] = EntityMetadata(
        default_graph_node_type="GoogleCalendarFreeBusyNode",
        create_entity_node=True,
        enable_llm_enrichment=False,  # FreeBusy data is just time ranges
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["label"],
        ),
        fields={
            "label": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                is_name=True,
            ),
            "owner_email": FieldMetadata(
                search=SearchConfig(embeddable=True),
                graph=GraphEdgeConfig(
                    edge_type="OWNED_BY",
                    to_node_type="PersonNode",
                    create_reverse_edge=True,
                    reverse_edge_type="OWNS",
                    is_list=False,
                ),
            ),
        },
        entity_relations=[
            EntityRelationConfig(
                edge_type="PART_OF",
                to_entity_type="GoogleCalendarListEntity",
                to_id_field="calendar_id",
                create_reverse_edge=True,
                reverse_edge_type="HAS_FREEBUSY",
            ),
        ],
    )

    freebusy_key: str = ContextDField(
        ...,
        description="Stable identifier for the free/busy snapshot.",
        is_entity_id=True,
    )
    label: str = ContextDField(
        ...,
        description="Display label for the free/busy entry.",
        is_name=True,
        embeddable=True,
    )
    calendar_id: str = ContextDField(
        ..., description="ID of the calendar for which free/busy is returned.", embeddable=False
    )
    busy: List[Dict[str, str]] = ContextDField(
        default_factory=list,
        description="List of time ranges during which this calendar is busy.",
        embeddable=True,
    )
    owner_email: Optional[str] = ContextDField(
        None,
        description="Email address of the calendar owner (authenticated user).",
        embeddable=True,
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="Link back to the calendar UI.",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Clickable calendar URL for this free/busy entry."""
        if self.web_url_value:
            return self.web_url_value
        encoded = urllib.parse.quote(self.calendar_id)
        return f"https://calendar.google.com/calendar/u/0/r?cid={encoded}"
