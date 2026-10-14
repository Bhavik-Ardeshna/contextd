"""Tracking context for sync operations."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from contextd.core.guard_rail_service import GuardRailService
    from contextd.platform.sync.pipeline.entity_tracker import EntityTracker
    from contextd.platform.sync.state.builder import SyncStateBuilder
    from contextd.platform.sync.state_publisher import SyncStatePublisher


@dataclass
class TrackingContext:
    """Progress tracking - only needed during active sync.

    Attributes:
        entity_tracker: Centralized entity state tracker
        state_publisher: Publishes progress to Redis pubsub
        state_builder: Builds comprehensive state snapshots
        guard_rail: Rate limiting service (optional)
    """

    entity_tracker: "EntityTracker"
    state_publisher: "SyncStatePublisher"
    state_builder: "SyncStateBuilder"
    guard_rail: Optional["GuardRailService"] = None
