"""Type definitions for entity resolution."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class MatchConfidence(Enum):
    """Confidence level of entity match."""

    EXACT = "exact"           # Email match or identical name
    HIGH = "high"             # Fuzzy score > 0.9
    MEDIUM = "medium"         # Fuzzy score 0.7-0.9
    LOW = "low"               # Fuzzy score 0.5-0.7
    NO_MATCH = "no_match"     # No suitable match found


@dataclass
class ResolutionCandidate:
    """A candidate match from the graph."""

    node_id: str
    node_type: str
    properties: Dict[str, Any]
    match_score: float
    match_reason: str  # "email_exact", "name_fuzzy", etc.


@dataclass
class ResolutionResult:
    """Result of entity resolution."""

    node_id: str                          # Resolved node ID (existing or new)
    is_new: bool                          # True if new ID was generated
    confidence: MatchConfidence           # How confident is the match
    matched_candidate: Optional[ResolutionCandidate] = None
    # Metadata about the resolution for debugging/auditing
    resolution_metadata: Dict[str, Any] = field(default_factory=dict)
    # Processed name data for storage
    processed_name: Optional["ProcessedName"] = None


@dataclass
class ProcessedName:
    """Result of name processing."""

    normalized_name: str          # Normalized for storage/matching: "jack smith"
    display_name: str             # For display: "Jack Smith"
    first_name: Optional[str]     # "Jack"
    last_name: Optional[str]      # "Smith"
    name_source: str              # "email", "raw", "username", "fallback"
    original_value: str           # Original input value


@dataclass
class PersonResolutionInput:
    """Input for PersonNode resolution."""

    name: Optional[str] = None
    email: Optional[str] = None
    username: Optional[str] = None
    source_id: Optional[str] = None       # Original ID from source system
    source_type: str = ""                 # "asana", "notion", "clickup", etc.
    additional_properties: Dict[str, Any] = field(default_factory=dict)

    def get_resolution_key(self) -> str:
        """Get key for caching resolution results.

        Returns a unique key based on the most reliable identifier.
        """
        if self.email:
            return f"person:email:{self.email.lower().strip()}"
        elif self.name:
            return f"person:name:{self.name.lower().strip()}"
        elif self.source_id and self.source_type:
            return f"person:source:{self.source_type}:{self.source_id}"
        elif self.username:
            return f"person:username:{self.username.lower()}"
        return f"person:unknown:{id(self)}"

    def __hash__(self) -> int:
        """Make hashable for use in sets/dicts."""
        return hash(self.get_resolution_key())

    def __eq__(self, other: object) -> bool:
        """Equality based on resolution key."""
        if not isinstance(other, PersonResolutionInput):
            return False
        return self.get_resolution_key() == other.get_resolution_key()
