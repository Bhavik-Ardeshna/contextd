"""ClickUp entity normalizer.

Transforms ClickUp-specific entity structures into the canonical
NormalizedEntity format, extracting:
- People from assignees, user, assigned_by fields
- Tags from tags array
- Status and priority configurations
- Custom fields
- Parent/child relationships
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


@register_normalizer(r"ClickUp.*Entity", source_type="clickup")
class ClickUpNormalizer(BaseEntityNormalizer):
    """Normalizer for ClickUp entities.

    Handles extraction of nested data from ClickUp's JSON structures:
    - assignees: List of user dicts with id, username, email, color, etc.
    - user: Single user dict (for comments, file uploads)
    - tags: List of tag dicts with name, tag_fg, tag_bg
    - status: Dict with status, color, type, orderindex
    - priority: Dict with id, priority, color, orderindex
    - custom_fields: List of custom field values
    """

    source_type = "clickup"

    def normalize(self, entity: BaseEntity) -> NormalizedEntity:
        """Transform ClickUp entity to NormalizedEntity.

        Args:
            entity: ClickUp entity instance

        Returns:
            NormalizedEntity with extracted data
        """
        entity_class_name = entity.__class__.__name__

        # Route to specific handler based on entity type
        if "Task" in entity_class_name:
            return self._normalize_task(entity)
        elif "Subtask" in entity_class_name:
            return self._normalize_subtask(entity)
        elif "Comment" in entity_class_name:
            return self._normalize_comment(entity)
        elif "File" in entity_class_name:
            return self._normalize_file(entity)
        elif "Workspace" in entity_class_name:
            return self._normalize_workspace(entity)
        elif "Space" in entity_class_name:
            return self._normalize_space(entity)
        elif "Folder" in entity_class_name:
            return self._normalize_folder(entity)
        elif "List" in entity_class_name:
            return self._normalize_list(entity)
        else:
            # Fall back to generic normalization
            return self._normalize_generic(entity)

    def _normalize_task(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize ClickUp task entity."""
        # Extract people using base class helper with custom extractor
        people = self.extract_people_with_roles(
            entity,
            {"assignees": PersonRole.ASSIGNEE},
            person_extractor=self._extract_clickup_person,
        )

        # Extract tags
        tags = self._extract_clickup_tags(getattr(entity, "tags", []) or [])

        # Extract status and priority
        status = self._extract_clickup_status(getattr(entity, "status", None))
        priority = self._extract_clickup_priority(getattr(entity, "priority", None))

        # Extract custom fields
        custom_fields = self._extract_clickup_custom_fields(getattr(entity, "custom_fields", []) or [])

        # Build relations using base class helper
        relations: List[RelationRef] = []
        self.add_relation_if_exists(relations, entity, "list_id", "ClickUpListEntity", RelationType.PART_OF)
        self.add_relation_if_exists(relations, entity, "parent", "ClickUpTaskEntity", RelationType.PARENT)

        return self.create_base_normalized_entity(
            entity,
            description=getattr(entity, "description", None),
            content=getattr(entity, "description", None),
            people=people,
            tags=tags,
            relations=relations,
            status=status,
            priority=priority,
            custom_fields=custom_fields,
            due_at_field="due_date",
            properties={
                "task_id": getattr(entity, "task_id", None),
                "list_id": getattr(entity, "list_id", None),
                "folder_id": getattr(entity, "folder_id", None),
                "space_id": getattr(entity, "space_id", None),
                "workspace_id": getattr(entity, "workspace_id", None),
                "time_estimate": getattr(entity, "time_estimate", None),
                "time_spent": getattr(entity, "time_spent", None),
                "start_date": getattr(entity, "start_date", None),
            },
        )

    def _normalize_subtask(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize ClickUp subtask entity."""
        people = self.extract_people_with_roles(
            entity,
            {"assignees": PersonRole.ASSIGNEE},
            person_extractor=self._extract_clickup_person,
        )

        status = self._extract_clickup_status(getattr(entity, "status", None))

        relations: List[RelationRef] = []
        self.add_relation_if_exists(relations, entity, "parent_task_id", "ClickUpTaskEntity", RelationType.PARENT)

        return self.create_base_normalized_entity(
            entity,
            description=getattr(entity, "description", None),
            content=getattr(entity, "description", None),
            people=people,
            relations=relations,
            status=status,
            due_at_field="due_date",
            properties={
                "subtask_id": getattr(entity, "subtask_id", None),
                "parent_task_id": getattr(entity, "parent_task_id", None),
                "nesting_level": getattr(entity, "nesting_level", None),
            },
        )

    def _normalize_comment(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize ClickUp comment entity."""
        # Extract people with their roles
        people = self.extract_people_with_roles(
            entity,
            {
                "user": PersonRole.AUTHOR,
                "assignee": PersonRole.ASSIGNEE,
            },
            person_extractor=self._extract_clickup_person,
        )

        # Handle assigned_by with custom property
        assigned_by_data = getattr(entity, "assigned_by", None)
        if assigned_by_data:
            assigner = self._extract_clickup_person(assigned_by_data, role=PersonRole.OTHER)
            if assigner:
                assigner.properties["assigned_by"] = True
                people.append(assigner)

        relations: List[RelationRef] = []
        self.add_relation_if_exists(relations, entity, "task_id", "ClickUpTaskEntity", RelationType.COMMENT_ON)

        return self.create_base_normalized_entity(
            entity,
            content=getattr(entity, "text_content", None),
            people=people,
            relations=relations,
            updated_at_field="created_at",  # Comments don't have updated_at
            properties={
                "comment_id": getattr(entity, "comment_id", None),
                "task_id": getattr(entity, "task_id", None),
                "resolved": getattr(entity, "resolved", False),
                "reactions": getattr(entity, "reactions", []),
            },
        )

    def _normalize_file(self, entity: BaseEntity) -> NormalizedFileEntity:
        """Normalize ClickUp file entity."""
        people = self.extract_people_with_roles(
            entity,
            {"user": PersonRole.CREATOR},
            person_extractor=self._extract_clickup_person,
        )

        relations: List[RelationRef] = []
        task_id = getattr(entity, "task_id", None)
        if task_id:
            relations.append(
                RelationRef(
                    entity_id=str(task_id),
                    entity_type="ClickUpTaskEntity",
                    relation_type=RelationType.ATTACHMENT_OF,
                    name=getattr(entity, "task_name", None),
                )
            )

        return self.create_base_file_entity(
            entity,
            file_url=getattr(entity, "url", ""),
            description=getattr(entity, "title", None),
            people=people,
            relations=relations,
            properties={
                "attachment_id": getattr(entity, "attachment_id", None),
                "task_id": task_id,
                "task_name": getattr(entity, "task_name", None),
                "version": getattr(entity, "version", None),
                "extension": getattr(entity, "extension", None),
                "workspace_id": getattr(entity, "workspace_id", None),
            },
            file_type_field="extension",
        )

    def _normalize_workspace(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize ClickUp workspace entity."""
        people = self.extract_people_with_roles(
            entity,
            {"members": PersonRole.MEMBER},
            person_extractor=self._extract_clickup_person,
        )

        return self.create_base_normalized_entity(
            entity,
            people=people,
            properties={
                "workspace_id": getattr(entity, "workspace_id", None),
                "color": getattr(entity, "color", None),
                "avatar": getattr(entity, "avatar", None),
            },
        )

    def _normalize_space(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize ClickUp space entity."""
        relations: List[RelationRef] = []
        self.add_relation_if_exists(relations, entity, "workspace_id", "ClickUpWorkspaceEntity", RelationType.PART_OF)

        status = self._extract_clickup_status(getattr(entity, "status", None))

        return self.create_base_normalized_entity(
            entity,
            relations=relations,
            status=status,
            properties={
                "space_id": getattr(entity, "space_id", None),
                "workspace_id": getattr(entity, "workspace_id", None),
                "private": getattr(entity, "private", False),
                "multiple_assignees": getattr(entity, "multiple_assignees", False),
                "features": getattr(entity, "features", {}),
            },
        )

    def _normalize_folder(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize ClickUp folder entity."""
        relations: List[RelationRef] = []
        self.add_relation_if_exists(relations, entity, "space_id", "ClickUpSpaceEntity", RelationType.PART_OF)

        return self.create_base_normalized_entity(
            entity,
            relations=relations,
            properties={
                "folder_id": getattr(entity, "folder_id", None),
                "workspace_id": getattr(entity, "workspace_id", None),
                "space_id": getattr(entity, "space_id", None),
                "hidden": getattr(entity, "hidden", False),
                "task_count": getattr(entity, "task_count", None),
            },
        )

    def _normalize_list(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize ClickUp list entity."""
        relations: List[RelationRef] = []
        folder_id = getattr(entity, "folder_id", None)
        space_id = getattr(entity, "space_id", None)

        # Lists can be in folders or directly in spaces
        if folder_id:
            self.add_relation_if_exists(relations, entity, "folder_id", "ClickUpFolderEntity", RelationType.PART_OF, "folder_name")
        elif space_id:
            self.add_relation_if_exists(relations, entity, "space_id", "ClickUpSpaceEntity", RelationType.PART_OF, "space_name")

        status = self._extract_clickup_status(getattr(entity, "status", None))
        priority = self._extract_clickup_priority(getattr(entity, "priority", None))

        return self.create_base_normalized_entity(
            entity,
            description=getattr(entity, "content", None),
            content=getattr(entity, "content", None),
            relations=relations,
            status=status,
            priority=priority,
            due_at_field="due_date",
            properties={
                "list_id": getattr(entity, "list_id", None),
                "workspace_id": getattr(entity, "workspace_id", None),
                "space_id": space_id,
                "folder_id": folder_id,
                "folder_name": getattr(entity, "folder_name", None),
                "space_name": getattr(entity, "space_name", None),
                "task_count": getattr(entity, "task_count", None),
                "assignee": getattr(entity, "assignee", None),
            },
        )

    def _normalize_generic(self, entity: BaseEntity) -> NormalizedEntity:
        """Generic normalization for unknown ClickUp entity types."""
        return self.create_base_normalized_entity(entity)

    # -------------------------------------------------------------------------
    # ClickUp-specific extraction helpers
    # -------------------------------------------------------------------------

    def _extract_clickup_person(
        self,
        data: Optional[Dict[str, Any]],
        role: PersonRole = PersonRole.OTHER,
    ) -> Optional[PersonRef]:
        """Extract a person from ClickUp user structure.

        ClickUp user structure:
        {
            "id": 123456,
            "username": "johndoe",
            "email": "john@example.com",
            "color": "#536cfe",
            "initials": "JD",
            "profilePicture": "https://..."
        }
        """
        if not data or not isinstance(data, dict):
            return None

        # ClickUp uses numeric IDs
        user_id = data.get("id")
        if not user_id:
            return None

        return PersonRef(
            id=str(user_id),
            name=data.get("username"),
            email=data.get("email"),
            role=role,
            avatar_url=data.get("profilePicture") or data.get("profile_picture"),
            username=data.get("username"),
            properties={
                "color": data.get("color"),
                "initials": data.get("initials"),
            },
        )

    def _extract_clickup_tags(
        self,
        data_list: Optional[List[Dict[str, Any]]],
    ) -> List[TagRef]:
        """Extract tags from ClickUp tag list.

        ClickUp tag structure:
        {
            "name": "tag-name",
            "tag_fg": "#000000",
            "tag_bg": "#ffffff",
            "creator": 123456
        }
        """
        if not data_list or not isinstance(data_list, list):
            return []

        tags = []
        for item in data_list:
            if not isinstance(item, dict):
                continue

            name = item.get("name")
            if not name:
                continue

            tags.append(
                TagRef(
                    id=name,  # ClickUp tags don't have separate IDs
                    name=name,
                    color=item.get("tag_bg"),
                    tag_type="tag",
                    properties={
                        "tag_fg": item.get("tag_fg"),
                        "tag_bg": item.get("tag_bg"),
                        "creator": item.get("creator"),
                    },
                )
            )

        return tags

    def _extract_clickup_status(
        self,
        data: Optional[Dict[str, Any]],
    ) -> Optional[StatusRef]:
        """Extract status from ClickUp status structure.

        ClickUp status structure:
        {
            "status": "in progress",
            "color": "#d3d3d3",
            "type": "custom",
            "orderindex": 1
        }
        """
        if not data or not isinstance(data, dict):
            return None

        status_name = data.get("status")
        if not status_name:
            return None

        # Map ClickUp status types to categories
        status_type = data.get("type", "custom")
        category = None
        if status_type == "open":
            category = "todo"
        elif status_type == "custom":
            category = "in_progress"
        elif status_type == "closed":
            category = "done"

        return StatusRef(
            id=None,
            name=status_name,
            color=data.get("color"),
            category=category,
            properties={
                "type": status_type,
                "orderindex": data.get("orderindex"),
            },
        )

    def _extract_clickup_priority(
        self,
        data: Optional[Dict[str, Any]],
    ) -> Optional[PriorityRef]:
        """Extract priority from ClickUp priority structure.

        ClickUp priority structure:
        {
            "id": "1",
            "priority": "urgent",
            "color": "#f50000",
            "orderindex": "1"
        }
        """
        if not data or not isinstance(data, dict):
            return None

        priority_name = data.get("priority")
        if not priority_name:
            return None

        # Parse orderindex as level (lower = more urgent)
        level = None
        orderindex = data.get("orderindex")
        if orderindex is not None:
            try:
                level = int(orderindex)
            except (ValueError, TypeError):
                pass

        return PriorityRef(
            id=data.get("id"),
            name=priority_name,
            level=level,
            color=data.get("color"),
            properties={},
        )

    def _extract_clickup_custom_fields(
        self,
        data_list: Optional[List[Dict[str, Any]]],
    ) -> List[CustomFieldRef]:
        """Extract custom fields from ClickUp custom field list.

        ClickUp custom field structure:
        {
            "id": "abc123",
            "name": "Field Name",
            "type": "text",
            "value": "field value",
            "type_config": {...}
        }
        """
        if not data_list or not isinstance(data_list, list):
            return []

        fields = []
        for item in data_list:
            if not isinstance(item, dict):
                continue

            field_id = item.get("id")
            field_name = item.get("name")

            if not field_id or not field_name:
                continue

            value = item.get("value")
            display_value = None

            # Handle different value types
            if isinstance(value, dict):
                display_value = value.get("name") or str(value)
            elif isinstance(value, list):
                display_value = ", ".join(
                    str(v.get("name", v)) if isinstance(v, dict) else str(v)
                    for v in value
                )
            elif value is not None:
                display_value = str(value)

            fields.append(
                CustomFieldRef(
                    id=field_id,
                    name=field_name,
                    field_type=item.get("type", "unknown"),
                    value=value,
                    display_value=display_value,
                    properties={
                        "type_config": item.get("type_config"),
                        "required": item.get("required"),
                    },
                )
            )

        return fields
