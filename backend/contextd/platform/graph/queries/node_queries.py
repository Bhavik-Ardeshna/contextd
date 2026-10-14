"""Node-related Cypher query builders."""
import json
from typing import TYPE_CHECKING, Any, Dict, Optional, Set

if TYPE_CHECKING:
    from contextd.platform.graph.models.node import GraphNode


# Prefix for fulltext-searchable properties to avoid conflicts
FULLTEXT_PROPERTY_PREFIX = "ft_"

# Common searchable field names that will be extracted for fulltext indexing
DEFAULT_SEARCHABLE_FIELDS = {
    "name", "title", "description", "notes", "html_notes", "content",
    "text", "body", "summary", "workspace_name", "project_name",
    "current_status", "status", "tags", "labels", "owner", "team",
}


class NodeQueryBuilder:
    """Builds Cypher queries for node operations.

    Inspired by graphiti's query builders but simplified for our needs.
    All queries use MERGE for idempotent operations.

    Fulltext Search Support:
    - Searchable fields from entity properties are extracted and stored as
      individual node properties with 'ft_' prefix (e.g., ft_name, ft_notes)
    - The full properties JSON is also kept for complete data storage
    - This enables efficient Neo4j fulltext indexing on specific fields
    """

    @staticmethod
    def build_create_or_update_query() -> str:
        """Build query to create or update a node.

        Uses MERGE to handle both create and update cases.
        Node is identified by (node_id, organization_id) pair.

        Note: Searchable fields (ft_*) are set via the fulltext_properties parameter.
        """
        return """
        MERGE (n:GraphNode {node_id: $node_id, organization_id: $organization_id})
        ON CREATE SET
            n.node_type = $node_type,
            n.properties = $properties,
            n.metadata = $metadata,
            n.labels = $labels,
            n.created_at = datetime($created_at),
            n.updated_at = datetime($updated_at),
            n.source_sync_id = $source_sync_id,
            n.source_entity_definition_id = $source_entity_definition_id
        ON MATCH SET
            n.node_type = $node_type,
            n.properties = $properties,
            n.metadata = $metadata,
            n.labels = $labels,
            n.updated_at = datetime($updated_at),
            n.source_sync_id = $source_sync_id,
            n.source_entity_definition_id = $source_entity_definition_id
        WITH n
        // Set fulltext-searchable properties (ft_*)
        SET n += $fulltext_properties
        RETURN n.node_id as node_id, n.node_type as node_type
        """

    @staticmethod
    def build_get_by_id_query() -> str:
        """Build query to get a node by ID."""
        return """
        MATCH (n:GraphNode {node_id: $node_id, organization_id: $organization_id})
        RETURN n.node_id as node_id,
               COALESCE(n.node_type, 'Unknown') as node_type,
               COALESCE(n.properties, '{}') as properties,
               COALESCE(n.metadata, '{}') as metadata,
               n.organization_id as organization_id,
               COALESCE(n.labels, []) as labels,
               n.created_at as created_at,
               n.updated_at as updated_at,
               n.source_sync_id as source_sync_id,
               n.source_entity_definition_id as source_entity_definition_id
        """

    @staticmethod
    def build_get_by_organization_query() -> str:
        """Build query to get all nodes for an organization."""
        return """
        MATCH (n:GraphNode {organization_id: $organization_id})
        RETURN n.node_id as node_id,
               COALESCE(n.node_type, 'Unknown') as node_type,
               COALESCE(n.properties, '{}') as properties,
               COALESCE(n.metadata, '{}') as metadata,
               n.organization_id as organization_id,
               COALESCE(n.labels, []) as labels,
               n.created_at as created_at,
               n.updated_at as updated_at,
               n.source_sync_id as source_sync_id,
               n.source_entity_definition_id as source_entity_definition_id
        LIMIT $limit
        """

    @staticmethod
    def build_delete_query() -> str:
        """Build query to delete a node and its relationships."""
        return """
        MATCH (n:GraphNode {node_id: $node_id, organization_id: $organization_id})
        OPTIONAL MATCH (n)-[r]-()
        DELETE r, n
        RETURN count(n) as deleted_count
        """

    @staticmethod
    def build_batch_delete_query() -> str:
        """Build query to batch delete nodes and their relationships.

        Efficiently deletes multiple nodes by node_id within an organization.
        Uses UNWIND for batch processing.
        """
        return """
        UNWIND $node_ids as nid
        MATCH (n:GraphNode {node_id: nid, organization_id: $organization_id})
        OPTIONAL MATCH (n)-[r]-()
        DELETE r, n
        RETURN count(DISTINCT n) as deleted_count
        """

    @staticmethod
    def build_batch_create_or_update_query() -> str:
        """Build query to batch create or update nodes.

        Uses UNWIND for efficient batch processing.
        Note: Returns count of input rows processed, not unique nodes.

        Fulltext properties (ft_*) are merged via += operator to add searchable fields.
        """
        return """
        UNWIND $nodes as node_data
        MERGE (n:GraphNode {
            node_id: node_data.node_id,
            organization_id: node_data.organization_id
        })
        ON CREATE SET
            n.node_type = node_data.node_type,
            n.properties = node_data.properties,
            n.metadata = node_data.metadata,
            n.labels = node_data.labels,
            n.created_at = datetime(node_data.created_at),
            n.updated_at = datetime(node_data.updated_at),
            n.source_sync_id = node_data.source_sync_id,
            n.source_entity_definition_id = node_data.source_entity_definition_id
        ON MATCH SET
            n.node_type = node_data.node_type,
            n.properties = node_data.properties,
            n.metadata = node_data.metadata,
            n.labels = node_data.labels,
            n.updated_at = datetime(node_data.updated_at),
            n.source_sync_id = node_data.source_sync_id,
            n.source_entity_definition_id = node_data.source_entity_definition_id
        WITH n, node_data
        // Set fulltext-searchable properties (ft_*)
        SET n += node_data.fulltext_properties
        WITH n
        RETURN count(DISTINCT n) as nodes_processed
        """

    @staticmethod
    def build_node_exists_query() -> str:
        """Build query to check if a node exists."""
        return """
        MATCH (n:GraphNode {node_id: $node_id, organization_id: $organization_id})
        RETURN count(n) > 0 as exists
        """

    @staticmethod
    def _serialize_for_neo4j(data: Any) -> Any:
        """Serialize complex types for Neo4j storage.

        Neo4j only supports primitive types and arrays of primitives.
        Any nested dicts/objects must be JSON-serialized.

        Args:
            data: Data to serialize

        Returns:
            Neo4j-compatible data
        """
        if data is None:
            return None
        elif isinstance(data, (str, int, float, bool)):
            return data
        elif isinstance(data, dict):
            # Serialize nested dicts as JSON strings
            return json.dumps(data)
        elif isinstance(data, list):
            # Check if list contains only primitives
            if all(isinstance(item, (str, int, float, bool, type(None))) for item in data):
                return data
            else:
                # Contains complex types, serialize as JSON
                return json.dumps(data)
        else:
            # Other types (datetime, UUID, etc.) - convert to string
            return str(data)

    @staticmethod
    def _serialize_properties(properties: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize all property values for Neo4j compatibility.

        Args:
            properties: Property dictionary

        Returns:
            Serialized properties safe for Neo4j
        """
        serialized = {}
        for key, value in properties.items():
            serialized[key] = NodeQueryBuilder._serialize_for_neo4j(value)
        return serialized

    @staticmethod
    def extract_fulltext_properties(
        properties: Dict[str, Any],
        searchable_fields: Optional[Set[str]] = None,
    ) -> Dict[str, str]:
        """Extract fulltext-searchable properties from entity properties.

        Extracts specified fields from the properties dict and returns them
        as a flat dict with 'ft_' prefix for Neo4j fulltext indexing.

        Args:
            properties: Entity properties dict
            searchable_fields: Set of field names to extract (uses defaults if None)

        Returns:
            Dict of {ft_fieldname: value} for searchable fields
        """
        if not properties:
            return {}

        fields_to_extract = searchable_fields or DEFAULT_SEARCHABLE_FIELDS
        fulltext_props = {}

        for field in fields_to_extract:
            if field in properties:
                value = properties[field]
                # Convert to string for fulltext indexing
                if value is not None:
                    if isinstance(value, (list, dict)):
                        # Convert complex types to JSON string
                        fulltext_props[f"{FULLTEXT_PROPERTY_PREFIX}{field}"] = json.dumps(value)
                    else:
                        fulltext_props[f"{FULLTEXT_PROPERTY_PREFIX}{field}"] = str(value)

        return fulltext_props

    @staticmethod
    def prepare_node_parameters(
        node: "GraphNode",
        searchable_fields: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """Prepare node data for query parameters.

        Extracts searchable fields from properties and stores them separately
        as ft_* properties for efficient fulltext indexing.

        Args:
            node: GraphNode instance
            searchable_fields: Optional set of field names to extract for fulltext

        Returns:
            Dictionary of query parameters including fulltext_properties
        """
        import json

        # Convert entire properties and metadata dicts to JSON strings
        # Neo4j doesn't support nested dictionaries, so we store them as JSON
        properties_json = json.dumps(node.properties) if node.properties else "{}"
        metadata_json = json.dumps(node.metadata) if node.metadata else "{}"

        # Extract fulltext-searchable properties
        fulltext_properties = NodeQueryBuilder.extract_fulltext_properties(
            node.properties, searchable_fields
        )

        return {
            "node_id": node.node_id,
            "node_type": node.node_type,
            "properties": properties_json,  # JSON string, not dict
            "metadata": metadata_json,      # JSON string, not dict
            "organization_id": str(node.organization_id),
            "labels": node.labels,
            "created_at": node.created_at.isoformat(),
            "updated_at": node.updated_at.isoformat(),
            "source_sync_id": str(node.source_sync_id) if node.source_sync_id else None,
            "source_entity_definition_id": str(node.source_entity_definition_id) if node.source_entity_definition_id else None,
            "fulltext_properties": fulltext_properties,  # Individual searchable fields
        }
