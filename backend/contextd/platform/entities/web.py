"""Web entity definitions."""

from typing import Any, Dict, Optional

from pydantic import Field

from contextd.platform.entities._base import FileEntity


class WebFileEntity(FileEntity):
    """File entity created from web content via web_fetcher transformer.

    This entity represents a file that was created by downloading and processing
    web content through the web_fetcher transformer. It contains the original
    web URL and metadata from the crawling process.
    """

    original_url: str = Field(..., description="Original URL that was crawled to create this file")
    crawl_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata from the web crawling process (Firecrawl response data)",
    )
    web_title: Optional[str] = Field(None, description="Title extracted from the web page")
    web_description: Optional[str] = Field(
        None, description="Description extracted from the web page"
    )
