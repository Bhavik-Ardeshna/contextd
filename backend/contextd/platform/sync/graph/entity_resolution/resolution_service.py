"""Main entity resolution service.

Coordinates multiple entity resolvers and provides
a unified interface for the sync pipeline.
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from .cache import ResolutionCache
from .person_resolver import PersonNodeResolver
from .types import PersonResolutionInput, ProcessedName, ResolutionResult

logger = logging.getLogger(__name__)


class EntityResolutionService:
    """Main service for entity resolution.

    Coordinates multiple entity resolvers and provides
    unified interface for the sync pipeline.

    Usage:
        # Initialize service
        resolution_service = EntityResolutionService(
            graph_driver=neo4j_driver,
            organization_id=org_id,
        )

        # Resolve a single person
        result = await resolution_service.resolve_person(
            name="John Smith",
            email="john@example.com",
            source_type="asana"
        )

        # Use resolved ID in graph event
        node_id = result.node_id

        # Check if it's a new node
        if result.is_new:
            # Get properties to store
            props = resolution_service.get_person_properties(result)

        # Batch resolve multiple persons
        results = await resolution_service.resolve_persons_batch([
            {"name": "John", "email": "john@a.com"},
            {"name": "Jane", "email": "jane@b.com"},
        ])

        # Get cache stats
        stats = resolution_service.get_cache_stats()
    """

    def __init__(
        self,
        graph_driver: Any,
        organization_id: UUID,
        fuzzy_threshold: float = 0.8,
    ):
        """Initialize the resolution service.

        Args:
            graph_driver: Neo4j driver instance for graph queries
            organization_id: Organization UUID for scoping
            fuzzy_threshold: Minimum score for fuzzy matches (0-1)
        """
        self.graph_driver = graph_driver
        self.organization_id = organization_id
        self.fuzzy_threshold = fuzzy_threshold

        # Shared cache for all resolvers in this sync
        self._cache = ResolutionCache()

        # Initialize resolvers
        self._person_resolver = PersonNodeResolver(
            graph_driver=graph_driver,
            organization_id=organization_id,
            cache=self._cache,
            fuzzy_threshold=fuzzy_threshold,
        )

        logger.info(
            f"EntityResolutionService initialized for org {organization_id} "
            f"(fuzzy_threshold={fuzzy_threshold})"
        )

    # -------------------------------------------------------------------------
    # Person Resolution
    # -------------------------------------------------------------------------

    async def resolve_person(
        self,
        name: Optional[str] = None,
        email: Optional[str] = None,
        username: Optional[str] = None,
        source_id: Optional[str] = None,
        source_type: str = "",
        additional_properties: Optional[Dict[str, Any]] = None,
    ) -> ResolutionResult:
        """Resolve a person to a node ID.

        Looks up the graph for existing PersonNodes that match
        the provided information. If found, returns the existing
        node_id. If not found, generates a new deterministic ID.

        Args:
            name: Person's name
            email: Person's email (preferred for matching)
            username: Username (optional)
            source_id: ID from source system
            source_type: Source system name (asana, notion, etc.)
            additional_properties: Extra properties to store

        Returns:
            ResolutionResult with:
            - node_id: The resolved or generated node ID
            - is_new: True if this is a new node
            - confidence: Match confidence level
            - processed_name: Processed name data for storage
        """
        input_data = PersonResolutionInput(
            name=name,
            email=email,
            username=username,
            source_id=source_id,
            source_type=source_type,
            additional_properties=additional_properties or {},
        )

        return await self._person_resolver.resolve(input_data)

    async def resolve_persons_batch(
        self,
        persons: List[Dict[str, Any]],
    ) -> Dict[str, ResolutionResult]:
        """Batch resolve multiple persons efficiently.

        More efficient than resolving one at a time because:
        - Batches email lookups into single query
        - Reuses fuzzy matching candidates
        - Shared cache across all inputs

        Args:
            persons: List of person dicts with keys:
                - name: str (optional)
                - email: str (optional)
                - username: str (optional)
                - source_id: str (optional)
                - source_type: str (optional)
                - properties: dict (optional)

        Returns:
            Dict mapping cache keys to ResolutionResults
        """
        inputs = [
            PersonResolutionInput(
                name=p.get("name"),
                email=p.get("email"),
                username=p.get("username"),
                source_id=p.get("source_id"),
                source_type=p.get("source_type", ""),
                additional_properties=p.get("properties", {}),
            )
            for p in persons
        ]

        return await self._person_resolver.resolve_batch(inputs)

    def get_person_properties(
        self,
        result: ResolutionResult,
        input_data: Optional[PersonResolutionInput] = None,
    ) -> Dict[str, Any]:
        """Get properties to store for a new PersonNode.

        Call this when result.is_new is True to get the
        properties that should be stored on the new node.

        Args:
            result: ResolutionResult from resolve_person()
            input_data: Original input (optional, uses result metadata if not provided)

        Returns:
            Dict of properties for the node
        """
        processed = result.processed_name
        if not processed:
            # Fallback to extracting from metadata
            metadata = result.resolution_metadata
            processed = ProcessedName(
                normalized_name=metadata.get("processed_name", "unknown"),
                display_name=metadata.get("display_name", "Unknown"),
                first_name=None,
                last_name=None,
                name_source=metadata.get("name_source", "fallback"),
                original_value=metadata.get("input_name", ""),
            )

        # Build input data from metadata if not provided
        if input_data is None:
            metadata = result.resolution_metadata
            input_data = PersonResolutionInput(
                name=metadata.get("input_name"),
                email=metadata.get("input_email"),
                source_type=metadata.get("source_type", ""),
            )

        return self._person_resolver.get_node_properties_for_new_person(
            input_data, processed
        )

    # -------------------------------------------------------------------------
    # Future: Other Entity Resolution
    # -------------------------------------------------------------------------

    # async def resolve_company(
    #     self,
    #     name: Optional[str] = None,
    #     domain: Optional[str] = None,
    #     source_id: Optional[str] = None,
    #     source_type: str = "",
    # ) -> ResolutionResult:
    #     """Resolve a company to a node ID."""
    #     pass

    # async def resolve_project(
    #     self,
    #     name: str,
    #     source_id: Optional[str] = None,
    #     source_type: str = "",
    # ) -> ResolutionResult:
    #     """Resolve a project to a node ID."""
    #     pass

    # -------------------------------------------------------------------------
    # Cache Management
    # -------------------------------------------------------------------------

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get resolution cache statistics.

        Returns:
            Dict with cache metrics:
            - hits: Number of cache hits
            - misses: Number of cache misses
            - stores: Number of items stored
            - size: Current cache size
            - hit_rate: Cache hit rate (0-1)
        """
        return self._cache.stats

    def clear_cache(self) -> None:
        """Clear resolution cache.

        Call this at the start of each sync to ensure
        fresh lookups. The cache is meant to prevent
        repeated queries within a single sync.
        """
        self._cache.clear()
        logger.info("Entity resolution cache cleared")

    def get_cached_resolution(self, cache_key: str) -> Optional[ResolutionResult]:
        """Get a cached resolution result by key.

        Useful for debugging or checking if a specific
        entity has been resolved.

        Args:
            cache_key: Cache key (e.g., "person:email:john@example.com")

        Returns:
            Cached ResolutionResult or None
        """
        return self._cache.get(cache_key)

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def get_person_cache_key(
        self,
        name: Optional[str] = None,
        email: Optional[str] = None,
        source_id: Optional[str] = None,
        source_type: str = "",
    ) -> str:
        """Get the cache key for a person.

        Useful for checking if a person has already been resolved.

        Args:
            name: Person's name
            email: Person's email
            source_id: Source system ID
            source_type: Source system name

        Returns:
            Cache key string
        """
        input_data = PersonResolutionInput(
            name=name,
            email=email,
            source_id=source_id,
            source_type=source_type,
        )
        return input_data.get_resolution_key()
