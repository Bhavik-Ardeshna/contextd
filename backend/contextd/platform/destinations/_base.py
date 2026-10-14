"""Base destination classes."""

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, List, Optional
from uuid import UUID

from contextd.core.logging import ContextualLogger
from contextd.core.logging import logger as default_logger
from contextd.platform.entities._base import BaseEntity
from contextd.schemas.search import ContextDTemporalConfig, SearchResult


class BaseDestination(ABC):
    """Common base destination class. This is the umbrella interface for all destinations."""

    # Class variables for integration metadata
    _labels: ClassVar[List[str]] = []

    def __init__(self):
        """Initialize the base destination."""
        self._logger: Optional[ContextualLogger] = (
            None  # Store contextual logger as instance variable
        )

    @property
    def logger(self):
        """Get the logger for this destination, falling back to default if not set."""
        if self._logger is not None:
            return self._logger
        # Return a real default logger
        return default_logger

    def set_logger(self, logger: ContextualLogger) -> None:
        """Set a contextual logger for this destination."""
        self._logger = logger

    @classmethod
    @abstractmethod
    async def create(
        cls,
        credentials: Optional[any],
        config: Optional[dict],
        collection_id: UUID,
        organization_id: Optional[UUID] = None,
        logger: Optional[ContextualLogger] = None,
    ) -> "BaseDestination":
        """Create a new destination with credentials and config (matches source pattern).

        Args:
            credentials: Authentication credentials (for destination-specific integrations)
            config: Configuration parameters (e.g., bucket_name, url)
            collection_id: Collection UUID
            organization_id: Organization UUID
            logger: Logger instance
        """
        pass

    @abstractmethod
    async def setup_collection(self, collection_id: UUID, vector_size: int) -> None:
        """Set up the collection for storing entities."""
        pass

    @abstractmethod
    async def bulk_insert(self, entities: list[BaseEntity]) -> None:
        """Bulk insert entities into the destination."""
        pass

    @abstractmethod
    async def delete_by_sync_id(self, sync_id: UUID) -> None:
        """Delete entities from the destination by sync ID."""
        pass

    @abstractmethod
    async def bulk_delete_by_parent_ids(self, parent_ids: list[str], sync_id: UUID) -> None:
        """Bulk delete entities for multiple parent IDs within a given sync."""
        pass

    @abstractmethod
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
        """Execute search against the destination.

        This is the standard search interface that all destinations must implement.
        Destinations handle embedding generation (if needed) and filter translation internally.

        Args:
            queries: List of search query texts (supports query expansion)
            contextd_collection_id: ContextD collection UUID for multi-tenant filtering
            limit: Maximum number of results to return
            offset: Number of results to skip (pagination)
            filter: Optional filter dict (ContextD canonical format, destination translates)
            dense_embeddings: Pre-computed dense embeddings (if client-side embedding)
            sparse_embeddings: Pre-computed sparse embeddings for hybrid search
            retrieval_strategy: Search strategy - "hybrid", "neural", or "keyword"
            temporal_config: Optional temporal relevance config (destination translates)

        Returns:
            List of SearchResult objects in the standard format
        """
        pass

    def translate_filter(self, filter: Optional[Dict[str, Any]]) -> Any:
        """Translate ContextD filter to destination-native format.

        Default implementation is a no-op.
        Override this method for destinations that use different filter formats.

        Args:
            filter: ContextD canonical filter dict

        Returns:
            Destination-native filter format
        """
        return filter

    def translate_temporal(self, config: Optional[ContextDTemporalConfig]) -> Any:
        """Translate ContextD temporal config to destination-native format.

        Default implementation is a no-op. Override for destinations that
        require different temporal relevance configurations.

        Args:
            config: ContextD temporal relevance configuration

        Returns:
            Destination-native temporal config (or None if not supported)
        """
        return config


class VectorDBDestination(BaseDestination):
    """Abstract base class for destinations backed by a vector database.

    Inherits from BaseDestination and can have additional vector-specific methods if necessary.
    """

    @abstractmethod
    async def get_vector_config_names(self) -> list[str]:
        """Get the vector config names for the destination."""
        pass
