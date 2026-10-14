"""Entity Resolution Module.

Provides entity resolution capabilities for the graph event generator.
Resolves entities from different sources to the same node IDs using
fuzzy matching and graph lookups.

Usage:
    from contextd.platform.sync.graph.entity_resolution import (
        EntityResolutionService,
        PersonResolutionInput,
        ResolutionResult,
    )

    # Initialize service
    service = EntityResolutionService(
        graph_driver=neo4j_driver,
        organization_id=org_id,
    )

    # Resolve a person
    result = await service.resolve_person(
        name="John Smith",
        email="john@example.com",
        source_type="asana",
    )

    # Use resolved ID
    node_id = result.node_id
"""

from .base_resolver import BaseEntityResolver
from .cache import ResolutionCache
from .fuzzy_matcher import (
    compute_name_similarity,
    jaro_winkler_similarity,
    levenshtein_ratio,
    normalize_email,
    normalize_name,
)
from .name_processor import NameProcessor, process_person_name
from .person_resolver import PersonNodeResolver
from .resolution_service import EntityResolutionService
from .types import (
    MatchConfidence,
    PersonResolutionInput,
    ProcessedName,
    ResolutionCandidate,
    ResolutionResult,
)

__all__ = [
    # Types
    "MatchConfidence",
    "PersonResolutionInput",
    "ProcessedName",
    "ResolutionCandidate",
    "ResolutionResult",
    # Cache
    "ResolutionCache",
    # Fuzzy matching
    "compute_name_similarity",
    "jaro_winkler_similarity",
    "levenshtein_ratio",
    "normalize_email",
    "normalize_name",
    # Name processing
    "NameProcessor",
    "process_person_name",
    # Resolvers
    "BaseEntityResolver",
    "PersonNodeResolver",
    # Main service
    "EntityResolutionService",
]
