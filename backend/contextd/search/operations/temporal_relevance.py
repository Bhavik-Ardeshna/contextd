"""Temporal relevance operation.

The live ContextD search path is Neo4j fulltext. It does not expose a native
timestamp-distribution API for query-time decay, so this operation is currently
constructed only for destinations that explicitly opt into temporal support.
"""

from typing import Any, List

from contextd.api.context import ApiContext
from contextd.platform.destinations._base import BaseDestination
from contextd.search.context import SearchContext

from ._base import SearchOperation


class TemporalRelevance(SearchOperation):
    """Emit a clean skip event for destinations without temporal relevance support."""

    def __init__(
        self,
        weight: float,
        destination: BaseDestination,
        supporting_sources: list[str] | None = None,
    ) -> None:
        """Initialize the temporal relevance operation."""
        self.weight = weight
        self.destination = destination
        self.supporting_sources = supporting_sources

    def depends_on(self) -> List[str]:
        """Depends on filter operations."""
        return ["QueryInterpretation", "UserFilter"]

    async def execute(
        self,
        context: SearchContext,
        state: dict[str, Any],
        ctx: ApiContext,
    ) -> None:
        """Skip temporal relevance unless a destination implements it."""
        destination_name = type(self.destination).__name__
        ctx.logger.info(
            "[TemporalRelevance] Destination %s does not support temporal relevance; skipping",
            destination_name,
        )
        await context.emitter.emit(
            "recency_skipped",
            {
                "reason": "destination_not_supported",
                "destination": destination_name,
                "requested_weight": self.weight,
            },
            op_name=self.__class__.__name__,
        )
