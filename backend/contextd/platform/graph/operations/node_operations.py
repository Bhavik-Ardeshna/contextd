"""Node CRUD operations."""
import json
import logging
from typing import List, Optional
from uuid import UUID

from ..driver.neo4j_driver import Neo4jDriver
from ..models.node import GraphNode
from ..queries.node_queries import NodeQueryBuilder

logger = logging.getLogger(__name__)


class NodeOperations:
    """Handles all node-related database operations.

    Provides high-level interface for node CRUD operations.
    """

    def __init__(self, driver: Neo4jDriver):
        """Initialize node operations.

        Args:
            driver: Neo4j driver instance
        """
        self.driver = driver
        self.query_builder = NodeQueryBuilder()

    async def create_or_update(self, node: GraphNode) -> GraphNode:
        """Create or update a node.

        Args:
            node: Node to create or update

        Returns:
            Created/updated node
        """
        query = self.query_builder.build_create_or_update_query()
        params = self.query_builder.prepare_node_parameters(node)

        try:
            await self.driver.execute_write(query, params)
            logger.debug(f"Created/updated node: {node.node_id}")
            return node
        except Exception as e:
            logger.error(f"Failed to create/update node {node.node_id}: {e}")
            raise

    async def get_by_id(
        self,
        node_id: str,
        organization_id: UUID,
    ) -> Optional[GraphNode]:
        """Get a node by ID.

        Args:
            node_id: Node ID
            organization_id: Organization ID

        Returns:
            Node if found, None otherwise
        """
        query = self.query_builder.build_get_by_id_query()
        params = {
            "node_id": node_id,
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

            return GraphNode(
                node_id=record["node_id"],
                node_type=record["node_type"],
                properties=properties,
                metadata=metadata,
                organization_id=UUID(record["organization_id"]),
                labels=record["labels"] or [],
                created_at=record["created_at"],
                updated_at=record["updated_at"],
                source_sync_id=UUID(record["source_sync_id"]) if record.get("source_sync_id") else None,
                source_entity_definition_id=UUID(record["source_entity_definition_id"]) if record.get("source_entity_definition_id") else None,
            )
        except Exception as e:
            logger.error(f"Failed to get node {node_id}: {e}")
            raise

    async def get_by_organization(
        self,
        organization_id: UUID,
        limit: int = 1000,
    ) -> List[GraphNode]:
        """Get all nodes for an organization.

        Args:
            organization_id: Organization ID
            limit: Maximum number of nodes to return

        Returns:
            List of nodes
        """
        query = self.query_builder.build_get_by_organization_query()
        params = {
            "organization_id": str(organization_id),
            "limit": limit,
        }

        try:
            records = await self.driver.execute_read(query, params)

            nodes = []
            for record in records:
                # Deserialize JSON strings back to dicts
                properties = json.loads(record["properties"]) if isinstance(record["properties"], str) else (record["properties"] or {})
                metadata = json.loads(record["metadata"]) if isinstance(record["metadata"], str) else (record["metadata"] or {})

                # Handle NULL node_type (fallback to "Unknown" or infer from entity_type in properties)
                node_type = record.get("node_type")
                if not node_type:
                    # Try to infer from properties.entity_type or use default
                    node_type = properties.get("entity_type") or "Unknown"

                # DateTime conversion is now handled by the driver
                node = GraphNode(
                    node_id=record["node_id"],
                    node_type=node_type,
                    properties=properties,
                    metadata=metadata,
                    organization_id=UUID(record["organization_id"]),
                    labels=record["labels"] or [],
                    created_at=record["created_at"],
                    updated_at=record["updated_at"],
                    source_sync_id=UUID(record["source_sync_id"]) if record.get("source_sync_id") else None,
                    source_entity_definition_id=UUID(record["source_entity_definition_id"]) if record.get("source_entity_definition_id") else None,
                )
                nodes.append(node)

            logger.debug(f"Retrieved {len(nodes)} nodes for organization {organization_id}")
            return nodes
        except Exception as e:
            logger.error(f"Failed to get nodes for organization {organization_id}: {e}")
            raise

    async def delete(
        self,
        node_id: str,
        organization_id: UUID,
    ) -> bool:
        """Delete a node.

        Args:
            node_id: Node ID
            organization_id: Organization ID

        Returns:
            True if deleted, False otherwise
        """
        query = self.query_builder.build_delete_query()
        params = {
            "node_id": node_id,
            "organization_id": str(organization_id),
        }

        try:
            records = await self.driver.execute_write(query, params)
            deleted = records[0]["deleted_count"] > 0 if records else False
            if deleted:
                logger.debug(f"Deleted node: {node_id}")
            return deleted
        except Exception as e:
            logger.error(f"Failed to delete node {node_id}: {e}")
            raise

    async def batch_create_or_update(self, nodes: List[GraphNode]) -> int:
        """Batch create or update nodes.

        Deduplicates nodes by node_id before processing to avoid redundant
        Neo4j operations. When multiple events reference the same node,
        the last one wins (most recent data).

        Args:
            nodes: List of nodes to create/update (may contain duplicates)

        Returns:
            Number of unique nodes processed
        """
        if not nodes:
            return 0

        # Deduplicate nodes by node_id - last occurrence wins (most recent data)
        unique_nodes_map: dict[str, GraphNode] = {}
        for node in nodes:
            unique_nodes_map[node.node_id] = node

        unique_nodes = list(unique_nodes_map.values())

        if len(nodes) != len(unique_nodes):
            logger.debug(
                f"Deduplicated {len(nodes)} node events to {len(unique_nodes)} unique nodes"
            )

        query = self.query_builder.build_batch_create_or_update_query()
        nodes_data = [
            self.query_builder.prepare_node_parameters(node)
            for node in unique_nodes
        ]
        params = {"nodes": nodes_data}

        try:
            logger.debug(f"Executing batch node creation for {len(unique_nodes)} unique nodes")
            logger.debug(f"Node IDs: {[n.node_id for n in unique_nodes]}")
            logger.debug(f"Node types: {[n.node_type for n in unique_nodes]}")
            logger.debug(f"Organization ID: {unique_nodes[0].organization_id if unique_nodes else 'none'}")

            records = await self.driver.execute_write(query, params)
            count = records[0]["nodes_processed"] if records else 0

            logger.debug(f"Batch processed {count} nodes (expected {len(unique_nodes)})")

            # Only warn if there's a real mismatch (not from deduplication)
            if count != len(unique_nodes):
                logger.warning(f"Node count mismatch: processed {count}, expected {len(unique_nodes)}")
                logger.warning(f"Expected node_ids: {[n.node_id for n in unique_nodes]}")
                # Check what actually exists in Neo4j
                verify_query = """
                MATCH (n:GraphNode)
                WHERE n.node_id IN $node_ids AND n.organization_id = $org_id
                RETURN n.node_id, n.node_type
                """
                verify_params = {
                    "node_ids": [n.node_id for n in unique_nodes],
                    "org_id": str(unique_nodes[0].organization_id)
                }
                existing = await self.driver.execute_read(verify_query, verify_params)
                logger.warning(f"Nodes found in Neo4j: {existing}")

            return count
        except Exception as e:
            logger.error(f"Failed to batch create/update nodes: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params keys: {list(params.keys())}")
            raise

    async def exists(
        self,
        node_id: str,
        organization_id: UUID,
    ) -> bool:
        """Check if a node exists.

        Args:
            node_id: Node ID
            organization_id: Organization ID

        Returns:
            True if exists, False otherwise
        """
        query = self.query_builder.build_node_exists_query()
        params = {
            "node_id": node_id,
            "organization_id": str(organization_id),
        }

        try:
            records = await self.driver.execute_read(query, params)
            return records[0]["exists"] if records else False
        except Exception as e:
            logger.error(f"Failed to check if node exists {node_id}: {e}")
            raise

    async def batch_delete(
        self,
        node_ids: List[str],
        organization_id: UUID,
    ) -> int:
        """Batch delete nodes and their relationships.

        Efficiently deletes multiple nodes in a single query.
        All relationships connected to these nodes are also deleted.

        Args:
            node_ids: List of node IDs to delete
            organization_id: Organization ID

        Returns:
            Number of nodes deleted
        """
        if not node_ids:
            return 0

        query = self.query_builder.build_batch_delete_query()
        params = {
            "node_ids": node_ids,
            "organization_id": str(organization_id),
        }

        try:
            records = await self.driver.execute_write(query, params)
            deleted = records[0]["deleted_count"] if records else 0

            if deleted > 0:
                logger.info(
                    f"Batch deleted {deleted} nodes for organization {organization_id}"
                )

            return deleted
        except Exception as e:
            logger.error(
                f"Failed to batch delete nodes for organization {organization_id}: {e}"
            )
            raise
