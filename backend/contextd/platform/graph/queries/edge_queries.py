"""Edge-related Cypher query builders."""
import json
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from contextd.platform.graph.models.edge import GraphEdge


class EdgeQueryBuilder:
    """Builds Cypher queries for edge operations.

    Handles relationship creation with fact embeddings.
    Uses MERGE for nodes to auto-create stubs if they don't exist,
    preventing silent failures from batch ordering issues.
    """

    @staticmethod
    def build_create_or_update_query() -> str:
        """Build query to create or update an edge.

        Uses MERGE for nodes to auto-create stubs if they don't exist.
        Stores fact and fact_embedding on the relationship.
        """
        return """
        MERGE (source:GraphNode {node_id: $source_node_id, organization_id: $organization_id})
        ON CREATE SET source.node_type = 'Unknown', source.created_at = datetime(), source._stub = true
        MERGE (target:GraphNode {node_id: $target_node_id, organization_id: $organization_id})
        ON CREATE SET target.node_type = 'Unknown', target.created_at = datetime(), target._stub = true
        MERGE (source)-[r:RELATES_TO {edge_id: $edge_id}]->(target)
        ON CREATE SET
            r.relationship_type = $relationship_type,
            r.fact = $fact,
            r.fact_embedding = $fact_embedding,
            r.properties = $properties,
            r.metadata = $metadata,
            r.organization_id = $organization_id,
            r.created_at = datetime($created_at),
            r.updated_at = datetime($updated_at),
            r.source_sync_id = $source_sync_id,
            r.source_entity_definition_id = $source_entity_definition_id,
            r.valid_at = CASE WHEN $valid_at IS NOT NULL THEN datetime($valid_at) ELSE NULL END,
            r.invalid_at = CASE WHEN $invalid_at IS NOT NULL THEN datetime($invalid_at) ELSE NULL END
        ON MATCH SET
            r.relationship_type = $relationship_type,
            r.fact = $fact,
            r.fact_embedding = $fact_embedding,
            r.properties = $properties,
            r.metadata = $metadata,
            r.updated_at = datetime($updated_at),
            r.source_sync_id = $source_sync_id,
            r.source_entity_definition_id = $source_entity_definition_id,
            r.valid_at = CASE WHEN $valid_at IS NOT NULL THEN datetime($valid_at) ELSE NULL END,
            r.invalid_at = CASE WHEN $invalid_at IS NOT NULL THEN datetime($invalid_at) ELSE NULL END
        RETURN r.edge_id as edge_id, r.relationship_type as relationship_type
        """

    @staticmethod
    def build_get_by_id_query() -> str:
        """Build query to get an edge by ID."""
        return """
        MATCH (source:GraphNode)-[r:RELATES_TO {edge_id: $edge_id}]->(target:GraphNode)
        WHERE r.organization_id = $organization_id
        RETURN r.edge_id as edge_id,
               r.relationship_type as relationship_type,
               COALESCE(r.fact, '') as fact,
               r.fact_embedding as fact_embedding,
               COALESCE(r.properties, '{}') as properties,
               COALESCE(r.metadata, '{}') as metadata,
               r.organization_id as organization_id,
               r.created_at as created_at,
               r.updated_at as updated_at,
               r.source_sync_id as source_sync_id,
               r.source_entity_definition_id as source_entity_definition_id,
               r.valid_at as valid_at,
               r.invalid_at as invalid_at,
               source.node_id as source_node_id,
               target.node_id as target_node_id
        """

    @staticmethod
    def build_get_by_nodes_query() -> str:
        """Build query to get edges between two nodes."""
        return """
        MATCH (source:GraphNode {node_id: $source_node_id})-[r:RELATES_TO]->(target:GraphNode {node_id: $target_node_id})
        WHERE r.organization_id = $organization_id
        RETURN r.edge_id as edge_id,
               r.relationship_type as relationship_type,
               COALESCE(r.fact, '') as fact,
               r.fact_embedding as fact_embedding,
               COALESCE(r.properties, '{}') as properties,
               COALESCE(r.metadata, '{}') as metadata,
               r.organization_id as organization_id,
               r.created_at as created_at,
               r.updated_at as updated_at,
               r.source_sync_id as source_sync_id,
               r.source_entity_definition_id as source_entity_definition_id,
               r.valid_at as valid_at,
               r.invalid_at as invalid_at,
               source.node_id as source_node_id,
               target.node_id as target_node_id
        """

    @staticmethod
    def build_get_by_organization_query() -> str:
        """Build query to get all edges for an organization."""
        return """
        MATCH (source:GraphNode)-[r:RELATES_TO]->(target:GraphNode)
        WHERE r.organization_id = $organization_id
        RETURN r.edge_id as edge_id,
               r.relationship_type as relationship_type,
               COALESCE(r.fact, '') as fact,
               COALESCE(r.properties, '{}') as properties,
               COALESCE(r.metadata, '{}') as metadata,
               r.organization_id as organization_id,
               r.created_at as created_at,
               r.updated_at as updated_at,
               source.node_id as source_node_id,
               target.node_id as target_node_id
        LIMIT $limit
        """

    @staticmethod
    def build_delete_query() -> str:
        """Build query to delete an edge."""
        return """
        MATCH ()-[r:RELATES_TO {edge_id: $edge_id}]-()
        WHERE r.organization_id = $organization_id
        DELETE r
        RETURN count(r) as deleted_count
        """

    @staticmethod
    def build_batch_create_or_update_query() -> str:
        """Build query to batch create or update edges.

        Uses MERGE for nodes to auto-create minimal stubs if missing.
        This prevents silent failures when edges reference nodes that
        don't exist yet (e.g., cross-batch ordering issues).

        Nodes created as stubs have _stub=true flag and will be updated
        with full properties when the actual node is synced.
        """
        return """
        UNWIND $edges as edge_data
        MERGE (source:GraphNode {
            node_id: edge_data.source_node_id,
            organization_id: edge_data.organization_id
        })
        ON CREATE SET
            source.node_type = 'Unknown',
            source.created_at = datetime(),
            source._stub = true
        MERGE (target:GraphNode {
            node_id: edge_data.target_node_id,
            organization_id: edge_data.organization_id
        })
        ON CREATE SET
            target.node_type = 'Unknown',
            target.created_at = datetime(),
            target._stub = true
        MERGE (source)-[r:RELATES_TO {edge_id: edge_data.edge_id}]->(target)
        ON CREATE SET
            r.relationship_type = edge_data.relationship_type,
            r.fact = edge_data.fact,
            r.fact_embedding = edge_data.fact_embedding,
            r.properties = edge_data.properties,
            r.metadata = edge_data.metadata,
            r.organization_id = edge_data.organization_id,
            r.created_at = datetime(edge_data.created_at),
            r.updated_at = datetime(edge_data.updated_at),
            r.source_sync_id = edge_data.source_sync_id,
            r.source_entity_definition_id = edge_data.source_entity_definition_id,
            r.valid_at = CASE WHEN edge_data.valid_at IS NOT NULL THEN datetime(edge_data.valid_at) ELSE NULL END,
            r.invalid_at = CASE WHEN edge_data.invalid_at IS NOT NULL THEN datetime(edge_data.invalid_at) ELSE NULL END
        ON MATCH SET
            r.relationship_type = edge_data.relationship_type,
            r.fact = edge_data.fact,
            r.fact_embedding = edge_data.fact_embedding,
            r.properties = edge_data.properties,
            r.metadata = edge_data.metadata,
            r.updated_at = datetime(edge_data.updated_at),
            r.source_sync_id = edge_data.source_sync_id,
            r.source_entity_definition_id = edge_data.source_entity_definition_id,
            r.valid_at = CASE WHEN edge_data.valid_at IS NOT NULL THEN datetime(edge_data.valid_at) ELSE NULL END,
            r.invalid_at = CASE WHEN edge_data.invalid_at IS NOT NULL THEN datetime(edge_data.invalid_at) ELSE NULL END
        WITH r
        RETURN count(DISTINCT r) as edges_processed
        """

    @staticmethod
    def build_get_node_edges_query() -> str:
        """Build query to get all edges connected to a node."""
        return """
        MATCH (n:GraphNode {node_id: $node_id, organization_id: $organization_id})
        MATCH (n)-[r:RELATES_TO]-(other:GraphNode)
        RETURN r.edge_id as edge_id,
               r.relationship_type as relationship_type,
               r.fact as fact,
               r.properties as properties,
               r.metadata as metadata,
               r.created_at as created_at,
               r.updated_at as updated_at,
               startNode(r).node_id as source_node_id,
               endNode(r).node_id as target_node_id
        LIMIT $limit
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
            serialized[key] = EdgeQueryBuilder._serialize_for_neo4j(value)
        return serialized

    @staticmethod
    def prepare_edge_parameters(edge: "GraphEdge") -> Dict[str, Any]:
        """Prepare edge data for query parameters.

        Args:
            edge: GraphEdge instance

        Returns:
            Dictionary of query parameters
        """
        import json

        # Convert entire properties and metadata dicts to JSON strings
        # Neo4j doesn't support nested dictionaries, so we store them as JSON
        properties_json = json.dumps(edge.properties) if edge.properties else "{}"
        metadata_json = json.dumps(edge.metadata) if edge.metadata else "{}"

        return {
            "edge_id": edge.edge_id,
            "relationship_type": edge.relationship_type,
            "source_node_id": edge.source_node_id,
            "target_node_id": edge.target_node_id,
            "fact": edge.fact,
            "fact_embedding": edge.fact_embedding,
            "properties": properties_json,  # JSON string, not dict
            "metadata": metadata_json,      # JSON string, not dict
            "organization_id": str(edge.organization_id),
            "created_at": edge.created_at.isoformat(),
            "updated_at": edge.updated_at.isoformat(),
            "source_sync_id": str(edge.source_sync_id) if edge.source_sync_id else None,
            "source_entity_definition_id": str(edge.source_entity_definition_id) if edge.source_entity_definition_id else None,
            "valid_at": edge.valid_at.isoformat() if edge.valid_at else None,
            "invalid_at": edge.invalid_at.isoformat() if edge.invalid_at else None,
        }
