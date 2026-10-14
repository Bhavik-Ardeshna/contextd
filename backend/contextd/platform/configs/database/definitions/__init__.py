"""Database schema definitions.

Exports schema definitions for different database types.
"""

from contextd.platform.configs.database.definitions.postgres import (
    POSTGRES_SCHEMA_DEFINITIONS,
)

__all__ = ["POSTGRES_SCHEMA_DEFINITIONS"]
