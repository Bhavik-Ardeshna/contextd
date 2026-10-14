"""Context and dispatcher builders for platform operations.

Builders are factory classes that construct context objects and dispatchers.

Context Builders:
- ScopeContextBuilder: Creates ScopeContext
- InfraContextBuilder: Creates InfraContext
- SourceContextBuilder: Creates SourceContext
- DestinationsContextBuilder: Creates DestinationsContext
- TrackingContextBuilder: Creates TrackingContext
- SyncContextBuilder: Orchestrates all builders to create SyncContext
- CleanupContextBuilder: Creates CleanupContext for deletion operations
"""

from contextd.platform.builders.cleanup import CleanupContextBuilder
from contextd.platform.builders.destinations import DestinationsContextBuilder
from contextd.platform.builders.infra import InfraContextBuilder
from contextd.platform.builders.scope import ScopeContextBuilder
from contextd.platform.builders.source import SourceContextBuilder
from contextd.platform.builders.sync import SyncContextBuilder
from contextd.platform.builders.tracking import TrackingContextBuilder

__all__ = [
    "CleanupContextBuilder",
    "DestinationsContextBuilder",
    "InfraContextBuilder",
    "ScopeContextBuilder",
    "SourceContextBuilder",
    "SyncContextBuilder",
    "TrackingContextBuilder",
]
