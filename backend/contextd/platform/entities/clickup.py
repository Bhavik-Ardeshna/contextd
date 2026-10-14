"""ClickUp entity schemas.

Migration Note:
--------------
These entities are being migrated to use the new standardization layer.
The normalizers (platform/sync/normalizers/clickup.py) handle extraction
of nested data into canonical PersonRef, TagRef, etc. types.

Future versions will update field types to use structured references:
- assignees: List[Dict[str, Any]] -> List[PersonRef]
- tags: List[Dict[str, Any]] -> List[TagRef]

See platform/entities/_normalized.py for canonical schemas.
See platform/entities/_metadata.py for unified config classes.
"""

from typing import Any, Dict, List, Optional

from pydantic import computed_field

from contextd.platform.entities._base import BaseEntity, FileEntity
from contextd.platform.entities._contextd_field import ContextDField
from contextd.platform.entities._metadata import (
    EntityIndexConfig,
    EntityMetadata,
    FieldMetadata,
    GraphEdgeConfig,
    SearchConfig,
)


class ClickUpWorkspaceEntity(BaseEntity):
    """Schema for ClickUp workspace entities."""

    _entity_metadata: EntityMetadata = EntityMetadata(
        default_graph_node_type="ClickUpWorkspaceNode",
        create_entity_node=True,
        enable_llm_enrichment=False,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["name"],
        ),
    )

    workspace_id: str = ContextDField(..., description="Workspace ID", is_entity_id=True)
    name: str = ContextDField(..., description="Workspace name", is_name=True, embeddable=True)
    color: Optional[str] = ContextDField(None, description="Workspace color", embeddable=False)
    avatar: Optional[str] = ContextDField(
        None, description="Workspace avatar URL", embeddable=False, unhashable=True
    )
    members: List[Dict[str, Any]] = ContextDField(
        default_factory=list,
        description="List of workspace members",
        embeddable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        return f"https://app.clickup.com/{self.workspace_id}"


class ClickUpSpaceEntity(BaseEntity):
    """Schema for ClickUp space entities."""

    _entity_metadata: EntityMetadata = EntityMetadata(
        default_graph_node_type="ClickUpSpaceNode",
        create_entity_node=True,
        enable_llm_enrichment=False,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["name"],
        ),
    )

    space_id: str = ContextDField(..., description="Space ID", is_entity_id=True)
    name: str = ContextDField(..., description="Space name", is_name=True, embeddable=True)
    workspace_id: str = ContextDField(..., description="Parent workspace ID", embeddable=False)
    private: bool = ContextDField(
        False, description="Whether the space is private", embeddable=False
    )
    status: Dict[str, Any] = ContextDField(
        default_factory=dict, description="Space status configuration", embeddable=True
    )
    multiple_assignees: bool = ContextDField(
        False, description="Whether multiple assignees are allowed", embeddable=False
    )
    features: Dict[str, Any] = ContextDField(
        default_factory=dict, description="Space features configuration", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        return f"https://app.clickup.com/{self.workspace_id}/v/b/{self.space_id}"


class ClickUpFolderEntity(BaseEntity):
    """Schema for ClickUp folder entities."""

    _entity_metadata: EntityMetadata = EntityMetadata(
        default_graph_node_type="ClickUpFolderNode",
        create_entity_node=True,
        enable_llm_enrichment=False,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["name"],
        ),
    )

    folder_id: str = ContextDField(..., description="Folder ID", is_entity_id=True)
    name: str = ContextDField(..., description="Folder name", is_name=True, embeddable=True)
    workspace_id: str = ContextDField(..., description="Parent workspace ID", embeddable=False)
    space_id: str = ContextDField(..., description="Parent space ID", embeddable=False)
    hidden: bool = ContextDField(
        False, description="Whether the folder is hidden", embeddable=False
    )
    task_count: Optional[int] = ContextDField(
        None, description="Number of tasks in the folder", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        return f"https://app.clickup.com/{self.workspace_id}/v/f/{self.folder_id}"


class ClickUpListEntity(BaseEntity):
    """Schema for ClickUp list entities."""

    _entity_metadata: EntityMetadata = EntityMetadata(
        default_graph_node_type="ClickUpListNode",
        create_entity_node=True,
        enable_llm_enrichment=True,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["name", "content"],
        ),
    )

    list_id: str = ContextDField(..., description="List ID", is_entity_id=True)
    name: str = ContextDField(..., description="List name", is_name=True, embeddable=True)
    workspace_id: str = ContextDField(..., description="Parent workspace ID", embeddable=False)
    space_id: str = ContextDField(..., description="Parent space ID", embeddable=False)
    folder_id: Optional[str] = ContextDField(
        None, description="Parent folder ID (optional)", embeddable=False
    )
    content: Optional[str] = ContextDField(
        None, description="List content/description", embeddable=True
    )
    status: Optional[Dict[str, Any]] = ContextDField(
        None, description="List status configuration", embeddable=True
    )
    priority: Optional[Dict[str, Any]] = ContextDField(
        None, description="List priority configuration", embeddable=True
    )
    assignee: Optional[str] = ContextDField(
        None, description="List assignee username", embeddable=True
    )
    task_count: Optional[int] = ContextDField(
        None, description="Number of tasks in the list", embeddable=False
    )
    due_date: Optional[Any] = ContextDField(None, description="List due date", embeddable=False)
    start_date: Optional[Any] = ContextDField(None, description="List start date", embeddable=False)
    folder_name: Optional[str] = ContextDField(
        None, description="Parent folder name", embeddable=True
    )
    space_name: str = ContextDField(..., description="Parent space name", embeddable=True)

    @computed_field(return_type=str)
    def web_url(self) -> str:
        return f"https://app.clickup.com/{self.workspace_id}/v/li/{self.list_id}"


class ClickUpTaskEntity(BaseEntity):
    """Schema for ClickUp task entities.

    Unified Metadata Configuration:
    ------------------------------
    The `_entity_metadata` class attribute provides a unified configuration
    for graph construction, search/embedding, and LLM extraction.

    This is the recommended approach for new entities. Existing entities
    can continue using json_schema_extra for backward compatibility.

    Normalization:
    -------------
    The ClickUpNormalizer (platform/sync/normalizers/clickup.py) transforms
    this entity into NormalizedEntity format, extracting:
    - People from assignees list
    - Tags from tags list
    - Status and priority from dicts
    - Custom fields
    """

    # Unified metadata: graph + LLM + vector/fulltext (same as Asana/Postgres)
    _entity_metadata: EntityMetadata = EntityMetadata(
        default_graph_node_type="ClickUpTaskNode",
        create_entity_node=True,
        enable_llm_enrichment=True,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["name", "description"],
        ),
        fields={
            "name": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                is_name=True,
            ),
            "description": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.5),
            ),
            "assignees": FieldMetadata(
                search=SearchConfig(embeddable=True),
                graph=GraphEdgeConfig(
                    edge_type="ASSIGNED_TO",
                    to_node_type="PersonNode",
                    create_reverse_edge=True,
                    reverse_edge_type="ASSIGNED",
                    is_list=True,
                ),
            ),
            "tags": FieldMetadata(
                search=SearchConfig(embeddable=True),
                graph=GraphEdgeConfig(
                    edge_type="TAGGED_WITH",
                    to_node_type="TagNode",
                    create_reverse_edge=True,
                    reverse_edge_type="TAGS",
                    is_list=True,
                ),
            ),
            "status": FieldMetadata(
                search=SearchConfig(embeddable=True),
            ),
            "priority": FieldMetadata(
                search=SearchConfig(embeddable=True),
            ),
        },
    )

    task_id: str = ContextDField(..., description="Task ID", is_entity_id=True)
    name: str = ContextDField(..., description="Task name", is_name=True, embeddable=True)
    created_at: Optional[Any] = ContextDField(
        None, description="Task creation timestamp", is_created_at=True
    )
    updated_at: Optional[Any] = ContextDField(
        None, description="Task update timestamp", is_updated_at=True
    )
    status: Dict[str, Any] = ContextDField(
        default_factory=dict, description="Task status configuration", embeddable=True
    )
    priority: Optional[Dict[str, Any]] = ContextDField(
        None, description="Task priority configuration", embeddable=True
    )
    assignees: List[Dict[str, Any]] = ContextDField(
        default_factory=list,
        description="List of task assignees",
        embeddable=True,
    )
    tags: List[Dict[str, Any]] = ContextDField(
        default_factory=list, description="List of task tags", embeddable=True
    )
    due_date: Optional[Any] = ContextDField(None, description="Task due date", embeddable=True)
    start_date: Optional[Any] = ContextDField(None, description="Task start date", embeddable=True)
    time_estimate: Optional[int] = ContextDField(
        None, description="Estimated time in milliseconds", embeddable=False
    )
    time_spent: Optional[int] = ContextDField(
        None, description="Time spent in milliseconds", embeddable=False
    )
    custom_fields: List[Dict[str, Any]] = ContextDField(
        default_factory=list, description="List of custom fields", embeddable=True
    )
    list_id: str = ContextDField(..., description="Parent list ID", embeddable=False)
    folder_id: Optional[str] = ContextDField(None, description="Parent folder ID", embeddable=False)
    space_id: str = ContextDField(..., description="Parent space ID", embeddable=False)
    workspace_id: str = ContextDField(..., description="Parent workspace ID", embeddable=False)
    url: str = ContextDField(..., description="Task URL", embeddable=False, unhashable=True)
    description: Optional[str] = ContextDField(
        None, description="Task description", embeddable=True
    )
    parent: Optional[str] = ContextDField(
        None, description="Parent task ID if this is a subtask", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        return self.url


class ClickUpCommentEntity(BaseEntity):
    """Schema for ClickUp comment entities."""

    _entity_metadata: EntityMetadata = EntityMetadata(
        default_graph_node_type="ClickUpCommentNode",
        create_entity_node=True,
        enable_llm_enrichment=True,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["name", "text_content"],
        ),
    )

    comment_id: str = ContextDField(..., description="Comment ID", is_entity_id=True)
    name: str = ContextDField(..., description="Comment preview", is_name=True, embeddable=True)
    created_at: Optional[Any] = ContextDField(
        None, description="When the comment was created", is_created_at=True
    )
    task_id: str = ContextDField(..., description="Parent task ID", embeddable=False)
    user: Dict[str, Any] = ContextDField(
        ...,
        description="Comment author information",
        embeddable=True,
    )
    text_content: Optional[str] = ContextDField(
        None, description="Comment text content", embeddable=True
    )
    resolved: bool = ContextDField(
        False, description="Whether the comment is resolved", embeddable=False
    )
    assignee: Optional[Dict[str, Any]] = ContextDField(
        None,
        description="Comment assignee information",
        embeddable=True,
    )
    assigned_by: Optional[Dict[str, Any]] = ContextDField(
        None,
        description="User who assigned the comment",
        embeddable=True,
    )
    reactions: List[Dict[str, Any]] = ContextDField(
        default_factory=list, description="List of reactions to the comment", embeddable=True
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        return f"https://app.clickup.com/t/{self.task_id}"


class ClickUpSubtaskEntity(BaseEntity):
    """Schema for ClickUp subtask entities."""

    _entity_metadata: EntityMetadata = EntityMetadata(
        default_graph_node_type="ClickUpSubtaskNode",
        create_entity_node=True,
        enable_llm_enrichment=True,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["name", "description"],
        ),
    )

    subtask_id: str = ContextDField(..., description="Subtask ID", is_entity_id=True)
    name: str = ContextDField(..., description="Subtask name", is_name=True, embeddable=True)
    created_at: Optional[Any] = ContextDField(
        None, description="Subtask creation timestamp", is_created_at=True
    )
    updated_at: Optional[Any] = ContextDField(
        None, description="Subtask update timestamp", is_updated_at=True
    )
    parent_task_id: str = ContextDField(
        ..., description="Immediate parent task/subtask ID", embeddable=False
    )
    status: Dict[str, Any] = ContextDField(
        default_factory=dict, description="Subtask status configuration", embeddable=True
    )
    assignees: List[Dict[str, Any]] = ContextDField(
        default_factory=list,
        description="List of subtask assignees",
        embeddable=True,
    )
    due_date: Optional[Any] = ContextDField(None, description="Subtask due date", embeddable=True)
    description: Optional[str] = ContextDField(
        None, description="Subtask description", embeddable=True
    )
    nesting_level: Optional[int] = ContextDField(
        None,
        description="Nesting level (1 = direct subtask, 2 = nested subtask, etc.)",
        embeddable=False,
    )
    url: Optional[str] = ContextDField(
        None, description="Subtask URL", embeddable=False, unhashable=True
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        return self.url or f"https://app.clickup.com/t/{self.subtask_id}"


class ClickUpFileEntity(FileEntity):
    """Schema for ClickUp file attachments."""

    _entity_metadata: EntityMetadata = EntityMetadata(
        default_graph_node_type="ClickUpFileNode",
        create_entity_node=True,
        enable_llm_enrichment=False,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["name", "title"],
        ),
    )

    attachment_id: str = ContextDField(..., description="Attachment ID", is_entity_id=True)
    name: str = ContextDField(..., description="Attachment name", is_name=True, embeddable=True)
    task_id: str = ContextDField(
        ..., description="ID of the task this file is attached to", embeddable=False
    )
    task_name: str = ContextDField(
        ..., description="Name of the task this file is attached to", embeddable=True
    )
    version: Optional[int] = ContextDField(
        None, description="Version number of the attachment", embeddable=False
    )
    title: Optional[str] = ContextDField(
        None, description="Original title/name of the attachment", embeddable=True
    )
    extension: Optional[str] = ContextDField(None, description="File extension", embeddable=False)
    hidden: bool = ContextDField(
        False, description="Whether the attachment is hidden", embeddable=False
    )
    parent: Optional[str] = ContextDField(
        None, description="Parent attachment ID if applicable", embeddable=False
    )
    thumbnail_small: Optional[str] = ContextDField(
        None, description="URL for small thumbnail", embeddable=False, unhashable=True
    )
    thumbnail_medium: Optional[str] = ContextDField(
        None, description="URL for medium thumbnail", embeddable=False, unhashable=True
    )
    thumbnail_large: Optional[str] = ContextDField(
        None, description="URL for large thumbnail", embeddable=False, unhashable=True
    )
    is_folder: Optional[bool] = ContextDField(
        None, description="Whether this is a folder attachment", embeddable=False
    )
    total_comments: Optional[int] = ContextDField(
        None, description="Number of comments on this attachment", embeddable=False
    )
    url_w_query: Optional[str] = ContextDField(
        None, description="URL with query parameters", embeddable=False, unhashable=True
    )
    url_w_host: Optional[str] = ContextDField(
        None, description="URL with host parameters", embeddable=False, unhashable=True
    )
    email_data: Optional[Dict[str, Any]] = ContextDField(
        None, description="Email data if attachment is from email", embeddable=False
    )
    user: Optional[Dict[str, Any]] = ContextDField(
        None,
        description="User who uploaded the attachment",
        embeddable=True,
    )
    resolved: Optional[bool] = ContextDField(
        None, description="Whether the attachment is resolved", embeddable=False
    )
    resolved_comments: Optional[int] = ContextDField(
        None, description="Number of resolved comments", embeddable=False
    )
    source: Optional[int] = ContextDField(
        None, description="Source type of the attachment (numeric)", embeddable=False
    )
    attachment_type: Optional[int] = ContextDField(
        None, description="Type of the attachment (numeric)", embeddable=False
    )
    orientation: Optional[str] = ContextDField(
        None, description="Image orientation if applicable", embeddable=False
    )
    parent_id: Optional[str] = ContextDField(None, description="Parent task ID", embeddable=False)
    deleted: Optional[bool] = ContextDField(
        None, description="Whether the attachment is deleted", embeddable=False
    )
    workspace_id: Optional[str] = ContextDField(None, description="Workspace ID", embeddable=False)

    @computed_field(return_type=str)
    def web_url(self) -> str:
        return f"https://app.clickup.com/t/{self.task_id}"
