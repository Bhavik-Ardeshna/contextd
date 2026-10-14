"""Query embedding operation.

Converts text queries into dense embeddings for similarity-capable backends.
"""

from typing import Any, List, Optional

from contextd.api.context import ApiContext
from contextd.schemas.search import RetrievalStrategy
from contextd.search.context import SearchContext
from contextd.search.providers._base import BaseProvider

from ._base import SearchOperation


class EmbedQuery(SearchOperation):
    """Generate vector embeddings for queries."""

    def __init__(
        self, strategy: RetrievalStrategy, provider: BaseProvider, vector_size: int
    ) -> None:
        """Initialize with retrieval strategy, provider, and vector dimensions."""
        self.strategy = strategy
        self.provider = provider
        self.vector_size = vector_size

    def depends_on(self) -> List[str]:
        """Depends on query expansion to get all queries to embed."""
        return ["QueryExpansion"]

    async def execute(
        self,
        context: SearchContext,
        state: dict[str, Any],
        ctx: ApiContext,
    ) -> None:
        """Generate embeddings for queries."""
        ctx.logger.debug("[EmbedQuery] Generating embeddings for queries")

        # Emit embedding start
        await context.emitter.emit(
            "embedding_start",
            {"search_method": self.strategy.value},
            op_name=self.__class__.__name__,
        )

        # Determine queries to embed (expanded + original, or just original)
        queries = self._get_queries_to_embed(context, state)

        if self.strategy not in (RetrievalStrategy.HYBRID, RetrievalStrategy.NEURAL):
            raise RuntimeError(
                f"Client-side embeddings do not support strategy {self.strategy}."
            )

        # Note: Token validation is handled by the provider in its embed() method.
        dense_embeddings = await self._generate_dense_embeddings(queries, ctx)

        state["dense_embeddings"] = dense_embeddings
        state["sparse_embeddings"] = None

        # Report metrics for analytics
        self._report_metrics(
            state,
            embeddings_generated=len(dense_embeddings),
            has_dense=True,
            has_sparse=False,
            strategy=self.strategy.value,
        )

        # Emit embedding done with stats
        await self._emit_embedding_done(dense_embeddings, context.emitter)

    def _get_queries_to_embed(self, context: SearchContext, state: dict[str, Any]) -> List[str]:
        """Get all queries to embed (original + expanded)."""
        queries = [context.query]

        # Add expanded queries if available
        expanded = state.get("expanded_queries", [])
        if expanded:
            queries.extend(expanded)

        if not queries:
            raise ValueError("No queries to embed")

        return queries

    async def _generate_dense_embeddings(
        self, queries: List[str], ctx: ApiContext
    ) -> List[List[float]]:
        """Generate dense neural embeddings using provider.

        Uses Matryoshka truncation to get embeddings at the configured vector_size.
        This ensures embeddings match the destination's configured vector dimensions.
        """
        # Pass vector_size for Matryoshka truncation
        # OpenAI's text-embedding-3 models support arbitrary truncation
        ctx.logger.debug(
            f"[EmbedQuery] Generating {self.vector_size}-dim embeddings for {len(queries)} queries"
        )
        dense_embeddings = await self.provider.embed(queries, dimensions=self.vector_size)

        # Validate we got embeddings for all queries
        if len(dense_embeddings) != len(queries):
            raise RuntimeError(
                f"Embedding count mismatch: got {len(dense_embeddings)} for {len(queries)} queries"
            )

        # Validate dimensions
        if dense_embeddings and len(dense_embeddings[0]) != self.vector_size:
            ctx.logger.warning(
                f"[EmbedQuery] Dimension mismatch: got {len(dense_embeddings[0])}, "
                f"expected {self.vector_size}"
            )

        ctx.logger.debug(
            f"[EmbedQuery] Dense embeddings generated: {len(dense_embeddings)} x "
            f"{len(dense_embeddings[0]) if dense_embeddings else 0}-dim"
        )

        return dense_embeddings

    async def _emit_embedding_done(
        self,
        dense_embeddings: Optional[List[List[float]]],
        emitter,
    ) -> None:
        """Emit embedding_done event with statistics.

        Args:
            dense_embeddings: Dense neural embeddings (or None)
            emitter: Event emitter for streaming
        """
        neural_count = len(dense_embeddings) if dense_embeddings else 0
        dim = len(dense_embeddings[0]) if dense_embeddings and dense_embeddings else None

        # Determine model used
        model = None
        if dense_embeddings and self.provider.model_spec.embedding_model:
            model = self.provider.model_spec.embedding_model.name

        await emitter.emit(
            "embedding_done",
            {
                "neural_count": neural_count,
                "sparse_count": 0,
                "dim": dim,
                "model": model,
                "avg_nonzeros": None,
            },
            op_name=self.__class__.__name__,
        )
