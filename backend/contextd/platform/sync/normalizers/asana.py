"""Asana entity normalizer.

Transforms Asana-specific entity structures into the canonical
NormalizedEntity format, extracting:
- People from assignee, owner, members, followers, completed_by fields
- Tags from tags array
- Status from completed flag and approval_status
- Custom fields
- Dependencies and dependents as relations
"""

from typing import Any, Dict, List, Optional

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._normalized import (
    CustomFieldRef,
    NormalizedEntity,
    NormalizedFileEntity,
    PersonRef,
    PersonRole,
    RelationRef,
    RelationType,
    StatusRef,
    TagRef,
)
from contextd.platform.sync.normalizers._base import (
    BaseEntityNormalizer,
    register_normalizer,
)


@register_normalizer(r"Asana.*Entity", source_type="asana")
class AsanaNormalizer(BaseEntityNormalizer):
    """Normalizer for Asana entities.

    Handles extraction of nested data from Asana's JSON structures:
    - assignee: Single user dict with gid, name, email
    - owner: Single user dict (for projects)
    - members: List of user dicts (for projects)
    - followers: List of user dicts
    - completed_by: Single user dict (for completed tasks)
    - tags: List of tag dicts with gid, name, color
    - custom_fields: List of custom field values
    - dependencies/dependents: Task dependency relationships
    """

    source_type = "asana"

    def normalize(self, entity: BaseEntity) -> NormalizedEntity:
        """Transform Asana entity to NormalizedEntity.

        Args:
            entity: Asana entity instance

        Returns:
            NormalizedEntity with extracted data
        """
        entity_class_name = entity.__class__.__name__

        # Route to specific handler based on entity type
        if "Task" in entity_class_name:
            return self._normalize_task(entity)
        elif "Project" in entity_class_name:
            return self._normalize_project(entity)
        elif "Section" in entity_class_name:
            return self._normalize_section(entity)
        elif "Comment" in entity_class_name:
            return self._normalize_comment(entity)
        elif "File" in entity_class_name:
            return self._normalize_file(entity)
        elif "Workspace" in entity_class_name:
            return self._normalize_workspace(entity)
        else:
            return self._normalize_generic(entity)

    def _normalize_task(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Asana task entity."""
        # Extract people with roles using base helper
        people = self.extract_people_with_roles(
            entity,
            {
                "assignee": PersonRole.ASSIGNEE,
                "followers": PersonRole.FOLLOWER,
            },
            person_extractor=self._extract_asana_person,
        )

        # Handle completed_by with custom property
        completed_by_data = getattr(entity, "completed_by", None)
        if completed_by_data:
            completer = self._extract_asana_person(completed_by_data, role=PersonRole.OTHER)
            if completer:
                completer.properties["completed_by"] = True
                people.append(completer)

        # Extract tags, status, and custom fields
        tags = self._extract_asana_tags(getattr(entity, "tags", []) or [])
        status = self._extract_task_status(entity)
        custom_fields = self._extract_asana_custom_fields(getattr(entity, "custom_fields", []) or [])

        # Build relations
        relations: List[RelationRef] = []
        self.add_relation_if_exists(relations, entity, "project_gid", "AsanaProjectEntity", RelationType.PART_OF)
        self.add_relation_if_exists(relations, entity, "section_gid", "AsanaSectionEntity", RelationType.PART_OF)

        # Parent task relation
        parent_data = getattr(entity, "parent", None)
        if parent_data and isinstance(parent_data, dict) and parent_data.get("gid"):
            relations.append(
                RelationRef(
                    entity_id=parent_data["gid"],
                    entity_type="AsanaTaskEntity",
                    relation_type=RelationType.PARENT,
                    name=parent_data.get("name"),
                )
            )

        # Dependencies and dependents
        self._add_dependency_relations(relations, entity)

        # Handle due_at from multiple possible fields
        due_at = self.parse_datetime(getattr(entity, "due_at", None))
        if not due_at:
            due_at = self.parse_datetime(getattr(entity, "due_on", None))

        return self.create_base_normalized_entity(
            entity,
            description=getattr(entity, "notes", None),
            content=getattr(entity, "html_notes", None) or getattr(entity, "notes", None),
            web_url=self.extract_web_url(entity, ["permalink_url"]),
            people=people,
            tags=tags,
            relations=relations,
            status=status,
            custom_fields=custom_fields,
            updated_at_field="modified_at",
            completed_at_field="completed_at",
            properties={
                "gid": getattr(entity, "gid", None),
                "project_gid": getattr(entity, "project_gid", None),
                "section_gid": getattr(entity, "section_gid", None),
                "completed": getattr(entity, "completed", False),
                "approval_status": getattr(entity, "approval_status", None),
                "resource_subtype": getattr(entity, "resource_subtype", None),
                "num_subtasks": getattr(entity, "num_subtasks", 0),
                "num_likes": getattr(entity, "num_likes", 0),
                "actual_time_minutes": getattr(entity, "actual_time_minutes", None),
            },
        )

    def _add_dependency_relations(self, relations: List[RelationRef], entity: BaseEntity) -> None:
        """Add dependency and dependent relations for tasks."""
        # Dependencies (tasks this task depends on)
        for dep in getattr(entity, "dependencies", []) or []:
            if isinstance(dep, dict) and dep.get("gid"):
                relations.append(
                    RelationRef(
                        entity_id=dep["gid"],
                        entity_type="AsanaTaskEntity",
                        relation_type=RelationType.DEPENDS_ON,
                        name=dep.get("name"),
                    )
                )

        # Dependents (tasks that depend on this one)
        for dep in getattr(entity, "dependents", []) or []:
            if isinstance(dep, dict) and dep.get("gid"):
                relations.append(
                    RelationRef(
                        entity_id=dep["gid"],
                        entity_type="AsanaTaskEntity",
                        relation_type=RelationType.BLOCKS,
                        name=dep.get("name"),
                    )
                )

    def _normalize_project(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Asana project entity."""
        people = self.extract_people_with_roles(
            entity,
            {
                "owner": PersonRole.OWNER,
                "members": PersonRole.MEMBER,
                "followers": PersonRole.FOLLOWER,
            },
            person_extractor=self._extract_asana_person,
        )

        status = self._extract_project_status(entity)
        custom_fields = self._extract_asana_custom_fields(getattr(entity, "custom_fields", []) or [])

        relations: List[RelationRef] = []
        self.add_relation_if_exists(relations, entity, "workspace_gid", "AsanaWorkspaceEntity", RelationType.PART_OF, "workspace_name")

        # Team relation
        team_data = getattr(entity, "team", None)
        if team_data and isinstance(team_data, dict) and team_data.get("gid"):
            relations.append(
                RelationRef(
                    entity_id=team_data["gid"],
                    entity_type="AsanaTeamEntity",
                    relation_type=RelationType.PART_OF,
                    name=team_data.get("name"),
                )
            )

        # Handle due_at from multiple possible fields
        due_at = self.parse_datetime(getattr(entity, "due_date", None))
        if not due_at:
            due_at = self.parse_datetime(getattr(entity, "due_on", None))

        return self.create_base_normalized_entity(
            entity,
            description=getattr(entity, "notes", None),
            content=getattr(entity, "html_notes", None) or getattr(entity, "notes", None),
            web_url=self.extract_web_url(entity, ["permalink_url"]),
            people=people,
            relations=relations,
            status=status,
            custom_fields=custom_fields,
            updated_at_field="modified_at",
            properties={
                "gid": getattr(entity, "gid", None),
                "workspace_gid": getattr(entity, "workspace_gid", None),
                "workspace_name": getattr(entity, "workspace_name", None),
                "archived": getattr(entity, "archived", False),
                "is_public": getattr(entity, "is_public", False),
                "color": getattr(entity, "color", None),
                "default_view": getattr(entity, "default_view", None),
            },
        )

    def _normalize_section(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Asana section entity."""
        relations: List[RelationRef] = []
        self.add_relation_if_exists(relations, entity, "project_gid", "AsanaProjectEntity", RelationType.PART_OF)

        return self.create_base_normalized_entity(
            entity,
            relations=relations,
            properties={
                "gid": getattr(entity, "gid", None),
                "project_gid": getattr(entity, "project_gid", None),
            },
        )

    def _normalize_comment(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Asana comment entity."""
        people = self.extract_people_with_roles(
            entity,
            {"author": PersonRole.AUTHOR},
            person_extractor=self._extract_asana_person,
        )

        relations: List[RelationRef] = []
        self.add_relation_if_exists(relations, entity, "task_gid", "AsanaTaskEntity", RelationType.COMMENT_ON)

        # Build name from author if entity doesn't have a name
        name = getattr(entity, "name", None)
        if not name:
            author_data = getattr(entity, "author", None)
            if author_data:
                author_name = author_data.get("name", "Unknown")
                name = f"Comment by {author_name}"

        return self.create_base_normalized_entity(
            entity,
            name=name or "Comment",
            content=getattr(entity, "text", None) or getattr(entity, "html_text", None),
            people=people,
            relations=relations,
            properties={
                "gid": getattr(entity, "gid", None),
                "task_gid": getattr(entity, "task_gid", None),
                "resource_subtype": getattr(entity, "resource_subtype", None),
                "is_pinned": getattr(entity, "is_pinned", False),
                "is_edited": getattr(entity, "is_edited", False),
                "num_likes": getattr(entity, "num_likes", 0),
                "type": getattr(entity, "type", "comment"),
            },
        )

    def _normalize_file(self, entity: BaseEntity) -> NormalizedFileEntity:
        """Normalize Asana file attachment entity."""
        relations: List[RelationRef] = []
        task_gid = getattr(entity, "task_gid", None)
        if task_gid:
            relations.append(
                RelationRef(
                    entity_id=str(task_gid),
                    entity_type="AsanaTaskEntity",
                    relation_type=RelationType.ATTACHMENT_OF,
                    name=getattr(entity, "task_name", None),
                )
            )

        return self.create_base_file_entity(
            entity,
            file_url=getattr(entity, "download_url", "") or getattr(entity, "view_url", ""),
            web_url=self.extract_web_url(entity, ["view_url"]),
            relations=relations,
            properties={
                "gid": getattr(entity, "gid", None),
                "task_gid": task_gid,
                "task_name": getattr(entity, "task_name", None),
                "project_gid": getattr(entity, "project_gid", None),
                "resource_type": getattr(entity, "resource_type", None),
                "host": getattr(entity, "host", None),
                "permanent": getattr(entity, "permanent", False),
            },
        )

    def _normalize_workspace(self, entity: BaseEntity) -> NormalizedEntity:
        """Normalize Asana workspace entity."""
        return self.create_base_normalized_entity(
            entity,
            web_url=self.extract_web_url(entity, ["permalink_url"]),
            properties={
                "gid": getattr(entity, "gid", None),
                "is_organization": getattr(entity, "is_organization", False),
                "email_domains": getattr(entity, "email_domains", []),
            },
        )

    def _normalize_generic(self, entity: BaseEntity) -> NormalizedEntity:
        """Generic normalization for unknown Asana entity types."""
        return self.create_base_normalized_entity(
            entity,
            updated_at_field="modified_at",
        )

    # -------------------------------------------------------------------------
    # Asana-specific extraction helpers
    # -------------------------------------------------------------------------

    def _extract_asana_person(
        self,
        data: Optional[Dict[str, Any]],
        role: PersonRole = PersonRole.OTHER,
    ) -> Optional[PersonRef]:
        """Extract a person from Asana user structure.

        Asana user structure:
        {
            "gid": "12345",
            "name": "John Doe",
            "email": "john@example.com",
            "resource_type": "user",
            "photo": {
                "image_128x128": "https://..."
            }
        }
        """
        if not data or not isinstance(data, dict):
            return None

        user_gid = data.get("gid")
        if not user_gid:
            return None

        # Extract avatar URL from photo object
        avatar_url = None
        photo = data.get("photo")
        if photo and isinstance(photo, dict):
            avatar_url = (
                photo.get("image_128x128")
                or photo.get("image_60x60")
                or photo.get("image_36x36")
            )

        return PersonRef(
            id=str(user_gid),
            name=data.get("name"),
            email=data.get("email"),
            role=role,
            avatar_url=avatar_url,
            username=None,  # Asana doesn't have usernames
            properties={
                "resource_type": data.get("resource_type"),
            },
        )

    def _extract_asana_tags(
        self,
        data_list: Optional[List[Dict[str, Any]]],
    ) -> List[TagRef]:
        """Extract tags from Asana tag list.

        Asana tag structure:
        {
            "gid": "12345",
            "name": "Tag Name",
            "color": "light-green",
            "resource_type": "tag"
        }
        """
        if not data_list or not isinstance(data_list, list):
            return []

        tags = []
        for item in data_list:
            if not isinstance(item, dict):
                continue

            gid = item.get("gid")
            name = item.get("name")
            if not name:
                continue

            tags.append(
                TagRef(
                    id=gid or name,
                    name=name,
                    color=item.get("color"),
                    tag_type="tag",
                    properties={
                        "resource_type": item.get("resource_type"),
                    },
                )
            )

        return tags

    def _extract_task_status(
        self,
        entity: BaseEntity,
    ) -> Optional[StatusRef]:
        """Extract status from Asana task entity.

        Asana uses:
        - completed (bool): Whether the task is complete
        - approval_status: pending, approved, rejected, changes_requested
        """
        completed = getattr(entity, "completed", False)
        approval_status = getattr(entity, "approval_status", None)

        if approval_status:
            # For approval tasks
            category = None
            if approval_status == "approved":
                category = "done"
            elif approval_status == "rejected":
                category = "done"
            elif approval_status in ("pending", "changes_requested"):
                category = "in_progress"

            return StatusRef(
                id=None,
                name=approval_status.replace("_", " ").title(),
                color=None,
                category=category,
                properties={
                    "approval_status": approval_status,
                },
            )

        # For regular tasks
        if completed:
            return StatusRef(
                id=None,
                name="Completed",
                color="green",
                category="done",
                properties={
                    "completed": True,
                },
            )
        else:
            return StatusRef(
                id=None,
                name="Open",
                color=None,
                category="todo",
                properties={
                    "completed": False,
                },
            )

    def _extract_project_status(
        self,
        entity: BaseEntity,
    ) -> Optional[StatusRef]:
        """Extract status from Asana project entity.

        Asana projects have current_status which includes:
        {
            "color": "green",
            "text": "Project is on track",
            "author": {...}
        }
        """
        current_status = getattr(entity, "current_status", None)
        if not current_status or not isinstance(current_status, dict):
            return None

        color = current_status.get("color")
        text = current_status.get("text")

        if not color and not text:
            return None

        # Map Asana colors to categories
        category = None
        if color == "green":
            category = "in_progress"
        elif color == "yellow":
            category = "in_progress"
        elif color == "red":
            category = "in_progress"
        elif color == "complete":
            category = "done"

        return StatusRef(
            id=None,
            name=text or color or "Unknown",
            color=color,
            category=category,
            properties={
                "status_update": current_status,
            },
        )

    def _extract_asana_custom_fields(
        self,
        data_list: Optional[List[Dict[str, Any]]],
    ) -> List[CustomFieldRef]:
        """Extract custom fields from Asana custom field list.

        Asana custom field structure:
        {
            "gid": "abc123",
            "name": "Field Name",
            "display_value": "displayed value",
            "type": "enum",
            "enum_value": {
                "gid": "123",
                "name": "Option Name",
                "color": "blue"
            }
        }
        """
        if not data_list or not isinstance(data_list, list):
            return []

        fields = []
        for item in data_list:
            if not isinstance(item, dict):
                continue

            field_gid = item.get("gid")
            field_name = item.get("name")

            if not field_gid or not field_name:
                continue

            # Get display value
            display_value = item.get("display_value")

            # Get the actual value based on type
            field_type = item.get("type", "text")
            value = None

            if field_type == "enum":
                enum_value = item.get("enum_value")
                if enum_value:
                    value = enum_value
                    if not display_value:
                        display_value = enum_value.get("name")
            elif field_type == "multi_enum":
                multi_value = item.get("multi_enum_values", [])
                value = multi_value
                if not display_value:
                    display_value = ", ".join(v.get("name", "") for v in multi_value if isinstance(v, dict))
            elif field_type == "number":
                value = item.get("number_value")
                if not display_value and value is not None:
                    display_value = str(value)
            elif field_type == "text":
                value = item.get("text_value")
                if not display_value and value:
                    display_value = value
            elif field_type == "date":
                date_value = item.get("date_value")
                if date_value:
                    value = date_value
                    if not display_value:
                        display_value = date_value.get("date", str(date_value))
            elif field_type == "people":
                people_value = item.get("people_value", [])
                value = people_value
                if not display_value:
                    display_value = ", ".join(p.get("name", "") for p in people_value if isinstance(p, dict))
            else:
                value = item.get("value")

            # Skip if no value
            if value is None and not display_value:
                continue

            fields.append(
                CustomFieldRef(
                    id=field_gid,
                    name=field_name,
                    field_type=field_type,
                    value=value,
                    display_value=display_value,
                    properties={
                        "resource_type": item.get("resource_type"),
                        "resource_subtype": item.get("resource_subtype"),
                        "enabled": item.get("enabled"),
                    },
                )
            )

        return fields
