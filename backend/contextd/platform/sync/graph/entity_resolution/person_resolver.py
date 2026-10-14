"""PersonNode entity resolver implementation.

Resolves person references from various sources (Asana, Notion, ClickUp, etc.)
to consistent node IDs using email matching and fuzzy name matching.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from .base_resolver import BaseEntityResolver
from .cache import ResolutionCache
from .fuzzy_matcher import (
    compute_name_similarity,
    normalize_email,
    normalize_name,
)
from .name_processor import NameProcessor
from .queries import PersonResolutionQueries
from .types import (
    MatchConfidence,
    PersonResolutionInput,
    ProcessedName,
    ResolutionCandidate,
    ResolutionResult,
)

logger = logging.getLogger(__name__)


class PersonNodeResolver(BaseEntityResolver[PersonResolutionInput]):
    """Resolver for PersonNode entities.

    Resolution strategy (in priority order):
    1. Exact email match → EXACT confidence
    2. Fuzzy name match (>0.9) → HIGH confidence
    3. Fuzzy name match (>0.8) → MEDIUM confidence
    4. No match → Generate new ID

    Handles data from multiple sources:
    - Asana: name, email from user objects
    - Notion: name from people mentions
    - ClickUp: name, email from assignees
    - etc.

    Features:
    - Name extraction from email addresses
    - Fuzzy name matching using Jaro-Winkler
    - Caching to avoid repeated graph queries
    - Batch resolution for efficiency
    """

    def __init__(
        self,
        graph_driver: Any,
        organization_id: UUID,
        cache: Optional[ResolutionCache] = None,
        fuzzy_threshold: float = 0.8,
    ):
        """Initialize the PersonNode resolver.

        Args:
            graph_driver: Neo4j driver instance
            organization_id: Organization UUID
            cache: Optional resolution cache (creates new if not provided)
            fuzzy_threshold: Minimum score for fuzzy name matches
        """
        super().__init__(graph_driver, organization_id, fuzzy_threshold)
        self.cache = cache or ResolutionCache()
        self.queries = PersonResolutionQueries()
        self._name_processor = NameProcessor()

        # Cache of all persons for fuzzy matching (lazy loaded)
        self._all_persons_cache: Optional[List[Dict[str, Any]]] = None

    @property
    def node_type(self) -> str:
        return "PersonNode"

    async def resolve(self, input_data: PersonResolutionInput) -> ResolutionResult:
        """Resolve a PersonRef to a node ID.

        Args:
            input_data: Person information to resolve

        Returns:
            ResolutionResult with node_id and metadata
        """
        # Check cache first
        cache_key = input_data.get_resolution_key()
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit for person resolution: {cache_key}")
            return cached

        # Process the name for better matching
        processed = self._name_processor.process(
            name=input_data.name,
            email=input_data.email,
            username=input_data.username,
        )

        # Try to find existing node
        result = await self._find_existing_node(input_data, processed)

        # Store processed name in result for node creation
        result.processed_name = processed

        # Cache and return
        self.cache.set(cache_key, result)
        return result

    async def resolve_batch(
        self, inputs: List[PersonResolutionInput]
    ) -> Dict[str, ResolutionResult]:
        """Resolve multiple persons efficiently.

        Batches email lookups for efficiency.

        Args:
            inputs: List of PersonResolutionInput

        Returns:
            Dict mapping cache keys to ResolutionResults
        """
        results: Dict[str, ResolutionResult] = {}
        uncached_inputs: List[PersonResolutionInput] = []

        # Check cache for all inputs
        for input_data in inputs:
            cache_key = input_data.get_resolution_key()
            cached = self.cache.get(cache_key)
            if cached is not None:
                results[cache_key] = cached
            else:
                uncached_inputs.append(input_data)

        if not uncached_inputs:
            return results

        # Batch resolve uncached inputs by email first
        emails_to_lookup = [
            (inp, inp.email)
            for inp in uncached_inputs
            if inp.email
        ]

        if emails_to_lookup:
            email_results = await self._batch_find_by_emails(
                [email for _, email in emails_to_lookup]
            )

            resolved_by_email = set()
            for inp, email in emails_to_lookup:
                normalized = normalize_email(email)
                if normalized in email_results:
                    node_data = email_results[normalized]
                    processed = self._name_processor.process(
                        name=inp.name,
                        email=inp.email,
                        username=inp.username,
                    )
                    result = ResolutionResult(
                        node_id=node_data["node_id"],
                        is_new=False,
                        confidence=MatchConfidence.EXACT,
                        matched_candidate=ResolutionCandidate(
                            node_id=node_data["node_id"],
                            node_type="PersonNode",
                            properties=node_data["properties"],
                            match_score=1.0,
                            match_reason="batch_email_exact",
                        ),
                        resolution_metadata={
                            "match_method": "batch_email",
                            "matched_email": email,
                        },
                        processed_name=processed,
                    )
                    cache_key = inp.get_resolution_key()
                    results[cache_key] = result
                    self.cache.set(cache_key, result)
                    resolved_by_email.add(inp)

            # Remove resolved inputs
            uncached_inputs = [inp for inp in uncached_inputs if inp not in resolved_by_email]

        # Remaining: individual resolution with fuzzy matching
        for inp in uncached_inputs:
            result = await self.resolve(inp)
            cache_key = inp.get_resolution_key()
            results[cache_key] = result

        return results

    async def _find_existing_node(
        self,
        input_data: PersonResolutionInput,
        processed: ProcessedName,
    ) -> ResolutionResult:
        """Find existing node or create new ID."""
        # Strategy 1: Try exact email match
        if input_data.email:
            email_match = await self._find_by_email(input_data.email)
            if email_match:
                logger.info(
                    f"Person resolved by email: {input_data.email} → {email_match.node_id}"
                )
                return ResolutionResult(
                    node_id=email_match.node_id,
                    is_new=False,
                    confidence=MatchConfidence.EXACT,
                    matched_candidate=email_match,
                    resolution_metadata={
                        "match_method": "email_exact",
                        "input_email": input_data.email,
                        "matched_email": email_match.properties.get("email"),
                        "processed_name": processed.normalized_name,
                    }
                )

        # Strategy 2: Try fuzzy name match using PROCESSED name
        if processed.normalized_name and processed.normalized_name != "unknown":
            name_match = await self._find_by_fuzzy_name(
                processed.normalized_name,
                input_data.email,
            )
            if name_match:
                confidence = self._score_to_confidence(name_match.match_score)
                logger.info(
                    f"Person resolved by name: '{input_data.name}' → "
                    f"{name_match.node_id} (score: {name_match.match_score:.2f})"
                )
                return ResolutionResult(
                    node_id=name_match.node_id,
                    is_new=False,
                    confidence=confidence,
                    matched_candidate=name_match,
                    resolution_metadata={
                        "match_method": "name_fuzzy",
                        "input_name": input_data.name,
                        "processed_name": processed.normalized_name,
                        "matched_name": name_match.properties.get("name"),
                        "match_score": name_match.match_score,
                        "match_reason": name_match.match_reason,
                    }
                )

        # No match found - generate new ID
        new_id = self._generate_new_id(input_data, processed)
        logger.info(
            f"Person not found, generating new ID: "
            f"name='{input_data.name}', email='{input_data.email}' → {new_id}"
        )

        return ResolutionResult(
            node_id=new_id,
            is_new=True,
            confidence=MatchConfidence.NO_MATCH,
            resolution_metadata={
                "match_method": "new_id_generated",
                "input_name": input_data.name,
                "input_email": input_data.email,
                "processed_name": processed.normalized_name,
                "display_name": processed.display_name,
                "name_source": processed.name_source,
                "source_type": input_data.source_type,
            }
        )

    async def _load_all_persons(self) -> List[Dict[str, Any]]:
        """Load all PersonNodes for the organization.

        Properties are stored as JSON strings in Neo4j,
        so we fetch all and parse in Python.

        Results are cached for the duration of this resolver instance.
        """
        if self._all_persons_cache is not None:
            return self._all_persons_cache

        if not self.graph_driver:
            self._all_persons_cache = []
            return []

        query = self.queries.build_find_all_persons_query()
        params = {"organization_id": str(self.organization_id)}

        try:
            records = await self.graph_driver.execute_read(query, params)
            persons = []

            for record in (records or []):
                node_id = record.get("node_id")
                properties_raw = record.get("properties")

                if not node_id:
                    continue

                # Parse JSON properties
                properties = {}
                if properties_raw:
                    if isinstance(properties_raw, str):
                        try:
                            properties = json.loads(properties_raw)
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse properties for node {node_id}")
                    elif isinstance(properties_raw, dict):
                        properties = properties_raw

                persons.append({
                    "node_id": node_id,
                    "properties": properties,
                })

            self._all_persons_cache = persons
            logger.info(f"Loaded {len(persons)} existing PersonNodes for resolution")
            return persons

        except Exception as e:
            logger.warning(f"Error loading all persons: {e}")
            self._all_persons_cache = []
            return []

    async def _find_by_email(self, email: str) -> Optional[ResolutionCandidate]:
        """Find PersonNode by exact email match.

        Searches through all loaded persons in Python
        since properties are JSON strings in Neo4j.
        """
        if not email:
            return None

        # Load all persons (cached after first call)
        all_persons = await self._load_all_persons()

        normalized_email_input = normalize_email(email)

        for person in all_persons:
            properties = person.get("properties", {})
            person_email = properties.get("email")

            if person_email and normalize_email(person_email) == normalized_email_input:
                logger.debug(f"Found email match: {email} → {person['node_id']}")
                return ResolutionCandidate(
                    node_id=person["node_id"],
                    node_type="PersonNode",
                    properties=properties,
                    match_score=1.0,
                    match_reason="email_exact",
                )

        return None

    async def _find_by_fuzzy_name(
        self,
        normalized_name: str,
        email: Optional[str] = None,
    ) -> Optional[ResolutionCandidate]:
        """Find PersonNode by fuzzy name matching.

        Loads all persons and performs fuzzy matching in Python.
        """
        if not normalized_name or normalized_name == "unknown":
            return None

        # Load all persons (cached after first call)
        all_persons = await self._load_all_persons()

        if not all_persons:
            return None

        # Score all candidates
        best_candidate: Optional[ResolutionCandidate] = None
        best_score = 0.0

        for person in all_persons:
            properties = person.get("properties", {})
            candidate_name = properties.get("name", "")

            if not candidate_name:
                continue

            # Normalize candidate name for comparison
            normalized_candidate = normalize_name(candidate_name)

            if not normalized_candidate:
                continue

            # Compute fuzzy score
            score, method = compute_name_similarity(normalized_name, normalized_candidate)

            # Boost score if emails match (even partially)
            if email and properties.get("email"):
                if normalize_email(email) == normalize_email(properties["email"]):
                    score = 1.0  # Exact match if email matches
                    method = "email_confirmed"

            logger.debug(
                f"Comparing '{normalized_name}' vs '{normalized_candidate}': "
                f"score={score:.2f}, method={method}"
            )

            if score > best_score and score >= self.fuzzy_threshold:
                best_score = score
                best_candidate = ResolutionCandidate(
                    node_id=person["node_id"],
                    node_type="PersonNode",
                    properties=properties,
                    match_score=score,
                    match_reason=f"name_fuzzy_{method}",
                )

        if best_candidate:
            logger.debug(
                f"Best fuzzy match for '{normalized_name}': "
                f"{best_candidate.node_id} (score={best_score:.2f})"
            )

        return best_candidate

    async def _batch_find_by_emails(
        self, emails: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Batch lookup nodes by emails.

        Returns:
            Dict mapping email (lowercase) to {node_id, properties}
        """
        if not emails:
            return {}

        # Load all persons (cached)
        all_persons = await self._load_all_persons()

        # Build email -> person mapping
        results: Dict[str, Dict[str, Any]] = {}
        search_emails = {normalize_email(e) for e in emails if e}

        for person in all_persons:
            properties = person.get("properties", {})
            person_email = properties.get("email")

            if person_email:
                normalized = normalize_email(person_email)
                if normalized in search_emails:
                    results[normalized] = {
                        "node_id": person["node_id"],
                        "properties": properties,
                    }

        return results

    def _generate_new_id(
        self,
        input_data: PersonResolutionInput,
        processed: Optional[ProcessedName] = None,
    ) -> str:
        """Generate deterministic new ID for a person.

        Priority: email > processed normalized name > UUID
        """
        # Use email if available (most reliable)
        if input_data.email:
            return f"person_{normalize_email(input_data.email)}"

        # Use processed normalized name
        if processed and processed.normalized_name and processed.normalized_name != "unknown":
            safe_name = processed.normalized_name.replace(" ", "_")
            return f"person_{safe_name}"

        # Fallback to UUID
        return f"person_{uuid4()}"

    def get_node_properties_for_new_person(
        self,
        input_data: PersonResolutionInput,
        processed: ProcessedName,
    ) -> Dict[str, Any]:
        """Build node properties for a new PersonNode.

        Stores BOTH raw and processed data for flexibility:
        - name: Processed/normalized for matching
        - display_name: For UI display
        - raw_name: Original input (for debugging)
        - first_name, last_name: Extracted parts
        - All source identifiers

        Args:
            input_data: Original input data
            processed: Processed name data

        Returns:
            Dict of properties for the node
        """
        properties: Dict[str, Any] = {
            # Processed fields (for matching)
            "name": processed.normalized_name,
            "display_name": processed.display_name,
        }

        # Add optional processed fields
        if processed.first_name:
            properties["first_name"] = processed.first_name
        if processed.last_name:
            properties["last_name"] = processed.last_name

        # Raw inputs (for debugging/audit)
        if input_data.name:
            properties["raw_name"] = input_data.name
        properties["name_source"] = processed.name_source

        # Identifiers
        if input_data.email:
            properties["email"] = input_data.email
        if input_data.username:
            properties["username"] = input_data.username
        if input_data.source_id:
            properties["source_id"] = input_data.source_id

        # Source tracking
        if input_data.source_type:
            properties["source_type"] = input_data.source_type

        # Add any additional properties from source
        if input_data.additional_properties:
            properties["source_properties"] = input_data.additional_properties

        return properties
