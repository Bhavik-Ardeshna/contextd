"""Handlers module for sync pipeline.

Contains handlers that execute resolved actions.

Generic Protocol:
    ActionHandler[T, B] - parameterized by payload type T and batch type B

Type Aliases:
    EntityActionHandler = ActionHandler[BaseEntity, EntityActionBatch]

Entity Handlers:
- ArfHandler: Raw entity storage for audit/replay (CRF = ContextD Raw Format)
- EntityPostgresHandler: Entity metadata persistence (runs last)
- IndexHandler: Entity-level indexing for semantic and fulltext search

Architecture:
    All handlers implement ActionHandler[T, B] with their specific types.
    Entity handlers use T=BaseEntity, B=EntityActionBatch.
    The dispatchers call handlers concurrently for their respective sync types.
"""

# Handlers
from .arf import ArfHandler
from .entity_postgres import EntityPostgresHandler
from .index_handler import IndexHandler, create_index_handler

# Protocol and type aliases
from .protocol import EntityActionHandler

__all__ = [
    # Protocol and type aliases
    "EntityActionHandler",
    # Entity handlers
    "ArfHandler",
    "EntityPostgresHandler",
    "IndexHandler",
    "create_index_handler",
]
