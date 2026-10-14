"""Neo4j fulltext search destination for the default ContextD search path."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from contextd.core.logging import ContextualLogger
from contextd.platform.destinations._base import BaseDestination
from contextd.platform.entities._base import BaseEntity
from contextd.platform.graph.driver.neo4j_driver import convert_neo4j_types
from contextd.platform.graph.fulltext_service import FulltextService
from contextd.schemas.search import ContextDTemporalConfig, SearchResult


class Neo4jFulltextDestination(BaseDestination):
    """Read-only destination backed by Neo4j fulltext indexes.

    Sync writes graph nodes and ft_* properties through the graph commit path. This adapter
    only exposes those existing indexes through the destination search contract.
    """

    _requires_client_embedding = False
    _supports_temporal_relevance = False
    _supports_user_filters = False

    def __init__(
        self,
        collection_id: UUID,
        organization_id: UUID,
        readable_collection_id: str,
    ) -> None:
        super().__init__()
        self.collection_id = collection_id
        self.organization_id = organization_id
        self.readable_collection_id = readable_collection_id

    @classmethod
    async def create(
        cls,
        credentials: Optional[Any] = None,
        config: Optional[dict] = None,
        collection_id: UUID | None = None,
        organization_id: Optional[UUID] = None,
        logger: Optional[ContextualLogger] = None,
    ) -> "Neo4jFulltextDestination":
        """Create the read-only Neo4j fulltext destination."""
        if collection_id is None:
            raise ValueError("collection_id is required")
        if organization_id is None:
            raise ValueError("organization_id is required")
        readable_collection_id = str((config or {}).get("readable_collection_id") or "")
        if not readable_collection_id:
            raise ValueError("readable_collection_id is required")

        instance = cls(
            collection_id=collection_id,
            organization_id=organization_id,
            readable_collection_id=readable_collection_id,
        )
        if logger is not None:
            instance.set_logger(logger)
        return instance

    async def setup_collection(self, collection_id: UUID, vector_size: int) -> None:
        """No-op: graph fulltext indexes are managed by the graph commit path."""

    async def bulk_insert(self, entities: list[BaseEntity]) -> None:
        """Reject writes; this destination is search-only."""
        raise NotImplementedError("Neo4jFulltextDestination is read-only")

    async def delete_by_sync_id(self, sync_id: UUID) -> None:
        """Reject cleanup writes; graph cleanup is owned by graph services."""
        raise NotImplementedError("Neo4jFulltextDestination does not delete graph data")

    async def bulk_delete_by_parent_ids(self, parent_ids: list[str], sync_id: UUID) -> None:
        """Reject cleanup writes; graph cleanup is owned by graph services."""
        raise NotImplementedError("Neo4jFulltextDestination does not delete graph data")

    async def search(
        self,
        queries: List[str],
        contextd_collection_id: UUID,
        limit: int,
        offset: int,
        filter: Optional[Dict[str, Any]] = None,
        dense_embeddings: Optional[List[List[float]]] = None,
        sparse_embeddings: Optional[List[Any]] = None,
        retrieval_strategy: str = "hybrid",
        temporal_config: Optional[ContextDTemporalConfig] = None,
    ) -> List[SearchResult]:
        """Search Neo4j fulltext indexes and return canonical search results."""
        if filter:
            raise ValueError("Neo4j fulltext search does not support metadata filters yet")
        if temporal_config:
            raise ValueError("Neo4j fulltext search does not support temporal relevance yet")

        service = await FulltextService.create(
            organization_id=self.organization_id,
            readable_collection_id=self.readable_collection_id,
        )
        try:
            seen: set[str] = set()
            results: list[SearchResult] = []
            fetch_limit = max(limit + offset, limit)

            for query in queries:
                rows = await service.search_fulltext(
                    query=query,
                    limit=fetch_limit,
                    min_score=0.0,
                    organization_id=str(self.organization_id),
                )
                for row in rows:
                    node_id = str(row.get("node_id") or "")
                    if not node_id or node_id in seen:
                        continue
                    seen.add(node_id)
                    results.append(self._row_to_search_result(row))

            return results[offset : offset + limit]
        finally:
            await service.close()

    def _row_to_search_result(self, row: dict[str, Any]) -> SearchResult:
        """Convert a fulltext row into the canonical search result shape."""
        properties = row.get("properties")
        if not isinstance(properties, dict):
            properties = {}

        payload = dict(properties)
        node_id = str(row.get("node_id") or payload.get("node_id") or "")
        node_type = row.get("node_type") or payload.get("node_type")
        name = row.get("name") or payload.get("name") or payload.get("title")

        payload.update(
            {
                "node_id": node_id,
                "entity_id": payload.get("entity_id") or node_id,
                "node_type": node_type,
                "name": name,
                "source": row.get("source", "neo4j_fulltext"),
                "matched_fields": convert_neo4j_types(row.get("matched_fields", {})),
            }
        )

        return SearchResult(
            id=node_id,
            score=float(row.get("score") or 0.0),
            payload=convert_neo4j_types(payload),
        )
