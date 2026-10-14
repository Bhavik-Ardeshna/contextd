"""Graph event generator.

Generates graph events from NormalizedEntity schema for building knowledge graphs.

All connectors should use normalizers (see normalizers/_base.py) to transform
raw entities into NormalizedEntity format, then use generate_events_from_normalized()
for consistent node ID generation and proper entity resolution.

Entity Resolution:
    When an EntityResolutionService is provided, the generator will query the graph
    to find existing nodes before generating events. This enables:
    - Cross-connector person merging (same person from Asana + Notion = same node)
    - Fuzzy name matching for better deduplication
    - Proper handling of data from different sources
"""

import hashlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID, uuid4

from contextd.platform.contexts.sync import SyncContext
from contextd.platform.entities._normalized import (
    NormalizedEntity,
    PersonRef,
)
from contextd.platform.sync.graph.event_normalizer import GraphEventNormalizer
from contextd.platform.sync.semantic_merge.normalize_identity import normalize_email
from contextd.schemas.graph_event import (
    EdgeEventPayload,
    MetadataEventPayload,
    NodeEventPayload,
    NodeReference,
    TypedGraphEvent,
)

if TYPE_CHECKING:
    from contextd.platform.sync.graph.entity_resolution import EntityResolutionService

logger = logging.getLogger(__name__)


class GraphEventGenerator:
    """Generates graph events from NormalizedEntity schema.

    This generator uses the normalized entity approach to ensure consistent
    node ID generation and proper entity resolution across all connectors.

    All connectors should use the normalizers (see normalizers/_base.py) to
    transform raw entities into NormalizedEntity format before event generation.

    The generate_events_from_normalized() method is the primary entry point.
    """

    def __init__(
        self,
        resolution_service: Optional["EntityResolutionService"] = None,
    ):
        """Initialize event generator.

        Args:
            resolution_service: Optional entity resolution service for graph-based
                               entity matching. If provided, enables:
                               - Cross-connector person merging
                               - Fuzzy name matching
                               - Proper deduplication across sources

                               If not provided, falls back to deterministic ID generation.
        """
        # Event normalizer for ensuring consistent schema
        self.normalizer = GraphEventNormalizer()

        # Entity resolution service for graph-based matching
        self._resolution_service = resolution_service

    # -------------------------------------------------------------------------
    # NormalizedEntity-Based Event Generation
    # -------------------------------------------------------------------------

    async def generate_events_from_normalized(
        self,
        normalized: NormalizedEntity,
        entity_definition_id: UUID,
        sync_context: SyncContext,
    ) -> List[TypedGraphEvent]:
        """Generate graph events from a NormalizedEntity.

        This method generates events directly from the normalized schema,
        ensuring consistent graph structure regardless of source connector.

        Events generated:
        - Source entity node (CREATE/UPDATE)
        - PersonNode events and edges from normalized.people
        - TagNode events from normalized.tags
        - Relation edges from normalized.relations
        - StatusNode from normalized.status
        - PriorityNode from normalized.priority
        - LLM-extracted nodes and edges from normalized.llm_extractions

        Args:
            normalized: NormalizedEntity with canonical data
            entity_definition_id: Entity definition ID
            sync_context: Sync context

        Returns:
            List of generated graph events
        """
        events: List[TypedGraphEvent] = []
        source_node_id = self._source_node_id(normalized)

        # 1. Create NODE event for the source entity itself
        source_node_event = self._create_source_entity_node_event(
            normalized, entity_definition_id, source_node_id
        )
        events.append(source_node_event)

        # 2. Generate PersonNode events and edges from people refs
        if normalized.people:
            person_events = await self._create_person_events(
                normalized,
                entity_definition_id,
                source_node_id=source_node_id,
                source_type=normalized.source_type,
            )
            events.extend(person_events)

        # 3. Generate TagNode events and edges from tag refs
        if normalized.tags:
            tag_events = self._create_tag_events(
                normalized, entity_definition_id, source_node_id
            )
            events.extend(tag_events)

        # 4. Generate relation edges from relation refs
        if normalized.relations:
            relation_events = self._create_relation_events(
                normalized, entity_definition_id, source_node_id
            )
            events.extend(relation_events)

        # 5. Generate StatusNode event and edge if status exists
        if normalized.status:
            status_events = self._create_status_events(
                normalized, entity_definition_id, source_node_id
            )
            events.extend(status_events)

        # 6. Generate PriorityNode event and edge if priority exists
        if normalized.priority:
            priority_events = self._create_priority_events(
                normalized, entity_definition_id, source_node_id
            )
            events.extend(priority_events)

        # 7. Generate METADATA event for the normalized entity itself
        metadata_event = self._create_normalized_metadata_event(
            normalized, entity_definition_id
        )
        events.append(metadata_event)

        # 8. Generate LLM extraction events (nodes + edges) from normalized.llm_extractions
        if normalized.llm_extractions:
            llm_events = self._create_llm_extraction_events(
                normalized, entity_definition_id, source_node_id
            )
            events.extend(llm_events)

        return events

    def _create_source_entity_node_event(
        self,
        normalized: NormalizedEntity,
        entity_definition_id: UUID,
        source_node_id: str,
    ) -> TypedGraphEvent:
        """Create NODE event for the source entity.

        Args:
            normalized: NormalizedEntity
            entity_definition_id: Entity definition ID

        Returns:
            NODE_CREATE event (downstream handles upserts via MERGE)
        """
        # Always CREATE - downstream graph operations handle upserts via MERGE
        operation = "CREATE"

        # Build node properties from normalized data
        node_properties = {
            "id": normalized.entity_id,
            "name": normalized.name,
            "entity_type": normalized.entity_type,
            "source_type": normalized.source_type,
        }

        # Add optional fields if present
        if normalized.description:
            node_properties["description"] = normalized.description
        if normalized.web_url:
            node_properties["web_url"] = normalized.web_url
        if normalized.created_at:
            node_properties["created_at"] = normalized.created_at.isoformat()
        if normalized.updated_at:
            node_properties["updated_at"] = normalized.updated_at.isoformat()
        if normalized.due_at:
            node_properties["due_at"] = normalized.due_at.isoformat()
        if normalized.breadcrumb_names:
            node_properties["breadcrumb"] = " > ".join(normalized.breadcrumb_names)

        # Add all remaining properties from normalized entity
        if normalized.properties:
            node_properties.update(normalized.properties)

        return TypedGraphEvent(
            event_id=uuid4(),
            event_type=f"NODE_{operation}",
            entity_id=source_node_id,
            entity_type=normalized.entity_type,
            entity_definition_id=entity_definition_id,
            field_name="__entity__",
            timestamp=datetime.now(UTC),
            payload=NodeEventPayload(
                node_id=source_node_id,
                node_type=normalized.entity_type,
                node_properties=node_properties,
                operation=operation,
            ),
            metadata={
                "all_properties": normalized.properties or {},
            },
        )

    async def _create_person_events(
        self,
        normalized: NormalizedEntity,
        entity_definition_id: UUID,
        source_node_id: Optional[str] = None,
        source_type: str = "",
    ) -> List[TypedGraphEvent]:
        """Create PersonNode events and edges from people refs.

        Uses EntityResolutionService (if available) to:
        - Query graph for existing PersonNodes
        - Match by email or fuzzy name
        - Reuse existing node IDs for cross-connector merging

        Args:
            normalized: NormalizedEntity with people refs
            entity_definition_id: Entity definition ID
            source_type: Source connector type (e.g., "asana", "notion")

        Returns:
            List of NODE and EDGE events for each person (including reverse edges)
        """
        events = []
        source_node_id = source_node_id or self._source_node_id(normalized)

        for person in normalized.people:
            # Skip unidentifiable persons (no meaningful name, email, or id)
            # Also handles cases where values are "None" strings
            has_name = person.name and person.name.lower() not in ("none", "unknown", "")
            has_email = person.email and person.email.lower() not in ("none", "")
            has_id = person.id and str(person.id).lower() not in ("none", "")

            if not has_name and not has_email and not has_id:
                logger.debug(f"Skipping unidentifiable person (no name/email/id): role={person.role}")
                continue

            # Generate stable node ID for person (using resolution service if available)
            person_node_id, node_properties = await self._resolve_person_node(
                person, source_type
            )

            # Always CREATE - downstream graph operations handle upserts via MERGE
            operation = "CREATE"

            # Create PersonNode event
            node_event = TypedGraphEvent(
                event_id=uuid4(),
                event_type=f"NODE_{operation}",
                entity_id=person_node_id,
                entity_type="PersonNode",
                entity_definition_id=entity_definition_id,
                field_name="people",
                timestamp=datetime.now(UTC),
                payload=NodeEventPayload(
                    node_id=person_node_id,
                    node_type="PersonNode",
                    node_properties=node_properties,
                    operation=operation,
                ),
            )
            events.append(node_event)

            # Create edge from entity to person (forward edge)
            edge_type = self._get_edge_type_for_role(person.role)
            reverse_edge_type = self._get_reverse_edge_type_for_role(person.role)

            edge_event = TypedGraphEvent(
                event_id=uuid4(),
                event_type="EDGE_CREATE",
                entity_id=source_node_id,
                entity_type=normalized.entity_type,
                entity_definition_id=entity_definition_id,
                field_name="people",
                timestamp=datetime.now(UTC),
                payload=EdgeEventPayload(
                    from_node=NodeReference(
                        node_id=source_node_id,
                        node_type=normalized.entity_type,
                    ),
                    to_node=NodeReference(
                        node_id=person_node_id,
                        node_type="PersonNode",
                    ),
                    edge_type=edge_type,
                    direction="outgoing",
                    edge_properties={"role": person.role},
                    operation="CREATE",
                    is_reverse_edge=False,
                ),
            )
            events.append(edge_event)

            # Create reverse edge from person to entity
            reverse_edge_event = TypedGraphEvent(
                event_id=uuid4(),
                event_type="EDGE_CREATE",
                entity_id=source_node_id,
                entity_type=normalized.entity_type,
                entity_definition_id=entity_definition_id,
                field_name="people",
                timestamp=datetime.now(UTC),
                payload=EdgeEventPayload(
                    from_node=NodeReference(
                        node_id=person_node_id,
                        node_type="PersonNode",
                    ),
                    to_node=NodeReference(
                        node_id=source_node_id,
                        node_type=normalized.entity_type,
                    ),
                    edge_type=reverse_edge_type,
                    direction="incoming",
                    edge_properties={"role": person.role},
                    operation="CREATE",
                    is_reverse_edge=True,
                ),
            )
            events.append(reverse_edge_event)

        return events

    def _create_tag_events(
        self,
        normalized: NormalizedEntity,
        entity_definition_id: UUID,
        source_node_id: Optional[str] = None,
    ) -> List[TypedGraphEvent]:
        """Create TagNode events and edges from tag refs.

        Args:
            normalized: NormalizedEntity with tag refs
            entity_definition_id: Entity definition ID

        Returns:
            List of NODE and EDGE events for each tag (including reverse edges)
        """
        events = []
        source_node_id = source_node_id or self._source_node_id(normalized)

        for tag in normalized.tags:
            # Generate stable node ID for tag
            tag_node_id = f"tag_{tag.id}" if tag.id else f"tag_{tag.name}"

            # Always CREATE - downstream graph operations handle upserts via MERGE
            operation = "CREATE"

            # Build node properties
            node_properties = {
                "id": tag.id,
                "name": tag.name,
            }
            if tag.color:
                node_properties["color"] = tag.color
            if tag.tag_type:
                node_properties["tag_type"] = tag.tag_type
            if tag.properties:
                node_properties.update(tag.properties)

            # Create TagNode event
            node_event = TypedGraphEvent(
                event_id=uuid4(),
                event_type=f"NODE_{operation}",
                entity_id=tag_node_id,
                entity_type="TagNode",
                entity_definition_id=entity_definition_id,
                field_name="tags",
                timestamp=datetime.now(UTC),
                payload=NodeEventPayload(
                    node_id=tag_node_id,
                    node_type="TagNode",
                    node_properties=node_properties,
                    operation=operation,
                ),
            )
            events.append(node_event)

            # Create forward edge from entity to tag (TAGGED_WITH / HAS_TAG)
            edge_event = TypedGraphEvent(
                event_id=uuid4(),
                event_type="EDGE_CREATE",
                entity_id=source_node_id,
                entity_type=normalized.entity_type,
                entity_definition_id=entity_definition_id,
                field_name="tags",
                timestamp=datetime.now(UTC),
                payload=EdgeEventPayload(
                    from_node=NodeReference(
                        node_id=source_node_id,
                        node_type=normalized.entity_type,
                    ),
                    to_node=NodeReference(
                        node_id=tag_node_id,
                        node_type="TagNode",
                    ),
                    edge_type="TAGGED_WITH",
                    direction="outgoing",
                    edge_properties={},
                    operation="CREATE",
                    is_reverse_edge=False,
                ),
            )
            events.append(edge_event)

            # Create reverse edge from tag to entity (TAGS)
            reverse_edge_event = TypedGraphEvent(
                event_id=uuid4(),
                event_type="EDGE_CREATE",
                entity_id=source_node_id,
                entity_type=normalized.entity_type,
                entity_definition_id=entity_definition_id,
                field_name="tags",
                timestamp=datetime.now(UTC),
                payload=EdgeEventPayload(
                    from_node=NodeReference(
                        node_id=tag_node_id,
                        node_type="TagNode",
                    ),
                    to_node=NodeReference(
                        node_id=source_node_id,
                        node_type=normalized.entity_type,
                    ),
                    edge_type="TAGS",
                    direction="incoming",
                    edge_properties={},
                    operation="CREATE",
                    is_reverse_edge=True,
                ),
            )
            events.append(reverse_edge_event)

        return events

    def _create_relation_events(
        self,
        normalized: NormalizedEntity,
        entity_definition_id: UUID,
        source_node_id: str,
    ) -> List[TypedGraphEvent]:
        """Create EDGE events from relation refs.

        For each relation, we also create a placeholder NODE for the target entity
        if it doesn't exist yet. This ensures edges can always be created even if
        the related entity hasn't been synced yet.

        Args:
            normalized: NormalizedEntity with relation refs
            entity_definition_id: Entity definition ID

        Returns:
            List of NODE (placeholder) and EDGE events for each relation
        """
        events = []

        for relation in normalized.relations:
            # NOTE: We do NOT create placeholder nodes for relation targets.
            # Neo4j MERGE operations in downstream graph construction will
            # handle creating minimal nodes if needed. When the actual entity
            # is synced later, it will update those nodes with proper data.
            # This prevents creating nodes with IDs as names.

            relation_properties = {
                key: value
                for key, value in (relation.properties or {}).items()
                if value is not None
            }
            # Database connectors can attach Forge-compatible edge labels to
            # RelationRef.properties; fall back to the generic relation map for
            # SaaS connectors and older sync events.
            edge_type = str(
                relation_properties.get("edge_type")
                or self._map_relation_type_to_edge(relation.relation_type)
            )
            reverse_edge_type = str(
                relation_properties.get("reverse_edge_type")
                or edge_type
                or self._map_relation_type_to_reverse_edge(relation.relation_type)
            )

            # Create forward edge event
            edge_event = TypedGraphEvent(
                event_id=uuid4(),
                event_type="EDGE_CREATE",
                entity_id=source_node_id,
                entity_type=normalized.entity_type,
                entity_definition_id=entity_definition_id,
                field_name="relations",
                timestamp=datetime.now(UTC),
                payload=EdgeEventPayload(
                    from_node=NodeReference(
                        node_id=source_node_id,
                        node_type=normalized.entity_type,
                    ),
                    to_node=NodeReference(
                        node_id=relation.entity_id,
                        node_type=relation.entity_type,
                    ),
                    edge_type=edge_type,
                    direction="outgoing",
                    edge_properties={
                        "relation_type": relation.relation_type,
                        "target_name": relation.name or "",
                        **relation_properties,
                    },
                    operation="CREATE",
                    is_reverse_edge=False,
                ),
                metadata={
                    "source_properties": normalized.properties or {},
                    "target_properties": relation.properties or {},
                },
            )
            events.append(edge_event)

            # Create reverse edge event
            reverse_edge_event = TypedGraphEvent(
                event_id=uuid4(),
                event_type="EDGE_CREATE",
                entity_id=source_node_id,
                entity_type=normalized.entity_type,
                entity_definition_id=entity_definition_id,
                field_name="relations",
                timestamp=datetime.now(UTC),
                payload=EdgeEventPayload(
                    from_node=NodeReference(
                        node_id=relation.entity_id,
                        node_type=relation.entity_type,
                    ),
                    to_node=NodeReference(
                        node_id=source_node_id,
                        node_type=normalized.entity_type,
                    ),
                    edge_type=reverse_edge_type,
                    direction="incoming",
                    edge_properties={
                        "relation_type": relation.relation_type,
                        "source_name": normalized.name or "",
                        **relation_properties,
                        "source_column": relation_properties.get("source_column"),
                        "is_reverse_edge": True,
                    },
                    operation="CREATE",
                    is_reverse_edge=True,
                ),
                metadata={
                    "source_properties": relation.properties or {},
                    "target_properties": normalized.properties or {},
                },
            )
            events.append(reverse_edge_event)

        return events

    def _create_status_events(
        self,
        normalized: NormalizedEntity,
        entity_definition_id: UUID,
        source_node_id: str,
    ) -> List[TypedGraphEvent]:
        """Create StatusNode event and edge from status ref.

        Args:
            normalized: NormalizedEntity with status ref
            entity_definition_id: Entity definition ID

        Returns:
            List containing NODE and EDGE events for status (including reverse edges)
        """
        events = []
        status = normalized.status

        if not status:
            return events

        # Generate stable node ID for status
        status_node_id = f"status_{status.id}" if status.id else f"status_{status.name}"

        # Always CREATE - downstream graph operations handle upserts via MERGE
        operation = "CREATE"

        # Build node properties
        node_properties = {
            "id": status.id or status.name,
            "name": status.name,
        }
        if status.color:
            node_properties["color"] = status.color
        if status.category:
            node_properties["category"] = status.category
        if status.properties:
            node_properties.update(status.properties)

        # Create StatusNode event
        node_event = TypedGraphEvent(
            event_id=uuid4(),
            event_type=f"NODE_{operation}",
            entity_id=status_node_id,
            entity_type="StatusNode",
            entity_definition_id=entity_definition_id,
            field_name="status",
            timestamp=datetime.now(UTC),
            payload=NodeEventPayload(
                node_id=status_node_id,
                node_type="StatusNode",
                node_properties=node_properties,
                operation=operation,
            ),
        )
        events.append(node_event)

        # Create forward edge from entity to status (HAS_STATUS)
        edge_event = TypedGraphEvent(
            event_id=uuid4(),
            event_type="EDGE_CREATE",
            entity_id=source_node_id,
            entity_type=normalized.entity_type,
            entity_definition_id=entity_definition_id,
            field_name="status",
            timestamp=datetime.now(UTC),
            payload=EdgeEventPayload(
                from_node=NodeReference(
                    node_id=source_node_id,
                    node_type=normalized.entity_type,
                ),
                to_node=NodeReference(
                    node_id=status_node_id,
                    node_type="StatusNode",
                ),
                edge_type="HAS_STATUS",
                direction="outgoing",
                edge_properties={},
                operation="CREATE",
                is_reverse_edge=False,
            ),
        )
        events.append(edge_event)

        # Create reverse edge from status to entity (STATUS_OF)
        reverse_edge_event = TypedGraphEvent(
            event_id=uuid4(),
            event_type="EDGE_CREATE",
            entity_id=source_node_id,
            entity_type=normalized.entity_type,
            entity_definition_id=entity_definition_id,
            field_name="status",
            timestamp=datetime.now(UTC),
            payload=EdgeEventPayload(
                from_node=NodeReference(
                    node_id=status_node_id,
                    node_type="StatusNode",
                ),
                to_node=NodeReference(
                    node_id=source_node_id,
                    node_type=normalized.entity_type,
                ),
                edge_type="STATUS_OF",
                direction="incoming",
                edge_properties={},
                operation="CREATE",
                is_reverse_edge=True,
            ),
        )
        events.append(reverse_edge_event)

        return events

    def _create_priority_events(
        self,
        normalized: NormalizedEntity,
        entity_definition_id: UUID,
        source_node_id: str,
    ) -> List[TypedGraphEvent]:
        """Create PriorityNode event and edge from priority ref.

        Args:
            normalized: NormalizedEntity with priority ref
            entity_definition_id: Entity definition ID

        Returns:
            List containing NODE and EDGE events for priority (including reverse edges)
        """
        events = []
        priority = normalized.priority

        if not priority:
            return events

        # Generate stable node ID for priority
        priority_node_id = f"priority_{priority.id}" if priority.id else f"priority_{priority.name}"

        # Always CREATE - downstream graph operations handle upserts via MERGE
        operation = "CREATE"

        # Build node properties
        node_properties = {
            "id": priority.id or priority.name,
            "name": priority.name,
        }
        if priority.level is not None:
            node_properties["level"] = priority.level
        if priority.color:
            node_properties["color"] = priority.color
        if priority.properties:
            node_properties.update(priority.properties)

        # Create PriorityNode event
        node_event = TypedGraphEvent(
            event_id=uuid4(),
            event_type=f"NODE_{operation}",
            entity_id=priority_node_id,
            entity_type="PriorityNode",
            entity_definition_id=entity_definition_id,
            field_name="priority",
            timestamp=datetime.now(UTC),
            payload=NodeEventPayload(
                node_id=priority_node_id,
                node_type="PriorityNode",
                node_properties=node_properties,
                operation=operation,
            ),
        )
        events.append(node_event)

        # Create forward edge from entity to priority (HAS_PRIORITY)
        edge_event = TypedGraphEvent(
            event_id=uuid4(),
            event_type="EDGE_CREATE",
            entity_id=source_node_id,
            entity_type=normalized.entity_type,
            entity_definition_id=entity_definition_id,
            field_name="priority",
            timestamp=datetime.now(UTC),
            payload=EdgeEventPayload(
                from_node=NodeReference(
                    node_id=source_node_id,
                    node_type=normalized.entity_type,
                ),
                to_node=NodeReference(
                    node_id=priority_node_id,
                    node_type="PriorityNode",
                ),
                edge_type="HAS_PRIORITY",
                direction="outgoing",
                edge_properties={},
                operation="CREATE",
                is_reverse_edge=False,
            ),
        )
        events.append(edge_event)

        # Create reverse edge from priority to entity (PRIORITY_OF)
        reverse_edge_event = TypedGraphEvent(
            event_id=uuid4(),
            event_type="EDGE_CREATE",
            entity_id=source_node_id,
            entity_type=normalized.entity_type,
            entity_definition_id=entity_definition_id,
            field_name="priority",
            timestamp=datetime.now(UTC),
            payload=EdgeEventPayload(
                from_node=NodeReference(
                    node_id=priority_node_id,
                    node_type="PriorityNode",
                ),
                to_node=NodeReference(
                    node_id=source_node_id,
                    node_type=normalized.entity_type,
                ),
                edge_type="PRIORITY_OF",
                direction="incoming",
                edge_properties={},
                operation="CREATE",
                is_reverse_edge=True,
            ),
        )
        events.append(reverse_edge_event)

        return events

    def _create_llm_extraction_events(
        self,
        normalized: NormalizedEntity,
        entity_definition_id: UUID,
        source_node_id: str,
    ) -> List[TypedGraphEvent]:
        """Create NODE and EDGE events for LLM-extracted entities.

        Follows same pattern as _create_person_events, _create_tag_events:
        1. Create NODE for the extracted entity
        2. Create EDGE from source entity to extracted entity
        3. Create reverse EDGE for bidirectional traversal
        4. Create EDGE from extracted entity to related persons (if any)

        Args:
            normalized: NormalizedEntity with llm_extractions
            entity_definition_id: Entity definition ID

        Returns:
            List of NODE and EDGE events for each LLM extraction
        """
        events = []

        if not normalized.llm_extractions:
            return events

        for extraction in normalized.llm_extractions:
            extraction_node_id = extraction.id

            # 1. Create NODE event for extracted entity
            node_properties = {
                "id": extraction.id,
                "name": extraction.name,
                "subtype": extraction.entity_type.split(":")[-1] if ":" in extraction.entity_type else extraction.entity_type,
            }
            if extraction.description:
                node_properties["description"] = extraction.description
            if extraction.related_to:
                node_properties["related_to"] = extraction.related_to
            # Add any additional properties
            node_properties.update(extraction.properties)

            # Always CREATE - downstream graph operations handle upserts via MERGE
            node_event = TypedGraphEvent(
                event_id=uuid4(),
                event_type="NODE_CREATE",
                entity_id=extraction_node_id,
                entity_type=extraction.entity_type,
                entity_definition_id=entity_definition_id,
                field_name="llm_extractions",
                timestamp=datetime.now(UTC),
                payload=NodeEventPayload(
                    node_id=extraction_node_id,
                    node_type=extraction.entity_type,
                    node_properties=node_properties,
                    operation="CREATE",
                ),
                metadata={
                    "llm_extracted": True,
                    "extraction_confidence": extraction.confidence,
                    "extraction_model": extraction.extraction_model,
                },
            )
            events.append(node_event)

            # 2. Create forward EDGE from source entity to extracted entity
            edge_event = TypedGraphEvent(
                event_id=uuid4(),
                event_type="EDGE_CREATE",
                entity_id=source_node_id,
                entity_type=normalized.entity_type,
                entity_definition_id=entity_definition_id,
                field_name="llm_extractions",
                timestamp=datetime.now(UTC),
                payload=EdgeEventPayload(
                    from_node=NodeReference(
                        node_id=source_node_id,
                        node_type=normalized.entity_type,
                    ),
                    to_node=NodeReference(
                        node_id=extraction_node_id,
                        node_type=extraction.entity_type,
                    ),
                    edge_type=extraction.edge_type,
                    direction="outgoing",
                    edge_properties={"confidence": extraction.confidence},
                    operation="CREATE",
                    is_reverse_edge=False,
                ),
            )
            events.append(edge_event)

            # 3. Create reverse EDGE for bidirectional traversal
            reverse_edge_type = self._get_llm_reverse_edge_type(extraction.edge_type)
            reverse_edge_event = TypedGraphEvent(
                event_id=uuid4(),
                event_type="EDGE_CREATE",
                entity_id=source_node_id,
                entity_type=normalized.entity_type,
                entity_definition_id=entity_definition_id,
                field_name="llm_extractions",
                timestamp=datetime.now(UTC),
                payload=EdgeEventPayload(
                    from_node=NodeReference(
                        node_id=extraction_node_id,
                        node_type=extraction.entity_type,
                    ),
                    to_node=NodeReference(
                        node_id=source_node_id,
                        node_type=normalized.entity_type,
                    ),
                    edge_type=reverse_edge_type,
                    direction="incoming",
                    edge_properties={"confidence": extraction.confidence},
                    operation="CREATE",
                    is_reverse_edge=True,
                ),
            )
            events.append(reverse_edge_event)

        return events

    def _get_llm_reverse_edge_type(self, edge_type: str) -> str:
        """Map LLM edge type to reverse edge type.

        Args:
            edge_type: Forward edge type from LLM extraction

        Returns:
            Reverse edge type for bidirectional traversal
        """
        reverse_map = {
            "CONTAINS_ACTION_ITEM": "ACTION_ITEM_IN",
            "MENTIONS_PROJECT": "PROJECT_MENTIONED_IN",
            "HAS_DEADLINE": "DEADLINE_FOR",
            "CONTAINS_DECISION": "DECISION_IN",
            "ASSIGNS_TASK": "TASK_ASSIGNED_BY",
            "HAS_FOLLOW_UP": "FOLLOW_UP_FOR",
            "REFERENCES": "REFERENCED_BY",
            "EXTRACTED_FROM": "CONTAINS_EXTRACTION",
        }
        return reverse_map.get(edge_type, f"{edge_type}_REVERSE")

    def _source_node_id(self, normalized: NormalizedEntity) -> str:
        """Prefer semantic canonical ID when present for the source node."""
        return (normalized.properties or {}).get("semantic_canonical_node_id") or normalized.entity_id

    def _create_normalized_metadata_event(
        self,
        normalized: NormalizedEntity,
        entity_definition_id: UUID,
    ) -> TypedGraphEvent:
        """Create METADATA event containing full normalized entity data.

        This event stores the complete normalized schema for the entity,
        enabling full data retrieval from graph events.

        Args:
            normalized: NormalizedEntity with all data
            entity_definition_id: Entity definition ID

        Returns:
            METADATA_UPDATE event
        """
        # Serialize normalized entity to dict
        normalized_data = normalized.model_dump(mode='json')

        return TypedGraphEvent(
            event_id=uuid4(),
            event_type="METADATA_UPDATE",
            entity_id=normalized.entity_id,
            entity_type=normalized.entity_type,
            entity_definition_id=entity_definition_id,
            field_name="__normalized_entity__",
            timestamp=datetime.now(UTC),
            payload=MetadataEventPayload(
                category="normalized_entity",
                old_value_hash=None,
                new_value_hash=hashlib.md5(
                    str(normalized_data).encode()
                ).hexdigest(),
                indexed=True,
                metadata=normalized_data,
            ),
        )

    async def _resolve_person_node(
        self,
        person: PersonRef,
        source_type: str = "",
    ) -> tuple[str, Dict[str, Any]]:
        """Resolve a PersonRef to a node ID and properties.

        Uses EntityResolutionService (if available) to:
        - Query graph for existing PersonNodes
        - Match by email or fuzzy name
        - Process and normalize names for better matching

        Args:
            person: PersonRef object
            source_type: Source connector type

        Returns:
            Tuple of (node_id, node_properties)
        """
        # Semantic merge stamps final graph node_id on person.id (person_…)
        pid = person.id
        if pid and str(pid).startswith("person_"):
            pp = dict(person.properties or {})
            node_properties: Dict[str, Any] = {
                "id": pid,
                "role": person.role,
            }
            node_properties.update(pp)
            nm = person.name or pp.get("name") or node_properties.get("name")
            node_properties["name"] = nm if nm not in (None, "") else "Unknown"
            raw_em = person.email or pp.get("email") or node_properties.get("email")
            if raw_em:
                node_properties["email"] = (
                    normalize_email(str(raw_em)) or str(raw_em).strip().lower()
                )
            if person.username:
                node_properties["username"] = person.username
            if person.avatar_url:
                node_properties["avatar_url"] = person.avatar_url
            return str(pid), node_properties

        # Legacy: semantic_canonical_node_id on properties (older pipeline)
        sem = (person.properties or {}).get("semantic_canonical_node_id")
        if sem:
            node_properties = {
                "id": person.id,
                "name": person.name or "Unknown",
                "role": person.role,
            }
            if person.email:
                node_properties["email"] = person.email
            if person.username:
                node_properties["username"] = person.username
            if person.avatar_url:
                node_properties["avatar_url"] = person.avatar_url
            if person.properties:
                node_properties.update(person.properties)
            return sem, node_properties

        # If resolution service is available, use it
        if self._resolution_service:
            try:
                result = await self._resolution_service.resolve_person(
                    name=person.name,
                    email=person.email,
                    username=person.username,
                    source_id=person.id,
                    source_type=source_type,
                    additional_properties=person.properties,
                )

                # Build properties from resolution result
                if result.is_new and result.processed_name:
                    # New node - use processed name data
                    node_properties = self._resolution_service.get_person_properties(result)
                    # Add role from PersonRef
                    node_properties["role"] = person.role
                    if person.avatar_url:
                        node_properties["avatar_url"] = person.avatar_url
                else:
                    # Existing node - preserve existing properties, only update what's provided
                    # IMPORTANT: Don't overwrite existing name with "Unknown" if new source has no name
                    existing_props = result.matched_candidate.properties if result.matched_candidate else {}

                    # Use new name if provided, otherwise preserve existing name
                    resolved_name = person.name if person.name else existing_props.get("name", "Unknown")

                    node_properties = {
                        "id": person.id or existing_props.get("id"),
                        "name": resolved_name,
                        "role": person.role,
                    }
                    # Preserve existing email if new source doesn't have one
                    if person.email:
                        node_properties["email"] = person.email
                    elif existing_props.get("email"):
                        node_properties["email"] = existing_props["email"]
                    # Preserve existing username if new source doesn't have one
                    if person.username:
                        node_properties["username"] = person.username
                    elif existing_props.get("username"):
                        node_properties["username"] = existing_props["username"]
                    if person.avatar_url:
                        node_properties["avatar_url"] = person.avatar_url
                    elif existing_props.get("avatar_url"):
                        node_properties["avatar_url"] = existing_props["avatar_url"]
                    if person.properties:
                        node_properties.update(person.properties)

                logger.debug(
                    f"Resolved person: name='{person.name}', email='{person.email}' "
                    f"→ {result.node_id} (is_new={result.is_new}, "
                    f"confidence={result.confidence.value})"
                )

                return result.node_id, node_properties

            except Exception as e:
                logger.warning(
                    f"Entity resolution failed, falling back to deterministic ID: {e}"
                )

        # Fallback: deterministic ID generation without graph lookup
        node_id = self._generate_person_node_id_fallback(person)
        node_properties = {
            "id": person.id,
            "name": person.name or "Unknown",
            "role": person.role,
        }
        if person.email:
            node_properties["email"] = person.email
        if person.username:
            node_properties["username"] = person.username
        if person.avatar_url:
            node_properties["avatar_url"] = person.avatar_url
        if person.properties:
            node_properties.update(person.properties)

        return node_id, node_properties

    def _generate_person_node_id_fallback(self, person: PersonRef) -> str:
        """Generate stable node ID for a PersonRef (fallback without resolution service).

        Args:
            person: PersonRef object

        Returns:
            Stable node ID string
        """
        # Priority for cross-connector person resolution:
        # 1. Email (most reliable, same across all connectors)
        # 2. Normalized name (allows merging same person without email)
        # 3. Connector-specific ID (fallback, won't merge across connectors)
        if person.email:
            # Email is most reliable for cross-connector merging
            return f"person_{person.email.lower()}"
        elif person.name:
            # Use normalized name for cross-connector merging when email unavailable
            # This allows "Bhavik Ardeshna" from Asana to merge with same name from Notion
            normalized_name = person.name.lower().strip().replace(" ", "_")
            return f"person_{normalized_name}"
        elif person.id:
            # Fallback to ID if no name (won't merge across connectors)
            return f"person_{person.id}"
        else:
            return f"person_{uuid4()}"

    def _get_edge_type_for_role(self, role: str) -> str:
        """Map person role to edge type.

        Args:
            role: Person role string

        Returns:
            Edge type string
        """
        role_to_edge = {
            "assignee": "ASSIGNED_TO",
            "owner": "OWNED_BY",
            "member": "HAS_MEMBER",
            "follower": "FOLLOWED_BY",
            "creator": "CREATED_BY",
            "editor": "EDITED_BY",
            "author": "AUTHORED_BY",
            "reviewer": "REVIEWED_BY",
            "approver": "APPROVED_BY",
            "watcher": "WATCHED_BY",
            "mentioned": "MENTIONS",
            "other": "RELATED_TO",
        }
        return role_to_edge.get(role, "RELATED_TO")

    def _get_reverse_edge_type_for_role(self, role: str) -> str:
        """Map person role to reverse edge type.

        This creates the reverse relationship from PersonNode to the source entity.

        Args:
            role: Person role string

        Returns:
            Reverse edge type string
        """
        role_to_reverse_edge = {
            "assignee": "ASSIGNED",
            "owner": "OWNS",
            "member": "MEMBER_OF",
            "follower": "FOLLOWS",
            "creator": "CREATED",
            "editor": "EDITED",
            "author": "AUTHORED",
            "reviewer": "REVIEWED",
            "approver": "APPROVED",
            "watcher": "WATCHES",
            "mentioned": "MENTIONED_IN",
            "other": "RELATED_TO",
        }
        return role_to_reverse_edge.get(role, "RELATED_TO")

    def _map_relation_type_to_edge(self, relation_type: str) -> str:
        """Map relation type to edge type.

        Args:
            relation_type: Relation type string

        Returns:
            Edge type string
        """
        relation_to_edge = {
            "parent": "HAS_PARENT",
            "child": "HAS_CHILD",
            "depends_on": "DEPENDS_ON",
            "blocks": "BLOCKS",
            "related_to": "RELATED_TO",
            "duplicate_of": "DUPLICATE_OF",
            "part_of": "PART_OF",
            "contains": "CONTAINS",
            "references": "REFERENCES",
            "attachment_of": "ATTACHMENT_OF",
            "comment_on": "COMMENT_ON",
            "other": "RELATED_TO",
        }
        return relation_to_edge.get(relation_type, "RELATED_TO")

    def _map_relation_type_to_reverse_edge(self, relation_type: str) -> str:
        """Map relation type to reverse edge type.

        Args:
            relation_type: Relation type string

        Returns:
            Reverse edge type string
        """
        relation_to_reverse_edge = {
            "parent": "HAS_CHILD",
            "child": "HAS_PARENT",
            "depends_on": "BLOCKS",
            "blocks": "DEPENDS_ON",
            "related_to": "RELATED_TO",
            "duplicate_of": "DUPLICATED_BY",
            "part_of": "CONTAINS",
            "contains": "PART_OF",
            "references": "REFERENCED_BY",
            "attachment_of": "HAS_ATTACHMENT",
            "comment_on": "HAS_COMMENT",
            "other": "RELATED_TO",
        }
        return relation_to_reverse_edge.get(relation_type, "RELATED_TO")
