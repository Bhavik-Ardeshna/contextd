"""Entity action types, resolver, and dispatcher.

Entity-specific action pipeline for sync operations.
"""

from contextd.platform.sync.actions.entity.builder import EntityDispatcherBuilder
from contextd.platform.sync.actions.entity.dispatcher import EntityActionDispatcher
from contextd.platform.sync.actions.entity.resolver import EntityActionResolver
from contextd.platform.sync.actions.entity.types import (
    EntityActionBatch,
    EntityDeleteAction,
    EntityInsertAction,
    EntityKeepAction,
    EntityUpdateAction,
)

__all__ = [
    # Types
    "EntityActionBatch",
    "EntityDeleteAction",
    "EntityInsertAction",
    "EntityKeepAction",
    "EntityUpdateAction",
    # Resolver and Dispatcher
    "EntityActionResolver",
    "EntityActionDispatcher",
    "EntityDispatcherBuilder",
]
