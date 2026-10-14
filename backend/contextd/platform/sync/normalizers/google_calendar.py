"""Google Calendar entity normalizer for canonical data model transformation.

This module normalizes Google Calendar entities (calendars, events, freebusy) into
the canonical NormalizedEntity format for consistent pipeline processing.

Google Calendar Entity Types:
- GoogleCalendarCalendarEntity: Underlying calendar resources
- GoogleCalendarListEntity: User's calendar list entries
- GoogleCalendarEventEntity: Calendar events
- GoogleCalendarFreeBusyEntity: Free/busy information
"""

from typing import Any, List, Optional

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._normalized import (
    NormalizedEntity,
    PersonRef,
    PersonRole,
    RelationRef,
    RelationType,
    TagRef,
)
from contextd.platform.sync.normalizers._base import (
    BaseEntityNormalizer,
    register_normalizer,
)


@register_normalizer(r"GoogleCalendar.*Entity", source_type="google_calendar")
class GoogleCalendarNormalizer(BaseEntityNormalizer):
    """Normalizer for Google Calendar entities.

    Google Calendar entity structure:
    - CalendarList entries represent the user's view of calendars
    - Calendar entities are the underlying calendar resources
    - Events have organizer, creator, and attendees
    - FreeBusy shows time ranges when the user is busy
    """

    source_type = "google_calendar"

    def normalize(self, entity: BaseEntity) -> NormalizedEntity:
        """Transform Google Calendar entity to NormalizedEntity.

        Route to specific handler based on entity type.
        """
        entity_class_name = entity.__class__.__name__

        if "Event" in entity_class_name:
            return self._normalize_event(entity)
        elif "CalendarList" in entity_class_name:
            return self._normalize_calendar_list(entity)
        elif "Calendar" in entity_class_name and "List" not in entity_class_name:
            return self._normalize_calendar(entity)
        elif "FreeBusy" in entity_class_name:
            return self._normalize_freebusy(entity)
        else:
            return self._normalize_generic(entity)

    def _normalize_calendar(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Google Calendar entity (the underlying calendar resource).

        Calendars have:
        - display_name: User-facing name
        - description: Calendar description
        - location: Geographic location
        - time_zone: Timezone setting
        - owner_email: The authenticated user
        """
        # Add owner as a person reference
        people: List[PersonRef] = []
        owner_email = getattr(entity, "owner_email", None)
        if owner_email:
            people.append(self._create_person_from_email(owner_email, PersonRole.OWNER))

        return self.create_base_normalized_entity(
            entity,
            name=getattr(entity, "display_name", None) or entity.name,
            description=getattr(entity, "description", None),
            content=getattr(entity, "summary", None),
            people=people,
            properties={
                "calendar_key": getattr(entity, "calendar_key", None),
                "summary": getattr(entity, "summary", None),
                "location": getattr(entity, "location", None),
                "time_zone": getattr(entity, "time_zone", None),
                "owner_email": owner_email,
            },
        )

    def _normalize_calendar_list(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Google Calendar List entity (user's view of a calendar).

        CalendarList entries have:
        - display_name: User-facing name
        - summary: Calendar title
        - access_role: User's access level
        - primary: Whether it's the primary calendar
        - owner_email: The authenticated user
        """
        # Add owner as a person reference
        people: List[PersonRef] = []
        owner_email = getattr(entity, "owner_email", None)
        if owner_email:
            people.append(self._create_person_from_email(owner_email, PersonRole.OWNER))

        # Create tags for access role and primary status
        tags: List[TagRef] = []
        access_role = getattr(entity, "access_role", None)
        if access_role:
            tags.append(
                TagRef(
                    id=f"access_{access_role}",
                    name=access_role.title(),
                    tag_type="access_role",
                    properties={},
                )
            )

        if getattr(entity, "primary", False):
            tags.append(
                TagRef(
                    id="primary_calendar",
                    name="Primary",
                    tag_type="status",
                    properties={},
                )
            )

        return self.create_base_normalized_entity(
            entity,
            name=getattr(entity, "display_name", None) or entity.name,
            description=getattr(entity, "summary", None),
            people=people,
            tags=tags,
            properties={
                "calendar_key": getattr(entity, "calendar_key", None),
                "summary": getattr(entity, "summary", None),
                "summary_override": getattr(entity, "summary_override", None),
                "access_role": access_role,
                "primary": getattr(entity, "primary", False),
                "hidden": getattr(entity, "hidden", False),
                "owner_email": owner_email,
            },
        )

    def _normalize_event(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Google Calendar Event entity.

        Events have:
        - title/summary: Event name
        - description: Event details
        - location: Where the event takes place
        - organizer: Who organized the event
        - creator: Who created the event
        - attendees: Who is invited
        - start/end times: When the event occurs
        - owner_email: The authenticated user
        """
        # Extract people from organizer, creator, and attendees
        people: List[PersonRef] = []

        # Add organizer
        organizer = getattr(entity, "organizer", None) or {}
        organizer_email = getattr(entity, "organizer_email", None) or organizer.get("email")
        if organizer_email:
            organizer_name = organizer.get("displayName")
            people.append(
                PersonRef(
                    id=organizer_email.lower(),
                    name=organizer_name,
                    email=organizer_email,
                    role=PersonRole.OWNER,  # Organizer is like owner of the event
                    properties={"is_organizer": True},
                )
            )

        # Add creator (if different from organizer)
        creator = getattr(entity, "creator", None) or {}
        creator_email = getattr(entity, "creator_email", None) or creator.get("email")
        if creator_email and creator_email.lower() != (organizer_email or "").lower():
            creator_name = creator.get("displayName")
            people.append(
                PersonRef(
                    id=creator_email.lower(),
                    name=creator_name,
                    email=creator_email,
                    role=PersonRole.CREATOR,
                    properties={"is_creator": True},
                )
            )

        # Add attendees
        attendees = getattr(entity, "attendees", None) or []
        for attendee in attendees:
            attendee_email = attendee.get("email")
            if attendee_email:
                # Skip if already added as organizer or creator
                if attendee_email.lower() in [
                    (organizer_email or "").lower(),
                    (creator_email or "").lower(),
                ]:
                    continue

                attendee_name = attendee.get("displayName")
                response_status = attendee.get("responseStatus", "needsAction")

                # Map response status to role
                if attendee.get("organizer"):
                    role = PersonRole.OWNER
                elif response_status == "accepted":
                    role = PersonRole.ASSIGNEE
                else:
                    role = PersonRole.MEMBER

                people.append(
                    PersonRef(
                        id=attendee_email.lower(),
                        name=attendee_name,
                        email=attendee_email,
                        role=role,
                        properties={
                            "response_status": response_status,
                            "optional": attendee.get("optional", False),
                        },
                    )
                )

        # Add owner as a person reference
        owner_email = getattr(entity, "owner_email", None)
        if owner_email and owner_email.lower() not in [
            (organizer_email or "").lower(),
            (creator_email or "").lower(),
        ]:
            # Only add if not already organizer or creator
            already_added = any(p.id == owner_email.lower() for p in people)
            if not already_added:
                people.append(self._create_person_from_email(owner_email, PersonRole.WATCHER))

        # Create tags for event status and type
        tags: List[TagRef] = []
        status = getattr(entity, "status", None)
        if status:
            tags.append(
                TagRef(
                    id=f"status_{status}",
                    name=status.title(),
                    tag_type="status",
                    properties={},
                )
            )

        event_type = getattr(entity, "event_type", None)
        if event_type and event_type != "default":
            tags.append(
                TagRef(
                    id=f"event_type_{event_type}",
                    name=event_type.title(),
                    tag_type="event_type",
                    properties={},
                )
            )

        # Build relations - event belongs to calendar
        relations: List[RelationRef] = []
        calendar_key = getattr(entity, "calendar_key", None)
        if calendar_key:
            relations.append(
                RelationRef(
                    entity_id=calendar_key,
                    entity_type="GoogleCalendarListEntity",
                    relation_type=RelationType.PART_OF,
                    name=f"Calendar {calendar_key}",
                )
            )

        # Build content from description
        description = getattr(entity, "description", None)
        location = getattr(entity, "location", None)
        content_parts = []
        if description:
            content_parts.append(description)
        if location:
            content_parts.append(f"Location: {location}")
        content = "\n".join(content_parts) if content_parts else None

        return self.create_base_normalized_entity(
            entity,
            name=getattr(entity, "title", None) or getattr(entity, "summary", None) or entity.name,
            description=description,
            content=content,
            people=people,
            tags=tags,
            relations=relations,
            created_at_field="created_time",
            updated_at_field="updated_time",
            properties={
                "event_key": getattr(entity, "event_key", None),
                "calendar_key": calendar_key,
                "location": location,
                "status": status,
                "event_type": event_type,
                "start_datetime": self._serialize_datetime(
                    getattr(entity, "start_datetime", None)
                ),
                "start_date": getattr(entity, "start_date", None),
                "end_datetime": self._serialize_datetime(getattr(entity, "end_datetime", None)),
                "end_date": getattr(entity, "end_date", None),
                "recurring_event_id": getattr(entity, "recurring_event_id", None),
                "visibility": getattr(entity, "visibility", None),
                "transparency": getattr(entity, "transparency", None),
                "organizer_email": organizer_email,
                "creator_email": creator_email,
                "owner_email": owner_email,
            },
        )

    def _normalize_freebusy(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Google Calendar FreeBusy entity.

        FreeBusy entries show time ranges when the user is busy.
        """
        # Add owner as a person reference
        people: List[PersonRef] = []
        owner_email = getattr(entity, "owner_email", None)
        if owner_email:
            people.append(self._create_person_from_email(owner_email, PersonRole.OWNER))

        # Build relations - freebusy belongs to calendar
        relations: List[RelationRef] = []
        calendar_id = getattr(entity, "calendar_id", None)
        if calendar_id:
            relations.append(
                RelationRef(
                    entity_id=calendar_id,
                    entity_type="GoogleCalendarListEntity",
                    relation_type=RelationType.PART_OF,
                    name=f"Calendar {calendar_id}",
                )
            )

        # Serialize busy ranges
        busy = getattr(entity, "busy", []) or []
        busy_serialized = [
            {"start": b.get("start"), "end": b.get("end")} for b in busy if b
        ]

        return self.create_base_normalized_entity(
            entity,
            name=getattr(entity, "label", None) or entity.name,
            people=people,
            relations=relations,
            properties={
                "freebusy_key": getattr(entity, "freebusy_key", None),
                "calendar_id": calendar_id,
                "busy": busy_serialized,
                "owner_email": owner_email,
            },
        )

    def _normalize_generic(self, entity: BaseEntity) -> NormalizedEntity:
        """Generic fallback for unknown Google Calendar entity types."""
        return self.create_base_normalized_entity(entity)

    def _create_person_from_email(
        self,
        email: str,
        role: PersonRole,
        name: Optional[str] = None,
    ) -> PersonRef:
        """Create a PersonRef from an email address.

        Args:
            email: Email address
            role: Role of the person
            name: Optional display name
        """
        return PersonRef(
            id=email.lower(),  # Normalize email as ID
            name=name,
            email=email,
            role=role,
            properties={},
        )

    def _serialize_datetime(self, value: Any) -> Optional[str]:
        """Convert datetime to ISO string if not None."""
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)
