"""Pipeline components for entity processing.

This module contains the event-driven entity pipeline architecture:

Core Components:
- EntityTracker: Central entity state tracking (dedup + counts + pubsub)

Processing Helpers:
- HashComputer: Computes content hashes
- TextualRepresentationBuilder: Builds textual representations
- CleanupService: Handles orphan and temp file cleanup
"""

# Core components
# Processing helpers
from contextd.platform.sync.pipeline.cleanup_service import cleanup_service
from contextd.platform.sync.pipeline.entity_tracker import EntityTracker
from contextd.platform.sync.pipeline.hash_computer import hash_computer
from contextd.platform.sync.pipeline.text_builder import (
    TextualRepresentationBuilder,
    text_builder,
)

__all__ = [
    # Core components
    "EntityTracker",
    # Processing helpers
    "cleanup_service",
    "hash_computer",
    "TextualRepresentationBuilder",
    "text_builder",
]
