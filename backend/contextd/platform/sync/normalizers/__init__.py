"""Entity normalizers for canonical data model transformation.

This package provides normalizers that transform connector-specific entities
into the canonical NormalizedEntity format for consistent pipeline processing.

Each connector gets a specific normalizer that knows how to:
- Extract nested people data (assignees, owners, members)
- Extract tags and labels
- Extract relationships to other entities
- Normalize status and priority fields
- Handle custom fields

Usage:
    from contextd.platform.sync.normalizers import get_normalizer_for_entity

    normalizer = get_normalizer_for_entity(entity)
    normalized = normalizer.normalize(entity)
"""

from contextd.platform.sync.normalizers._base import (
    BaseEntityNormalizer,
    DefaultEntityNormalizer,
    NormalizerRegistry,
    get_normalizer_for_entity,
    register_normalizer,
)

# Import connector-specific normalizers to register them
from contextd.platform.sync.normalizers.asana import AsanaNormalizer
from contextd.platform.sync.normalizers.clickup import ClickUpNormalizer
from contextd.platform.sync.normalizers.database import DatabaseEntityNormalizer
from contextd.platform.sync.normalizers.gmail import GmailNormalizer
from contextd.platform.sync.normalizers.google_calendar import GoogleCalendarNormalizer
from contextd.platform.sync.normalizers.notion import NotionNormalizer
from contextd.platform.sync.normalizers.salesforce import SalesforceNormalizer

# PostgreSQL uses same pipeline as Asana: graph + LLM; reuse database normalizer
NormalizerRegistry.register(r".*TableEntity$", DatabaseEntityNormalizer, source_type="postgresql")
NormalizerRegistry.register(r".*TableEntity$", DatabaseEntityNormalizer, source_type="clickhouse")

__all__ = [
    "BaseEntityNormalizer",
    "DefaultEntityNormalizer",
    "NormalizerRegistry",
    "get_normalizer_for_entity",
    "register_normalizer",
    # Connector-specific normalizers
    "AsanaNormalizer",
    "ClickUpNormalizer",
    "GmailNormalizer",
    "GoogleCalendarNormalizer",
    "NotionNormalizer",
    "SalesforceNormalizer",
]
