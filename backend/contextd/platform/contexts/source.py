"""Source context for sync operations."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contextd.platform.sources._base import BaseSource
    from contextd.platform.sync.cursor import SyncCursor


@dataclass
class SourceContext:
    """Everything needed to run the source pipeline.

    Attributes:
        source: Configured source instance
        cursor: Sync cursor for incremental syncs
    """

    source: "BaseSource"
    cursor: "SyncCursor"
