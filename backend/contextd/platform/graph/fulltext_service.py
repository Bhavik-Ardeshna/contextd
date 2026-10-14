"""Neo4j fulltext index service.

Provides management and search capabilities for Neo4j fulltext indexes.

Architecture:
- Searchable fields are stored as individual node properties with 'ft_' prefix
  (e.g., ft_name, ft_notes, ft_description) by the NodeQueryBuilder
- Fulltext index is created on these ft_* properties on the GraphNode label
- This enables efficient, field-specific fulltext search with proper scoring

Features:
- Auto-create fulltext indexes on ft_* properties
- Search across all GraphNode entities with optional node_type filtering
- Configurable analyzers (standard, simple, whitespace)
- Index status monitoring

Index Strategy:
- Single unified index on GraphNode label covering all ft_* properties
- The ft_* properties are extracted from entity properties during node creation
- Default searchable fields: name, title, description, notes, content, etc.
"""

import logging
from typing import Any, Dict, List, Optional

from neo4j.exceptions import ClientError

from contextd.platform.configs.index import FulltextIndexConfig, get_index_config
from contextd.platform.graph.config import get_graph_config
from contextd.platform.graph.driver.neo4j_driver import Neo4jDriver
from contextd.platform.graph.queries.node_queries import (
    DEFAULT_SEARCHABLE_FIELDS,
    FULLTEXT_PROPERTY_PREFIX,
)

logger = logging.getLogger(__name__)

# Lucene operators we do not add fuzzy ~ to
_LUCENE_OPERATORS = frozenset({"and", "or", "not"})


def _make_fulltext_query_fuzzy(query: str) -> str:
    """Make a fulltext query use fuzzy matching by appending ~ to each term.

    Neo4j/Lucene fulltext: term~ enables fuzzy matching (typos, variants).
    We tokenize on whitespace and append ~ to each word-like token that is not
    a Lucene operator and does not already end with ~. So any text search
    (RetrieveNode, GraphSearch) gets fuzzy by default.
    """
    if not query or not query.strip():
        return query
    tokens = query.strip().split()
    out = []
    for t in tokens:
        t_lower = t.lower()
        if t_lower in _LUCENE_OPERATORS or t.endswith("~"):
            out.append(t)
        elif any(c.isalnum() for c in t):
            out.append(t.rstrip("~") + "~")
        else:
            out.append(t)
    return " ".join(out)


class FulltextService:
    """Service for managing Neo4j fulltext indexes.

    Provides:
    - Index creation and management on ft_* properties
    - Fulltext search across node types
    - Index status monitoring

    Index Design:
        - Single index named 'graphnode_fulltext' on GraphNode label
        - Indexes ft_* properties (ft_name, ft_notes, ft_description, etc.)
        - These properties are extracted from entity properties during node creation
        - Supports field-specific boosting and proper fulltext scoring
    """

    # Unified index name for all GraphNode entities
    UNIFIED_INDEX_NAME = "graphnode_fulltext"

    def __init__(self, driver: Neo4jDriver):
        """Initialize fulltext service.

        Args:
            driver: Neo4j driver instance
        """
        self._driver = driver
        self._config = get_index_config()
        self._created_indexes: Dict[str, str] = {}
        self._unified_index_created: bool = False

    @classmethod
    async def create(
        cls,
        *,
        organization_id: Optional[Any] = None,
        readable_collection_id: Optional[str] = None,
        database: Optional[str] = None,
    ) -> "FulltextService":
        """Factory method to create fulltext service.

        Returns:
            FulltextService instance with connected driver

        Raises:
            Exception: If Neo4j connection fails
        """
        config = get_graph_config()
        if not config.enabled:
            raise ValueError("Graph construction is disabled")

        driver = Neo4jDriver(
            uri=config.neo4j_uri,
            user=config.neo4j_user,
            password=config.neo4j_password,
            database=database or config.neo4j_database,
        )
        await driver.connect()
        if readable_collection_id and organization_id:
            target_database = await driver.ensure_context_database(
                organization_id,
                readable_collection_id,
            )
            driver.database = target_database
        elif database:
            await driver.ensure_database(database)

        return cls(driver)

    def get_index_name(self, node_type: str) -> str:
        """Get the fulltext index name.

        Returns the unified index name since all nodes use GraphNode label
        with ft_* properties for fulltext search.

        Args:
            node_type: Node type (kept for API compatibility)

        Returns:
            Unified fulltext index name
        """
        return self.UNIFIED_INDEX_NAME

    def _get_fulltext_property_names(self) -> List[str]:
        """Get list of ft_* property names to index.

        Generates property names with FULLTEXT_PROPERTY_PREFIX for all
        default searchable fields.

        Returns:
            List of property names like ['ft_name', 'ft_notes', ...]
        """
        return [
            f"{FULLTEXT_PROPERTY_PREFIX}{field}"
            for field in DEFAULT_SEARCHABLE_FIELDS
        ]

    async def ensure_fulltext_index(
        self,
        node_type: str,
        fields: List[str],
        analyzer: str = "standard",
    ) -> bool:
        """Ensure the unified fulltext index exists on ft_* properties.

        Creates a single fulltext index on GraphNode label covering all
        ft_* properties (ft_name, ft_notes, ft_description, etc.).
        These properties are extracted from entity data during node creation.

        Args:
            node_type: Node type (used for tracking, actual index is unified)
            fields: Fields (used for logging, actual index uses ft_* properties)
            analyzer: Lucene analyzer to use

        Returns:
            True if index was created, False if already exists
        """
        index_name = self.UNIFIED_INDEX_NAME

        # Check cache first - if unified index was created, we're done
        if self._unified_index_created:
            self._created_indexes[node_type] = index_name
            return False

        # Check if index already exists in database
        existing_index = await self._get_existing_index(index_name)
        if existing_index:
            self._unified_index_created = True
            self._created_indexes[node_type] = index_name
            logger.debug(f"Fulltext index {index_name} already exists")
            return False

        # Build index on ft_* properties
        ft_properties = self._get_fulltext_property_names()

        index_config = FulltextIndexConfig(
            index_name=index_name,
            node_type="GraphNode",
            fields=ft_properties,  # ft_name, ft_notes, etc.
            analyzer=analyzer,
        )

        try:
            await self._create_index(index_config)
            self._unified_index_created = True
            self._created_indexes[node_type] = index_name
            logger.info(
                f"Created fulltext index {index_name} on GraphNode.{ft_properties}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to create fulltext index {index_name}: {e}")
            raise

    async def _get_existing_index(self, index_name: str) -> Optional[Dict[str, Any]]:
        """Check if a fulltext index exists.

        Args:
            index_name: Name of the index

        Returns:
            Index info if exists, None otherwise
        """
        query = """
        SHOW INDEXES
        WHERE type = 'FULLTEXT' AND name = $index_name
        """

        try:
            records = await self._driver.execute_read(query, {"index_name": index_name})
            return records[0] if records else None
        except Exception as e:
            logger.warning(f"Error checking index {index_name}: {e}")
            return None

    async def _create_index(self, config: FulltextIndexConfig) -> None:
        """Create a fulltext index on ft_* properties.

        Creates the index on GraphNode label with specified ft_* properties.
        These properties are individual string fields extracted from entity data,
        enabling proper fulltext scoring and field-specific search.

        Args:
            config: Index configuration with ft_* property names
        """
        # Build field list for the index (e.g., n.ft_name, n.ft_notes)
        fields_list = ", ".join([f"n.{field}" for field in config.fields])

        query = f"""
        CREATE FULLTEXT INDEX {config.index_name} IF NOT EXISTS
        FOR (n:GraphNode)
        ON EACH [{fields_list}]
        OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: '{config.analyzer}' }} }}
        """

        try:
            await self._driver.execute_write(query)
            logger.info(f"Created fulltext index {config.index_name} with fields: {config.fields}")
        except ClientError as e:
            # Ignore "already exists" errors
            if "EquivalentSchemaRuleAlreadyExists" in str(e) or "AlreadyExists" in str(e):
                logger.debug(f"Index {config.index_name} already exists")
            else:
                raise

    async def search_fulltext(
        self,
        query: str,
        node_types: Optional[List[str]] = None,
        limit: int = 20,
        min_score: float = 0.0,
        organization_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search the unified fulltext index on ft_* properties.

        Searches the GraphNode fulltext index which indexes ft_* properties
        (ft_name, ft_notes, ft_description, etc.). These are individual string
        fields extracted from entity data, enabling proper fulltext scoring.

        Args:
            query: Search query (supports Lucene syntax like 'project AND status')
            node_types: Node types to filter (searches all if None)
            limit: Maximum results
            min_score: Minimum relevance score (0.0-1.0)
            organization_id: Filter by organization UUID

        Returns:
            List of matching nodes with scores, containing:
            - node_id: Unique node identifier
            - node_type: Entity type (e.g., 'AsanaTaskEntity')
            - name: Entity name (from properties)
            - properties: Full entity data dict
            - score: Fulltext relevance score
            - source: 'fulltext'

        Note: The query is automatically made fuzzy (each term gets ~) so that
        any text search tolerates typos and variants.
        """
        await self.ensure_fulltext_index(
            node_type="GraphNode",
            fields=self._get_fulltext_property_names(),
            analyzer=get_graph_config().fulltext_analyzer,
        )
        query = _make_fulltext_query_fuzzy(query)
        try:
            results = await self._search_single_index(
                index_name=self.UNIFIED_INDEX_NAME,
                query=query,
                limit=limit * 2 if node_types else limit,  # Fetch more if filtering
                min_score=min_score,
                organization_id=organization_id,
                node_types=node_types,
            )

            # Apply limit after filtering
            return results[:limit]

        except Exception as e:
            logger.warning(f"Error searching fulltext index: {e}")
            return []

    async def _search_single_index(
        self,
        index_name: str,
        query: str,
        limit: int = 20,
        min_score: float = 0.0,
        organization_id: Optional[str] = None,
        node_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Search a single fulltext index on ft_* properties.

        The search queries the index which covers ft_* properties
        (ft_name, ft_notes, etc.). Results include both the matched
        ft_* fields and the full properties JSON.

        Args:
            index_name: Name of the index
            query: Search query (Lucene syntax supported)
            limit: Maximum results
            min_score: Minimum score threshold
            organization_id: Filter by organization
            node_types: Filter by node types

        Returns:
            List of matching nodes with properties and scores
        """
        import json

        # Build WHERE clauses
        where_clauses = ["score >= $min_score"]
        params: Dict[str, Any] = {
            "query": query,
            "limit": limit,
            "min_score": min_score,
            "index_name": index_name,
        }

        if organization_id:
            where_clauses.append("node.organization_id = $org_id")
            params["org_id"] = organization_id

        if node_types:
            where_clauses.append("node.node_type IN $node_types")
            params["node_types"] = node_types

        where_clause = " AND ".join(where_clauses)

        # Query returns both ft_* properties (for matched text) and full properties JSON
        cypher_query = f"""
        CALL db.index.fulltext.queryNodes($index_name, $query)
        YIELD node, score
        WHERE {where_clause}
        RETURN
            node.node_id AS node_id,
            node.node_type AS node_type,
            node.properties AS properties,
            node.ft_name AS ft_name,
            node.ft_notes AS ft_notes,
            node.ft_description AS ft_description,
            node.ft_title AS ft_title,
            labels(node) AS labels,
            score
        ORDER BY score DESC
        LIMIT $limit
        """

        records = await self._driver.execute_read(cypher_query, params)

        results = []
        for record in records:
            props = record["properties"]
            # Parse JSON if it's a string
            if isinstance(props, str):
                try:
                    props = json.loads(props)
                except (json.JSONDecodeError, TypeError):
                    props = {}

            # Get name from ft_name first, then fall back to properties
            name = record.get("ft_name")
            if not name and isinstance(props, dict):
                name = props.get("name") or props.get("title")

            results.append({
                "node_id": record["node_id"],
                "node_type": record["node_type"],
                "name": name,
                "labels": record["labels"],
                "properties": props,
                "score": record["score"],
                "source": "fulltext",
                # Include matched ft_* fields for debugging/highlighting
                "matched_fields": {
                    k: v for k, v in {
                        "ft_name": record.get("ft_name"),
                        "ft_notes": record.get("ft_notes"),
                        "ft_description": record.get("ft_description"),
                        "ft_title": record.get("ft_title"),
                    }.items() if v
                },
            })

        return results

    async def get_index_status(self) -> Dict[str, Any]:
        """Get status of all fulltext indexes.

        Returns:
            Dictionary with index information
        """
        query = """
        SHOW INDEXES
        WHERE type = 'FULLTEXT'
        RETURN name, state, populationPercent, labelsOrTypes, properties
        """

        try:
            records = await self._driver.execute_read(query)

            indexes = []
            for record in records:
                indexes.append({
                    "name": record["name"],
                    "state": record["state"],
                    "population_percent": record["populationPercent"],
                    "labels": record["labelsOrTypes"],
                    "properties": record["properties"],
                })

            return {
                "total_indexes": len(indexes),
                "indexes": indexes,
                "cached_indexes": list(self._created_indexes.keys()),
            }
        except Exception as e:
            logger.error(f"Error getting index status: {e}")
            return {"error": str(e)}

    async def drop_index(self, node_type: str) -> bool:
        """Drop a fulltext index.

        Args:
            node_type: Node type whose index to drop

        Returns:
            True if dropped, False if didn't exist
        """
        index_name = self.get_index_name(node_type)

        query = f"DROP INDEX {index_name} IF EXISTS"

        try:
            await self._driver.execute_write(query)
            if node_type in self._created_indexes:
                del self._created_indexes[node_type]
            logger.info(f"Dropped fulltext index {index_name}")
            return True
        except Exception as e:
            logger.error(f"Error dropping index {index_name}: {e}")
            return False

    async def close(self) -> None:
        """Close the Neo4j connection."""
        if self._driver:
            await self._driver.close()


# Module-level instance for singleton pattern
_fulltext_service: Optional[FulltextService] = None


async def get_fulltext_service() -> FulltextService:
    """Get or create the fulltext service singleton.

    Returns:
        FulltextService instance
    """
    global _fulltext_service

    if _fulltext_service is None:
        _fulltext_service = await FulltextService.create()

    return _fulltext_service
