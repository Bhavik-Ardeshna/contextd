"""Todoist entity schemas.

Based on the Todoist REST API reference, we define entity schemas for
Todoist objects, Projects, Sections, Tasks, and Comments.
"""

from datetime import datetime
from typing import Any, List, Optional

from pydantic import computed_field

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._contextd_field import ContextDField


class TodoistProjectEntity(BaseEntity):
    """Schema for Todoist project entities.

    Reference:
        https://developer.todoist.com/rest/v2/#projects
    """

    project_id: str = ContextDField(..., description="Todoist project ID.", is_entity_id=True)
    project_name: str = ContextDField(
        ..., description="Display name of the project.", embeddable=True, is_name=True
    )
    created_time: datetime = ContextDField(
        ..., description="When the project snapshot was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="When the project snapshot was updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="URL to open the project in Todoist.",
        embeddable=False,
        unhashable=True,
    )

    # API fields
    color: Optional[str] = ContextDField(
        None, description="Color of the project (e.g., 'grey', 'blue')", embeddable=False
    )
    comment_count: int = ContextDField(
        0, description="Number of comments in the project", embeddable=False
    )
    order: int = ContextDField(0, description="Project order in the project list", embeddable=False)
    is_shared: bool = ContextDField(
        False, description="Whether the project is shared with others", embeddable=False
    )
    is_favorite: bool = ContextDField(
        False, description="Whether the project is marked as a favorite", embeddable=False
    )
    is_inbox_project: bool = ContextDField(
        False, description="Whether this is the Inbox project", embeddable=False
    )
    is_team_inbox: bool = ContextDField(
        False, description="Whether this is the team Inbox project", embeddable=False
    )
    view_style: Optional[str] = ContextDField(
        None, description="Project view style ('list' or 'board')", embeddable=False
    )
    url: Optional[str] = ContextDField(
        None, description="URL to access the project", embeddable=False, unhashable=True
    )
    parent_id: Optional[str] = ContextDField(
        None, description="ID of the parent project if nested", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Return the Todoist project URL."""
        return self.web_url_value or self.url or ""


class TodoistSectionEntity(BaseEntity):
    """Schema for Todoist section entities.

    Reference:
        https://developer.todoist.com/rest/v2/#sections
    """

    section_id: str = ContextDField(..., description="Todoist section ID.", is_entity_id=True)
    section_name: str = ContextDField(
        ..., description="Display name of the section.", embeddable=True, is_name=True
    )
    project_id: str = ContextDField(
        ..., description="ID of the project this section belongs to", embeddable=False
    )
    order: int = ContextDField(0, description="Section order in the project", embeddable=False)


class TodoistTaskEntity(BaseEntity):
    """Schema for Todoist task entities.

    Reference:
        https://developer.todoist.com/rest/v2/#tasks
    """

    task_id: str = ContextDField(..., description="Todoist task ID.", is_entity_id=True)
    content: str = ContextDField(
        ..., description="The task content/title", embeddable=True, is_name=True
    )
    created_time: datetime = ContextDField(
        ..., description="When the task was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="Last update timestamp for the task.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="URL to open the task in Todoist.",
        embeddable=False,
        unhashable=True,
    )

    # API fields
    description: Optional[str] = ContextDField(
        None, description="Optional detailed description of the task", embeddable=True
    )
    comment_count: int = ContextDField(
        0, description="Number of comments on the task", embeddable=False
    )
    is_completed: bool = ContextDField(
        False, description="Whether the task is completed", embeddable=True
    )
    labels: List[str] = ContextDField(
        default_factory=list,
        description="List of label names attached to the task",
        embeddable=True,
    )
    order: int = ContextDField(
        0, description="Task order in the project or section", embeddable=False
    )
    priority: int = ContextDField(
        1, description="Task priority (1-4, 4 is highest)", ge=1, le=4, embeddable=True
    )
    project_id: Optional[str] = ContextDField(
        None, description="ID of the project this task belongs to", embeddable=False
    )
    section_id: Optional[str] = ContextDField(
        None, description="ID of the section this task belongs to", embeddable=False
    )
    parent_id: Optional[str] = ContextDField(
        None, description="ID of the parent task if subtask", embeddable=False
    )
    creator_id: Optional[str] = ContextDField(
        None, description="ID of the user who created the task", embeddable=False
    )
    assignee_id: Optional[str] = ContextDField(
        None, description="ID of the user assigned to the task", embeddable=False
    )
    assigner_id: Optional[str] = ContextDField(
        None, description="ID of the user who assigned the task", embeddable=False
    )
    due_date: Optional[str] = ContextDField(
        None, description="Due date in YYYY-MM-DD format", embeddable=True
    )
    due_datetime: Optional[Any] = ContextDField(
        None, description="Due date and time", embeddable=True
    )
    due_string: Optional[str] = ContextDField(
        None, description="Original due date string (e.g., 'tomorrow')", embeddable=True
    )
    due_is_recurring: bool = ContextDField(
        False, description="Whether the task is recurring", embeddable=False
    )
    due_timezone: Optional[str] = ContextDField(
        None, description="Timezone for the due date", embeddable=False
    )
    deadline_date: Optional[str] = ContextDField(
        None, description="Deadline date in YYYY-MM-DD format", embeddable=False
    )
    duration_amount: Optional[int] = ContextDField(
        None, description="Duration amount", embeddable=False
    )
    duration_unit: Optional[str] = ContextDField(
        None, description="Duration unit ('minute' or 'day')", embeddable=False
    )
    url: Optional[str] = ContextDField(
        None, description="URL to access the task", embeddable=False, unhashable=True
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Return the Todoist task URL."""
        return self.web_url_value or self.url or ""


class TodoistCommentEntity(BaseEntity):
    """Schema for Todoist comment entities.

    Reference:
        https://developer.todoist.com/rest/v2/#comments
    """

    comment_id: str = ContextDField(..., description="Todoist comment ID.", is_entity_id=True)
    task_id: str = ContextDField(
        ..., description="ID of the task this comment belongs to", embeddable=False
    )
    content: str = ContextDField(
        ..., description="The comment content", embeddable=True, is_name=True
    )
    posted_at: datetime = ContextDField(
        ..., description="When the comment was posted", is_created_at=True
    )
