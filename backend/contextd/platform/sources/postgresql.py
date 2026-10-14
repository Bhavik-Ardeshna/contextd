"""PostgreSQL source implementation.

This source connects to a PostgreSQL database and generates entities for each table
based on its schema structure. It dynamically creates entity classes at runtime
using the PolymorphicEntity system.
"""

import asyncio
import hashlib
import json
import logging
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, AsyncGenerator, Dict, List, Optional, Type, Union

import asyncpg

from contextd.core.pg_field_catalog_service import overwrite_catalog
from contextd.core.shared_models import RateLimitLevel
from contextd.db.session import get_db_context
from contextd.platform.configs.database.entity_registry import (
    DatabaseEntityClassRegistry,
)
from contextd.platform.configs.database.factory import DatabaseSchemaConverter
from contextd.platform.configs.database.metadata import ColumnMetadata, TableMetadata
from contextd.platform.configs.database.registry import DatabaseSchemaRegistry
from contextd.platform.configs.database.schema import (
    DatabaseColumn,
    DatabaseTable,
    ForeignKeyConfig,
)
from contextd.platform.cursors import PostgreSQLCursor
from contextd.platform.decorators import source
from contextd.platform.entities._base import BaseEntity, PolymorphicEntity
from contextd.platform.entities._metadata import EntityIndexConfig, SearchConfig
from contextd.platform.sources._base import BaseSource
from contextd.schemas.source_connection import AuthenticationMethod

logger = logging.getLogger(__name__)

# Mapping of PostgreSQL types to Python types
PG_TYPE_MAP = {
    "integer": int,
    "bigint": int,
    "smallint": int,
    "decimal": float,
    "numeric": float,
    "real": float,
    "double precision": float,
    "character varying": str,
    "character": str,
    "text": str,
    "boolean": bool,
    "timestamp": datetime,
    "timestamp with time zone": datetime,
    "date": datetime,
    "time": datetime,
    "json": Any,  # JSON can be dict, list, or primitive
    "jsonb": Any,  # JSONB can be dict, list, or primitive
}


@source(
    name="PostgreSQL",
    short_name="postgresql",
    auth_methods=[AuthenticationMethod.DIRECT, AuthenticationMethod.AUTH_PROVIDER],
    oauth_type=None,
    auth_config_class="PostgreSQLAuthConfig",
    config_class="PostgreSQLConfig",
    labels=["Database"],
    supports_continuous=True,
    cursor_class=PostgreSQLCursor,
    rate_limit_level=RateLimitLevel.ORG,
)
class PostgreSQLSource(BaseSource):
    """PostgreSQL source connector integrates with PostgreSQL databases to extract structured data.

    Synchronizes data from database tables.

    It uses dynamic schema introspection to create appropriate entity classes
    and provides comprehensive access to relational data with proper type mapping and relationships.
    """

    _RESERVED_ENTITY_FIELDS = {
        "entity_id",
        "breadcrumbs",
        "name",
        "created_at",
        "updated_at",
        "textual_representation",
        "contextd_system_metadata",
        "schema_name",
        "table_name",
        "primary_key_columns",
    }

    def __init__(self, schema_definitions: Optional[Dict[str, DatabaseTable]] = None):
        """Initialize the PostgreSQL source.

        Args:
            schema_definitions: Optional dictionary of predefined schema definitions
                (table_key -> DatabaseTable). If provided, uses these instead of
                dynamic discovery.
        """
        super().__init__()  # Initialize BaseSource to get cursor support
        self.conn: Optional[asyncpg.Connection] = None
        self.entity_classes: Dict[str, Type[PolymorphicEntity]] = {}
        self.column_field_mappings: Dict[str, Dict[str, str]] = {}
        self.schema_definitions = schema_definitions or {}
        self.schema_converter = DatabaseSchemaConverter()
        self._cursor_column_type_cache: Dict[str, str] = {}

    @classmethod
    async def create(
        cls, credentials: Dict[str, Any], config: Optional[Dict[str, Any]] = None
    ) -> "PostgreSQLSource":
        """Create a new PostgreSQL source instance.

        Args:
            credentials: Dictionary containing connection details:
                - host: Database host
                - port: Database port
                - database: Database name
                - user: Username
                - password: Password
                - schema: Schema to sync (defaults to 'public')
                - tables: Table to sync (defaults to '*')
            config: Optional configuration parameters for the PostgreSQL source.
        """
        instance = cls()
        credentials_config = (
            credentials.model_dump()
            if hasattr(credentials, "model_dump")
            else dict(credentials)
        )
        config = config or {}
        schema = (
            config.get("schema")
            or config.get("db_schema")
            or credentials_config.get("schema")
            or credentials_config.get("db_schema")
            or "public"
        )
        instance.config = {
            **credentials_config,
            **config,
            "schema": schema,
            "db_schema": schema,
            "tables": config.get("tables") or credentials_config.get("tables") or "*",
        }
        return instance

    def _get_table_key(self, schema: str, table: str) -> str:
        """Generate consistent table key for identification."""
        return f"{schema}.{table}"

    def _normalize_model_field_name(self, column_name: str) -> str:
        """Normalize column names to avoid collisions with entity base fields."""
        if column_name == "id":
            return "id_"
        if column_name in self._RESERVED_ENTITY_FIELDS:
            return f"{column_name}_field"
        return column_name

    async def _connect(self) -> None:
        """Establish database connection with timeout and error handling."""
        if not self.conn:
            try:
                # Convert localhost to 127.0.0.1 to avoid DNS resolution issues
                host = (
                    "127.0.0.1"
                    if self.config["host"].lower() in ("localhost", "127.0.0.1")
                    else self.config["host"]
                )
                sslmode = str(self.config.get("sslmode") or "").lower()
                if sslmode == "disable" or host in {"localhost", "127.0.0.1", "::1"}:
                    ssl = False
                elif sslmode in {
                    "allow",
                    "prefer",
                    "require",
                    "verify-ca",
                    "verify-full",
                }:
                    ssl = sslmode
                else:
                    ssl = "require"

                self.conn = await asyncpg.connect(
                    host=host,
                    port=self.config["port"],
                    user=self.config["user"],
                    password=self.config["password"],
                    database=self.config["database"],
                    ssl=ssl,
                    timeout=60.0,  # Connection timeout: allow slow or distant hosts (e.g. cloud DB)
                    command_timeout=900.0,  # Command timeout (15 minutes for slow queries)
                    # Add server settings to prevent idle timeouts
                    server_settings={
                        "jit": "off",  # Disable JIT for predictable performance
                        "statement_timeout": "0",  # No statement timeout (handled client-side)
                        "idle_in_transaction_session_timeout": "0",  # Disable idle timeout
                        "tcp_keepalives_idle": "30",  # Send keepalive after 30s of idle
                        "tcp_keepalives_interval": "10",  # Keepalive interval 10s
                        "tcp_keepalives_count": "6",  # Number of keepalives before considering dead
                    },
                )
                self.logger.info(
                    f"Connected to PostgreSQL at {host}:{self.config['port']}, "
                    f"database: {self.config['database']}"
                )
            except asyncpg.InvalidPasswordError as e:
                raise ValueError("Invalid database credentials") from e
            except asyncpg.InvalidCatalogNameError as e:
                raise ValueError(
                    f"Database '{self.config['database']}' does not exist"
                ) from e
            except asyncio.TimeoutError as e:
                raise ValueError(
                    f"Connection to {self.config['host']}:{self.config['port']} timed out. "
                    "Ensure the server can reach the database (outbound firewall, network, DNS)."
                ) from e
            except (
                OSError,
                asyncpg.CannotConnectNowError,
                asyncpg.ConnectionDoesNotExistError,
            ) as e:
                raise ValueError(
                    f"Could not connect to database at {self.config['host']}:{self.config['port']}."
                    " Please check if the database is running and the port is correct. "
                    f"Error: {str(e)}"
                ) from e
            except Exception as e:
                raise ValueError(f"Database connection failed: {str(e)}") from e

    async def _ensure_connection(self) -> None:
        """Ensure connection is alive and reconnect if needed."""
        if self.conn:
            try:
                # Test connection with a simple query
                await self.conn.fetchval("SELECT 1")
            except (
                asyncpg.ConnectionDoesNotExistError,
                asyncpg.InterfaceError,
                OSError,
            ) as e:
                self.logger.warning(f"Connection lost, reconnecting: {e}")
                self.conn = None
                await self._connect()
            except Exception as e:
                self.logger.error(f"Connection test failed: {e}")
                self.conn = None
                await self._connect()
        else:
            await self._connect()

    async def _get_table_info(self, schema: str, table: str) -> Dict[str, Any]:
        """Get table/view structure information.

        Args:
            schema: Schema name
            table: Table or view name

        Returns:
            Dictionary containing column information and primary keys
        """
        # Get column information (works for both tables and views)
        columns_query = """
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position
        """
        columns = await self.conn.fetch(columns_query, schema, table)

        # Get primary key information (views won't have primary keys)
        pk_query = """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = ($1 || '.' || $2)::regclass AND i.indisprimary
        """
        try:
            primary_keys = [
                pk["attname"] for pk in await self.conn.fetch(pk_query, schema, table)
            ]
        except asyncpg.exceptions.UndefinedTableError:
            # This can happen for views which don't have primary keys
            primary_keys = []

        # If no primary keys found (common for views), try to find best candidate columns
        # This ensures each row gets a unique entity_id without creating huge keys
        if not primary_keys and columns:
            column_names = [col["column_name"] for col in columns]

            # Heuristic: Look for common primary key column names
            # Priority order: id, uuid, guid, then any column ending with _id
            table_key = self._get_table_key(schema, table)
            if "id" in column_names:
                primary_keys = ["id"]
                self.logger.debug(
                    f"No primary keys found for {table_key} (might be a view). "
                    f"Using 'id' column for entity identification."
                )
            elif "uuid" in column_names:
                primary_keys = ["uuid"]
                self.logger.debug(
                    f"No primary keys found for {table_key} (might be a view). "
                    f"Using 'uuid' column for entity identification."
                )
            elif "guid" in column_names:
                primary_keys = ["guid"]
                self.logger.debug(
                    f"No primary keys found for {table_key} (might be a view). "
                    f"Using 'guid' column for entity identification."
                )
            else:
                # Look for columns ending with _id
                id_columns = [col for col in column_names if col.endswith("_id")]
                if id_columns:
                    # Use the first _id column found
                    primary_keys = [id_columns[0]]
                    self.logger.debug(
                        f"No primary keys found for {table_key} (might be a view). "
                        f"Using '{id_columns[0]}' column for entity identification."
                    )
                else:
                    # Last resort: use first column to avoid huge composite keys
                    # This prevents the index size error while still providing some identification
                    primary_keys = [column_names[0]] if column_names else []
                    table_key = self._get_table_key(schema, table)
                    self.logger.warning(
                        f"No primary keys or id columns found for {table_key}. "
                        f"Using first column '{primary_keys[0] if primary_keys else 'none'}' "
                        f"for entity identification. This may not guarantee uniqueness."
                    )

        # Build column metadata
        column_info = {}
        for col in columns:
            pg_type = col["data_type"].lower()
            python_type = PG_TYPE_MAP.get(pg_type, Any)

            column_info[col["column_name"]] = {
                "python_type": python_type,
                "nullable": col["is_nullable"] == "YES",
                "default": col["column_default"],
                "pg_type": pg_type,
            }

        return {
            "columns": column_info,
            "primary_keys": primary_keys,
        }

    async def _build_introspected_schemas(
        self, schema: str, tables: List[str]
    ) -> Dict[str, DatabaseTable]:
        """Introspect database schema and build DatabaseTable definitions with default graph/LLM metadata.

        Same pattern as Asana: automatic schema discovery with graph nodes and LLM enrichment enabled.
        """
        # FK map supporting cross-schema and composite
        # foreign keys (#4). Uses pg_constraint for full
        # cross-schema support instead of information_schema
        # which is limited to the current schema.
        fk_query = """
            SELECT
                cn.nspname AS table_schema,
                cl.relname AS table_name,
                a_src.attname AS column_name,
                cn_ref.nspname AS foreign_table_schema,
                cl_ref.relname AS foreign_table_name,
                a_ref.attname AS foreign_column_name,
                c.conname AS constraint_name,
                array_position(c.conkey, a_src.attnum)
                    AS key_position
            FROM pg_constraint c
            JOIN pg_class cl ON cl.oid = c.conrelid
            JOIN pg_namespace cn ON cn.oid = cl.relnamespace
            JOIN pg_class cl_ref ON cl_ref.oid = c.confrelid
            JOIN pg_namespace cn_ref
                ON cn_ref.oid = cl_ref.relnamespace
            JOIN LATERAL unnest(c.conkey)
                WITH ORDINALITY AS k(attnum, ord)
                ON true
            JOIN pg_attribute a_src
                ON a_src.attrelid = c.conrelid
                AND a_src.attnum = k.attnum
            JOIN LATERAL unnest(c.confkey)
                WITH ORDINALITY AS fk(attnum, ord)
                ON fk.ord = k.ord
            JOIN pg_attribute a_ref
                ON a_ref.attrelid = c.confrelid
                AND a_ref.attnum = fk.attnum
            WHERE c.contype = 'f'
              AND cn.nspname = $1
            ORDER BY c.conname, k.ord
        """
        fk_rows = await self.conn.fetch(fk_query, schema)
        fk_map: Dict[tuple, Dict[str, str]] = {}
        for r in fk_rows:
            fk_map[
                (
                    r["table_schema"],
                    r["table_name"],
                    r["column_name"],
                )
            ] = {
                "ref_schema": r["foreign_table_schema"],
                "ref_table": r["foreign_table_name"],
                "ref_column": r["foreign_column_name"],
            }

        result: Dict[str, DatabaseTable] = {}
        for table in tables:
            table_info = await self._get_table_info(schema, table)
            table_key = self._get_table_key(schema, table)

            columns: Dict[str, DatabaseColumn] = {}
            column_metadata: Dict[str, ColumnMetadata] = {}
            primary_keys = table_info["primary_keys"]
            text_like = ("character varying", "character", "text", "varchar")
            _NAME_EXACT = {
                "name",
                "title",
                "label",
                "subject",
                "display_name",
                "full_name",
            }
            _NAME_SUFFIXES = ("_name", "_title", "_label")
            name_col_found = False

            for col_name, col_meta in table_info["columns"].items():
                pg_type = col_meta.get(
                    "pg_type", col_meta.get("python_type", str).__name__
                )
                if isinstance(pg_type, type):
                    pg_type = "text"
                pg_type_lower = str(pg_type).lower()
                is_pk = col_name in primary_keys
                fk_key = (schema, table, col_name)
                fk_info = fk_map.get(fk_key)

                col_def = DatabaseColumn(
                    name=col_name,
                    column_type=pg_type_lower.replace(" ", "_"),
                    nullable=col_meta.get("nullable", True),
                    default=col_meta.get("default"),
                    primary_key=is_pk,
                    foreign_key=(
                        ForeignKeyConfig(
                            column=col_name,
                            ref_schema=fk_info["ref_schema"],
                            ref_table=fk_info["ref_table"],
                            ref_column=fk_info["ref_column"],
                        )
                        if fk_info
                        else None
                    ),
                )
                columns[col_name] = col_def

                # Default metadata: embeddable for text, is_entity_id for pk, is_name/is_created_at/is_updated_at
                embeddable = pg_type_lower in text_like or "char" in pg_type_lower
                is_name = False
                if not name_col_found:
                    col_lower = col_name.lower()
                    if col_lower in _NAME_EXACT or col_lower.endswith(_NAME_SUFFIXES):
                        is_name = True
                        name_col_found = True
                is_created_at = col_name.lower() in (
                    "created_at",
                    "created",
                    "creation_date",
                )
                is_updated_at = col_name.lower() in (
                    "updated_at",
                    "updated",
                    "modified_at",
                    "modified",
                )
                column_metadata[col_name] = ColumnMetadata(
                    search=SearchConfig(embeddable=embeddable),
                    is_entity_id=is_pk,
                    is_name=is_name,
                    is_created_at=is_created_at,
                    is_updated_at=is_updated_at,
                )

            table_metadata = TableMetadata(
                default_graph_node_type=f"DatabaseTableNode_{schema}_{table}",
                create_entity_node=True,
                enable_llm_enrichment=False,
                index=EntityIndexConfig(
                    enabled=True,
                    fulltext_enabled=True,
                    priority_fields=[c for c in ("name", "title") if c in columns],
                ),
                columns=column_metadata,
            )

            fk_configs = [
                ForeignKeyConfig(
                    column=k[2],
                    ref_schema=v["ref_schema"],
                    ref_table=v["ref_table"],
                    ref_column=v["ref_column"],
                )
                for k, v in fk_map.items()
                if k[0] == schema and k[1] == table
            ]

            table_def = DatabaseTable(
                table_name=table,
                schema_name=schema,
                description=f"Table {schema}.{table} (introspected)",
                columns=columns,
                primary_keys=primary_keys,
                foreign_keys=fk_configs,
                table_metadata=table_metadata,
            )
            result[table_key] = table_def

        return result

    def _infer_implicit_foreign_keys(self, all_tables: Dict[str, DatabaseTable]) -> int:
        """Infer FK relationships from column naming conventions.

        For databases without explicit FK constraints, detects implicit
        relationships by matching columns ending in ``_id`` to existing
        tables (e.g. ``person_id`` → ``persons.id``).

        Only adds inferred FKs where no explicit FK already exists for
        that column.

        Returns:
            Number of implicit FKs added.
        """
        count = 0
        for table_key, table_def in all_tables.items():
            existing_fk_cols = {fk.column for fk in table_def.foreign_keys}
            schema = table_def.schema_name

            for col_name in table_def.columns:
                if (
                    not col_name.endswith("_id")
                    or col_name in existing_fk_cols
                    or col_name == "id"
                ):
                    continue

                base = col_name[:-3]  # strip "_id"

                bases = [base]
                if "_" in base:
                    # home_studio_id should resolve to studios.id, not just
                    # home_studios.id.
                    bases.append(base.rsplit("_", 1)[-1])

                candidates = []
                for item in bases:
                    if item.endswith("y"):
                        candidates.append(f"{schema}.{item[:-1]}ies")
                    candidates.extend(
                        [
                            f"{schema}.{item}s",
                            f"{schema}.{item}es",
                            f"{schema}.{item}",
                        ]
                    )

                for candidate in candidates:
                    if candidate in all_tables and candidate != table_key:
                        ref_table = all_tables[candidate]
                        pk_col = (
                            ref_table.primary_keys[0]
                            if ref_table.primary_keys
                            else "id"
                        )
                        table_def.foreign_keys.append(
                            ForeignKeyConfig(
                                column=col_name,
                                ref_schema=ref_table.schema_name,
                                ref_table=ref_table.table_name,
                                ref_column=pk_col,
                            )
                        )
                        count += 1
                        break

        return count

    async def _create_entity_class(
        self, schema: str, table: str
    ) -> Type[PolymorphicEntity]:
        """Create a entity class for a specific table or view.

        Checks for predefined schema definitions first, then falls back to
        dynamic discovery.

        Args:
            schema: Schema name
            table: Table or view name

        Returns:
            Dynamically created entity class for the table/view with metadata attached
        """
        table_key = self._get_table_key(schema, table)

        # Check if entity class already exists in cache
        if table_key in self.entity_classes:
            return self.entity_classes[table_key]

        # Check if entity class is already registered (from pre-registration)
        from contextd.platform.configs.database.entity_registry import (
            DatabaseEntityClassRegistry,
        )

        registered_class = DatabaseEntityClassRegistry.get_entity_class(table_key)
        if registered_class:
            self.entity_classes[table_key] = registered_class
            return registered_class

        # Check registry first (for schemas loaded in sync factory)
        from contextd.platform.configs.database.registry import DatabaseSchemaRegistry

        registry_schema = DatabaseSchemaRegistry.get_schema("postgres", table_key)
        if registry_schema:
            table_def = registry_schema
        elif table_key in self.schema_definitions:
            table_def = self.schema_definitions[table_key]
        else:
            table_def = None

        if table_def:

            # Get column mapping (still need to normalize column names)
            # We'll create a mapping from the table definition
            column_mapping: Dict[str, str] = {}
            normalized_columns: Dict[str, Dict[str, Any]] = {}

            for original_name, col_def in table_def.columns.items():
                base_name = self._normalize_model_field_name(original_name)
                candidate = base_name
                suffix = 1
                while candidate in normalized_columns:
                    suffix += 1
                    candidate = f"{base_name}_{suffix}"
                normalized_columns[candidate] = {
                    "python_type": PG_TYPE_MAP.get(col_def.column_type.lower(), Any),
                    "nullable": col_def.nullable,
                    "default": col_def.default,
                }
                column_mapping[original_name] = candidate

            self.column_field_mappings[table_key] = column_mapping

            # Use schema converter to create entity class with metadata
            # Get all tables from registry and instance schemas for FK resolution
            from contextd.platform.configs.database.registry import (
                DatabaseSchemaRegistry,
            )

            all_registry_tables = DatabaseSchemaRegistry.get_all_schemas("postgres")
            all_tables = {**all_registry_tables, **self.schema_definitions}
            entity_class = self.schema_converter.convert_table_to_entity_class(
                table_def, column_mapping, all_tables
            )

            # Cache the entity class
            self.entity_classes[table_key] = entity_class

            # Register the entity class with its entity definition ID (if not already registered)
            await self._register_entity_class(
                table_key, entity_class, table_def.schema_name, table_def.table_name
            )

            return entity_class

        # Fallback to dynamic discovery
        table_info = await self._get_table_info(schema, table)

        normalized_columns: Dict[str, Dict[str, Any]] = {}
        column_mapping: Dict[str, str] = {}
        for original_name, column_meta in table_info["columns"].items():
            base_name = self._normalize_model_field_name(original_name)
            candidate = base_name
            suffix = 1
            while candidate in normalized_columns:
                suffix += 1
                candidate = f"{base_name}_{suffix}"
            normalized_columns[candidate] = column_meta
            column_mapping[original_name] = candidate

        self.column_field_mappings[table_key] = column_mapping

        entity_class = PolymorphicEntity.create_table_entity_class(
            table_name=table,
            schema_name=schema,
            columns=normalized_columns,
            primary_keys=table_info["primary_keys"],
        )

        # Cache the entity class
        self.entity_classes[table_key] = entity_class

        # Register the entity class (for dynamic discovery, use reserved ID)
        await self._register_entity_class(table_key, entity_class, schema, table)

        return entity_class

    async def _register_entity_class(
        self,
        table_key: str,
        entity_class: Type[PolymorphicEntity],
        schema_name: str,
        table_name: str,
    ) -> None:
        """Register a dynamically created entity class with its entity definition ID.

        Args:
            table_key: Table key in format 'schema.table'
            entity_class: The dynamically created entity class
            schema_name: Schema name
            table_name: Table name
        """
        from contextd.platform.configs.database.entity_registry import (
            DatabaseEntityClassRegistry,
        )

        # Check if already registered. Concurrent table streams can create duplicate
        # dynamic classes for the same table; map each alias to the same definition.
        existing_class = DatabaseEntityClassRegistry.get_entity_class(table_key)
        if existing_class:
            existing_definition_id = DatabaseEntityClassRegistry.get_entity_definition_id(
                existing_class
            )
            if existing_definition_id:
                DatabaseEntityClassRegistry.register_entity_class(
                    table_key, entity_class, existing_definition_id
                )
                return

        # Look up entity definition ID
        # Entity definition name format: DatabaseTable_{schema}_{table}
        entity_name = f"DatabaseTable_{schema_name}_{table_name}"

        try:
            # Try to get entity definition ID from database
            from contextd.db.session import get_db_context

            async with get_db_context() as db:
                from contextd import crud

                try:
                    entity_def = await crud.entity_definition.get_by_entity_class_name(
                        db, entity_class_name=entity_name
                    )
                    entity_definition_id = entity_def.id
                except Exception:
                    # If not found, use reserved polymorphic entity ID as fallback
                    from contextd.db.init_db_native import RESERVED_TABLE_ENTITY_ID

                    entity_definition_id = RESERVED_TABLE_ENTITY_ID
        except Exception:
            # If database lookup fails, use reserved polymorphic entity ID as fallback
            from contextd.db.init_db_native import RESERVED_TABLE_ENTITY_ID

            entity_definition_id = RESERVED_TABLE_ENTITY_ID

        # Register the entity class
        DatabaseEntityClassRegistry.register_entity_class(
            table_key, entity_class, entity_definition_id
        )

    async def _get_tables(self, schema: str) -> List[str]:
        """Get list of tables in a schema.

        Args:
            schema: Schema name

        Returns:
            List of table names
        """
        query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = $1
            AND table_type = 'BASE TABLE'
        """
        tables = await self.conn.fetch(query, schema)
        return [table["table_name"] for table in tables]

    async def _get_tables_and_views(self, schema: str) -> List[str]:
        """Get list of tables, views, and materialized views.

        Args:
            schema: Schema name

        Returns:
            List of table, view, and materialized view names
        """
        # Regular tables and views from information_schema
        query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = $1
            AND table_type IN ('BASE TABLE', 'VIEW')
        """
        rows = await self.conn.fetch(query, schema)
        result = [item["table_name"] for item in rows]

        # Materialized views from pg_matviews (#3)
        matview_query = """
            SELECT matviewname
            FROM pg_matviews
            WHERE schemaname = $1
        """
        matview_rows = await self.conn.fetch(matview_query, schema)
        for row in matview_rows:
            name = row["matviewname"]
            if name not in result:
                result.append(name)

        return result

    async def _get_materialized_views(self, schema: str) -> List[str]:
        """Get list of materialized views in a schema.

        Args:
            schema: Schema name

        Returns:
            List of materialized view names
        """
        query = """
            SELECT matviewname
            FROM pg_matviews
            WHERE schemaname = $1
        """
        rows = await self.conn.fetch(query, schema)
        return [row["matviewname"] for row in rows]

    async def _get_table_list(self, schema: str) -> List[str]:
        """Get the list of tables to process based on configuration.

        When wildcard (*) is used, base tables and materialized
        views are returned.
        When specific names are provided, tables, views, and
        materialized views are checked.
        """
        tables_config = self.config.get("tables", "*") or "*"

        if tables_config == "*":
            # Include base tables + materialized views (#3)
            base = await self._get_tables(schema)
            matviews = await self._get_materialized_views(schema)
            combined = base + [m for m in matviews if m not in base]
            if matviews:
                self.logger.info(
                    "Including materialized views: " f"{', '.join(matviews)}"
                )
            return combined

        tables = [t.strip() for t in tables_config.split(",") if t.strip()]

        if not tables:
            base = await self._get_tables(schema)
            matviews = await self._get_materialized_views(schema)
            return base + [m for m in matviews if m not in base]

        # Check tables, views, and materialized views
        available = await self._get_tables_and_views(schema)
        invalid_items = set(tables) - set(available)
        if invalid_items:
            raise ValueError(
                f"Tables/views not found in schema "
                f"'{schema}': {', '.join(invalid_items)}"
            )

        base_tables = set(await self._get_tables(schema))
        non_base = [t for t in tables if t not in base_tables]
        if non_base:
            self.logger.info(f"Including views/matviews: " f"{', '.join(non_base)}")

        return tables

    # ----------------------------------------------------------
    # #1  Schema change detection & evolution
    # ----------------------------------------------------------
    async def _detect_schema_changes(
        self,
        schema: str,
        tables: List[str],
        new_snapshot: List[Dict[str, Any]],
    ) -> None:
        """Compare new introspected schema against stored catalog.

        Logs added/removed/changed columns so operators can
        react to upstream schema evolution.
        """
        if not (
            getattr(self, "_organization_id", None)
            and getattr(self, "_source_connection_id", None)
        ):
            return

        try:
            from sqlalchemy import select

            from contextd.models.pg_field_catalog import (
                PgFieldCatalogTable,
            )

            async with get_db_context() as db:
                old_tables = (
                    await db.scalars(
                        select(PgFieldCatalogTable).where(
                            PgFieldCatalogTable.organization_id
                            == self._organization_id,
                            PgFieldCatalogTable.source_connection_id
                            == self._source_connection_id,
                        )
                    )
                ).all()

            if not old_tables:
                self.logger.info(
                    "No previous catalog found — " "first sync, skipping schema diff"
                )
                return

            # Build lookup: (schema, table) -> {col_name: type}
            old_map: Dict[str, Dict[str, str]] = {}
            for t in old_tables:
                key = f"{t.schema_name}.{t.table_name}"
                old_map[key] = {c.column_name: c.data_type or "" for c in t.columns}

            new_map: Dict[str, Dict[str, str]] = {}
            for t in new_snapshot:
                key = f"{t['schema_name']}.{t['table_name']}"
                new_map[key] = {
                    c["column_name"]: c.get("data_type", "")
                    for c in t.get("columns", [])
                }

            # Detect changes
            added_tables = set(new_map) - set(old_map)
            removed_tables = set(old_map) - set(new_map)
            common = set(old_map) & set(new_map)

            if added_tables:
                self.logger.info(
                    f"Schema change: new tables: " f"{', '.join(sorted(added_tables))}"
                )
            if removed_tables:
                self.logger.warning(
                    f"Schema change: removed tables: "
                    f"{', '.join(sorted(removed_tables))}"
                )

            for tbl in sorted(common):
                old_cols = old_map[tbl]
                new_cols = new_map[tbl]
                added = set(new_cols) - set(old_cols)
                removed = set(old_cols) - set(new_cols)
                type_changed = [
                    c
                    for c in set(old_cols) & set(new_cols)
                    if old_cols[c] != new_cols[c]
                ]
                if added:
                    self.logger.info(
                        f"Schema change [{tbl}]: "
                        f"added columns: "
                        f"{', '.join(sorted(added))}"
                    )
                if removed:
                    self.logger.warning(
                        f"Schema change [{tbl}]: "
                        f"removed columns: "
                        f"{', '.join(sorted(removed))}"
                    )
                if type_changed:
                    for c in type_changed:
                        self.logger.warning(
                            f"Schema change [{tbl}]: "
                            f"column '{c}' type changed "
                            f"from '{old_cols[c]}' "
                            f"to '{new_cols[c]}'"
                        )
        except Exception as e:
            self.logger.warning(f"Schema change detection failed: {e}")

    # ----------------------------------------------------------
    # #2  Smarter graph node type inference via LLM
    # ----------------------------------------------------------
    async def _infer_node_types_with_llm(
        self,
        schema: str,
        introspected: Dict[str, "DatabaseTable"],
    ) -> None:
        """Use LLM to infer meaningful graph node types, column aliases, and FK edge types.

        Calls the business logic extraction pipeline to replace generic names
        like DatabaseTableNode_public_orders with semantic types like Order, Person, Product.
        Also infers human-readable column aliases and semantic FK edge types.
        """
        self.logger.info(
            "Skipping LLM schema inference for structured PostgreSQL source"
        )
        return
        try:
            from contextd.platform.agent_orchestration.business_logic_extraction import (  # noqa: E501
                extract_business_logic_with_llm,
            )
        except ImportError:
            self.logger.debug("business_logic_extraction not available")
            return

        # Build sample data per table (up to 3 rows)
        samples: Dict[str, List[Dict[str, Any]]] = {}
        # Build FK info and column types for LLM context
        foreign_keys_by_table: Dict[str, List[Dict[str, str]]] = {}
        column_types_by_table: Dict[str, Dict[str, str]] = {}

        for table_key, table_def in introspected.items():
            tbl = table_def.table_name
            sch = table_def.schema_name or schema
            try:
                rows = await self.conn.fetch(f'SELECT * FROM "{sch}"."{tbl}" LIMIT 3')
                samples[table_key] = [dict(r) for r in rows]
            except Exception:
                samples[table_key] = []

            # Collect FK info
            if table_def.foreign_keys:
                foreign_keys_by_table[table_key] = [
                    {
                        "column": fk.column,
                        "ref_table": fk.ref_table,
                        "ref_column": fk.ref_column,
                    }
                    for fk in table_def.foreign_keys
                ]

            # Collect column types
            if table_def.columns:
                column_types_by_table[table_key] = {
                    col_name: col_def.column_type
                    for col_name, col_def in table_def.columns.items()
                }

        if not any(samples.values()):
            return

        try:
            result = await extract_business_logic_with_llm(
                source_type="postgresql",
                samples_by_entity_type=samples,
                foreign_keys_by_table=foreign_keys_by_table,
                column_types_by_table=column_types_by_table,
                logger_instance=logger,
            )
            if not result:
                return

            # --- Improvement C: Map node types by table name (not position) ---
            for table_key, table_def in introspected.items():
                if not table_def.table_metadata:
                    continue
                tbl = table_def.table_name
                # Try exact table name match, then table_key match
                inferred = result.table_node_types.get(
                    tbl
                ) or result.table_node_types.get(table_key)
                if inferred:
                    table_def.table_metadata.default_graph_node_type = inferred
                    self.logger.info(
                        f"LLM inferred node type " f"for {table_key}: {inferred}"
                    )

            # --- Improvement A: Apply column aliases as display_name ---
            for table_key, table_def in introspected.items():
                if not table_def.table_metadata:
                    continue
                tbl = table_def.table_name
                aliases = (
                    result.column_aliases.get(tbl)
                    or result.column_aliases.get(table_key)
                    or {}
                )
                for col_name, display_name in aliases.items():
                    col_meta = table_def.table_metadata.columns.get(col_name)
                    if col_meta:
                        col_meta.display_name = display_name
                        self.logger.debug(
                            f"LLM alias for {table_key}.{col_name}: {display_name}"
                        )

            # --- Improvement B: Store FK edge types for converter to use ---
            # Store on the table_def for later use by convert_foreign_keys_to_graph_edges
            for table_key, table_def in introspected.items():
                tbl = table_def.table_name
                fk_edges = {}
                for fk in table_def.foreign_keys:
                    edge_key = f"{tbl}.{fk.column}"
                    alt_key = f"{table_key}.{fk.column}"
                    edge_type = result.fk_edge_types.get(
                        edge_key
                    ) or result.fk_edge_types.get(alt_key)
                    if edge_type:
                        fk_edges[fk.column] = edge_type
                if fk_edges:
                    # Store as llm_edge_labels on table_metadata for converter
                    table_def.table_metadata.llm_edge_labels = fk_edges

            # --- Improvement E: Auto-configure search from entity_property_shapes ---
            if result.logic.entity_property_shapes:
                for table_key, table_def in introspected.items():
                    if not table_def.table_metadata:
                        continue
                    tbl = table_def.table_name
                    node_type = table_def.table_metadata.default_graph_node_type
                    # Find matching shapes by node_type or table name
                    useful_keys = (
                        result.logic.entity_property_shapes.get(node_type)
                        or result.logic.entity_property_shapes.get(tbl)
                        or []
                    )
                    for col_name in useful_keys:
                        col_meta = table_def.table_metadata.columns.get(col_name)
                        if col_meta and not col_meta.search.embeddable:
                            col_meta.search = SearchConfig(embeddable=True)
                            self.logger.debug(
                                f"LLM auto-enabled search for {table_key}.{col_name}"
                            )

        except Exception as e:
            self.logger.warning(
                f"LLM node type inference failed " f"(using defaults): {e}"
            )

    # ----------------------------------------------------------
    # #6  Data sampling for schema validation
    # ----------------------------------------------------------
    async def _sample_table_data(
        self,
        schema: str,
        table: str,
        sample_size: int = 100,
    ) -> Dict[str, Any]:
        """Sample rows from a table to detect data patterns.

        Returns column-level statistics: null ratio,
        distinct count estimate, and whether text columns
        contain JSON or enum-like values.
        """
        stats: Dict[str, Any] = {}
        try:
            rows = await self.conn.fetch(
                f'SELECT * FROM "{schema}"."{table}" ' f"LIMIT {sample_size}"
            )
            if not rows:
                return stats

            columns = list(rows[0].keys())
            total = len(rows)

            for col in columns:
                values = [r[col] for r in rows]
                nulls = sum(1 for v in values if v is None)
                non_null = [v for v in values if v is not None]
                distinct = len({str(v) for v in non_null})

                col_stats: Dict[str, Any] = {
                    "null_ratio": nulls / total,
                    "distinct_count": distinct,
                }

                # Detect JSON in text columns
                if non_null and isinstance(non_null[0], str):
                    json_count = 0
                    for v in non_null[:20]:
                        try:
                            json.loads(v)
                            json_count += 1
                        except (json.JSONDecodeError, ValueError):
                            pass
                    if non_null and json_count > len(non_null[:20]) * 0.8:
                        col_stats["likely_json"] = True

                # Detect enum-like columns (low cardinality)
                if 0 < distinct <= 20 and total >= 10 and distinct < total * 0.3:
                    col_stats["likely_enum"] = True
                    col_stats["enum_values"] = sorted({str(v) for v in non_null})[:20]

                stats[col] = col_stats

        except Exception as e:
            self.logger.debug(f"Sampling {schema}.{table} failed: {e}")

        return stats

    async def _convert_field_values(
        self, data: Dict[str, Any], model_fields: Dict[str, Any], table_key: str
    ) -> Dict[str, Any]:
        """Convert field values to the expected types based on the entity model.

        Args:
            data: The raw data dictionary from the database record
            model_fields: The model fields from the entity class
            table_key: Unique identifier for the table to resolve column mappings

        Returns:
            Dict with processed field values matching the expected types
        """
        processed_data = {}
        column_mapping = self.column_field_mappings.get(table_key, {})
        for field_name, field_value in data.items():
            model_field_name = column_mapping.get(field_name)
            if not model_field_name:
                model_field_name = self._normalize_model_field_name(field_name)

            # Skip if the field doesn't exist in the model
            if model_field_name not in model_fields:
                continue

            # If value is None, keep it as None
            if field_value is None:
                processed_data[model_field_name] = None
                continue

            # Get expected type from model field
            field_info = model_fields[model_field_name]
            field_type = field_info.annotation

            # Handle Union types (including Optional which is Union[T, None])
            if hasattr(field_type, "__origin__") and field_type.__origin__ is Union:
                # For Union types, get the non-None type (if it's Optional pattern)
                union_args = field_type.__args__
                # Filter out NoneType to get the actual type
                non_none_types = [arg for arg in union_args if arg is not type(None)]
                if non_none_types:
                    field_type = non_none_types[0]  # Take the first non-None type

            # Simple conversion: if target is string, convert to string
            if field_type is str and field_value is not None:
                processed_data[model_field_name] = str(field_value)
            else:
                # Let Pydantic handle everything else
                processed_data[model_field_name] = field_value

        return processed_data

    def _parse_json_fields(self, data: Dict[str, Any]) -> None:
        """Parse string fields that contain JSON data.

        Args:
            data: Dictionary to process (modified in place)
        """
        for key, value in data.items():
            if not isinstance(value, str):
                continue

            try:
                parsed_value = json.loads(value)
                data[key] = parsed_value
            except (json.JSONDecodeError, ValueError):
                # Keep as string if not valid JSON
                pass

    def _generate_entity_id(
        self, schema: str, table: str, data: Dict[str, Any], primary_keys: List[str]
    ) -> str:
        """Generate entity ID from primary key values or hash.

        Args:
            schema: Schema name
            table: Table name
            data: Record data
            primary_keys: List of primary key columns

        Returns:
            Generated entity ID
        """
        pk_values = [str(data[pk]) for pk in primary_keys if pk in data]
        table_key = self._get_table_key(schema, table)

        if pk_values:
            return f"{table_key}:" + ":".join(pk_values)

        # Fallback: use a hash of the row data if no primary keys are available
        row_hash = hashlib.md5(str(sorted(data.items())).encode()).hexdigest()[:16]
        entity_id = f"{table_key}:row_{row_hash}"
        self.logger.warning(
            f"No primary key values found for {table_key} row. "
            f"Using hash-based entity_id: {entity_id}"
        )
        return entity_id

    def _ensure_entity_id_length(self, entity_id: str, schema: str, table: str) -> str:
        """Ensure entity ID is within acceptable length limits.

        Args:
            entity_id: Original entity ID
            schema: Schema name
            table: Table name

        Returns:
            Entity ID (possibly hashed if too long)
        """
        # PostgreSQL btree index has a limit of ~2700 bytes, but we use 2000 to be safe
        if len(entity_id) <= 2000:
            return entity_id

        original_id = entity_id
        entity_hash = hashlib.sha256(entity_id.encode()).hexdigest()
        table_key = self._get_table_key(schema, table)
        entity_id = f"{table_key}:hashed_{entity_hash}"
        self.logger.warning(
            f"Entity ID too long ({len(original_id)} chars) for {table_key}. "
            f"Using hashed ID: {entity_id}"
        )
        return entity_id

    async def _process_record_to_entity(
        self,
        record: Any,
        schema: str,
        table: str,
        entity_class: Type[PolymorphicEntity],
        primary_keys: List[str],
    ) -> BaseEntity:
        """Process a database record into an entity."""
        data = dict(record)

        self._parse_json_fields(data)

        entity_id = self._generate_entity_id(schema, table, data, primary_keys)
        entity_id = self._ensure_entity_id_length(entity_id, schema, table)

        table_key = self._get_table_key(schema, table)
        processed_data = await self._convert_field_values(
            data, entity_class.model_fields, table_key
        )

        entity_name_field = self.column_field_mappings.get(table_key, {}).get("name")
        entity_name = (
            processed_data.get(entity_name_field) if entity_name_field else None
        )
        if not entity_name:
            entity_name = table

        return entity_class(
            entity_id=entity_id,
            breadcrumbs=[],  # Tables are top-level
            name=entity_name,
            created_at=None,
            updated_at=None,
            **processed_data,
        )

    def _quote_identifier(self, identifier: str) -> str:
        """Quote a PostgreSQL identifier for generated read-only SQL."""
        return f'"{identifier.replace(chr(34), chr(34) + chr(34))}"'

    async def _table_has_column(self, schema: str, table: str, column: str) -> bool:
        return bool(
            await self.conn.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = $1
                      AND table_name = $2
                      AND column_name = $3
                );
                """,
                schema,
                table,
                column,
            )
        )

    def _serialize_cursor_value(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (date, time)):
            return value.isoformat()
        return str(value)

    async def _get_cursor_column_type(
        self, schema: str, table: str, column: str
    ) -> str:
        cache_key = f"{schema}.{table}.{column}"
        if cache_key not in self._cursor_column_type_cache:
            row = await self.conn.fetchrow(
                """
                SELECT data_type, udt_name
                FROM information_schema.columns
                WHERE table_schema = $1
                  AND table_name = $2
                  AND column_name = $3
                """,
                schema,
                table,
                column,
            )
            data_type = (row["data_type"] if row else "") or ""
            udt_name = (row["udt_name"] if row else "") or ""
            self._cursor_column_type_cache[cache_key] = (
                f"{data_type} {udt_name}".lower()
            )
        return self._cursor_column_type_cache[cache_key]

    async def _deserialize_cursor_value(
        self, schema: str, table: str, column: str, value: Any
    ) -> Any:
        if not isinstance(value, str):
            return value
        raw = value.strip()
        if raw == "":
            return None

        column_type = await self._get_cursor_column_type(schema, table, column)
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw

        try:
            if "timestamp" in column_type:
                parsed = datetime.fromisoformat(normalized)
                if "without time zone" in column_type:
                    return parsed.replace(tzinfo=None)
                return parsed
            if "date" in column_type:
                return date.fromisoformat(raw.split("T", 1)[0])
            if "time" in column_type:
                return time.fromisoformat(raw.split("T", 1)[-1])
            if any(token in column_type for token in ("int", "serial")):
                return int(raw)
            if any(token in column_type for token in ("numeric", "decimal")):
                return Decimal(raw)
            if any(token in column_type for token in ("real", "double", "float")):
                return float(raw)
        except (ValueError, InvalidOperation) as exc:
            raise ValueError(
                f"Stored cursor value '{value}' is not valid for {schema}.{table}.{column}"
            ) from exc

        return value

    def _update_table_cursor(self, table_key: str, value: Any) -> None:
        if not self.cursor or value is None:
            return
        cursor_data = self.cursor.data or {}
        table_cursors = dict(cursor_data.get("table_cursors") or {})
        table_cursors[table_key] = self._serialize_cursor_value(value)
        self.cursor.update(table_cursors=table_cursors)

    async def _process_table_with_streaming(  # noqa: C901
        self,
        schema: str,
        table: str,
        entity_class: Type[PolymorphicEntity],
    ) -> AsyncGenerator[BaseEntity, None]:
        """Process table using server-side cursor for efficient streaming.

        Uses PostgreSQL's server-side cursor for optimal performance on large tables.
        This avoids the OFFSET penalty and streams data efficiently.

        IMPORTANT: Entities are yielded immediately as they're processed — there is no
        Python-level buffering. Previously, a 2000-entity buffer pattern caused long idle
        periods on the PostgreSQL connection while the buffer drained through a
        backpressure-limited queue, leading to connection drops on cloud PostgreSQL
        services (NeonDB, RDS, etc.) and sync stalls at ~76,800 entities.

        asyncpg's ``prefetch`` parameter still handles efficient network-level batching
        (fetching rows in chunks from PostgreSQL), so throughput is not impacted.

        Args:
            schema: Schema name
            table: Table name
            entity_class: Entity class for the table

        Yields:
            Entities from the table
        """
        table_key = self._get_table_key(schema, table)

        total_records = 0
        primary_keys = entity_class.model_fields[
            "primary_key_columns"
        ].default_factory()

        try:
            # Use server-side cursor for efficient streaming
            # This is much more efficient than client-side fetch with OFFSET
            self.logger.info(f"Starting server-side cursor stream for {table_key}")

            PREFETCH_SIZE = 2000  # asyncpg prefetches this many rows from PG at a time

            query = f"""
                SELECT * FROM "{schema}"."{table}"
            """
            query_args: list[Any] = []
            cursor_field = self.config.get("cursor_field")
            has_cursor_column = False
            if cursor_field:
                has_cursor_column = await self._table_has_column(
                    schema, table, cursor_field
                )
                if has_cursor_column:
                    table_cursors = (self.cursor.data if self.cursor else {}).get(
                        "table_cursors", {}
                    )
                    cursor_value = table_cursors.get(table_key)
                    cursor_value = await self._deserialize_cursor_value(
                        schema, table, cursor_field, cursor_value
                    )
                    quoted_cursor = self._quote_identifier(cursor_field)
                    if cursor_value not in (None, ""):
                        query = f"""
                            SELECT * FROM "{schema}"."{table}"
                            WHERE {quoted_cursor} > $1
                            ORDER BY {quoted_cursor} ASC
                        """
                        query_args.append(cursor_value)
                    else:
                        query = f"""
                            SELECT * FROM "{schema}"."{table}"
                            ORDER BY {quoted_cursor} ASC
                        """
                else:
                    self.logger.warning(
                        f"Cursor field '{cursor_field}' was not found on {table_key}; "
                        "falling back to full table streaming."
                    )

            # Use server-side cursor with prefetch for efficient streaming.
            # The transaction is required by asyncpg for server-side cursors.
            # Entities are yielded immediately (no buffering) to minimize idle time
            # on the PG connection during downstream backpressure pauses.
            async with self.conn.transaction():
                cursor = self.conn.cursor(query, *query_args, prefetch=PREFETCH_SIZE)

                async for record in cursor:
                    # Process record to entity using consolidated logic
                    entity = await self._process_record_to_entity(
                        record, schema, table, entity_class, primary_keys
                    )

                    # Yield entity immediately — no buffering.
                    # This prevents long idle periods on the PG connection that occur
                    # when a large buffer must drain through the backpressure-limited queue.
                    yield entity
                    if has_cursor_column and cursor_field:
                        self._update_table_cursor(table_key, record.get(cursor_field))
                    total_records += 1

                    # Log progress periodically
                    if total_records % 5000 == 0:
                        self.logger.info(
                            f"Table {table_key}: Streamed {total_records} records"
                        )

            self.logger.info(
                f"Table {table_key}: Completed server-side cursor stream, {total_records} records"
            )

        except Exception as e:
            self.logger.error(
                f"Server-side cursor failed for {table_key} "
                f"after {total_records} records: {e}"
            )
            # Re-raise the exception since we don't have a fallback
            # The sync will fail and can be retried
            raise

    async def _process_table(
        self,
        schema: str,
        table: str,
    ) -> AsyncGenerator[BaseEntity, None]:
        """Process a single table using server-side cursor streaming.

        Uses PostgreSQL's server-side cursor for efficient streaming of data,
        maintaining transaction consistency and avoiding OFFSET penalties.

        Args:
            schema: Schema name
            table: Table name

        Yields:
            Entities from the table
        """
        table_key = self._get_table_key(schema, table)

        # Verify connection is still alive before starting a new table.
        # This catches connection drops that may have occurred during backpressure
        # pauses between tables (e.g., cloud PG load balancer timeouts).
        await self._ensure_connection()

        # Create entity class if not already created
        if table_key not in self.entity_classes:
            self.entity_classes[table_key] = await self._create_entity_class(
                schema, table
            )

        entity_class = self.entity_classes[table_key]
        # Always use server-side cursor for efficient streaming
        # This provides consistent snapshot isolation and better performance
        self.logger.info(f"Using server-side cursor for streaming {table_key}")
        async for entity in self._process_table_with_streaming(
            schema, table, entity_class
        ):
            yield entity

    async def generate_entities(  # noqa: C901
        self,
    ) -> AsyncGenerator[BaseEntity, None]:
        """Generate entities for all tables with schema
        change detection, LLM inference, data sampling,
        and per-table error isolation.
        """
        table_results: Dict[str, str] = {}  # #9 tracking
        try:
            await self._connect()
            schema = self.config.get("schema", "public") or "public"
            tables = await self._get_table_list(schema)

            self.logger.info(
                f"Found {len(tables)} table(s) to sync "
                f"in schema '{schema}': {', '.join(tables)}"
            )

            # Introspect schema
            DatabaseSchemaRegistry.clear_schemas("postgres")
            DatabaseEntityClassRegistry.clear()
            self.entity_classes.clear()
            self.logger.debug(
                "Cleared DatabaseSchemaRegistry, "
                "DatabaseEntityClassRegistry, and "
                "entity_classes cache for fresh sync"
            )
            introspected = await self._build_introspected_schemas(schema, tables)

            # Log explicit FK count from introspection
            explicit_fk_count = sum(len(t.foreign_keys) for t in introspected.values())
            self.logger.debug(
                f"Introspected {len(introspected)} table(s) "
                f"with {explicit_fk_count} explicit FK(s)"
            )

            # Infer implicit FKs from column naming conventions
            implicit_fk_count = self._infer_implicit_foreign_keys(introspected)
            if implicit_fk_count:
                self.logger.info(
                    f"Inferred {implicit_fk_count} implicit "
                    f"FK relationship(s) from column naming"
                )

            # #2 Smarter node type inference via LLM
            await self._infer_node_types_with_llm(schema, introspected)

            DatabaseSchemaRegistry.register_schemas("postgres", introspected)
            self.logger.info(
                f"Loaded automatic schema for "
                f"{len(introspected)} table(s) "
                f"(graph + LLM enabled)"
            )

            # #6 Data sampling for schema validation
            for tbl in tables:
                try:
                    sample_stats = await self._sample_table_data(schema, tbl)
                    tkey = self._get_table_key(schema, tbl)
                    for col, stats in sample_stats.items():
                        if stats.get("likely_json"):
                            self.logger.info(f"[{tkey}] column " f"'{col}' likely JSON")
                        if stats.get("likely_enum"):
                            vals = stats.get("enum_values", [])
                            self.logger.info(
                                f"[{tkey}] column " f"'{col}' likely enum: " f"{vals}"
                            )
                except Exception as e:
                    self.logger.debug(f"Sampling {tbl} failed: {e}")

            # Persist field catalog & detect schema changes
            try:
                snapshot = await self._build_field_catalog_snapshot(schema, tables)

                # #1 Schema change detection
                await self._detect_schema_changes(schema, tables, snapshot)

                if getattr(self, "_organization_id", None) and getattr(
                    self, "_source_connection_id", None
                ):
                    async with get_db_context() as db:
                        await overwrite_catalog(
                            db=db,
                            organization_id=self._organization_id,
                            source_connection_id=self._source_connection_id,
                            snapshot=snapshot,
                            logger=self.logger,
                        )
                        await db.commit()
            except Exception as e:
                self.logger.warning(f"Field catalog update failed: {e}")

            # #9 Per-table error isolation
            for i, table in enumerate(tables, 1):
                table_key = self._get_table_key(schema, table)
                self.logger.info(f"Processing table " f"{i}/{len(tables)}: {table_key}")

                try:
                    await self._ensure_connection()
                    async for entity in self._process_table(schema, table):
                        yield entity
                    table_results[table_key] = "success"
                except Exception as e:
                    table_results[table_key] = f"error: {e}"
                    self.logger.error(
                        f"Table {table_key} failed: {e}. "
                        f"Continuing with remaining tables."
                    )
                    # Reset connection for next table
                    if self.conn:
                        try:
                            await self.conn.close()
                        except Exception:
                            pass
                        self.conn = None

            # #9 Summary of per-table results
            ok = sum(1 for v in table_results.values() if v == "success")
            failed = len(table_results) - ok
            if failed:
                self.logger.warning(
                    f"Sync completed: {ok} tables OK, " f"{failed} failed"
                )
                for t, r in table_results.items():
                    if r != "success":
                        self.logger.warning(f"  {t}: {r}")
                if ok == 0:
                    raise ValueError(
                        "All selected PostgreSQL tables failed during sync; "
                        "marking the sync job as failed instead of completing with zero data."
                    )
            else:
                self.logger.info(
                    f"Successfully completed sync " f"for all {len(tables)} table(s)"
                )

        finally:
            if self.conn:
                self.logger.info("Closing PostgreSQL connection")
                await self.conn.close()
                self.conn = None

    async def _build_field_catalog_snapshot(
        self, schema: str, tables: List[str]
    ) -> List[Dict[str, Any]]:
        """Build a full catalog snapshot for the given tables."""
        results: List[Dict[str, Any]] = []

        # Preload FK map using pg_constraint (#4)
        fk_query = """
            SELECT
                cn.nspname AS table_schema,
                cl.relname AS table_name,
                a_src.attname AS column_name,
                cn_ref.nspname AS foreign_table_schema,
                cl_ref.relname AS foreign_table_name,
                a_ref.attname AS foreign_column_name
            FROM pg_constraint c
            JOIN pg_class cl
                ON cl.oid = c.conrelid
            JOIN pg_namespace cn
                ON cn.oid = cl.relnamespace
            JOIN pg_class cl_ref
                ON cl_ref.oid = c.confrelid
            JOIN pg_namespace cn_ref
                ON cn_ref.oid = cl_ref.relnamespace
            JOIN LATERAL unnest(c.conkey)
                WITH ORDINALITY AS k(attnum, ord)
                ON true
            JOIN pg_attribute a_src
                ON a_src.attrelid = c.conrelid
                AND a_src.attnum = k.attnum
            JOIN LATERAL unnest(c.confkey)
                WITH ORDINALITY AS fk(attnum, ord)
                ON fk.ord = k.ord
            JOIN pg_attribute a_ref
                ON a_ref.attrelid = c.confrelid
                AND a_ref.attnum = fk.attnum
            WHERE c.contype = 'f'
              AND cn.nspname = $1
            ORDER BY c.conname, k.ord
        """
        fk_rows = await self.conn.fetch(fk_query, schema)
        fk_map: Dict[tuple[str, str, str], Dict[str, str]] = {}
        for r in fk_rows:
            fk_map[
                (
                    r["table_schema"],
                    r["table_name"],
                    r["column_name"],
                )
            ] = {
                "ref_schema": r["foreign_table_schema"],
                "ref_table": r["foreign_table_name"],
                "ref_column": r["foreign_column_name"],
            }

        # Enum values (user-defined types)
        enum_query = """
            SELECT t.typname AS udt_name, e.enumlabel AS enum_value
            FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
        """
        enum_rows = await self.conn.fetch(enum_query)
        enum_values: Dict[str, List[str]] = {}
        for r in enum_rows:
            enum_values.setdefault(r["udt_name"], []).append(r["enum_value"])

        for table in tables:
            info = await self._get_table_info(schema, table)

            # Columns with details from information_schema
            columns_query = """
                SELECT
                    column_name,
                    data_type,
                    udt_name,
                    is_nullable,
                    column_default,
                    ordinal_position
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position
            """
            col_rows = await self.conn.fetch(columns_query, schema, table)
            cols: List[Dict[str, Any]] = []
            for c in col_rows:
                key = (schema, table, c["column_name"])
                fk = fk_map.get(key)
                udt = c["udt_name"]
                cols.append(
                    {
                        "column_name": c["column_name"],
                        "data_type": c["data_type"],
                        "udt_name": udt,
                        "is_nullable": c["is_nullable"] == "YES",
                        "default_value": c["column_default"],
                        "ordinal_position": c["ordinal_position"],
                        "is_primary_key": c["column_name"] in info["primary_keys"],
                        "is_foreign_key": fk is not None,
                        "ref_schema": fk.get("ref_schema") if fk else None,
                        "ref_table": fk.get("ref_table") if fk else None,
                        "ref_column": fk.get("ref_column") if fk else None,
                        "enum_values": enum_values.get(udt),
                        # Simple filterable heuristic: prefer scalar/text/date
                        "is_filterable": (c["data_type"] not in ("json", "jsonb")),
                    }
                )

            # Choose a recency column heuristically (prefer timestamp-like names and types)
            recency_column = self._select_recency_column(cols)
            try:
                self.logger.debug(
                    f"[PGCatalog] {schema}.{table}: columns={len(cols)}, recency={recency_column}"
                )
            except Exception:
                pass

            results.append(
                {
                    "schema_name": schema,
                    "table_name": table,
                    "recency_column": recency_column,
                    "primary_keys": info["primary_keys"],
                    "foreign_keys": [
                        {
                            "column": k[2],
                            **v,
                        }
                        for k, v in fk_map.items()
                        if k[0] == schema and k[1] == table
                    ],
                    "columns": cols,
                }
            )

        return results

    def _select_recency_column(self, columns: List[Dict[str, Any]]) -> Optional[str]:
        """Select a reasonable recency column from column metadata.

        Heuristic: prefer timestamp/timestamptz types; prefer names containing
        'updated', 'modified', 'last_edited', then fall back to any timestamp/date.
        """
        if not columns:
            return None

        def is_ts(col: Dict[str, Any]) -> bool:
            dt = (col.get("data_type") or "").lower()
            return dt in {
                "timestamp",
                "timestamp with time zone",
                "timestamptz",
                "date",
            }

        candidates = [c for c in columns if is_ts(c)]
        if not candidates:
            return None

        name_scores: List[tuple[int, str]] = []
        for c in candidates:
            name = c.get("column_name", "").lower()
            score = 0
            if any(
                k in name
                for k in ("updated", "modified", "last_edited", "last_modified")
            ):
                score += 2
            if name.endswith("_at"):
                score += 1
            name_scores.append((score, c["column_name"]))

        # Pick the highest score; if tie, keep first in ordinal_position order
        name_scores.sort(key=lambda x: (-x[0],))
        return name_scores[0][1] if name_scores else candidates[0]["column_name"]

    async def validate(self) -> bool:
        """Verify PostgreSQL credentials, schema access, and (optionally) tables."""
        try:
            # 1) Connect (handles common connection errors and timeouts)
            await self._connect()

            # 2) Simple ping
            try:
                _ = await self.conn.fetchval("SELECT 1;")
            except Exception as e:
                self.logger.error(f"PostgreSQL ping failed: {e}")
                return False

            # 3) Schema existence
            schema = (self.config or {}).get("schema", "public") or "public"
            exists = await self.conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = $1);",
                schema,
            )
            if not exists:
                self.logger.error(
                    f"Schema '{schema}' does not exist or is inaccessible."
                )
                return False

            # 4) If specific tables were requested, verify they exist
            tables_cfg = (self.config or {}).get("tables", "*") or "*"
            if isinstance(tables_cfg, str) and tables_cfg != "*":
                requested = [t.strip() for t in tables_cfg.split(",") if t.strip()]
                # If no valid tables after filtering, skip validation (will default to all)
                if requested:
                    available = await self._get_tables(schema)
                    missing = [t for t in requested if t not in available]
                    if missing:
                        self.logger.error(
                            f"Tables not found in schema '{schema}': {', '.join(missing)}"
                        )
                        return False

            return True

        except (
            asyncpg.InvalidPasswordError,
            asyncpg.InvalidCatalogNameError,
            ValueError,
        ) as e:
            self.logger.error(f"PostgreSQL validation failed (credentials/config): {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during PostgreSQL validation: {e}")
            return False
        finally:
            if self.conn:
                await self.conn.close()
                self.conn = None
