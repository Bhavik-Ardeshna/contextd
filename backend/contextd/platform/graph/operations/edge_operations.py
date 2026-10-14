"""Edge CRUD operations."""
import json
import logging
from typing import List, Optional
from uuid import UUID

from ..driver.neo4j_driver import Neo4jDriver
from ..models.edge import GraphEdge
from ..queries.edge_queries import EdgeQueryBuilder

logger = logging.getLogger(__name__)


class EdgeOperations:
    """Handles all edge-related database operations.

    Provides high-level interface for edge CRUD operations.
    """

    def __init__(self, driver: Neo4jDriver):
        """Initialize edge operations.

        Args:
            driver: Neo4j driver instance
        """
        self.driver = driver
        self.query_builder = EdgeQueryBuilder()

    async def create_or_update(self, edge: GraphEdge) -> GraphEdge:
        """Create or update an edge.

        Args:
            edge: Edge to create or update

        Returns:
            Created/updated edge

        Raises:
            Exception: If source or target node doesn't exist
        """
        query = self.query_builder.build_create_or_update_query()
        params = self.query_builder.prepare_edge_parameters(edge)

        try:
            await self.driver.execute_write(query, params)
            logger.debug(f"Created/updated edge: {edge.edge_id}")
            return edge
        except Exception as e:
            logger.error(f"Failed to create/update edge {edge.edge_id}: {e}")
            raise

    async def get_by_id(
        self,
        edge_id: str,
        organization_id: UUID,
    ) -> Optional[GraphEdge]:
        """Get an edge by ID.

        Args:
            edge_id: Edge ID
            organization_id: Organization ID

        Returns:
            Edge if found, None otherwise
        """
        query = self.query_builder.build_get_by_id_query()
        params = {
            "edge_id": edge_id,
            "organization_id": str(organization_id),
        }

        try:
            records = await self.driver.execute_read(query, params)
            if not records:
                return None

            record = records[0]

            # Deserialize JSON strings back to dicts
            properties = json.loads(record["properties"]) if isinstance(record["properties"], str) else (record["properties"] or {})
            metadata = json.loads(record["metadata"]) if isinstance(record["metadata"], str) else (record["metadata"] or {})

            return GraphEdge(
                edge_id=record["edge_id"],
                relationship_type=record["relationship_type"],
                source_node_id=record["source_node_id"],
                target_node_id=record["target_node_id"],
                fact=record["fact"],
                fact_embedding=record.get("fact_embedding"),
                properties=properties,
                metadata=metadata,
                organization_id=UUID(record["organization_id"]),
                created_at=record["created_at"],
                updated_at=record["updated_at"],
                source_sync_id=UUID(record["source_sync_id"]) if record.get("source_sync_id") else None,
                source_entity_definition_id=UUID(record["source_entity_definition_id"]) if record.get("source_entity_definition_id") else None,
                valid_at=record.get("valid_at"),
                invalid_at=record.get("invalid_at"),
            )
        except Exception as e:
            logger.error(f"Failed to get edge {edge_id}: {e}")
            raise

    async def get_by_nodes(
        self,
        source_node_id: str,
        target_node_id: str,
        organization_id: UUID,
    ) -> List[GraphEdge]:
        """Get edges between two nodes.

        Args:
            source_node_id: Source node ID
            target_node_id: Target node ID
            organization_id: Organization ID

        Returns:
            List of edges between the nodes
        """
        query = self.query_builder.build_get_by_nodes_query()
        params = {
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "organization_id": str(organization_id),
        }

        try:
            records = await self.driver.execute_read(query, params)
            edges = []
            for record in records:
                # Deserialize JSON strings back to dicts
                properties = json.loads(record["properties"]) if isinstance(record["properties"], str) else (record["properties"] or {})
                metadata = json.loads(record["metadata"]) if isinstance(record["metadata"], str) else (record["metadata"] or {})

                edge = GraphEdge(
                    edge_id=record["edge_id"],
                    relationship_type=record["relationship_type"],
                    source_node_id=record["source_node_id"],
                    target_node_id=record["target_node_id"],
                    fact=record["fact"],
                    fact_embedding=record.get("fact_embedding"),
                    properties=properties,
                    metadata=metadata,
                    organization_id=UUID(record["organization_id"]),
                    created_at=record["created_at"],
                    updated_at=record["updated_at"],
                    source_sync_id=UUID(record["source_sync_id"]) if record.get("source_sync_id") else None,
                    source_entity_definition_id=UUID(record["source_entity_definition_id"]) if record.get("source_entity_definition_id") else None,
                    valid_at=record.get("valid_at"),
                    invalid_at=record.get("invalid_at"),
                )
                edges.append(edge)

            return edges
        except Exception as e:
            logger.error(f"Failed to get edges between nodes: {e}")
            raise

    async def get_by_organization(
        self,
        organization_id: UUID,
        limit: int = 1000,
    ) -> List[GraphEdge]:
        """Get all edges for an organization.

        Args:
            organization_id: Organization ID
            limit: Maximum number of edges to return

        Returns:
            List of edges
        """
        query = self.query_builder.build_get_by_organization_query()
        params = {
            "organization_id": str(organization_id),
            "limit": limit,
        }

        try:
            records = await self.driver.execute_read(query, params)

            edges = []
            for record in records:
                # Deserialize JSON strings back to dicts
                properties = json.loads(record["properties"]) if isinstance(record["properties"], str) else (record["properties"] or {})
                metadata = json.loads(record["metadata"]) if isinstance(record["metadata"], str) else (record["metadata"] or {})

                # DateTime conversion is now handled by the driver
                edge = GraphEdge(
                    edge_id=record["edge_id"],
                    relationship_type=record["relationship_type"],
                    source_node_id=record["source_node_id"],
                    target_node_id=record["target_node_id"],
                    fact=record["fact"],
                    properties=properties,
                    metadata=metadata,
                    organization_id=UUID(record["organization_id"]),
                    created_at=record["created_at"],
                    updated_at=record["updated_at"],
                )
                edges.append(edge)

            logger.debug(f"Retrieved {len(edges)} edges for organization {organization_id}")
            return edges
        except Exception as e:
            logger.error(f"Failed to get edges for organization {organization_id}: {e}")
            raise

    async def get_node_edges(
        self,
        node_id: str,
        organization_id: UUID,
        limit: int = 100,
    ) -> List[GraphEdge]:
        """Get all edges connected to a node.

        Args:
            node_id: Node ID
            organization_id: Organization ID
            limit: Maximum number of edges to return

        Returns:
            List of edges
        """
        query = self.query_builder.build_get_node_edges_query()
        params = {
            "node_id": node_id,
            "organization_id": str(organization_id),
            "limit": limit,
        }

        try:
            records = await self.driver.execute_read(query, params)
            edges = []
            for record in records:
                # Deserialize JSON strings back to dicts
                properties = json.loads(record["properties"]) if isinstance(record["properties"], str) else (record["properties"] or {})
                metadata = json.loads(record["metadata"]) if isinstance(record["metadata"], str) else (record["metadata"] or {})

                edge = GraphEdge(
                    edge_id=record["edge_id"],
                    relationship_type=record["relationship_type"],
                    source_node_id=record["source_node_id"],
                    target_node_id=record["target_node_id"],
                    fact=record["fact"],
                    properties=properties,
                    metadata=metadata,
                    organization_id=organization_id,
                    created_at=record["created_at"],
                    updated_at=record["updated_at"],
                )
                edges.append(edge)

            return edges
        except Exception as e:
            logger.error(f"Failed to get edges for node {node_id}: {e}")
            raise

    async def delete(
        self,
        edge_id: str,
        organization_id: UUID,
    ) -> bool:
        """Delete an edge.

        Args:
            edge_id: Edge ID
            organization_id: Organization ID

        Returns:
            True if deleted, False otherwise
        """
        query = self.query_builder.build_delete_query()
        params = {
            "edge_id": edge_id,
            "organization_id": str(organization_id),
        }

        try:
            records = await self.driver.execute_write(query, params)
            deleted = records[0]["deleted_count"] > 0 if records else False
            if deleted:
                logger.debug(f"Deleted edge: {edge_id}")
            return deleted
        except Exception as e:
            logger.error(f"Failed to delete edge {edge_id}: {e}")
            raise

    async def batch_create_or_update(self, edges: List[GraphEdge]) -> int:
        """Batch create or update edges.

        Args:
            edges: List of edges to create/update

        Returns:
            Number of edges processed

        Raises:
            Exception: If any source or target node doesn't exist
        """
        if not edges:
            return 0

        query = self.query_builder.build_batch_create_or_update_query()
        edges_data = [
            self.query_builder.prepare_edge_parameters(edge)
            for edge in edges
        ]
        params = {"edges": edges_data}

        try:
            logger.debug(f"Executing batch edge creation for {len(edges)} edges")
            logger.debug(f"Edge source->target: {[(e.source_node_id, e.target_node_id) for e in edges]}")
            logger.debug(f"Organization ID: {edges[0].organization_id if edges else 'none'}")

            records = await self.driver.execute_write(query, params)
            count = records[0]["edges_processed"] if records else 0

            logger.info(f"Batch processed {count} edges (expected {len(edges)})")

            if count != len(edges):
                logger.warning(f"Edge count mismatch: processed {count}, expected {len(edges)}")
                logger.warning("Checking if source/target nodes exist...")

                # Get all unique node IDs that edges reference
                all_node_ids = set()
                for edge in edges:
                    all_node_ids.add(edge.source_node_id)
                    all_node_ids.add(edge.target_node_id)

                # Check which nodes exist
                verify_query = """
                MATCH (n:GraphNode)
                WHERE n.node_id IN $node_ids AND n.organization_id = $org_id
                RETURN n.node_id
                """
                verify_params = {
                    "node_ids": list(all_node_ids),
                    "org_id": str(edges[0].organization_id)
                }
                existing = await self.driver.execute_read(verify_query, verify_params)
                existing_ids = {rec["n.node_id"] for rec in existing}

                missing_nodes = all_node_ids - existing_ids

                logger.warning(f"Expected {len(all_node_ids)} unique nodes for edges")
                logger.warning(f"Found {len(existing_ids)} nodes in Neo4j")
                logger.warning(f"Missing nodes: {missing_nodes}")

            return count
        except Exception as e:
            logger.error(f"Failed to batch create/update edges: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params keys: {list(params.keys())}")
            raise
