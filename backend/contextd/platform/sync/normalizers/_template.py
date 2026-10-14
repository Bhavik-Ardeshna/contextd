"""Template for creating a new connector normalizer.

This file serves as a guide for adding new connectors to the normalization system.
Copy this file and customize it for your specific connector.

STEPS TO ADD A NEW CONNECTOR:
1. Copy this file and rename it (e.g., jira.py, linear.py, monday.py)
2. Update the class name, source_type, and register_normalizer pattern
3. Implement connector-specific person extractor (if user structure differs)
4. Implement connector-specific tag/status/priority extractors (if needed)
5. Add entity-specific normalization methods
6. Register the normalizer in __init__.py
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


# =============================================================================
# STEP 1: Register your normalizer with a pattern matching your entity names
# =============================================================================
@register_normalizer(r"YourConnector.*Entity", source_type="yourconnector")
class YourConnectorNormalizer(BaseEntityNormalizer):
    """Normalizer for YourConnector entities.

    Document the data structures from this connector:
    - users: How users are represented (id, name, email fields)
    - tasks/items: Main work items
    - tags/labels: How tags are structured
    - status: Status field structure
    - priority: Priority field structure
    """

    source_type = "yourconnector"

    # =========================================================================
    # STEP 2: Main routing method - route entities to specific handlers
    # =========================================================================
    def normalize(self, entity: BaseEntity) -> NormalizedEntity:
        """Transform entity to NormalizedEntity.

        Route to specific handler based on entity type.
        """
        entity_class_name = entity.__class__.__name__

        # Route based on entity type - customize for your connector
        if "Task" in entity_class_name or "Issue" in entity_class_name:
            return self._normalize_task(entity)
        elif "Project" in entity_class_name:
            return self._normalize_project(entity)
        elif "Comment" in entity_class_name:
            return self._normalize_comment(entity)
        elif "File" in entity_class_name or "Attachment" in entity_class_name:
            return self._normalize_file(entity)
        else:
            return self._normalize_generic(entity)

    # =========================================================================
    # STEP 3: Entity-specific normalization methods
    # =========================================================================
    def _normalize_task(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize task/issue entity.

        This is typically the main work item entity.
        """
        # --- Extract People ---
        # Use extract_people_with_roles with your custom person extractor
        # Map field names to PersonRole
        people = self.extract_people_with_roles(
            entity,
            {
                "assignee": PersonRole.ASSIGNEE,      # Single person field
                "assignees": PersonRole.ASSIGNEE,    # List of people field
                "reporter": PersonRole.CREATOR,
                "watchers": PersonRole.FOLLOWER,
            },
            person_extractor=self._extract_person,  # Your custom extractor
        )

        # --- Extract Tags ---
        # Use your connector-specific tag extractor
        tags = self._extract_tags(getattr(entity, "labels", []) or [])

        # --- Extract Status & Priority ---
        status = self._extract_status(getattr(entity, "status", None))
        priority = self._extract_priority(getattr(entity, "priority", None))

        # --- Extract Custom Fields ---
        custom_fields = self._extract_custom_fields(
            getattr(entity, "custom_fields", []) or []
        )

        # --- Build Relations ---
        relations: List[RelationRef] = []
        # Use add_relation_if_exists for simple field -> relation mappings
        self.add_relation_if_exists(
            relations, entity, "project_id", "YourConnectorProjectEntity", RelationType.PART_OF
        )
        self.add_relation_if_exists(
            relations, entity, "parent_id", "YourConnectorTaskEntity", RelationType.PARENT
        )

        # For more complex relations (like dependencies), handle manually:
        # for dep in getattr(entity, "dependencies", []) or []:
        #     if isinstance(dep, dict) and dep.get("id"):
        #         relations.append(RelationRef(
        #             entity_id=dep["id"],
        #             entity_type="YourConnectorTaskEntity",
        #             relation_type=RelationType.DEPENDS_ON,
        #             name=dep.get("name"),
        #         ))

        # --- Create NormalizedEntity using base helper ---
        return self.create_base_normalized_entity(
            entity,
            # Override name if connector uses different field
            # name=getattr(entity, "title", None) or entity.name,
            description=getattr(entity, "description", None),
            content=getattr(entity, "description", None),
            # Let base class auto-extract web_url, or specify custom fields:
            # web_url=self.extract_web_url(entity, ["permalink", "url"]),
            people=people,
            tags=tags,
            relations=relations,
            status=status,
            priority=priority,
            custom_fields=custom_fields,
            # Specify timestamp field names if different from defaults
            # created_at_field="created_at",  # default
            # updated_at_field="updated_at",  # default
            due_at_field="due_date",  # if your connector has due dates
            completed_at_field="completed_at",  # if tasks can be completed
            properties={
                # Include connector-specific IDs and metadata
                "task_id": getattr(entity, "task_id", None),
                "project_id": getattr(entity, "project_id", None),
                # Add other relevant properties
            },
        )

    def _normalize_project(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize project/container entity."""
        people = self.extract_people_with_roles(
            entity,
            {
                "owner": PersonRole.OWNER,
                "lead": PersonRole.OWNER,
                "members": PersonRole.MEMBER,
            },
            person_extractor=self._extract_person,
        )

        relations: List[RelationRef] = []
        self.add_relation_if_exists(
            relations, entity, "workspace_id", "YourConnectorWorkspaceEntity", RelationType.PART_OF
        )

        return self.create_base_normalized_entity(
            entity,
            description=getattr(entity, "description", None),
            people=people,
            relations=relations,
            properties={
                "project_id": getattr(entity, "project_id", None),
                "workspace_id": getattr(entity, "workspace_id", None),
            },
        )

    def _normalize_comment(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize comment entity."""
        people = self.extract_people_with_roles(
            entity,
            {"author": PersonRole.AUTHOR},
            person_extractor=self._extract_person,
        )

        relations: List[RelationRef] = []
        self.add_relation_if_exists(
            relations, entity, "task_id", "YourConnectorTaskEntity", RelationType.COMMENT_ON
        )

        return self.create_base_normalized_entity(
            entity,
            content=getattr(entity, "body", None) or getattr(entity, "text", None),
            people=people,
            relations=relations,
            properties={
                "comment_id": getattr(entity, "comment_id", None),
                "task_id": getattr(entity, "task_id", None),
            },
        )

    def _normalize_file(self, entity: BaseEntity) -> NormalizedFileEntity:
        """Normalize file/attachment entity."""
        people = self.extract_people_with_roles(
            entity,
            {"uploaded_by": PersonRole.CREATOR},
            person_extractor=self._extract_person,
        )

        relations: List[RelationRef] = []
        self.add_relation_if_exists(
            relations, entity, "task_id", "YourConnectorTaskEntity", RelationType.ATTACHMENT_OF
        )

        return self.create_base_file_entity(
            entity,
            file_url=getattr(entity, "download_url", "") or getattr(entity, "url", ""),
            people=people,
            relations=relations,
            properties={
                "attachment_id": getattr(entity, "attachment_id", None),
                "task_id": getattr(entity, "task_id", None),
            },
        )

    def _normalize_generic(self, entity: BaseEntity) -> NormalizedEntity:
        """Generic fallback for unknown entity types."""
        return self.create_base_normalized_entity(entity)

    # =========================================================================
    # STEP 4: Connector-specific extraction helpers
    # =========================================================================
    def _extract_person(
        self,
        data: Optional[Dict[str, Any]],
        role: PersonRole = PersonRole.OTHER,
    ) -> Optional[PersonRef]:
        """Extract person from connector's user structure.

        Customize this based on how your connector represents users.

        Example structures from different connectors:
        - Jira: {"accountId": "...", "displayName": "...", "emailAddress": "..."}
        - Linear: {"id": "...", "name": "...", "email": "..."}
        - Monday: {"id": 123, "name": "...", "email": "..."}
        - GitHub: {"id": 123, "login": "...", "avatar_url": "..."}
        """
        if not data or not isinstance(data, dict):
            return None

        # Extract ID - try common field names
        user_id = (
            data.get("id")
            or data.get("accountId")  # Jira
            or data.get("user_id")
            or data.get("gid")  # Asana
        )
        if not user_id:
            return None

        # Extract name - try common field names
        name = (
            data.get("name")
            or data.get("displayName")  # Jira
            or data.get("display_name")
            or data.get("full_name")
            or data.get("login")  # GitHub
            or data.get("username")
        )

        # Extract email - handle nested structures
        email = data.get("email") or data.get("emailAddress")
        # Some APIs nest email in a person/user object
        if not email and isinstance(data.get("person"), dict):
            email = data["person"].get("email")

        return PersonRef(
            id=str(user_id),
            name=name,
            email=email,
            role=role,
            avatar_url=data.get("avatar_url") or data.get("avatarUrl") or data.get("photo"),
            username=data.get("username") or data.get("login"),
            properties={
                # Include any connector-specific user properties
                "user_type": data.get("type"),
            },
        )

    def _extract_tags(
        self,
        data_list: Optional[List[Dict[str, Any]]],
    ) -> List[TagRef]:
        """Extract tags from connector's label/tag structure.

        Customize based on how your connector represents tags.

        Example structures:
        - Jira: [{"id": "...", "name": "bug"}]
        - Linear: [{"id": "...", "name": "...", "color": "#ff0000"}]
        - GitHub: [{"id": 123, "name": "bug", "color": "d73a4a"}]
        """
        if not data_list or not isinstance(data_list, list):
            return []

        tags = []
        for item in data_list:
            if not isinstance(item, dict):
                # Handle simple string tags
                if isinstance(item, str):
                    tags.append(TagRef(id=item, name=item, tag_type="tag"))
                continue

            tag_id = item.get("id") or item.get("name")
            tag_name = item.get("name") or item.get("label")

            if not tag_name:
                continue

            tags.append(
                TagRef(
                    id=str(tag_id) if tag_id else tag_name,
                    name=tag_name,
                    color=item.get("color"),
                    tag_type=item.get("type", "tag"),
                    properties={},
                )
            )

        return tags

    def _extract_status(
        self,
        data: Optional[Any],
    ) -> Optional[StatusRef]:
        """Extract status from connector's status structure.

        Customize based on how your connector represents status.

        Example structures:
        - Simple string: "In Progress"
        - Object: {"id": "...", "name": "In Progress", "category": "inProgress"}
        - Jira: {"name": "In Progress", "statusCategory": {"key": "inProgress"}}
        """
        if not data:
            return None

        # Handle simple string status
        if isinstance(data, str):
            return StatusRef(name=data)

        if not isinstance(data, dict):
            return None

        status_name = data.get("name") or data.get("status") or data.get("state")
        if not status_name:
            return None

        # Map to category (todo, in_progress, done)
        category = self._map_status_category(
            data.get("category")
            or data.get("statusCategory", {}).get("key")
            or data.get("type")
        )

        return StatusRef(
            id=data.get("id"),
            name=status_name,
            color=data.get("color"),
            category=category,
            properties={},
        )

    def _map_status_category(self, category: Optional[str]) -> Optional[str]:
        """Map connector-specific status category to standard categories.

        Standard categories: "todo", "in_progress", "done"
        """
        if not category:
            return None

        category_lower = category.lower()

        # Map common category names
        if category_lower in ("todo", "to do", "open", "new", "backlog"):
            return "todo"
        elif category_lower in ("inprogress", "in_progress", "in progress", "active", "started"):
            return "in_progress"
        elif category_lower in ("done", "closed", "complete", "completed", "resolved"):
            return "done"

        return None

    def _extract_priority(
        self,
        data: Optional[Any],
    ) -> Optional[PriorityRef]:
        """Extract priority from connector's priority structure.

        Customize based on how your connector represents priority.

        Example structures:
        - Simple string: "High"
        - Integer: 1 (urgent), 2 (high), 3 (medium), 4 (low)
        - Object: {"id": "...", "name": "High", "order": 2}
        """
        if not data:
            return None

        # Handle integer priority
        if isinstance(data, int):
            return PriorityRef(name=f"Priority {data}", level=data)

        # Handle string priority
        if isinstance(data, str):
            level = self._priority_name_to_level(data)
            return PriorityRef(name=data, level=level)

        if not isinstance(data, dict):
            return None

        priority_name = data.get("name") or data.get("priority")
        if not priority_name:
            return None

        level = data.get("level") or data.get("order") or data.get("orderindex")
        if level is None:
            level = self._priority_name_to_level(priority_name)

        return PriorityRef(
            id=data.get("id"),
            name=priority_name,
            level=int(level) if level is not None else None,
            color=data.get("color"),
            properties={},
        )

    def _priority_name_to_level(self, name: str) -> Optional[int]:
        """Map priority names to numeric levels (higher = more urgent)."""
        name_lower = name.lower()
        level_map = {
            "urgent": 4,
            "highest": 4,
            "critical": 4,
            "high": 3,
            "medium": 2,
            "normal": 2,
            "low": 1,
            "lowest": 0,
            "none": 0,
        }
        return level_map.get(name_lower)

    def _extract_custom_fields(
        self,
        data_list: Optional[List[Dict[str, Any]]],
    ) -> List[CustomFieldRef]:
        """Extract custom fields from connector's custom field structure.

        Most connectors use a list of dicts like:
        [{"id": "...", "name": "Field Name", "type": "text", "value": "..."}]
        """
        if not data_list or not isinstance(data_list, list):
            return []

        fields = []
        for item in data_list:
            if not isinstance(item, dict):
                continue

            field_id = item.get("id") or item.get("key")
            field_name = item.get("name") or item.get("label")

            if not field_id or not field_name:
                continue

            value = item.get("value")
            display_value = item.get("displayValue") or item.get("display_value")

            # Format display value if not provided
            if display_value is None and value is not None:
                if isinstance(value, dict):
                    display_value = value.get("name") or str(value)
                elif isinstance(value, list):
                    display_value = ", ".join(
                        str(v.get("name", v)) if isinstance(v, dict) else str(v)
                        for v in value
                    )
                else:
                    display_value = str(value)

            # Skip empty values
            if value is None and not display_value:
                continue

            fields.append(
                CustomFieldRef(
                    id=str(field_id),
                    name=field_name,
                    field_type=item.get("type", "unknown"),
                    value=value,
                    display_value=display_value,
                    properties={},
                )
            )

        return fields
