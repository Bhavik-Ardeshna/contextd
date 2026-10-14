"""Notion entity schemas."""

from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import computed_field

from contextd.core.datetime_utils import utc_now_naive
from contextd.platform.entities._base import BaseEntity, FileEntity
from contextd.platform.entities._contextd_field import ContextDField
from contextd.platform.entities._metadata import (
    EntityIndexConfig,
    EntityMetadata,
    FieldMetadata,
    LLMExtractionConfig,
    SearchConfig,
)


class NotionDatabaseEntity(BaseEntity):
    """Schema for a Notion database."""

    database_id: str = ContextDField(..., description="The ID of the database.", is_entity_id=True)
    title: str = ContextDField(
        ..., description="The title of the database", embeddable=True, is_name=True
    )
    created_time: Optional[datetime] = ContextDField(
        None, description="When the database was created.", is_created_at=True
    )
    created_by: Optional[Dict[str, Any]] = ContextDField(
        None,
        description="User who created this database",
        embeddable=True,
    )
    updated_time: Optional[datetime] = ContextDField(
        None, description="When the database was last edited.", is_updated_at=True
    )
    last_edited_by: Optional[Dict[str, Any]] = ContextDField(
        None,
        description="User who last edited this database",
        embeddable=True,
    )
    description: str = ContextDField(
        default="", description="The description of the database", embeddable=True
    )
    properties: Dict[str, Any] = ContextDField(
        default_factory=dict, description="Database properties schema", embeddable=False
    )
    properties_text: Optional[str] = ContextDField(
        default=None,
        description="Human-readable schema description",
        embeddable=True,
    )
    parent_id: str = ContextDField(
        ...,
        description="The ID of the parent",
        embeddable=False,
    )
    parent_type: str = ContextDField(
        ..., description="The type of the parent (workspace, page_id, etc.)", embeddable=False
    )
    icon: Optional[Dict[str, Any]] = ContextDField(
        None, description="The icon of the database", embeddable=False
    )
    cover: Optional[Dict[str, Any]] = ContextDField(
        None, description="The cover of the database", embeddable=False
    )
    archived: bool = ContextDField(
        default=False, description="Whether the database is archived", embeddable=False
    )
    is_inline: bool = ContextDField(
        default=False, description="Whether the database is inline", embeddable=False
    )
    url: str = ContextDField(
        ..., description="The URL of the database", embeddable=False, unhashable=True
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Browser URL for the database."""
        return self.url or ""

    def model_post_init(self, __context) -> None:
        """Post-init hook to generate properties_text from schema."""
        super().model_post_init(__context)

        # Generate human-readable schema text if not already set
        if self.properties and not self.properties_text:
            self.properties_text = self._generate_schema_text()

    def _generate_schema_text(self) -> str:
        """Generate human-readable text from database schema for embedding.

        Creates a clean representation of the database structure.
        """
        if not self.properties:
            return ""

        text_parts = []

        for prop_name, prop_info in self.properties.items():
            if isinstance(prop_info, dict):
                prop_type = prop_info.get("type", "unknown")

                # Build property description
                desc_parts = [f"{prop_name} ({prop_type})"]

                # Add options if available
                if "options" in prop_info and prop_info["options"]:
                    options_str = ", ".join(prop_info["options"][:5])  # Limit to first 5
                    if len(prop_info["options"]) > 5:
                        options_str += f" +{len(prop_info['options']) - 5} more"
                    desc_parts.append(f"options: {options_str}")

                # Add format for numbers
                if "format" in prop_info:
                    desc_parts.append(f"format: {prop_info['format']}")

                text_parts.append(" ".join(desc_parts))

        return " | ".join(text_parts) if text_parts else ""


class NotionPageEntity(BaseEntity):
    """Schema for a Notion page with aggregated content."""

    _entity_metadata: ClassVar[EntityMetadata] = EntityMetadata(
        default_graph_node_type="NotionPageNode",
        create_entity_node=True,
        enable_llm_enrichment=True,
        index=EntityIndexConfig(
            enabled=True,
            fulltext_enabled=True,
            priority_fields=["title", "content", "properties_text"],
        ),
        fields={
            "title": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=2.0),
                is_name=True,
            ),
            "content": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.5),
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
                    extraction_hint="""Analyze this Notion page and extract only these graph-worthy entity types:
- Person: a person important enough to track across pages and tools as their own reusable node
- Task: a concrete actionable item, follow-up, or piece of work worth tracking across tools
- Project: a named initiative, workstream, roadmap item, or program
- Decision: an explicit decision, approval, or committed direction
- Company: a company, customer, partner, vendor, or organization worth linking across documents and email
- Team: a named team, org unit, squad, or working group

Do not invent any other node types.
Do not create standalone time/date nodes. Dates should only appear as properties on richer nodes such as Task, Project, or Decision.
Only extract things that deserve a reusable node in the knowledge graph rather than remaining as plain text in the page.
For Person entities, include email when available.
If an extracted entity relates to a specific person, include that person's email in fields like assigned_to, owner, or related_to.
Person must be a real human—never a software product, integration bot, or service name standing in for a person; use Company or Product when the referent is an org or offering. Each extracted type must denote a real, substantive entity, not generic UI text.""",
                    confidence_threshold=0.65,
                ),
            ),
            "properties_text": FieldMetadata(
                search=SearchConfig(embeddable=True, boost=1.0),
            ),
        },
    )

    page_id: str = ContextDField(..., description="The ID of the page.", is_entity_id=True)
    parent_id: str = ContextDField(
        ...,
        description="The ID of the parent",
        embeddable=False,
    )
    parent_type: str = ContextDField(
        ...,
        description="The type of the parent (workspace, page_id, database_id, etc.)",
        embeddable=False,
    )
    title: str = ContextDField(
        ..., description="The title of the page", embeddable=True, is_name=True
    )
    created_time: Optional[datetime] = ContextDField(
        None, description="When the page was created.", is_created_at=True
    )
    created_by: Optional[Dict[str, Any]] = ContextDField(
        None,
        description="User who created this page",
        embeddable=True,
    )
    updated_time: Optional[datetime] = ContextDField(
        None, description="When the page was last edited.", is_updated_at=True
    )
    last_edited_by: Optional[Dict[str, Any]] = ContextDField(
        None,
        description="User who last edited this page",
        embeddable=True,
    )
    content: Optional[str] = ContextDField(
        default=None,
        description="Full aggregated content",
        embeddable=True,
    )
    properties: Dict[str, Any] = ContextDField(
        default_factory=dict, description="Formatted page properties for search", embeddable=False
    )
    properties_text: Optional[str] = ContextDField(
        default=None,
        description="Human-readable properties text",
        embeddable=True,
    )
    property_entities: List[Any] = ContextDField(
        default_factory=list, description="Structured property entities", embeddable=False
    )
    assignees: Optional[List[Dict[str, Any]]] = ContextDField(
        None,
        description="Assigned people (extracted from properties)",
        embeddable=True,
    )
    tags: Optional[List[str]] = ContextDField(
        None,
        description="Tags (extracted from multi_select properties)",
        embeddable=True,
    )
    files: List[Any] = ContextDField(
        default_factory=list, description="Files referenced in the page", embeddable=False
    )
    icon: Optional[Dict[str, Any]] = ContextDField(
        None, description="The icon of the page", embeddable=False
    )
    cover: Optional[Dict[str, Any]] = ContextDField(
        None, description="The cover of the page", embeddable=False
    )
    archived: bool = ContextDField(
        default=False, description="Whether the page is archived", embeddable=False
    )
    in_trash: bool = ContextDField(
        default=False, description="Whether the page is in trash", embeddable=False
    )
    url: str = ContextDField(
        ..., description="The URL of the page", embeddable=False, unhashable=True
    )
    content_blocks_count: int = ContextDField(
        default=0, description="Number of blocks processed", embeddable=False
    )
    max_depth: int = ContextDField(
        default=0, description="Maximum nesting depth of blocks", embeddable=False
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Browser URL for the page."""
        return self.url or ""

    # Lazy mechanics removed; eager-only entity

    def model_post_init(self, __context) -> None:
        """Post-init hook to extract assignees, tags, and generate properties_text."""
        super().model_post_init(__context)

        # Extract assignees from property_entities (people-type properties)
        if not self.assignees and self.property_entities:
            self.assignees = self._extract_assignees()

        # Extract tags from property_entities (multi_select properties)
        if not self.tags and self.property_entities:
            self.tags = self._extract_tags()

        # Generate human-readable properties text if not already set
        if self.properties and not self.properties_text:
            self.properties_text = self._generate_properties_text()

    def _extract_assignees(self) -> Optional[List[Dict[str, Any]]]:
        """Extract assignee information from property_entities.

        Looks for people-type properties (Assignee, Owner, etc.) and
        extracts the person details for graph relationship tracking.
        """
        assignees = []

        for prop_entity in self.property_entities:
            # Check if this is a people-type property
            if isinstance(prop_entity, dict) and prop_entity.get("property_type") == "people":
                value = prop_entity.get("value")
                if value and isinstance(value, list):
                    for person in value:
                        if isinstance(person, dict) and person.get("type") == "person":
                            # Extract key person info
                            assignees.append({
                                "id": person.get("id"),
                                "name": person.get("name", "Unknown"),
                                "email": person.get("person", {}).get("email"),
                                "property_name": prop_entity.get("property_name"),
                            })

        return assignees if assignees else None

    def _extract_tags(self) -> Optional[List[str]]:
        """Extract tags from property_entities.

        Looks for multi_select and select properties and extracts
        the tag values for graph relationship tracking.
        """
        tags = []

        for prop_entity in self.property_entities:
            if isinstance(prop_entity, dict):
                prop_type = prop_entity.get("property_type")

                if prop_type == "multi_select":
                    value = prop_entity.get("value")
                    if value and isinstance(value, list):
                        for tag in value:
                            if isinstance(tag, dict):
                                tag_name = tag.get("name")
                                if tag_name:
                                    tags.append(tag_name)

                elif prop_type == "select":
                    value = prop_entity.get("value")
                    if isinstance(value, dict):
                        tag_name = value.get("name")
                        if tag_name:
                            tags.append(tag_name)

        return tags if tags else None

    def _generate_properties_text(self) -> str:
        """Generate human-readable text from properties for embedding.

        Creates a clean, searchable representation of property values.
        """
        if not self.properties:
            return ""

        text_parts = []

        # Process properties in a logical order
        priority_keys = [
            "Product Name",
            "Name",
            "Title",
            "Status",
            "Priority",
            "Launch Status",
            "Owner",
            "Team",
            "Description",
        ]

        # First add priority properties
        for key in priority_keys:
            if key in self.properties:
                value = self.properties[key]
                if value and str(value).strip():
                    # Skip if it's the same as the page title
                    if key in ["Product Name", "Name", "Title"] and value == self.title:
                        continue
                    text_parts.append(f"{key}: {value}")

        # Then add remaining properties
        for key, value in self.properties.items():
            if key not in priority_keys and not key.endswith("_options"):
                if value and str(value).strip():
                    # Format the key nicely
                    formatted_key = key.replace("_", " ").title()
                    text_parts.append(f"{formatted_key}: {value}")

        return " | ".join(text_parts) if text_parts else ""


class NotionPropertyEntity(BaseEntity):
    """Schema for a Notion database page property."""

    # Base fields are inherited and set during entity creation:
    # - entity_id (property_id)
    # - breadcrumbs
    # - name (from property_name)
    # - created_at (None - properties don't have timestamps)
    # - updated_at (None - properties don't have timestamps)

    # API fields
    property_key: str = ContextDField(
        ...,
        description="Stable unique identifier for the property entity.",
        embeddable=False,
        is_entity_id=True,
    )
    property_id: str = ContextDField(..., description="The ID of the property", embeddable=False)
    property_name: str = ContextDField(
        ..., description="The name of the property", embeddable=True, is_name=True
    )
    property_type: str = ContextDField(..., description="The type of the property", embeddable=True)
    page_id: str = ContextDField(
        ...,
        description="The ID of the page this property belongs to",
        embeddable=False,
    )
    database_id: str = ContextDField(
        ...,
        description="The ID of the database this property belongs to",
        embeddable=False,
    )
    value: Optional[Any] = ContextDField(
        None,
        description="The raw value of the property",
        embeddable=True,
    )
    formatted_value: str = ContextDField(
        default="",
        description="The formatted/display value of the property",
        embeddable=True,
    )


class NotionFileEntity(FileEntity):
    """Schema for a Notion file.

    Reference:
        https://developers.notion.com/reference/file-object
    """

    # Base fields are inherited from BaseEntity:
    # - entity_id (file_id)
    # - breadcrumbs
    # - name
    # - created_at (None - Notion files don't have timestamps)
    # - updated_at (None - Notion files don't have timestamps)

    # File fields are inherited from FileEntity:
    # - url (download_url)
    # - size (None - not provided by Notion API in block content)
    # - file_type (e.g., "file", "external", "file_upload")
    # - mime_type
    # - local_path (set after download)

    # API fields (Notion-specific)
    file_id: str = ContextDField(
        ..., description="ID of the file in Notion", embeddable=False, is_entity_id=True
    )
    file_name: str = ContextDField(
        ..., description="Display name of the file", embeddable=True, is_name=True
    )
    expiry_time: Optional[datetime] = ContextDField(
        None, description="When the file URL expires (for Notion-hosted files)", embeddable=False
    )
    caption: str = ContextDField(default="", description="The caption of the file", embeddable=True)
    web_url_value: Optional[str] = ContextDField(
        None, description="Link to view/download the file.", embeddable=False, unhashable=True
    )

    def needs_refresh(self) -> bool:
        """Check if the file URL needs to be refreshed (for Notion-hosted files)."""
        if self.file_type == "file" and self.expiry_time:
            return utc_now_naive() >= self.expiry_time
        return False

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Browser URL for the file."""
        if self.web_url_value:
            return self.web_url_value
        return self.url
