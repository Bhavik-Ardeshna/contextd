"""State management for sync operations.

This package provides comprehensive state tracking and comparison for sync jobs:
- Field-level hash computation for granular change detection
- State snapshot building during sync execution
- State persistence to database
- State comparison for intelligent change detection (Phase 2)
"""

from contextd.platform.sync.state.builder import SyncStateBuilder
from contextd.platform.sync.state.field_hasher import FieldLevelHasher
from contextd.platform.sync.state.persistence import SyncStatePersistence, sync_state_persistence

__all__ = [
    "SyncStateBuilder",
    "FieldLevelHasher",
    "SyncStatePersistence",
    "sync_state_persistence",
]
