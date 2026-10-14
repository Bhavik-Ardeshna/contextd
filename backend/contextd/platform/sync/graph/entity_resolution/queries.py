"""Neo4j query builders for entity resolution.

Provides query templates for finding existing nodes
to resolve entities against.

NOTE: Properties are stored as JSON strings in Neo4j.
Queries fetch raw data and parsing happens in Python.
"""


class PersonResolutionQueries:
    """Query builders for PersonNode resolution.

    IMPORTANT: `properties` is stored as a JSON STRING in Neo4j,
    not as a native map. All queries return raw properties string
    which must be parsed in Python using json.loads().
    """

    @staticmethod
    def build_find_all_persons_query() -> str:
        """Find all PersonNodes for an organization.

        Returns all nodes for Python-side matching since
        properties are JSON strings that can't be queried directly.

        Parameters:
            $organization_id: Organization UUID string

        Returns:
            node_id, properties (as JSON string) for all PersonNodes
        """
        return """
        MATCH (p:GraphNode {
            node_type: 'PersonNode',
            organization_id: $organization_id
        })
        RETURN
            p.node_id as node_id,
            p.properties as properties
        """

    @staticmethod
    def build_count_persons_query() -> str:
        """Count total PersonNodes for an organization.

        Useful for deciding resolution strategy.

        Parameters:
            $organization_id: Organization UUID string

        Returns:
            count
        """
        return """
        MATCH (p:GraphNode {
            node_type: 'PersonNode',
            organization_id: $organization_id
        })
        RETURN count(p) as count
        """


class EntityResolutionQueries:
    """General query builders for entity resolution.

    NOTE: Properties are stored as JSON strings, so queries
    fetch all data and matching happens in Python.
    """

    @staticmethod
    def build_find_all_by_type_query() -> str:
        """Find all nodes of a type for an organization.

        Properties are stored as JSON strings, so we fetch all
        and filter/match in Python.

        Parameters:
            $organization_id: Organization UUID string
            $node_type: Node type (e.g., 'CompanyNode', 'ProjectNode')

        Returns:
            node_id, properties (as JSON string) for all matching nodes
        """
        return """
        MATCH (n:GraphNode {
            node_type: $node_type,
            organization_id: $organization_id
        })
        RETURN
            n.node_id as node_id,
            n.properties as properties
        """
