"""ClickHouse cursor schema for incremental sync."""

from typing import Dict

from pydantic import Field

from ._base import BaseCursor


class ClickHouseCursor(BaseCursor):
    """ClickHouse per-table cursor tracking."""

    table_cursors: Dict[str, str] = Field(
        default_factory=dict,
        description="Per-table cursor values as 'database.table' -> cursor value mapping",
    )
