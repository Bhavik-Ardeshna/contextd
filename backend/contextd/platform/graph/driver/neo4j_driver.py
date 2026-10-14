"""Neo4j driver for graph operations."""
import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession, EagerResult
from neo4j.exceptions import ClientError

from contextd.platform.graph.database import (
    neo4j_collection_database_name,
    quote_neo4j_identifier,
)

logger = logging.getLogger(__name__)


def convert_neo4j_types(obj: Any) -> Any:
    """Recursively convert Neo4j temporal types to Python native types.

    This function handles all Neo4j-specific types that aren't JSON serializable:
    - DateTime -> Python datetime (or ISO string)
    - Date -> Python date (or ISO string)
    - Time -> Python time (or ISO string)
    - Duration -> Python timedelta (or ISO duration string)

    Also handles nested structures (dicts, lists) recursively.

    Args:
        obj: Any object that may contain Neo4j types

    Returns:
        Object with all Neo4j types converted to Python native types
    """
    # Import Neo4j types lazily to avoid import errors when neo4j isn't connected
    try:
        from neo4j.time import Date as Neo4jDate
        from neo4j.time import DateTime as Neo4jDateTime
        from neo4j.time import Duration as Neo4jDuration
        from neo4j.time import Time as Neo4jTime
    except ImportError:
        # neo4j.time not available, return as-is
        return obj

    if obj is None:
        return None

    # Handle Neo4j DateTime
    if isinstance(obj, Neo4jDateTime):
        try:
            return obj.to_native()
        except (ValueError, OverflowError):
            # Fallback to ISO string if native conversion fails
            return obj.isoformat()

    # Handle Neo4j Date
    if isinstance(obj, Neo4jDate):
        try:
            return obj.to_native()
        except (ValueError, OverflowError):
            return obj.isoformat()

    # Handle Neo4j Time
    if isinstance(obj, Neo4jTime):
        try:
            return obj.to_native()
        except (ValueError, OverflowError):
            return obj.isoformat()

    # Handle Neo4j Duration
    if isinstance(obj, Neo4jDuration):
        try:
            # Convert to timedelta (may lose some precision for months/years)
            return timedelta(
                days=obj.days,
                seconds=obj.seconds,
                nanoseconds=obj.nanoseconds // 1000,  # Convert to microseconds
            )
        except (ValueError, OverflowError):
            # Fallback to ISO duration string
            return f"P{obj.months}M{obj.days}DT{obj.seconds}S"

    # Handle Python datetime objects (for consistency)
    if isinstance(obj, datetime):
        return obj

    if isinstance(obj, (date, time)):
        return obj

    # Handle dicts recursively
    if isinstance(obj, dict):
        return {key: convert_neo4j_types(value) for key, value in obj.items()}

    # Handle lists/tuples recursively
    if isinstance(obj, (list, tuple)):
        converted = [convert_neo4j_types(item) for item in obj]
        return type(obj)(converted) if isinstance(obj, tuple) else converted

    # Return primitives and other types as-is
    return obj


class Neo4jDriver:
    """Neo4j async driver wrapper for graph operations.

    Provides connection management, query execution, and health checks.
    Inspired by graphiti but simplified for our use case.
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
    ):
        """Initialize Neo4j driver.

        Args:
            uri: Neo4j connection URI (e.g., 'bolt://localhost:7687')
            user: Neo4j username
            password: Neo4j password
            database: Database name (default: 'neo4j')
        """
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self._driver: Optional[AsyncDriver] = None
        self._known_databases: set[str] = set()

    async def connect(self) -> None:
        """Establish connection to Neo4j."""
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                uri=self.uri,
                auth=(self.user, self.password),
                max_connection_lifetime=1800,  # 30 min; recycle to avoid defunct/stale connections
            )
            logger.info(f"Connected to Neo4j at {self.uri}")

    def for_database(self, database: str) -> "Neo4jDatabaseView":
        """Return a lightweight view that runs all queries in one database."""
        return Neo4jDatabaseView(self, database)

    async def ensure_context_database(
        self,
        organization_id: Any,
        readable_collection_id: Optional[str],
    ) -> str:
        """Ensure the collection-scoped Neo4j database exists and is indexed."""
        database = neo4j_collection_database_name(organization_id, readable_collection_id)
        await self.ensure_database(database)
        await self.build_indices(database=database)
        return database

    async def drop_context_database(
        self,
        organization_id: Any,
        readable_collection_id: Optional[str],
    ) -> str:
        """Drop the isolated Neo4j database for a ContextD collection."""
        database = neo4j_collection_database_name(organization_id, readable_collection_id)
        if not database:
            return database
        if not self._driver:
            await self.connect()

        await self.execute_query(
            f"DROP DATABASE {quote_neo4j_identifier(database)} IF EXISTS",
            database="system",
        )
        self._known_databases.discard(database)
        await self._wait_for_database_drop(database)
        return database

    async def ensure_database(self, database: str) -> None:
        """Create a Neo4j database when Enterprise multi-database support is available."""
        if not database or database in self._known_databases:
            return
        if not self._driver:
            await self.connect()

        database_name = quote_neo4j_identifier(database)
        try:
            await self.execute_query(
                f"CREATE DATABASE {database_name} IF NOT EXISTS",
                database="system",
            )
            await self._wait_for_database(database)
            self._known_databases.add(database)
            logger.info("Neo4j context database ready: %s", database)
        except Exception as e:
            logger.error(
                "Failed to create Neo4j database %s. Neo4j Enterprise Edition is required "
                "for collection-per-database isolation: %s",
                database,
                e,
            )
            raise

    async def _wait_for_database(self, database: str) -> None:
        """Wait briefly for a newly created Neo4j database to come online."""
        params = {"database": database}
        for _ in range(30):
            result = await self.execute_query(
                """
                SHOW DATABASES
                YIELD name, currentStatus
                WHERE name = $database
                RETURN currentStatus AS status
                """,
                params,
                database="system",
            )
            status = None
            if result.records:
                status = str(result.records[0].get("status") or "").lower()
            if status == "online":
                return
            await asyncio.sleep(0.2)
        raise TimeoutError(f"Neo4j database {database} did not become online")

    async def _wait_for_database_drop(self, database: str) -> None:
        """Wait briefly until a dropped Neo4j database disappears from system catalog."""
        params = {"database": database}
        for _ in range(40):
            result = await self.execute_query(
                """
                SHOW DATABASES
                YIELD name
                WHERE name = $database
                RETURN count(*) AS count
                """,
                params,
                database="system",
            )
            count = int(result.records[0].get("count") or 0) if result.records else 0
            if count == 0:
                return
            await asyncio.sleep(0.25)
        raise TimeoutError(f"Neo4j database {database} did not drop")

    async def close(self) -> None:
        """Close Neo4j connection."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j connection closed")

    async def execute_query(
        self,
        cypher_query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> EagerResult:
        """Execute a Cypher query.

        Args:
            cypher_query: Cypher query string
            parameters: Query parameters
            database: Database name (uses default if not provided)

        Returns:
            Query result

        Raises:
            Exception: If query execution fails
        """
        if not self._driver:
            await self.connect()

        params = parameters or {}
        db = database or self.database

        try:
            result = await self._driver.execute_query(
                cypher_query,
                parameters_=params,
                database_=db,
            )
            return result
        except Exception as e:
            logger.error(f"Error executing Neo4j query: {e}\n{cypher_query}\n{params}")
            raise

    async def execute_write(
        self,
        cypher_query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a write transaction with automatic type conversion.

        Automatically converts all Neo4j-specific types in returned data
        (DateTime, Date, Time, Duration) to Python native types.

        Args:
            cypher_query: Cypher query string
            parameters: Query parameters

        Returns:
            List of result records as dictionaries with Python-native types
        """
        if not self._driver:
            await self.connect()

        params = parameters or {}
        db = database or self.database

        async def _execute(tx):
            result = await tx.run(cypher_query, params)
            data = await result.data()

            # Convert all Neo4j types to Python native types (recursive)
            return [convert_neo4j_types(record) for record in data]

        async with self._driver.session(database=db) as session:
            try:
                records = await session.execute_write(_execute)
                return records
            except Exception as e:
                logger.error(f"Error executing write query: {e}\n{cypher_query}\n{params}")
                raise

    async def execute_read(
        self,
        cypher_query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a read transaction with automatic type conversion.

        Automatically converts all Neo4j-specific types (DateTime, Date, Time,
        Duration) to Python native types, including nested structures.

        Args:
            cypher_query: Cypher query string
            parameters: Query parameters

        Returns:
            List of result records as dictionaries with Python-native types
        """
        if not self._driver:
            await self.connect()

        params = parameters or {}
        db = database or self.database

        async def _execute(tx):
            result = await tx.run(cypher_query, params)
            data = await result.data()

            # Convert all Neo4j types to Python native types (recursive)
            return [convert_neo4j_types(record) for record in data]

        async with self._driver.session(database=db) as session:
            try:
                records = await session.execute_read(_execute)
                return records
            except Exception as e:
                logger.error(f"Error executing read query: {e}\n{cypher_query}\n{params}")
                raise

    def session(self, database: Optional[str] = None) -> AsyncSession:
        """Get a new session.

        Returns:
            Neo4j async session
        """
        if not self._driver:
            raise RuntimeError("Driver not connected. Call connect() first.")
        return self._driver.session(database=database or self.database)

    async def health_check(self) -> bool:
        """Check Neo4j connectivity.

        Returns:
            True if healthy, False otherwise
        """
        try:
            if not self._driver:
                await self.connect()
            await self._driver.verify_connectivity()
            return True
        except Exception as e:
            logger.error(f"Neo4j health check failed: {e}")
            return False

    async def build_indices(self, database: Optional[str] = None) -> None:
        """Build necessary indices for optimal query performance."""
        indices = [
            # Replace legacy org-wide uniqueness so repeated source row IDs can exist
            # independently inside each context database.
            """
            DROP CONSTRAINT node_id_org_unique IF EXISTS
            """,
            # Node ID index
            """
            CREATE INDEX node_id_idx IF NOT EXISTS
            FOR (n:GraphNode)
            ON (n.node_id)
            """,
            # Organization ID index
            """
            CREATE INDEX org_id_idx IF NOT EXISTS
            FOR (n:GraphNode)
            ON (n.organization_id)
            """,
            # Node type index
            """
            CREATE INDEX node_type_idx IF NOT EXISTS
            FOR (n:GraphNode)
            ON (n.node_type)
            """,
            # Collection/readable database index
            """
            CREATE INDEX collection_id_idx IF NOT EXISTS
            FOR (n:GraphNode)
            ON (n.collection_id)
            """,
            # Edge ID index (relationship property index)
            """
            CREATE INDEX edge_id_idx IF NOT EXISTS
            FOR ()-[r:RELATES_TO]-()
            ON (r.edge_id)
            """,
            # Relationship collection index
            """
            CREATE INDEX rel_collection_id_idx IF NOT EXISTS
            FOR ()-[r:RELATES_TO]-()
            ON (r.collection_id)
            """,
            # Collection-scoped node identity
            """
            CREATE CONSTRAINT node_id_org_collection_unique IF NOT EXISTS
            FOR (n:GraphNode)
            REQUIRE (n.node_id, n.organization_id, n.collection_id) IS UNIQUE
            """,
        ]

        for index_query in indices:
            try:
                await self.execute_write(index_query, database=database)
                logger.debug(f"Created index: {index_query[:50]}...")
            except ClientError as e:
                if "EquivalentSchemaRuleAlreadyExists" in str(e) or "AlreadyExists" in str(e):
                    logger.debug(f"Index already exists: {index_query[:50]}...")
                elif (
                    "node_id_org_collection_unique" in index_query
                    and "ConstraintCreationFailed" in str(e)
                ):
                    logger.warning(
                        "Duplicate GraphNode entries found. Attempting to merge duplicates."
                    )
                    await self._deduplicate_graph_nodes(database=database)
                    await self.execute_write(index_query, database=database)
                else:
                    logger.error(f"Error creating index: {e}")
                    raise
            except Exception as e:
                # Driver may raise non-ClientError for schema errors (e.g. DatabaseError)
                if (
                    "node_id_org_collection_unique" in index_query
                    and "ConstraintCreationFailed" in str(e)
                ):
                    logger.warning(
                        "Duplicate GraphNode entries found (constraint failed). Deduplicating."
                    )
                    await self._deduplicate_graph_nodes(database=database)
                    try:
                        await self.execute_write(index_query, database=database)
                    except Exception as retry_e:
                        logger.error("Constraint still failed after dedup: %s", retry_e)
                        raise
                else:
                    logger.error("Error creating index: %s", e)
                    raise

    async def _deduplicate_graph_nodes(self, database: Optional[str] = None) -> None:
        """Merge duplicate GraphNode entries by (node_id, organization_id, collection_id).
        Tries APOC merge first; falls back to deleting duplicate nodes if APOC is unavailable.
        """
        # Try APOC merge (preserves relationships)
        apoc_query = """
        MATCH (n:GraphNode)
        WITH n.node_id AS node_id,
             n.organization_id AS org_id,
             coalesce(n.collection_id, '') AS collection_id,
             collect(n) AS nodes
        WHERE size(nodes) > 1
        CALL apoc.refactor.mergeNodes(
            nodes,
            {properties: 'combine', mergeRels: true}
        ) YIELD node
        RETURN count(node) AS merged
        """
        try:
            await self.execute_write(apoc_query, database=database)
            logger.info("Deduplicated GraphNodes via APOC mergeNodes.")
            return
        except Exception as e:
            logger.warning(
                "APOC mergeNodes failed (APOC may be missing). Removing duplicate nodes: %s",
                e,
            )
        # Fallback: keep one node per (node_id, organization_id, collection_id), delete the rest
        # (Relationships attached to deleted nodes are removed by Neo4j.)
        fallback_query = """
        MATCH (n:GraphNode)
        WITH n.node_id AS node_id,
             n.organization_id AS org_id,
             coalesce(n.collection_id, '') AS collection_id,
             collect(n) AS nodes
        WHERE size(nodes) > 1
        WITH nodes[0] AS keep, nodes[1..] AS to_remove
        UNWIND to_remove AS dup
        DETACH DELETE dup
        """
        await self.execute_write(fallback_query, database=database)
        logger.info("Removed duplicate GraphNodes (fallback). Constraint can now be created.")

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


class Neo4jDatabaseView:
    """Database-scoped view over a shared Neo4jDriver connection."""

    def __init__(self, driver: Neo4jDriver, database: str) -> None:
        self._driver = driver
        self.database = database

    async def connect(self) -> None:
        await self._driver.connect()

    async def close(self) -> None:
        """No-op: the owning Neo4jDriver manages the underlying connection."""

    async def execute_query(
        self,
        cypher_query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> EagerResult:
        return await self._driver.execute_query(
            cypher_query,
            parameters=parameters,
            database=database or self.database,
        )

    async def execute_write(
        self,
        cypher_query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return await self._driver.execute_write(
            cypher_query,
            parameters=parameters,
            database=database or self.database,
        )

    async def execute_read(
        self,
        cypher_query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return await self._driver.execute_read(
            cypher_query,
            parameters=parameters,
            database=database or self.database,
        )

    def session(self, database: Optional[str] = None) -> AsyncSession:
        return self._driver.session(database=database or self.database)

    async def health_check(self) -> bool:
        return await self._driver.health_check()
