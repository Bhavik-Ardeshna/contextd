"""Microsoft Word entity schemas.

Entity schemas for Microsoft Word documents based on Microsoft Graph API:
 - WordDocument (Word file with full metadata)

Reference:
  https://learn.microsoft.com/en-us/graph/api/resources/driveitem
  https://learn.microsoft.com/en-us/graph/api/driveitem-get-content
"""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import computed_field

from contextd.platform.entities._base import FileEntity
from contextd.platform.entities._contextd_field import ContextDField


class WordDocumentEntity(FileEntity):
    """Schema for a Microsoft Word document as a file entity.

    Represents Word documents (.docx, .doc) stored in OneDrive/SharePoint.
    Extends FileEntity to leverage ContextD's file processing pipeline which will:
    - Download the Word document
    - Convert it to markdown using document converters
    - Chunk the content for indexing

    Reference:
        https://learn.microsoft.com/en-us/graph/api/resources/driveitem
    """

    id: str = ContextDField(
        ...,
        description="Drive item ID for the Word document.",
        is_entity_id=True,
    )
    title: str = ContextDField(
        ...,
        description="Human-readable title for the document.",
        is_name=True,
        embeddable=True,
    )
    created_datetime: Optional[datetime] = ContextDField(
        None,
        description="When the document was created.",
        embeddable=False,
        is_created_at=True,
    )
    last_modified_datetime: Optional[datetime] = ContextDField(
        None,
        description="When the document was last modified.",
        embeddable=False,
        is_updated_at=True,
    )
    web_url_override: Optional[str] = ContextDField(
        None,
        description="URL to open the document in Word Online.",
        embeddable=False,
        unhashable=True,
    )
    content_download_url: Optional[str] = ContextDField(
        None,
        description="Direct download URL for the document content.",
        embeddable=False,
        unhashable=True,
    )
    created_by: Optional[Dict[str, Any]] = ContextDField(
        None, description="Identity of the user who created the document.", embeddable=True
    )
    last_modified_by: Optional[Dict[str, Any]] = ContextDField(
        None, description="Identity of the user who last modified the document.", embeddable=True
    )
    parent_reference: Optional[Dict[str, Any]] = ContextDField(
        None,
        description="Information about the parent folder/drive location.",
        embeddable=False,
    )
    drive_id: Optional[str] = ContextDField(
        None, description="ID of the drive containing this document.", embeddable=False
    )
    folder_path: Optional[str] = ContextDField(
        None, description="Full path to the parent folder.", embeddable=True
    )
    description: Optional[str] = ContextDField(
        None, description="Description of the document if available.", embeddable=True
    )
    shared: Optional[Dict[str, Any]] = ContextDField(
        None, description="Information about sharing status of the document.", embeddable=True
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """URL exposed to the UI to open the document."""
        if self.web_url_override:
            return self.web_url_override
        if self.url:
            return self.url
        return f"https://graph.microsoft.com/v1.0/me/drive/items/{self.id}"
