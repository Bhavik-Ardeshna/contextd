"""Google Slides entity schemas.

Entity schemas for Google Slides based on Google Slides API and Google Drive API.
Google Slides presentations are exported as PDF/PPTX and represented as FileEntity objects
that get processed through ContextD's file processing pipeline.

References:
    https://developers.google.com/slides/api/reference/rest
    https://developers.google.com/drive/api/v3/reference/files
    https://developers.google.com/drive/api/guides/manage-downloads
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import computed_field

from contextd.platform.entities._base import BaseEntity, FileEntity
from contextd.platform.entities._contextd_field import ContextDField


class GoogleSlidesPresentationEntity(FileEntity):
    """Schema for a Google Slides presentation.

    Represents a Google Slides presentation retrieved via the Google Drive API.
    The presentation content is exported as PDF and processed through
    ContextD's file processing pipeline to create searchable chunks.

    Reference:
        https://developers.google.com/slides/api/reference/rest/v1/presentations
        https://developers.google.com/drive/api/v3/reference/files
    """

    presentation_id: str = ContextDField(
        ...,
        description="Unique Google Drive file ID of the presentation.",
        is_entity_id=True,
    )
    title: str = ContextDField(
        ...,
        description="Display title of the presentation (without file extension).",
        embeddable=True,
        is_name=True,
    )
    created_time: datetime = ContextDField(
        ...,
        description="When the presentation was created.",
        is_created_at=True,
    )
    modified_time: datetime = ContextDField(
        ...,
        description="When the presentation was last modified.",
        is_updated_at=True,
    )
    description: Optional[str] = ContextDField(
        None, description="Optional description of the presentation.", embeddable=True
    )
    starred: bool = ContextDField(
        False, description="Whether the user has starred this presentation.", embeddable=True
    )
    trashed: bool = ContextDField(
        False, description="Whether the presentation is in the trash.", embeddable=False
    )
    explicitly_trashed: bool = ContextDField(
        False,
        description="Whether the presentation was explicitly trashed by the user.",
        embeddable=False,
    )
    shared: bool = ContextDField(
        False, description="Whether the presentation is shared with others.", embeddable=True
    )
    shared_with_me_time: Optional[datetime] = ContextDField(
        None, description="Time when this presentation was shared with the user.", embeddable=False
    )
    sharing_user: Optional[Dict[str, Any]] = ContextDField(
        None, description="User who shared this presentation.", embeddable=True
    )
    owners: List[Dict[str, Any]] = ContextDField(
        default_factory=list, description="Owners of the presentation.", embeddable=True
    )
    permissions: Optional[List[Dict[str, Any]]] = ContextDField(
        None, description="Permissions for this presentation.", embeddable=False
    )
    parents: List[str] = ContextDField(
        default_factory=list,
        description="IDs of parent folders containing this presentation.",
        embeddable=False,
    )
    web_view_link: Optional[str] = ContextDField(
        None,
        description="Link to open the presentation in Google Slides editor.",
        embeddable=False,
        unhashable=True,
    )
    icon_link: Optional[str] = ContextDField(
        None, description="Link to the presentation's icon.", embeddable=False
    )
    modified_by_me_time: Optional[datetime] = ContextDField(
        None, description="Last time the user modified the presentation.", embeddable=False
    )
    viewed_by_me_time: Optional[datetime] = ContextDField(
        None, description="Last time the user viewed the presentation.", embeddable=False
    )
    version: Optional[int] = ContextDField(
        None, description="Version number of the presentation.", embeddable=True
    )
    slide_count: Optional[int] = ContextDField(
        None, description="Number of slides in the presentation.", embeddable=True
    )
    locale: Optional[str] = ContextDField(
        None, description="The locale of the presentation.", embeddable=True
    )
    revision_id: Optional[str] = ContextDField(
        None, description="The revision ID of the presentation.", embeddable=False
    )
    export_mime_type: Optional[str] = ContextDField(
        default="application/pdf",
        description="MIME type used for exporting the presentation content (PDF).",
        embeddable=False,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Link to open the presentation in Google Slides."""
        if self.web_view_link:
            return self.web_view_link
        return f"https://docs.google.com/presentation/d/{self.presentation_id}/edit"


class GoogleSlidesSlideEntity(BaseEntity):
    """Schema for a Google Slides slide.

    Represents an individual slide within a Google Slides presentation.
    This entity captures slide-specific metadata and content for detailed
    indexing and search capabilities.

    Reference:
        https://developers.google.com/slides/api/reference/rest/v1/presentations.pages
    """

    # Base fields are inherited from BaseEntity:
    # - entity_id (the slide ID)
    # - breadcrumbs (presentation breadcrumb)
    # - name (slide title or "Slide {number}")
    # - created_at (from created_time if available)
    # - updated_at (from modified_time if available)

    # API fields
    slide_id: str = ContextDField(
        ...,
        description="Unique ID of the slide within the presentation.",
        embeddable=False,
        is_entity_id=True,
    )
    presentation_id: str = ContextDField(
        ..., description="ID of the parent presentation containing this slide.", embeddable=False
    )
    slide_number: int = ContextDField(
        ..., description="The zero-based index of the slide in the presentation.", embeddable=True
    )
    title: str = ContextDField(
        ...,
        description="Title of the slide (or generated fallback).",
        embeddable=True,
        is_name=True,
    )
    notes: Optional[str] = ContextDField(
        None, description="Speaker notes for the slide.", embeddable=True
    )
    layout_type: Optional[str] = ContextDField(
        None, description="The type of slide layout.", embeddable=False
    )
    master_properties: Optional[Dict[str, Any]] = ContextDField(
        None, description="Properties of the slide master.", embeddable=False
    )
    elements: List[Dict[str, Any]] = ContextDField(
        default_factory=list, description="List of elements on the slide.", embeddable=False
    )
    text_content: Optional[str] = ContextDField(
        None, description="Extracted text content from all elements on the slide.", embeddable=True
    )
    background: Optional[Dict[str, Any]] = ContextDField(
        None, description="Background properties of the slide.", embeddable=False
    )
    color_scheme: Optional[Dict[str, Any]] = ContextDField(
        None, description="Color scheme of the slide.", embeddable=False
    )
    created_time: Optional[datetime] = ContextDField(
        None, description="When the slide was created.", embeddable=False
    )
    modified_time: Optional[datetime] = ContextDField(
        None, description="When the slide was last modified.", embeddable=False
    )
    presentation_title: Optional[str] = ContextDField(
        None, description="Title of the parent presentation.", embeddable=True
    )
    presentation_url: Optional[str] = ContextDField(
        None,
        description="URL to view the parent presentation.",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """URL to view this slide within its presentation."""
        if self.presentation_url:
            return self.presentation_url
        return (
            f"https://docs.google.com/presentation/d/{self.presentation_id}/edit"
            f"#slide=id.{self.slide_id}"
        )
