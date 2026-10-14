"""Stub entity schemas for testing purposes.

Provides deterministic, reproducible test entities with various content sizes
and types to simulate real-world data sources.
"""

from datetime import datetime
from typing import Optional

from pydantic import computed_field

from contextd.platform.entities._base import BaseEntity, CodeFileEntity, FileEntity
from contextd.platform.entities._contextd_field import ContextDField


class StubContainerEntity(BaseEntity):
    """Container entity for organizing stub entities.

    Acts as a parent breadcrumb for all generated stub entities,
    similar to how projects/workspaces work in real sources.
    """

    container_id: str = ContextDField(
        ...,
        description="Unique identifier for the stub container",
        is_entity_id=True,
    )
    container_name: str = ContextDField(
        ...,
        description="Name of the stub container",
        is_name=True,
        embeddable=True,
    )
    description: str = ContextDField(
        default="",
        description="Description of the stub container",
        embeddable=True,
    )
    created_at: Optional[datetime] = ContextDField(
        None,
        description="When the container was created",
        is_created_at=True,
    )
    seed: int = ContextDField(
        default=42,
        description="Random seed used for content generation",
        embeddable=False,
    )
    entity_count: int = ContextDField(
        default=10,
        description="Total number of entities in this container",
        embeddable=False,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Placeholder URL for the container."""
        return f"stub://container/{self.container_id}"


class SmallStubEntity(BaseEntity):
    """Small stub entity (~100-200 chars).

    Represents: Comments, notes, short messages.
    """

    stub_id: str = ContextDField(
        ...,
        description="Unique identifier for the stub entity",
        is_entity_id=True,
    )
    title: str = ContextDField(
        ...,
        description="Title of the stub entity",
        is_name=True,
        embeddable=True,
    )
    content: str = ContextDField(
        ...,
        description="Short content text (~100-200 chars)",
        embeddable=True,
    )
    author: str = ContextDField(
        default="",
        description="Author of the content",
        embeddable=True,
    )
    tags: list[str] = ContextDField(
        default_factory=list,
        description="Tags associated with this entity",
        embeddable=True,
    )
    created_at: Optional[datetime] = ContextDField(
        None,
        description="When the entity was created",
        is_created_at=True,
    )
    modified_at: Optional[datetime] = ContextDField(
        None,
        description="When the entity was last modified",
        is_updated_at=True,
    )
    sequence_number: int = ContextDField(
        default=0,
        description="Sequence number for ordering",
        embeddable=False,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Placeholder URL for the entity."""
        return f"stub://entity/small/{self.stub_id}"


class MediumStubEntity(BaseEntity):
    """Medium stub entity (~500-1000 chars).

    Represents: Tasks, pages, documents.
    """

    stub_id: str = ContextDField(
        ...,
        description="Unique identifier for the stub entity",
        is_entity_id=True,
    )
    title: str = ContextDField(
        ...,
        description="Title of the stub entity",
        is_name=True,
        embeddable=True,
    )
    description: str = ContextDField(
        ...,
        description="Detailed description (~500-1000 chars)",
        embeddable=True,
    )
    status: str = ContextDField(
        default="active",
        description="Status of the entity",
        embeddable=True,
    )
    priority: str = ContextDField(
        default="normal",
        description="Priority level",
        embeddable=True,
    )
    assignee: str = ContextDField(
        default="",
        description="Person assigned to this entity",
        embeddable=True,
    )
    tags: list[str] = ContextDField(
        default_factory=list,
        description="Tags associated with this entity",
        embeddable=True,
    )
    notes: str = ContextDField(
        default="",
        description="Additional notes",
        embeddable=True,
    )
    created_at: Optional[datetime] = ContextDField(
        None,
        description="When the entity was created",
        is_created_at=True,
    )
    modified_at: Optional[datetime] = ContextDField(
        None,
        description="When the entity was last modified",
        is_updated_at=True,
    )
    due_date: Optional[datetime] = ContextDField(
        None,
        description="Due date for the entity",
        embeddable=True,
    )
    sequence_number: int = ContextDField(
        default=0,
        description="Sequence number for ordering",
        embeddable=False,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Placeholder URL for the entity."""
        return f"stub://entity/medium/{self.stub_id}"


class LargeStubEntity(BaseEntity):
    """Large stub entity (~3000-5000 chars).

    Represents: Long articles, wikis, rich content.
    """

    stub_id: str = ContextDField(
        ...,
        description="Unique identifier for the stub entity",
        is_entity_id=True,
    )
    title: str = ContextDField(
        ...,
        description="Title of the stub entity",
        is_name=True,
        embeddable=True,
    )
    summary: str = ContextDField(
        ...,
        description="Brief summary of the content",
        embeddable=True,
    )
    content: str = ContextDField(
        ...,
        description="Full content text (~3000-5000 chars)",
        embeddable=True,
    )
    author: str = ContextDField(
        default="",
        description="Author of the content",
        embeddable=True,
    )
    category: str = ContextDField(
        default="general",
        description="Category of the content",
        embeddable=True,
    )
    tags: list[str] = ContextDField(
        default_factory=list,
        description="Tags associated with this entity",
        embeddable=True,
    )
    sections: list[str] = ContextDField(
        default_factory=list,
        description="Section headings in the content",
        embeddable=True,
    )
    references: list[str] = ContextDField(
        default_factory=list,
        description="References cited in the content",
        embeddable=True,
    )
    created_at: Optional[datetime] = ContextDField(
        None,
        description="When the entity was created",
        is_created_at=True,
    )
    modified_at: Optional[datetime] = ContextDField(
        None,
        description="When the entity was last modified",
        is_updated_at=True,
    )
    published_at: Optional[datetime] = ContextDField(
        None,
        description="When the content was published",
        embeddable=True,
    )
    word_count: int = ContextDField(
        default=0,
        description="Word count of the content",
        embeddable=False,
    )
    sequence_number: int = ContextDField(
        default=0,
        description="Sequence number for ordering",
        embeddable=False,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Placeholder URL for the entity."""
        return f"stub://entity/large/{self.stub_id}"


class SmallStubFileEntity(FileEntity):
    """Small stub file entity (~1-5 KB).

    Represents: Small text files, CSVs, config files.
    """

    stub_id: str = ContextDField(
        ...,
        description="Unique identifier for the stub file",
        is_entity_id=True,
    )
    file_name: str = ContextDField(
        ...,
        description="Name of the file",
        is_name=True,
        embeddable=True,
    )
    description: str = ContextDField(
        default="",
        description="Description of the file contents",
        embeddable=True,
    )
    file_extension: str = ContextDField(
        default=".txt",
        description="File extension",
        embeddable=True,
    )
    created_at: Optional[datetime] = ContextDField(
        None,
        description="When the file was created",
        is_created_at=True,
    )
    modified_at: Optional[datetime] = ContextDField(
        None,
        description="When the file was last modified",
        is_updated_at=True,
    )
    sequence_number: int = ContextDField(
        default=0,
        description="Sequence number for ordering",
        embeddable=False,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Placeholder URL for the file."""
        return f"stub://file/small/{self.stub_id}"


class LargeStubFileEntity(FileEntity):
    """Large stub file entity (~50-100 KB).

    Represents: PDFs, larger documents, reports.
    """

    stub_id: str = ContextDField(
        ...,
        description="Unique identifier for the stub file",
        is_entity_id=True,
    )
    file_name: str = ContextDField(
        ...,
        description="Name of the file",
        is_name=True,
        embeddable=True,
    )
    description: str = ContextDField(
        default="",
        description="Description of the file contents",
        embeddable=True,
    )
    file_extension: str = ContextDField(
        default=".txt",
        description="File extension",
        embeddable=True,
    )
    summary: str = ContextDField(
        default="",
        description="Summary of the document",
        embeddable=True,
    )
    author: str = ContextDField(
        default="",
        description="Author of the document",
        embeddable=True,
    )
    category: str = ContextDField(
        default="document",
        description="Category of the document",
        embeddable=True,
    )
    page_count: int = ContextDField(
        default=1,
        description="Estimated page count",
        embeddable=False,
    )
    created_at: Optional[datetime] = ContextDField(
        None,
        description="When the file was created",
        is_created_at=True,
    )
    modified_at: Optional[datetime] = ContextDField(
        None,
        description="When the file was last modified",
        is_updated_at=True,
    )
    sequence_number: int = ContextDField(
        default=0,
        description="Sequence number for ordering",
        embeddable=False,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Placeholder URL for the file."""
        return f"stub://file/large/{self.stub_id}"


class CodeStubFileEntity(CodeFileEntity):
    """Code stub file entity (~2-10 KB).

    Represents: Python, JavaScript, and other source code files.
    """

    stub_id: str = ContextDField(
        ...,
        description="Unique identifier for the stub code file",
        is_entity_id=True,
    )
    file_name: str = ContextDField(
        ...,
        description="Name of the code file",
        is_name=True,
        embeddable=True,
    )
    description: str = ContextDField(
        default="",
        description="Description of what the code does",
        embeddable=True,
    )
    functions: list[str] = ContextDField(
        default_factory=list,
        description="Function names defined in the file",
        embeddable=True,
    )
    classes: list[str] = ContextDField(
        default_factory=list,
        description="Class names defined in the file",
        embeddable=True,
    )
    imports: list[str] = ContextDField(
        default_factory=list,
        description="Import statements in the file",
        embeddable=True,
    )
    created_at: Optional[datetime] = ContextDField(
        None,
        description="When the file was created",
        is_created_at=True,
    )
    modified_at: Optional[datetime] = ContextDField(
        None,
        description="When the file was last modified",
        is_updated_at=True,
    )
    sequence_number: int = ContextDField(
        default=0,
        description="Sequence number for ordering",
        embeddable=False,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Placeholder URL for the code file."""
        return f"stub://file/code/{self.stub_id}"
