"""Base class for entity resolvers.

Provides abstract interface and common functionality
for entity-specific resolvers.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, List, TypeVar
from uuid import UUID

from .types import MatchConfidence, ResolutionResult

# Generic type for resolution input
T = TypeVar("T")


class BaseEntityResolver(ABC, Generic[T]):
    """Abstract base class for entity resolvers.

    Each entity type (PersonNode, CompanyNode, etc.) should have
    its own resolver implementation that knows how to:
    1. Build graph queries for matching
    2. Score candidates based on entity-specific rules
    3. Generate new IDs when no match found

    Design for extensibility:
    - Override resolve() for entity-specific resolution logic
    - Override _generate_new_id() for entity-specific ID format
    - Override resolve_batch() for optimized batch resolution

    Usage:
        class PersonNodeResolver(BaseEntityResolver[PersonResolutionInput]):
            @property
            def node_type(self) -> str:
                return "PersonNode"

            async def resolve(self, input_data: PersonResolutionInput) -> ResolutionResult:
                # Custom resolution logic
                ...
    """

    def __init__(
        self,
        graph_driver: Any,
        organization_id: UUID,
        fuzzy_threshold: float = 0.8,
    ):
        """Initialize the resolver.

        Args:
            graph_driver: Neo4j driver instance for graph queries
            organization_id: Organization UUID for scoping queries
            fuzzy_threshold: Minimum score for fuzzy matches (0-1)
        """
        self.graph_driver = graph_driver
        self.organization_id = organization_id
        self.fuzzy_threshold = fuzzy_threshold

    @property
    @abstractmethod
    def node_type(self) -> str:
        """Return the node type this resolver handles.

        Returns:
            Node type string (e.g., 'PersonNode', 'CompanyNode')
        """
        pass

    @abstractmethod
    async def resolve(self, input_data: T) -> ResolutionResult:
        """Resolve a single entity to a node ID.

        This is the main entry point for resolution. Implementations should:
        1. Check cache (if using one)
        2. Query graph for existing matches
        3. Apply entity-specific matching rules
        4. Generate new ID if no match found

        Args:
            input_data: Entity-specific input data

        Returns:
            ResolutionResult with node_id and match metadata
        """
        pass

    @abstractmethod
    async def resolve_batch(
        self, inputs: List[T]
    ) -> Dict[str, ResolutionResult]:
        """Resolve multiple entities efficiently in batch.

        Implementations should optimize for:
        - Batch graph queries where possible
        - Reuse of intermediate results
        - Caching across inputs

        Args:
            inputs: List of entity-specific input data

        Returns:
            Dict mapping input cache keys to ResolutionResults
        """
        pass

    @abstractmethod
    def _generate_new_id(self, input_data: T) -> str:
        """Generate a new node ID when no match is found.

        Should be deterministic based on input data for consistency.
        Two calls with the same input should return the same ID.

        Args:
            input_data: Entity-specific input data

        Returns:
            New node ID string
        """
        pass

    def _score_to_confidence(self, score: float) -> "MatchConfidence":
        """Convert a match score to confidence level.

        Override this if you need different thresholds for specific entity types.

        Args:
            score: Match score between 0 and 1

        Returns:
            MatchConfidence enum value
        """
        if score >= 1.0:
            return MatchConfidence.EXACT
        elif score >= 0.9:
            return MatchConfidence.HIGH
        elif score >= 0.7:
            return MatchConfidence.MEDIUM
        elif score >= 0.5:
            return MatchConfidence.LOW
        else:
            return MatchConfidence.NO_MATCH
