"""Notion entity normalizer.

Transforms Notion-specific entity structures into the canonical
NormalizedEntity format, extracting:
- People from created_by, last_edited_by, assignees, property_entities
- Tags from tags, multi_select properties
- Status from select/status properties
- Parent/child relationships
- Custom fields from property_entities
"""

from typing import Any, Dict, List, Optional

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._normalized import (
    CustomFieldRef,
    NormalizedEntity,
    NormalizedFileEntity,
    PersonRef,
    PersonRole,
    PriorityRef,
    RelationRef,
    RelationType,
    StatusRef,
    TagRef,
)
from contextd.platform.sync.normalizers._base import (
    BaseEntityNormalizer,
    register_normalizer,
)

# Notion URL fields - used across multiple methods
NOTION_URL_FIELDS = ["url", "web_url_value"]


@register_normalizer(r"Notion.*Entity", source_type="notion")
class NotionNormalizer(BaseEntityNormalizer):
    """Normalizer for Notion entities.

    Handles extraction of nested data from Notion's JSON structures:
    - created_by/last_edited_by: User objects with id, name, avatar_url
    - assignees: List of user dicts extracted from people-type properties
    - tags: List of strings from multi_select/select properties
    - property_entities: Structured property values with types and formatted values
    - parent_id/parent_type: Parent entity relationships
    """

    source_type = "notion"

    def normalize(self, entity: BaseEntity) -> NormalizedEntity:
        """Transform Notion entity to NormalizedEntity.

        Args:
            entity: Notion entity instance

        Returns:
            NormalizedEntity with extracted data
        """
        entity_class_name = entity.__class__.__name__

        # Route to specific handler based on entity type
        if "Database" in entity_class_name:
            return self._normalize_database(entity)
        elif "Page" in entity_class_name and "Property" not in entity_class_name:
            return self._normalize_page(entity)
        elif "Property" in entity_class_name:
            return self._normalize_property(entity)
        elif "File" in entity_class_name:
            return self._normalize_file(entity)
        else:
            return self._normalize_generic(entity)

    def _normalize_database(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Notion database entity."""
        # Extract people using base helper with custom extractor
        people = self.extract_people_with_roles(
            entity,
            {
                "created_by": PersonRole.CREATOR,
                "last_edited_by": PersonRole.EDITOR,
            },
            person_extractor=self._extract_notion_person,
        )

        # Build relations for parent
        relations: List[RelationRef] = []
        parent_id = getattr(entity, "parent_id", None)
        parent_type = getattr(entity, "parent_type", None)
        if parent_id and parent_type != "workspace":
            relations.append(
                RelationRef(
                    entity_id=parent_id,
                    entity_type=self._get_parent_entity_type(parent_type),
                    relation_type=RelationType.CHILD,
                    name=None,
                )
            )

        # Extract custom fields from properties schema
        custom_fields = self._extract_database_schema_fields(getattr(entity, "properties", {}))

        return self.create_base_normalized_entity(
            entity,
            name=getattr(entity, "title", None) or entity.name,
            description=getattr(entity, "description", None),
            content=getattr(entity, "properties_text", None),
            web_url=self.extract_web_url(entity, NOTION_URL_FIELDS),
            people=people,
            relations=relations,
            custom_fields=custom_fields,
            created_at_field="created_time",
            updated_at_field="updated_time",
            properties={
                "database_id": getattr(entity, "database_id", None),
                "parent_id": parent_id,
                "parent_type": parent_type,
                "archived": getattr(entity, "archived", False),
                "is_inline": getattr(entity, "is_inline", False),
                "icon": getattr(entity, "icon", None),
                "cover": getattr(entity, "cover", None),
            },
        )

    def _normalize_page(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Notion page entity."""
        # Get property_entities first for person info enrichment
        property_entities = getattr(entity, "property_entities", []) or []

        # Extract assignees from property_entities (they have full person info)
        property_people = self._extract_people_from_property_entities(property_entities)

        # Build lookup of person IDs to full info from property_entities
        person_info_by_id: Dict[str, PersonRef] = {}
        for person in property_people:
            if person.id:
                person_info_by_id[person.id] = person

        # Extract people from standard fields
        people = self.extract_people_with_roles(
            entity,
            {
                "created_by": PersonRole.CREATOR,
                "last_edited_by": PersonRole.EDITOR,
                "assignees": PersonRole.ASSIGNEE,
            },
            person_extractor=self._extract_notion_person,
        )

        # Enrich creator/editor with full info from property_entities if available
        for i, person in enumerate(people):
            if person.id and not person.name and person.id in person_info_by_id:
                enriched = person_info_by_id[person.id]
                people[i] = PersonRef(
                    id=person.id,
                    name=enriched.name,
                    email=enriched.email,
                    role=person.role,  # Keep original role
                    avatar_url=enriched.avatar_url or person.avatar_url,
                    username=enriched.username,
                    properties=person.properties,
                )

        # Add property_people (avoiding duplicates by ID+role)
        existing_keys = {(p.id, p.role) for p in people}
        for person in property_people:
            if (person.id, person.role) not in existing_keys:
                people.append(person)
                existing_keys.add((person.id, person.role))

        # Extract tags from tags field
        tags: List[TagRef] = []
        for tag_name in getattr(entity, "tags", []) or []:
            if tag_name:
                tags.append(TagRef(
                    id=tag_name,  # Use name as ID since Notion tags don't have separate IDs
                    name=tag_name,
                    color=None,
                    tag_type="tag",
                ))
        # Also extract tags from multi_select property_entities
        tags.extend(self._extract_tags_from_property_entities(property_entities))

        # Build relations
        relations: List[RelationRef] = []
        parent_id = getattr(entity, "parent_id", None)
        parent_type = getattr(entity, "parent_type", None)
        if parent_id:
            relations.append(
                RelationRef(
                    entity_id=parent_id,
                    entity_type=self._get_parent_entity_type(parent_type),
                    relation_type=RelationType.CHILD,
                    name=None,
                )
            )

        # Extract status, priority, due date, and custom fields from properties
        properties_dict = getattr(entity, "properties", {})
        status = self._extract_status_from_properties(properties_dict)
        priority = self._extract_priority_from_properties(properties_dict)
        due_at = self._extract_due_date_from_property_entities(property_entities)
        custom_fields = self._extract_custom_fields_from_property_entities(property_entities)

        return self.create_base_normalized_entity(
            entity,
            name=getattr(entity, "title", None) or entity.name,
            description=getattr(entity, "properties_text", None),
            content=getattr(entity, "content", None),
            web_url=self.extract_web_url(entity, NOTION_URL_FIELDS),
            people=people,
            tags=tags,
            relations=relations,
            status=status,
            priority=priority,
            custom_fields=custom_fields,
            due_at=due_at,
            created_at_field="created_time",
            updated_at_field="updated_time",
            properties={
                "page_id": getattr(entity, "page_id", None),
                "parent_id": parent_id,
                "parent_type": parent_type,
                "archived": getattr(entity, "archived", False),
                "in_trash": getattr(entity, "in_trash", False),
                "content_blocks_count": getattr(entity, "content_blocks_count", 0),
                "max_depth": getattr(entity, "max_depth", 0),
                "icon": getattr(entity, "icon", None),
                "cover": getattr(entity, "cover", None),
                "files": getattr(entity, "files", []),
            },
        )

    def _normalize_property(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Notion property entity."""
        relations: List[RelationRef] = []
        self.add_relation_if_exists(relations, entity, "page_id", "NotionPageEntity", RelationType.PART_OF)
        self.add_relation_if_exists(relations, entity, "database_id", "NotionDatabaseEntity", RelationType.PART_OF)

        property_name = getattr(entity, "property_name", None) or entity.name

        return self.create_base_normalized_entity(
            entity,
            name=property_name,
            content=getattr(entity, "formatted_value", None),
            web_url=None,  # Properties don't have web URLs
            relations=relations,
            properties={
                "property_key": getattr(entity, "property_key", None),
                "property_id": getattr(entity, "property_id", None),
                "property_name": property_name,
                "property_type": getattr(entity, "property_type", None),
                "page_id": getattr(entity, "page_id", None),
                "database_id": getattr(entity, "database_id", None),
                "value": getattr(entity, "value", None),
                "formatted_value": getattr(entity, "formatted_value", None),
            },
        )

    def _normalize_file(self, entity: BaseEntity) -> NormalizedFileEntity:
        """Normalize Notion file entity."""
        return self.create_base_file_entity(
            entity,
            file_url=getattr(entity, "url", ""),
            name=getattr(entity, "file_name", None) or entity.name,
            description=getattr(entity, "caption", None),
            web_url=self.extract_web_url(entity, NOTION_URL_FIELDS),
            properties={
                "file_id": getattr(entity, "file_id", None),
                "expiry_time": getattr(entity, "expiry_time", None),
                "caption": getattr(entity, "caption", None),
            },
        )

    def _normalize_generic(self, entity: BaseEntity) -> NormalizedEntity:
        """Generic normalization for unknown Notion entity types."""
        return self.create_base_normalized_entity(
            entity,
            created_at_field="created_time",
            updated_at_field="updated_time",
        )

    # -------------------------------------------------------------------------
    # Notion-specific extraction helpers
    # -------------------------------------------------------------------------

    def _to_dict(self, obj: Any) -> Optional[Dict[str, Any]]:
        """Convert an object to a dict, handling Pydantic models.

        Args:
            obj: Object to convert (dict, Pydantic model, or other)

        Returns:
            Dict if conversion successful, None otherwise
        """
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
        if hasattr(obj, "__dict__"):
            return vars(obj)
        return None

    def _extract_notion_person(
        self,
        data: Optional[Dict[str, Any]],
        role: PersonRole = PersonRole.OTHER,
    ) -> Optional[PersonRef]:
        """Extract a person from Notion user structure.

        Notion user structure:
        {
            "object": "user",
            "id": "uuid",
            "name": "John Doe",
            "avatar_url": "https://...",
            "type": "person",
            "person": {
                "email": "john@example.com"
            }
        }
        """
        if not data or not isinstance(data, dict):
            return None

        user_id = data.get("id")
        if not user_id:
            return None

        # Extract email from nested 'person' object
        email = None
        person_data = data.get("person", {})
        if isinstance(person_data, dict):
            email = person_data.get("email")

        return PersonRef(
            id=str(user_id),
            name=data.get("name"),
            email=email,
            role=role,
            avatar_url=data.get("avatar_url"),
            username=None,
            properties={
                "type": data.get("type"),
                "object": data.get("object"),
            },
        )

    def _get_parent_entity_type(self, parent_type: Optional[str]) -> str:
        """Map Notion parent type to entity type.

        Args:
            parent_type: Notion parent type string

        Returns:
            Entity type string
        """
        type_map = {
            "database_id": "NotionDatabaseEntity",
            "page_id": "NotionPageEntity",
            "workspace": "NotionWorkspaceEntity",
            "block_id": "NotionBlockEntity",
        }
        return type_map.get(parent_type, "NotionPageEntity")

    def _extract_database_schema_fields(
        self,
        properties: Optional[Dict[str, Any]],
    ) -> List[CustomFieldRef]:
        """Extract custom field definitions from database properties schema.

        Args:
            properties: Database properties schema dict

        Returns:
            List of CustomFieldRef representing the schema fields
        """
        if not properties or not isinstance(properties, dict):
            return []

        fields = []
        for prop_name, prop_info in properties.items():
            if not isinstance(prop_info, dict):
                continue

            prop_type = prop_info.get("type", "unknown")
            prop_id = prop_info.get("id")

            if not prop_id:
                continue

            # Extract options for select/multi_select types
            options = None
            if prop_type in ["select", "multi_select"]:
                type_config = prop_info.get(prop_type, {})
                if isinstance(type_config, dict):
                    options = type_config.get("options", [])

            fields.append(
                CustomFieldRef(
                    id=prop_id,
                    name=prop_name,
                    field_type=prop_type,
                    value=None,  # Schema only, no value
                    display_value=None,
                    properties={
                        "options": options,
                        "type_config": prop_info.get(prop_type, {}),
                    },
                )
            )

        return fields

    def _extract_custom_fields_from_property_entities(
        self,
        property_entities: Optional[List[Any]],
    ) -> List[CustomFieldRef]:
        """Extract custom fields from page property_entities.

        Args:
            property_entities: List of property entity dicts or Pydantic models

        Returns:
            List of CustomFieldRef
        """
        if not property_entities or not isinstance(property_entities, list):
            return []

        # Fields to skip (already handled elsewhere)
        skip_types = {"status", "people", "title"}
        skip_names = {"status", "priority", "assignee", "owner"}

        fields = []
        for prop_entity in property_entities:
            # Convert to dict if it's a Pydantic model
            prop_dict = self._to_dict(prop_entity)
            if not prop_dict:
                continue

            prop_name = prop_dict.get("property_name")
            prop_type = prop_dict.get("property_type")
            prop_id = prop_dict.get("property_id")

            if not prop_name or not prop_type:
                continue

            # Skip fields already handled by status, priority, people extraction
            if prop_type in skip_types:
                continue
            if prop_name.lower() in skip_names:
                continue

            value = prop_dict.get("value")
            formatted_value = prop_dict.get("formatted_value")

            # Skip empty values
            if value is None and not formatted_value:
                continue

            # Format display value based on type
            if formatted_value is None:
                formatted_value = self._format_property_value(value, prop_type)

            fields.append(
                CustomFieldRef(
                    id=prop_id or prop_name,
                    name=prop_name,
                    field_type=prop_type,
                    value=value,
                    display_value=formatted_value,
                    properties={},
                )
            )

        return fields

    def _format_property_value(self, value: Any, prop_type: str) -> Optional[str]:
        """Format a property value for display.

        Args:
            value: Raw property value
            prop_type: Property type

        Returns:
            Formatted string or None
        """
        if value is None:
            return None

        if isinstance(value, str):
            return value

        if isinstance(value, list):
            # Handle multi_select and similar list types
            parts = []
            for item in value:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("title") or str(item)
                    parts.append(str(name))
                else:
                    parts.append(str(item))
            return ", ".join(parts) if parts else None

        if isinstance(value, dict):
            # Handle select, date, etc.
            if "name" in value:
                return value["name"]
            if "start" in value:
                # Date type
                start = value.get("start", "")
                end = value.get("end", "")
                if end:
                    return f"{start} - {end}"
                return start
            return str(value)

        return str(value)

    def _extract_status_from_properties(
        self,
        properties: Optional[Dict[str, Any]],
    ) -> Optional[StatusRef]:
        """Extract status from page properties.

        Looks for common status field names like 'Status', 'State', etc.

        Args:
            properties: Page properties dict

        Returns:
            StatusRef if found, None otherwise
        """
        if not properties or not isinstance(properties, dict):
            return None

        # Common status field names
        status_keys = ["Status", "status", "State", "state", "Launch Status"]

        for key in status_keys:
            if key in properties:
                value = properties[key]
                if isinstance(value, str) and value:
                    return StatusRef(name=value)
                if isinstance(value, dict) and value.get("name"):
                    return StatusRef(
                        name=value["name"],
                        color=value.get("color"),
                    )

        return None

    def _extract_priority_from_properties(
        self,
        properties: Optional[Dict[str, Any]],
    ) -> Optional[PriorityRef]:
        """Extract priority from page properties.

        Looks for common priority field names like 'Priority', 'Urgency', etc.

        Args:
            properties: Page properties dict

        Returns:
            PriorityRef if found, None otherwise
        """
        if not properties or not isinstance(properties, dict):
            return None

        # Common priority field names
        priority_keys = ["Priority", "priority", "Urgency", "urgency", "Importance"]

        # Map common priority names to numeric levels (higher = more urgent)
        level_map = {
            "urgent": 4,
            "high": 3,
            "medium": 2,
            "normal": 2,
            "low": 1,
            "none": 0,
        }

        for key in priority_keys:
            if key in properties:
                value = properties[key]
                if isinstance(value, str) and value:
                    level = level_map.get(value.lower(), None)
                    return PriorityRef(name=value, level=level)
                if isinstance(value, dict) and value.get("name"):
                    name = value["name"]
                    level = level_map.get(name.lower(), None)
                    return PriorityRef(
                        id=value.get("id"),
                        name=name,
                        level=level,
                        color=value.get("color"),
                    )

        return None

    def _extract_due_date_from_property_entities(
        self,
        property_entities: Optional[List[Any]],
    ) -> Optional[str]:
        """Extract due date from property_entities.

        Looks for date-type properties with common due date field names.

        Args:
            property_entities: List of property entity dicts or Pydantic models

        Returns:
            ISO date string if found, None otherwise
        """
        if not property_entities or not isinstance(property_entities, list):
            return None

        # Common due date field names
        due_date_names = {"due date", "due", "deadline", "target date", "end date"}

        for prop_entity in property_entities:
            # Convert to dict if it's a Pydantic model
            prop_dict = self._to_dict(prop_entity)
            if not prop_dict:
                continue

            prop_type = prop_dict.get("property_type")
            prop_name = (prop_dict.get("property_name") or "").lower()

            # Only process date-type properties
            if prop_type != "date":
                continue

            # Check if it's a due date field
            if prop_name not in due_date_names:
                continue

            value = prop_dict.get("value")
            if value and isinstance(value, dict):
                start_date = value.get("start")
                if start_date:
                    return start_date

        return None

    def _extract_people_from_property_entities(
        self,
        property_entities: Optional[List[Any]],
    ) -> List[PersonRef]:
        """Extract people from property_entities (people-type properties).

        Args:
            property_entities: List of property entity dicts or Pydantic models

        Returns:
            List of PersonRef
        """
        people: List[PersonRef] = []

        if not property_entities or not isinstance(property_entities, list):
            return people

        for prop_entity in property_entities:
            # Convert to dict if it's a Pydantic model
            prop_dict = self._to_dict(prop_entity)
            if not prop_dict:
                continue

            prop_type = prop_dict.get("property_type")
            prop_name = prop_dict.get("property_name", "").lower()

            # Only process people-type properties
            if prop_type != "people":
                continue

            value = prop_dict.get("value")
            if not value or not isinstance(value, list):
                continue

            # Determine role based on property name
            role = PersonRole.OTHER
            if "assignee" in prop_name:
                role = PersonRole.ASSIGNEE
            elif "owner" in prop_name:
                role = PersonRole.OWNER
            elif "reviewer" in prop_name:
                role = PersonRole.REVIEWER
            elif "member" in prop_name:
                role = PersonRole.MEMBER

            for person_data in value:
                person_dict = self._to_dict(person_data)
                if person_dict:
                    person = self._extract_notion_person(person_dict, role=role)
                    if person:
                        people.append(person)

        return people

    def _extract_tags_from_property_entities(
        self,
        property_entities: Optional[List[Any]],
    ) -> List[TagRef]:
        """Extract tags from property_entities (multi_select properties).

        Args:
            property_entities: List of property entity dicts or Pydantic models

        Returns:
            List of TagRef
        """
        tags: List[TagRef] = []

        if not property_entities or not isinstance(property_entities, list):
            return tags

        for prop_entity in property_entities:
            # Convert to dict if it's a Pydantic model
            prop_dict = self._to_dict(prop_entity)
            if not prop_dict:
                continue

            prop_type = prop_dict.get("property_type")
            prop_name = prop_dict.get("property_name", "")

            # Only process multi_select properties (tags/labels)
            if prop_type != "multi_select":
                continue

            # Skip if it looks like a status or priority field
            if prop_name.lower() in ["status", "priority", "state", "urgency"]:
                continue

            value = prop_dict.get("value")
            if not value or not isinstance(value, list):
                continue

            for tag_data in value:
                tag_dict = self._to_dict(tag_data)
                if tag_dict and tag_dict.get("name"):
                    tags.append(
                        TagRef(
                            id=tag_dict.get("id", tag_dict["name"]),
                            name=tag_dict["name"],
                            color=tag_dict.get("color"),
                            tag_type=prop_name,  # Use property name as tag type
                        )
                    )

        return tags
