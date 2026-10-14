"""Graph construction service.

Converts graph events to Neo4j nodes and edges.
Main orchestrator for building the knowledge graph.

ID Consistency:
---------------
The graph uses entity_id as node_id to ensure traceability across storage systems:
- PostgreSQL entity.entity_id == Graph node.node_id

This allows querying related data across systems:
    SELECT e.*, n.* FROM entity e
    JOIN graph_node n ON e.entity_id = n.node_id
    WHERE e.entity_id = 'some_id';

The event generator already sets node_id = entity.entity_id for source entity nodes.
This constructor preserves that ID when creating/updating nodes.
"""
import logging
from datetime import datetime
from typing import Dict, List
from uuid import UUID

from contextd.platform.contexts.sync import SyncContext
from contextd.schemas.graph_event import (
    EdgeEventPayload,
    NodeEventPayload,
    TypedGraphEvent,
)

from .driver.neo4j_driver import Neo4jDriver
from .models.edge import GraphEdge
from .models.node import GraphNode
from .operations.edge_operations import EdgeOperations
from .operations.node_operations import NodeOperations

logger = logging.getLogger(__name__)


class GraphConstructor:
    """Main service for constructing the knowledge graph.

    Responsibilities:
    1. Convert graph events to GraphNode/GraphEdge models
    2. Coordinate batch operations for efficiency
    3. Handle node/edge lifecycle (create, update, delete)
    4. Manage organization-scoped graphs

    Inspired by graphiti's Graphiti class but simplified for our use case.
    """

    def __init__(
        self,
        driver: Neo4jDriver,
        batch_size: int = 100,
    ):
        """Initialize graph constructor.

        Args:
            driver: Neo4j driver instance
            batch_size: Number of operations to batch together
        """
        self.driver = driver
        self.batch_size = batch_size

        # Initialize operations handlers
        self.node_ops = NodeOperations(driver)
        self.edge_ops = EdgeOperations(driver)

    async def process_events(
        self,
        events: List[TypedGraphEvent],
        sync_context: SyncContext,
    ) -> Dict[str, int]:
        """Process a batch of graph events.

        Args:
            events: List of graph events to process
            sync_context: Sync context

        Returns:
            Statistics about processing (nodes_created, edges_created, etc.)
        """
        if not events:
            return {"nodes_processed": 0, "edges_processed": 0}

        # Separate events by type
        node_events = []
        edge_events = []

        for event in events:
            if event.event_type.startswith("NODE"):
                node_events.append(event)
            elif event.event_type.startswith("EDGE"):
                edge_events.append(event)

        stats = {
            "nodes_processed": 0,
            "edges_processed": 0,
        }

        # Process nodes first (edges require nodes to exist)
        if node_events:
            stats["nodes_processed"] = await self._process_node_events(
                node_events, sync_context
            )

        # Then process edges
        if edge_events:
            stats["edges_processed"] = await self._process_edge_events(
                edge_events, sync_context
            )

        logger.info(
            f"Processed {stats['nodes_processed']} nodes and "
            f"{stats['edges_processed']} edges for organization {sync_context.organization_id}"
        )

        return stats

    async def _process_node_events(
        self,
        events: List[TypedGraphEvent],
        sync_context: SyncContext,
    ) -> int:
        """Process node-related events.

        Args:
            events: List of node events
            sync_context: Sync context

        Returns:
            Number of nodes processed
        """
        nodes_to_upsert = []
        nodes_to_delete = []

        for event in events:
            payload = event.payload
            if not isinstance(payload, NodeEventPayload):
                logger.warning(f"Unexpected payload type for node event: {type(payload)}")
                continue

            if payload.operation == "DELETE":
                nodes_to_delete.append((payload.node_id, sync_context.organization_id))
            else:
                # CREATE or UPDATE
                node = self._event_to_node(event, sync_context)
                nodes_to_upsert.append(node)

        # Batch upsert nodes
        count = 0
        if nodes_to_upsert:
            count += await self.node_ops.batch_create_or_update(nodes_to_upsert)

        # Batch delete nodes for efficiency
        if nodes_to_delete:
            # Group by organization_id for batch delete
            # (typically all same org, but handle multiple just in case)
            deletes_by_org: Dict[UUID, List[str]] = {}
            for node_id, org_id in nodes_to_delete:
                if org_id not in deletes_by_org:
                    deletes_by_org[org_id] = []
                deletes_by_org[org_id].append(node_id)

            for org_id, node_ids in deletes_by_org.items():
                try:
                    deleted = await self.node_ops.batch_delete(node_ids, org_id)
                    count += deleted
                    logger.info(f"Batch deleted {deleted} nodes for organization {org_id}")
                except Exception as e:
                    logger.error(f"Failed to batch delete nodes: {e}")
                    # Fallback to individual deletes
                    for node_id in node_ids:
                        try:
                            if await self.node_ops.delete(node_id, org_id):
                                count += 1
                        except Exception as inner_e:
                            logger.error(f"Failed to delete node {node_id}: {inner_e}")

        return count

    async def _process_edge_events(
        self,
        events: List[TypedGraphEvent],
        sync_context: SyncContext,
    ) -> int:
        """Process edge-related events.

        Args:
            events: List of edge events
            sync_context: Sync context

        Returns:
            Number of edges processed
        """
        edges_to_upsert = []
        edges_to_delete = []

        for event in events:
            payload = event.payload
            if not isinstance(payload, EdgeEventPayload):
                logger.warning(f"Unexpected payload type for edge event: {type(payload)}")
                continue

            if payload.operation == "DELETE":
                # Generate edge ID for deletion
                edge_id = self._generate_edge_id(
                    payload.from_node.node_id,
                    payload.to_node.node_id,
                    payload.edge_type,
                )
                edges_to_delete.append((edge_id, sync_context.organization_id))
            else:
                # CREATE or UPDATE
                edge = self._event_to_edge(event, sync_context)
                edges_to_upsert.append(edge)

        # Batch upsert edges
        count = 0
        if edges_to_upsert:
            count += await self.edge_ops.batch_create_or_update(edges_to_upsert)

        # Delete edges
        for edge_id, org_id in edges_to_delete:
            try:
                deleted = await self.edge_ops.delete(edge_id, org_id)
                if deleted:
                    count += 1
            except Exception as e:
                logger.error(f"Failed to delete edge {edge_id}: {e}")

        return count

    def _event_to_node(
        self,
        event: TypedGraphEvent,
        sync_context: SyncContext,
    ) -> GraphNode:
        """Convert a graph event to a GraphNode.

        ID Consistency: The node_id is set from event.payload.node_id, which
        should match entity.entity_id for source entity nodes. This ensures
        the same ID is used in PostgreSQL and Neo4j.

        Args:
            event: Graph event
            sync_context: Sync context

        Returns:
            GraphNode instance
        """
        payload = event.payload
        assert isinstance(payload, NodeEventPayload)

        now = datetime.utcnow()

        # Validate ID consistency: for source entity nodes, node_id should match entity_id
        if event.entity_id and payload.node_id == event.entity_id:
            logger.debug(
                f"ID consistency verified: node_id={payload.node_id} matches entity_id={event.entity_id}"
            )

        return GraphNode(
            node_id=payload.node_id,
            node_type=payload.node_type,
            properties=payload.node_properties,
            metadata=event.metadata or {},
            organization_id=sync_context.organization_id,
            labels=[payload.node_type],  # Use node_type as label
            created_at=event.timestamp or now,
            updated_at=now,
            source_sync_id=sync_context.sync_id,
            source_entity_definition_id=event.entity_definition_id,
        )

    def _event_to_edge(
        self,
        event: TypedGraphEvent,
        sync_context: SyncContext,
    ) -> GraphEdge:
        """Convert a graph event to a GraphEdge.

        Args:
            event: Graph event
            sync_context: Sync context

        Returns:
            GraphEdge instance
        """
        payload = event.payload
        assert isinstance(payload, EdgeEventPayload)

        now = datetime.utcnow()

        # Generate stable edge ID based on nodes and relationship type
        edge_id = self._generate_edge_id(
            payload.from_node.node_id,
            payload.to_node.node_id,
            payload.edge_type,
        )

        # Generate fact text for the relationship
        fact = self._generate_fact_text(payload)

        return GraphEdge(
            edge_id=edge_id,
            relationship_type=payload.edge_type,
            source_node_id=payload.from_node.node_id,
            target_node_id=payload.to_node.node_id,
            fact=fact,
            fact_embedding=None,  # Will be generated later if needed
            properties=payload.edge_properties,
            metadata=event.metadata or {},
            organization_id=sync_context.organization_id,
            created_at=event.timestamp or now,
            updated_at=now,
            source_sync_id=sync_context.sync_id,
            source_entity_definition_id=event.entity_definition_id,
        )

    def _generate_edge_id(
        self,
        source_node_id: str,
        target_node_id: str,
        relationship_type: str,
    ) -> str:
        """Generate a stable edge ID.

        Uses a deterministic hash of the nodes and relationship type.

        Args:
            source_node_id: Source node ID
            target_node_id: Target node ID
            relationship_type: Relationship type

        Returns:
            Edge ID string
        """
        import hashlib

        # Create deterministic ID
        hash_input = f"{source_node_id}|{relationship_type}|{target_node_id}"
        edge_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        return f"edge_{edge_hash}"

    def _generate_fact_text(self, payload: EdgeEventPayload) -> str:
        """Generate natural language fact text for an edge.

        Args:
            payload: Edge event payload

        Returns:
            Fact text describing the relationship
        """
        # Format: "source_node [relationship_type] target_node"
        # Example: "John Smith [ASSIGNED_TO] Project Alpha"

        source_name = payload.edge_properties.get("source_name", payload.from_node.node_id)
        target_name = payload.edge_properties.get("target_name", payload.to_node.node_id)

        # Make relationship type more readable
        rel_type_readable = payload.edge_type.replace("_", " ").lower()

        return f"{source_name} {rel_type_readable} {target_name}"

    async def get_graph_for_organization(
        self,
        organization_id: UUID,
        limit: int = 1000,
    ) -> Dict[str, List]:
        """Get the entire graph for an organization.

        Useful for visualization and debugging.

        Args:
            organization_id: Organization ID
            limit: Maximum number of nodes/edges to return

        Returns:
            Dictionary with 'nodes' and 'edges' lists
        """
        try:
            nodes = await self.node_ops.get_by_organization(organization_id, limit)
            edges = await self.edge_ops.get_by_organization(organization_id, limit)

            # Use model_dump with mode='json' to properly serialize datetime objects
            node_dicts = [node.model_dump(mode='json') for node in nodes]
            edge_dicts = [edge.model_dump(mode='json') for edge in edges]

            return {
                "nodes": node_dicts,
                "edges": edge_dicts,
            }
        except Exception as e:
            logger.error(f"Failed to get graph for organization {organization_id}: {e}")
            raise

    async def batch_delete_orphans(
        self,
        node_ids: List[str],
        organization_id: UUID,
    ) -> Dict[str, int]:
        """Batch delete orphaned nodes and their edges from the graph.

        Used during sync cleanup to remove nodes that no longer exist in the source.
        This is more efficient than individual deletes for large orphan sets.

        Note: Fulltext index entries are automatically cleaned up when nodes are
        deleted - Neo4j fulltext indexes are live and track their indexed nodes.

        Args:
            node_ids: List of node IDs to delete
            organization_id: Organization ID

        Returns:
            Statistics about deletion operation
        """
        if not node_ids:
            return {"nodes_deleted": 0, "status": "skipped"}

        try:
            deleted_count = await self.node_ops.batch_delete(node_ids, organization_id)

            logger.info(
                f"[GraphConstructor] Batch deleted {deleted_count} orphaned nodes "
                f"for organization {organization_id}"
            )

            return {
                "nodes_deleted": deleted_count,
                "requested_count": len(node_ids),
                "status": "success",
            }
        except Exception as e:
            logger.error(
                f"[GraphConstructor] Failed to batch delete orphans: {e}",
                exc_info=True
            )
            return {
                "nodes_deleted": 0,
                "requested_count": len(node_ids),
                "status": "error",
                "error": str(e),
            }

    async def close(self):
        """Close the driver connection."""
        await self.driver.close()
