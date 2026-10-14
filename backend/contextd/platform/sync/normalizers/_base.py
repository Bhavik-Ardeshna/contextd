"""Base entity normalizer for canonical data model transformation.

This module provides the abstract base class for connector-specific normalizers
and a registry system for automatic normalizer selection.
"""

import logging
import re
from abc import ABC, abstractmethod
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional, Type, Union

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._normalized import (
    CustomFieldRef,
    LLMExtractionRef,
    NormalizedEntity,
    NormalizedFileEntity,
    PersonRef,
    PersonRole,
    PriorityRef,
    RelatedPersonRef,
    RelationRef,
    RelationType,
    StatusRef,
    TagRef,
)
from contextd.platform.llm.gateway import configured_llm_model

logger = logging.getLogger(__name__)


def _serialize_for_json(value: Any) -> Any:
    """Recursively convert datetime objects to ISO strings for JSON serialization.

    This ensures that nested datetime objects in dicts and lists are also serialized.

    Args:
        value: Any value that might contain datetime objects

    Returns:
        JSON-serializable version of the value
    """
    if isinstance(value, datetime):
        return value.isoformat()
    elif isinstance(value, date):
        return value.isoformat()
    elif isinstance(value, time):
        return value.isoformat()
    elif isinstance(value, dict):
        return {k: _serialize_for_json(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_serialize_for_json(item) for item in value]
    else:
        return value


class NormalizerRegistry:
    """Registry for connector-specific normalizers.

    Maps entity class names to their corresponding normalizer classes.
    """

    _registry: Dict[str, Type["BaseEntityNormalizer"]] = {}
    _source_registry: Dict[str, Type["BaseEntityNormalizer"]] = {}

    @classmethod
    def register(
        cls,
        entity_class_pattern: str,
        normalizer_class: Type["BaseEntityNormalizer"],
        source_type: Optional[str] = None,
    ) -> None:
        """Register a normalizer for an entity class pattern.

        Args:
            entity_class_pattern: Regex pattern matching entity class names
            normalizer_class: The normalizer class to use
            source_type: Optional source type (e.g., 'clickup')
        """
        cls._registry[entity_class_pattern] = normalizer_class
        if source_type:
            cls._source_registry[source_type] = normalizer_class

    @classmethod
    def get_normalizer(cls, entity: BaseEntity) -> "BaseEntityNormalizer":
        """Get the appropriate normalizer for an entity.

        Args:
            entity: The entity to normalize

        Returns:
            Appropriate normalizer instance

        Raises:
            ValueError: If no normalizer is registered for the entity type
        """
        entity_class_name = entity.__class__.__name__

        # Try exact pattern matches
        for pattern, normalizer_class in cls._registry.items():
            if re.match(pattern, entity_class_name):
                return normalizer_class()

        # Fall back to default normalizer
        return DefaultEntityNormalizer()

    @classmethod
    def get_normalizer_for_source(cls, source_type: str) -> "BaseEntityNormalizer":
        """Get normalizer by source type.

        Args:
            source_type: Source connector short_name (e.g., 'clickup')

        Returns:
            Appropriate normalizer instance
        """
        if source_type in cls._source_registry:
            return cls._source_registry[source_type]()
        return DefaultEntityNormalizer()


def register_normalizer(
    entity_pattern: str,
    source_type: Optional[str] = None,
):
    """Decorator to register a normalizer class.

    Args:
        entity_pattern: Regex pattern matching entity class names
        source_type: Optional source type

    Usage:
        @register_normalizer(r"ClickUp.*Entity", source_type="clickup")
        class ClickUpNormalizer(BaseEntityNormalizer):
            ...
    """

    def decorator(cls: Type["BaseEntityNormalizer"]):
        NormalizerRegistry.register(entity_pattern, cls, source_type)
        return cls

    return decorator


def get_normalizer_for_entity(entity: BaseEntity) -> "BaseEntityNormalizer":
    """Get the appropriate normalizer for an entity.

    Convenience function wrapping NormalizerRegistry.get_normalizer().

    Args:
        entity: The entity to normalize

    Returns:
        Appropriate normalizer instance
    """
    return NormalizerRegistry.get_normalizer(entity)


class BaseEntityNormalizer(ABC):
    """Base class for connector-specific entity normalizers.

    Subclasses implement connector-specific logic to extract:
    - People (assignees, owners, members, followers)
    - Tags and labels
    - Relationships (parent, child, dependencies)
    - Status and priority
    - Custom fields

    The normalize() method transforms any connector entity into
    the canonical NormalizedEntity format.
    """

    # Source type identifier (e.g., 'clickup', 'notion')
    source_type: str = "unknown"

    @abstractmethod
    def normalize(self, entity: BaseEntity) -> NormalizedEntity:
        """Transform connector entity to canonical NormalizedEntity format.

        Args:
            entity: Raw connector entity

        Returns:
            NormalizedEntity with standardized structure
        """
        pass

    # -------------------------------------------------------------------------
    # Common extraction helpers (used by subclasses)
    # -------------------------------------------------------------------------

    def extract_person_from_dict(
        self,
        data: Optional[Dict[str, Any]],
        role: PersonRole = PersonRole.OTHER,
        id_field: str = "id",
        name_field: str = "name",
        email_field: str = "email",
    ) -> Optional[PersonRef]:
        """Extract a single PersonRef from a dictionary.

        Args:
            data: Dictionary containing person data
            role: Role to assign to the person
            id_field: Field name for ID
            name_field: Field name for name
            email_field: Field name for email

        Returns:
            PersonRef if data is valid, None otherwise
        """
        if not data or not isinstance(data, dict):
            return None

        person_id = data.get(id_field) or data.get("gid") or data.get("user_id")
        if not person_id:
            return None

        # Extract name - try multiple common field names
        name = (
            data.get(name_field)
            or data.get("display_name")
            or data.get("full_name")
            or data.get("username")
        )

        # Extract email - try multiple common field names
        email = data.get(email_field) or data.get("email_address")
        # Some APIs nest email in a person object
        if not email and "person" in data:
            email = data["person"].get("email")

        return PersonRef(
            id=str(person_id),
            name=name,
            email=email,
            role=role,
            avatar_url=data.get("avatar_url") or data.get("photo") or data.get("profile_photo"),
            username=data.get("username"),
            properties={k: v for k, v in data.items() if k not in [id_field, name_field, email_field]},
        )

    def extract_people_from_list(
        self,
        data_list: Optional[List[Dict[str, Any]]],
        role: PersonRole = PersonRole.OTHER,
        **kwargs,
    ) -> List[PersonRef]:
        """Extract PersonRef list from a list of dictionaries.

        Args:
            data_list: List of person dictionaries
            role: Role to assign to all people
            **kwargs: Additional args passed to extract_person_from_dict

        Returns:
            List of PersonRef
        """
        if not data_list or not isinstance(data_list, list):
            return []

        people = []
        for item in data_list:
            person = self.extract_person_from_dict(item, role=role, **kwargs)
            if person:
                people.append(person)

        return people

    def extract_tag_from_dict(
        self,
        data: Optional[Dict[str, Any]],
        id_field: str = "id",
        name_field: str = "name",
        color_field: str = "color",
    ) -> Optional[TagRef]:
        """Extract a single TagRef from a dictionary.

        Args:
            data: Dictionary containing tag data
            id_field: Field name for ID
            name_field: Field name for name
            color_field: Field name for color

        Returns:
            TagRef if data is valid, None otherwise
        """
        if not data or not isinstance(data, dict):
            return None

        tag_id = data.get(id_field) or data.get("gid")
        tag_name = data.get(name_field)

        if not tag_id or not tag_name:
            return None

        return TagRef(
            id=str(tag_id),
            name=tag_name,
            color=data.get(color_field),
            tag_type=data.get("type"),
            properties={k: v for k, v in data.items() if k not in [id_field, name_field, color_field]},
        )

    def extract_tags_from_list(
        self,
        data_list: Optional[List[Dict[str, Any]]],
        **kwargs,
    ) -> List[TagRef]:
        """Extract TagRef list from a list of dictionaries.

        Args:
            data_list: List of tag dictionaries
            **kwargs: Additional args passed to extract_tag_from_dict

        Returns:
            List of TagRef
        """
        if not data_list or not isinstance(data_list, list):
            return []

        tags = []
        for item in data_list:
            tag = self.extract_tag_from_dict(item, **kwargs)
            if tag:
                tags.append(tag)

        return tags

    def extract_status(
        self,
        data: Optional[Union[Dict[str, Any], str]],
        id_field: str = "id",
        name_field: str = "status",
        color_field: str = "color",
    ) -> Optional[StatusRef]:
        """Extract StatusRef from status data.

        Args:
            data: Status data (dict or string)
            id_field: Field name for ID
            name_field: Field name for name
            color_field: Field name for color

        Returns:
            StatusRef if data is valid, None otherwise
        """
        if not data:
            return None

        if isinstance(data, str):
            return StatusRef(name=data)

        if isinstance(data, dict):
            status_name = data.get(name_field) or data.get("name")
            if not status_name:
                return None

            return StatusRef(
                id=data.get(id_field),
                name=status_name,
                color=data.get(color_field),
                category=data.get("type") or data.get("category"),
                properties={k: v for k, v in data.items() if k not in [id_field, name_field, color_field]},
            )

        return None

    def extract_priority(
        self,
        data: Optional[Union[Dict[str, Any], str, int]],
    ) -> Optional[PriorityRef]:
        """Extract PriorityRef from priority data.

        Args:
            data: Priority data (dict, string, or int)

        Returns:
            PriorityRef if data is valid, None otherwise
        """
        if not data:
            return None

        if isinstance(data, str):
            return PriorityRef(name=data)

        if isinstance(data, int):
            return PriorityRef(name=f"Priority {data}", level=data)

        if isinstance(data, dict):
            priority_name = data.get("priority") or data.get("name")
            if not priority_name:
                return None

            level = data.get("orderindex") or data.get("level") or data.get("order")

            return PriorityRef(
                id=data.get("id"),
                name=priority_name,
                level=int(level) if level is not None else None,
                color=data.get("color"),
                properties={k: v for k, v in data.items() if k not in ["id", "name", "priority", "color"]},
            )

        return None

    def extract_relation(
        self,
        entity_id: str,
        entity_type: str,
        relation_type: RelationType,
        name: Optional[str] = None,
    ) -> RelationRef:
        """Create a RelationRef.

        Args:
            entity_id: ID of the related entity
            entity_type: Type of the related entity
            relation_type: Type of relationship
            name: Optional name of the related entity

        Returns:
            RelationRef instance
        """
        return RelationRef(
            entity_id=entity_id,
            entity_type=entity_type,
            relation_type=relation_type,
            name=name,
        )

    def extract_custom_field(
        self,
        data: Dict[str, Any],
    ) -> Optional[CustomFieldRef]:
        """Extract CustomFieldRef from custom field data.

        Args:
            data: Custom field dictionary

        Returns:
            CustomFieldRef if data is valid, None otherwise
        """
        if not data or not isinstance(data, dict):
            return None

        field_id = data.get("id") or data.get("gid")
        field_name = data.get("name")
        field_type = data.get("type") or data.get("resource_subtype")

        if not field_id or not field_name:
            return None

        # Extract value based on field type
        value = data.get("value")
        display_value = data.get("display_value")

        # Handle common value structures
        if isinstance(value, dict):
            display_value = display_value or value.get("name") or value.get("display_value")
        elif isinstance(value, list):
            display_value = display_value or ", ".join(
                str(v.get("name", v)) if isinstance(v, dict) else str(v) for v in value
            )

        return CustomFieldRef(
            id=str(field_id),
            name=field_name,
            field_type=field_type or "unknown",
            value=value,
            display_value=str(display_value) if display_value else None,
            properties={k: v for k, v in data.items() if k not in ["id", "gid", "name", "type", "value"]},
        )

    def extract_custom_fields_from_list(
        self,
        data_list: Optional[List[Dict[str, Any]]],
    ) -> List[CustomFieldRef]:
        """Extract CustomFieldRef list from a list of dictionaries.

        Args:
            data_list: List of custom field dictionaries

        Returns:
            List of CustomFieldRef
        """
        if not data_list or not isinstance(data_list, list):
            return []

        fields = []
        for item in data_list:
            field = self.extract_custom_field(item)
            if field:
                fields.append(field)

        return fields

    # -------------------------------------------------------------------------
    # LLM Extraction Helpers
    # -------------------------------------------------------------------------

    def convert_llm_extractions_to_refs(
        self,
        entity: BaseEntity,
    ) -> List[LLMExtractionRef]:
        """Convert _llm_extracted_entities to LLMExtractionRef list.

        This is a shared helper that all normalizers can use to convert
        LLM-extracted entities into the normalized format. The extracted
        entities are stored on the raw entity by the LLM enrichment service.

        Args:
            entity: Entity with potential _llm_extracted_entities attribute

        Returns:
            List of LLMExtractionRef for graph event generation
        """
        if not hasattr(entity, '_llm_extracted_entities') or not entity._llm_extracted_entities:
            return []

        extraction_metadata = getattr(entity, '_llm_extraction_metadata', {})
        refs = []

        for extracted in entity._llm_extracted_entities:
            node_id = self._generate_extraction_node_id(extracted)

            # Convert related_to (legacy) and related_persons to RelatedPersonRef list
            related_persons = self._extract_related_persons(extracted.properties)

            refs.append(LLMExtractionRef(
                id=node_id,
                entity_type=extracted.type,
                name=extracted.properties.get("name", "Unknown"),
                edge_type=extracted.properties.get("_edge_type", "EXTRACTED_FROM"),
                description=extracted.properties.get("description"),
                related_to=extracted.properties.get("related_to"),
                related_persons=related_persons,
                confidence=extracted.confidence,
                extraction_model=extraction_metadata.get("model", configured_llm_model("extraction")),
                source_field=extracted.source_field,
                # Exclude internal properties (those starting with _)
                properties={k: v for k, v in extracted.properties.items()
                           if not k.startswith("_") and k not in ("related_to", "related_persons")},
            ))

        return refs

    def _extract_related_persons(
        self,
        properties: Dict[str, Any],
    ) -> List[RelatedPersonRef]:
        """Extract related persons from LLM extraction properties.

        Handles multiple formats:
        - related_to: "email@example.com" (single email)
        - related_to: "John Doe <email@example.com>" (name + email)
        - related_persons: [{"email": "...", "role": "..."}] (structured list)
        - assigned_to: "email@example.com" (alias for task assignment)
        - attendees: ["email1", "email2"] (for meetings)

        Args:
            properties: Extraction properties dict

        Returns:
            List of RelatedPersonRef objects
        """
        related_persons = []
        seen_emails = set()

        # Handle structured related_persons list
        if "related_persons" in properties and isinstance(properties["related_persons"], list):
            for person in properties["related_persons"]:
                if isinstance(person, dict) and "email" in person:
                    email = person["email"].lower()
                    if email not in seen_emails:
                        seen_emails.add(email)
                        related_persons.append(RelatedPersonRef(
                            email=person["email"],
                            role=person.get("role", "RELATES_TO"),
                            name=person.get("name"),
                        ))

        # Handle legacy related_to (single email string)
        if "related_to" in properties and properties["related_to"]:
            email = self._extract_email_from_string(properties["related_to"])
            if email and email.lower() not in seen_emails:
                seen_emails.add(email.lower())
                related_persons.append(RelatedPersonRef(
                    email=email,
                    role="RELATES_TO",
                    name=self._extract_name_from_email_string(properties["related_to"]),
                ))

        # Handle assigned_to field (common for tasks/action items)
        if "assigned_to" in properties and properties["assigned_to"]:
            value = properties["assigned_to"]
            if isinstance(value, str):
                email = self._extract_email_from_string(value)
                if email and email.lower() not in seen_emails:
                    seen_emails.add(email.lower())
                    related_persons.append(RelatedPersonRef(
                        email=email,
                        role="ASSIGNED_TO",
                        name=self._extract_name_from_email_string(value),
                    ))
            elif isinstance(value, list):
                for v in value:
                    email = self._extract_email_from_string(str(v))
                    if email and email.lower() not in seen_emails:
                        seen_emails.add(email.lower())
                        related_persons.append(RelatedPersonRef(
                            email=email,
                            role="ASSIGNED_TO",
                        ))

        # Handle attendees field (common for meetings)
        if "attendees" in properties and isinstance(properties["attendees"], list):
            for attendee in properties["attendees"]:
                email = self._extract_email_from_string(str(attendee))
                if email and email.lower() not in seen_emails:
                    seen_emails.add(email.lower())
                    related_persons.append(RelatedPersonRef(
                        email=email,
                        role="SCHEDULED_WITH",
                    ))

        # Handle owner field
        if "owner" in properties and properties["owner"]:
            email = self._extract_email_from_string(str(properties["owner"]))
            if email and email.lower() not in seen_emails:
                seen_emails.add(email.lower())
                related_persons.append(RelatedPersonRef(
                    email=email,
                    role="OWNED_BY",
                ))

        return related_persons

    def _extract_email_from_string(self, value: str) -> Optional[str]:
        """Extract email address from a string.

        Handles formats:
        - "email@example.com"
        - "John Doe <email@example.com>"
        - "\"John Doe\" <email@example.com>"

        Args:
            value: String that may contain an email

        Returns:
            Email address if found, None otherwise
        """
        if not value:
            return None

        # Check for <email> format
        if "<" in value and ">" in value:
            match = re.search(r'<([^>]+@[^>]+)>', value)
            if match:
                return match.group(1)

        # Check if the whole string is an email
        if "@" in value and "." in value.split("@")[-1]:
            # Simple email validation
            value = value.strip()
            if " " not in value:
                return value

        return None

    def _extract_name_from_email_string(self, value: str) -> Optional[str]:
        """Extract name from an email string if present.

        Args:
            value: String like "John Doe <email@example.com>"

        Returns:
            Name if found, None otherwise
        """
        if "<" in value:
            name = value.rsplit("<", 1)[0].strip().strip('"').strip()
            return name if name else None
        return None

    def _generate_extraction_node_id(self, extracted) -> str:
        """Generate stable node ID for an LLM-extracted entity.

        Uses name-based ID generation for deterministic IDs across syncs.

        Args:
            extracted: ExtractedEntity object

        Returns:
            Stable node ID string
        """
        from uuid import uuid4

        name = extracted.properties.get("name", "")
        if name:
            # Normalize name for stable ID
            normalized_name = name.lower().strip().replace(" ", "_")
            # Create type prefix from entity type (e.g., "EmailExtract:ActionItem" -> "emailextract_actionitem")
            type_prefix = extracted.type.lower().replace(":", "_")
            return f"{type_prefix}_{normalized_name}"

        # Fallback to UUID if no name (should rarely happen)
        return f"{extracted.type.lower().replace(':', '_')}_{uuid4()}"

    def parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse datetime from various formats.

        Args:
            value: Datetime value (string, int timestamp, or datetime)

        Returns:
            datetime if parseable, None otherwise (timezone-naive for DB compatibility)
        """
        if value is None:
            return None

        result = None

        if isinstance(value, datetime):
            result = value
        elif isinstance(value, (int, float)):
            # Assume milliseconds if > 10 digits
            if value > 10000000000:
                value = value / 1000
            try:
                result = datetime.fromtimestamp(value)
            except (ValueError, OSError):
                return None
        elif isinstance(value, str):
            # Try ISO format with timezone first (handles +00:00, Z, etc.)
            try:
                # Handle common ISO formats with timezone
                result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                # Try common formats without timezone
                formats = [
                    "%Y-%m-%dT%H:%M:%S.%f",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d",
                ]
                for fmt in formats:
                    try:
                        result = datetime.strptime(value, fmt)
                        break
                    except ValueError:
                        continue

        # Strip timezone info for DB compatibility (TIMESTAMP WITHOUT TIME ZONE)
        if result is not None and result.tzinfo is not None:
            # Convert to UTC then remove timezone
            result = result.replace(tzinfo=None)

        return result

    def extract_breadcrumbs(
        self, entity: BaseEntity
    ) -> tuple[List[str], List[str]]:
        """Extract breadcrumb IDs and names from entity.

        Args:
            entity: Entity with breadcrumbs

        Returns:
            Tuple of (breadcrumb_ids, breadcrumb_names)
        """
        breadcrumb_ids = []
        breadcrumb_names = []

        if hasattr(entity, "breadcrumbs") and entity.breadcrumbs:
            for bc in entity.breadcrumbs:
                breadcrumb_ids.append(bc.entity_id)
                breadcrumb_names.append(bc.name)

        return breadcrumb_ids, breadcrumb_names

    def extract_web_url(
        self,
        entity: BaseEntity,
        url_fields: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Extract web URL from entity, trying multiple field names.

        Handles both direct URL attributes and callable web_url methods.

        Args:
            entity: Entity to extract URL from
            url_fields: List of field names to try (default: url, permalink_url, view_url)

        Returns:
            Web URL string if found, None otherwise
        """
        if url_fields is None:
            url_fields = ["url", "permalink_url", "view_url", "web_url_value"]

        # Try direct URL fields first
        for field in url_fields:
            value = getattr(entity, field, None)
            if value and isinstance(value, str):
                return value

        # Try callable web_url method
        web_url_prop = getattr(entity, "web_url", None)
        if callable(web_url_prop):
            try:
                return web_url_prop()
            except Exception:
                pass

        return None

    def add_relation_if_exists(
        self,
        relations: List[RelationRef],
        entity: BaseEntity,
        id_field: str,
        entity_type: str,
        relation_type: RelationType,
        name_field: Optional[str] = None,
    ) -> None:
        """Add a relation to the list if the ID field exists on the entity.

        Args:
            relations: List to append relation to
            entity: Entity to extract relation from
            id_field: Field name for the related entity ID
            entity_type: Type of the related entity
            relation_type: Type of relationship
            name_field: Optional field name for related entity name
        """
        entity_id = getattr(entity, id_field, None)
        if entity_id:
            name = getattr(entity, name_field, None) if name_field else None
            relations.append(
                RelationRef(
                    entity_id=str(entity_id),
                    entity_type=entity_type,
                    relation_type=relation_type,
                    name=name,
                )
            )

    def extract_people_with_roles(
        self,
        entity: BaseEntity,
        field_role_map: Dict[str, PersonRole],
        person_extractor: Optional[callable] = None,
    ) -> List[PersonRef]:
        """Extract people from multiple fields with their roles.

        Args:
            entity: Entity to extract people from
            field_role_map: Dict mapping field names to PersonRole
            person_extractor: Optional custom function to extract person from dict
                              Signature: (data: Dict, role: PersonRole) -> Optional[PersonRef]

        Returns:
            List of PersonRef from all specified fields
        """
        people: List[PersonRef] = []
        extractor = person_extractor or self.extract_person_from_dict

        for field_name, role in field_role_map.items():
            data = getattr(entity, field_name, None)
            if not data:
                continue

            if isinstance(data, dict):
                # Single person
                person = extractor(data, role=role)
                if person:
                    people.append(person)
            elif isinstance(data, list):
                # List of people
                for item in data:
                    if isinstance(item, dict):
                        person = extractor(item, role=role)
                        if person:
                            people.append(person)

        return people

    def create_base_normalized_entity(
        self,
        entity: BaseEntity,
        name: Optional[str] = None,
        description: Optional[str] = None,
        content: Optional[str] = None,
        web_url: Optional[str] = None,
        people: Optional[List[PersonRef]] = None,
        tags: Optional[List[TagRef]] = None,
        relations: Optional[List[RelationRef]] = None,
        status: Optional[StatusRef] = None,
        priority: Optional[PriorityRef] = None,
        custom_fields: Optional[List[CustomFieldRef]] = None,
        llm_extractions: Optional[List[LLMExtractionRef]] = None,
        created_at_field: str = "created_at",
        updated_at_field: str = "updated_at",
        due_at_field: Optional[str] = None,
        due_at: Optional[str] = None,
        completed_at_field: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        include_llm_extractions: bool = True,
    ) -> NormalizedEntity:
        """Create a NormalizedEntity with common defaults.

        This method reduces boilerplate by handling:
        - Breadcrumb extraction
        - Timestamp parsing
        - Default empty lists for collections
        - LLM extraction conversion (if include_llm_extractions=True)

        Args:
            entity: Source entity
            name: Entity name (defaults to entity.name)
            description: Description text
            content: Content text
            web_url: Web URL (auto-extracted if None)
            people: List of people
            tags: List of tags
            relations: List of relations
            status: Status reference
            priority: Priority reference
            custom_fields: List of custom fields
            llm_extractions: List of LLM extraction refs (auto-extracted if None)
            created_at_field: Field name for created timestamp
            updated_at_field: Field name for updated timestamp
            due_at_field: Optional field name for due timestamp (on entity)
            due_at: Optional due date value (ISO string or datetime)
            completed_at_field: Optional field name for completed timestamp
            properties: Additional properties dict
            include_llm_extractions: Whether to auto-convert LLM extractions (default True)

        Returns:
            NormalizedEntity with populated fields
        """
        breadcrumb_ids, breadcrumb_names = self.extract_breadcrumbs(entity)

        # Parse timestamps
        created_at = self.parse_datetime(getattr(entity, created_at_field, None))
        updated_at = self.parse_datetime(getattr(entity, updated_at_field, None))
        # Use due_at parameter if provided, otherwise try due_at_field
        due_at_parsed = self.parse_datetime(due_at) if due_at else (
            self.parse_datetime(getattr(entity, due_at_field, None)) if due_at_field else None
        )
        completed_at = self.parse_datetime(getattr(entity, completed_at_field, None)) if completed_at_field else None

        # Auto-extract web_url if not provided
        if web_url is None:
            web_url = self.extract_web_url(entity)

        # Auto-convert LLM extractions if not provided and flag is True
        if llm_extractions is None and include_llm_extractions:
            llm_extractions = self.convert_llm_extractions_to_refs(entity)

        return NormalizedEntity(
            entity_id=entity.entity_id,
            entity_type=entity.__class__.__name__,
            source_type=self.source_type,
            name=name or entity.name,
            description=description,
            content=content,
            web_url=web_url,
            people=people or [],
            tags=tags or [],
            relations=relations or [],
            status=status,
            priority=priority,
            custom_fields=custom_fields or [],
            llm_extractions=llm_extractions or [],
            created_at=created_at,
            updated_at=updated_at,
            due_at=due_at_parsed,
            completed_at=completed_at,
            properties=properties or {},
            breadcrumb_ids=breadcrumb_ids,
            breadcrumb_names=breadcrumb_names,
        )

    def create_base_file_entity(
        self,
        entity: BaseEntity,
        file_url: str = "",
        name: Optional[str] = None,
        description: Optional[str] = None,
        web_url: Optional[str] = None,
        people: Optional[List[PersonRef]] = None,
        relations: Optional[List[RelationRef]] = None,
        properties: Optional[Dict[str, Any]] = None,
        file_size_field: str = "size",
        file_type_field: str = "file_type",
        mime_type_field: str = "mime_type",
        local_path_field: str = "local_path",
        include_llm_extractions: bool = True,
    ) -> NormalizedFileEntity:
        """Create a NormalizedFileEntity with common defaults.

        Args:
            entity: Source entity
            file_url: URL to the file
            name: File name (defaults to entity.name)
            description: Description text
            web_url: Web URL (auto-extracted if None)
            people: List of people
            relations: List of relations
            properties: Additional properties dict
            file_size_field: Field name for file size
            file_type_field: Field name for file type
            mime_type_field: Field name for MIME type
            local_path_field: Field name for local path
            include_llm_extractions: Whether to auto-convert LLM extractions (default True)

        Returns:
            NormalizedFileEntity with populated fields
        """
        breadcrumb_ids, breadcrumb_names = self.extract_breadcrumbs(entity)

        # Auto-extract web_url if not provided
        if web_url is None:
            web_url = self.extract_web_url(entity)

        # Auto-convert LLM extractions
        llm_extractions = []
        if include_llm_extractions:
            llm_extractions = self.convert_llm_extractions_to_refs(entity)

        return NormalizedFileEntity(
            entity_id=entity.entity_id,
            entity_type=entity.__class__.__name__,
            source_type=self.source_type,
            name=name or entity.name,
            description=description,
            content=None,
            web_url=web_url,
            people=people or [],
            tags=[],
            relations=relations or [],
            status=None,
            priority=None,
            custom_fields=[],
            llm_extractions=llm_extractions,
            created_at=self.parse_datetime(getattr(entity, "created_at", None)),
            updated_at=None,
            properties=properties or {},
            breadcrumb_ids=breadcrumb_ids,
            breadcrumb_names=breadcrumb_names,
            # File-specific fields
            file_url=file_url,
            file_size=getattr(entity, file_size_field, None),
            file_type=getattr(entity, file_type_field, None),
            mime_type=getattr(entity, mime_type_field, None),
            local_path=getattr(entity, local_path_field, None),
        )


class DefaultEntityNormalizer(BaseEntityNormalizer):
    """Default normalizer for entities without a specific normalizer.

    Provides basic normalization by extracting common fields.
    """

    source_type = "unknown"

    def normalize(self, entity: BaseEntity) -> NormalizedEntity:
        """Transform entity to NormalizedEntity using reflection.

        Args:
            entity: Any BaseEntity

        Returns:
            NormalizedEntity with basic field extraction
        """
        # Extract entity ID and name from flagged fields
        entity_id = getattr(entity, "entity_id", None) or str(id(entity))
        name = getattr(entity, "name", None) or entity.__class__.__name__

        # Try to get source type from metadata
        source_type = "unknown"
        if hasattr(entity, "contextd_system_metadata") and entity.contextd_system_metadata:
            source_type = entity.contextd_system_metadata.source_name or "unknown"

        # Extract timestamps
        created_at = self.parse_datetime(getattr(entity, "created_at", None))
        updated_at = self.parse_datetime(getattr(entity, "updated_at", None))

        # Extract breadcrumbs
        breadcrumb_ids, breadcrumb_names = self.extract_breadcrumbs(entity)

        # Try to extract description/content from common fields
        description = None
        content = None
        for field_name in ["description", "notes", "content", "body", "text"]:
            value = getattr(entity, field_name, None)
            if value:
                if not description:
                    description = value
                else:
                    content = value
                break

        # Try to extract web_url
        web_url = getattr(entity, "web_url", None)
        if callable(web_url):
            try:
                web_url = web_url()
            except Exception:
                web_url = None

        # Collect all other fields as properties
        properties = {}
        for field_name in entity.model_fields.keys():
            if field_name not in [
                "entity_id",
                "name",
                "breadcrumbs",
                "created_at",
                "updated_at",
                "description",
                "notes",
                "content",
                "textual_representation",
                "contextd_system_metadata",
            ]:
                value = getattr(entity, field_name, None)
                if value is not None:
                    # Recursively convert datetime objects for JSON serialization
                    properties[field_name] = _serialize_for_json(value)

        # Convert LLM extractions if present
        llm_extractions = self.convert_llm_extractions_to_refs(entity)

        return NormalizedEntity(
            entity_id=entity_id,
            entity_type=entity.__class__.__name__,
            source_type=source_type,
            name=name,
            description=description,
            content=content,
            web_url=web_url,
            people=[],
            tags=[],
            relations=[],
            status=None,
            priority=None,
            custom_fields=[],
            llm_extractions=llm_extractions,
            created_at=created_at,
            updated_at=updated_at,
            properties=properties,
            breadcrumb_ids=breadcrumb_ids,
            breadcrumb_names=breadcrumb_names,
        )
