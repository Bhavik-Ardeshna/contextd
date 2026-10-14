"""ClickHouse source implementation using clickhouse_connect.

Connects via clickhouse_connect.get_client(host, user, password, secure=True).
Uses the same PolymorphicEntity and DatabaseTable machinery as the PostgreSQL connector.
"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, AsyncGenerator, Dict, List, Optional, Type, Union

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
from contextd.platform.cursors import ClickHouseCursor
from contextd.platform.decorators import source
from contextd.platform.entities._base import BaseEntity, PolymorphicEntity
from contextd.platform.entities._metadata import EntityIndexConfig, SearchConfig
from contextd.platform.sources._base import BaseSource
from contextd.schemas.source_connection import AuthenticationMethod

logger = logging.getLogger(__name__)

# Mapping of ClickHouse types to Python types
CH_TYPE_MAP = {
    "uint8": int,
    "uint16": int,
    "uint32": int,
    "uint64": int,
    "int8": int,
    "int16": int,
    "int32": int,
    "int64": int,
    "float32": float,
    "float64": float,
    "decimal": float,
    "string": str,
    "fixedstring": str,
    "uuid": str,
    "date": datetime,
    "time": str,
    "time64": str,
    "datetime": datetime,
    "datetime64": datetime,
    "enum8": str,
    "enum16": str,
    "bool": bool,
    "boolean": bool,
    "json": Any,
    "array": list,
    "tuple": tuple,
    "map": dict,
    "nullable": Any,
}

# Regex to extract enum values from ClickHouse Enum type strings
# e.g. "Enum8('active' = 1, 'inactive' = 2)" -> ['active', 'inactive']
_ENUM_VALUES_RE = re.compile(r"'([^']*)'")


@source(
    name="ClickHouse",
    short_name="clickhouse",
    auth_methods=[AuthenticationMethod.DIRECT, AuthenticationMethod.AUTH_PROVIDER],
    oauth_type=None,
    auth_config_class="ClickHouseAuthConfig",
    config_class="ClickHouseConfig",
    labels=["Database"],
    supports_continuous=True,
    cursor_class=ClickHouseCursor,
    rate_limit_level=RateLimitLevel.ORG,
)
class ClickHouseSource(BaseSource):
    """ClickHouse source connector using clickhouse_connect.

    Connects with: host, user, password, secure=True (e.g. ClickHouse Cloud).
    Optional: database (default), tables (* or comma-separated).
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

    def __init__(  # noqa: D107
        self,
        schema_definitions: Optional[Dict[str, DatabaseTable]] = None,
    ):
        super().__init__()
        self._client: Any = None
        self.entity_classes: Dict[str, Type[PolymorphicEntity]] = {}
        self.column_field_mappings: Dict[str, Dict[str, str]] = {}
        self.schema_definitions = schema_definitions or {}
        self.schema_converter = DatabaseSchemaConverter()
        # Cache for sorting keys per table (used for ORDER BY optimization)
        self._sorting_keys: Dict[str, List[str]] = {}
        self._column_type_cache: Dict[str, str] = {}

    # ----------------------------------------------------------
    # Connection management
    # ----------------------------------------------------------

    def _get_client(self):  # noqa: ANN201
        """Return cached clickhouse_connect client, creating one if needed."""
        if self._client is not None:
            return self._client

        import clickhouse_connect

        port = self.config.get("port") or 8443

        self._client = clickhouse_connect.get_client(
            host=self.config["host"],
            user=self.config.get("user", "default"),
            password=self.config["password"],
            secure=self.config.get("secure", True),
            port=port,
            database=self.config.get("database", "default"),
        )
        return self._client

    async def _ensure_client(self) -> None:
        """Ensure client is alive; recreate on failure."""
        if self._client is not None:
            try:

                def ping():
                    self._client.query("SELECT 1")

                await asyncio.to_thread(ping)
                return
            except Exception as e:
                self.logger.warning(f"ClickHouse connection lost, reconnecting: {e}")
                self._client = None

        # Force creation of a new client
        self._get_client()

    def _close_client(self) -> None:
        """Safely close and null out the cached client."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    async def _query_json(
        self,
        query: str,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Run query and return rows as list of dicts (run in thread)."""

        def run() -> List[Dict[str, Any]]:
            client = self._get_client()
            if database:
                client.database = database
            q = query.rstrip().removesuffix(";")
            result = client.query(q)
            if not result.column_names or not result.result_set:
                return []
            return [
                dict(zip(result.column_names, row, strict=True))
                for row in result.result_set
            ]

        return await asyncio.to_thread(run)

    async def _connect(self) -> None:
        """Validate connection with SELECT 1."""
        try:
            result = await self._query_json("SELECT 1 AS n")
            if not result or result[0].get("n") != 1:
                raise ValueError("ClickHouse ping failed")
            self.logger.info(
                f"Connected to ClickHouse at {self.config['host']}, "
                f"database: {self.config.get('database', 'default')}"
            )
        except Exception as e:
            if "auth" in str(e).lower() or "password" in str(e).lower():
                raise ValueError("Invalid ClickHouse credentials") from e
            raise ValueError(f"ClickHouse connection failed: {str(e)}") from e

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _get_table_key(self, database: str, table: str) -> str:
        return f"{database}.{table}"

    def _normalize_model_field_name(self, column_name: str) -> str:
        if column_name == "id":
            return "id_"
        if column_name in self._RESERVED_ENTITY_FIELDS:
            return f"{column_name}_field"
        return column_name

    # ----------------------------------------------------------
    # Table discovery (tables, views, materialized views)
    # ----------------------------------------------------------

    async def _get_tables(self, database: str) -> List[str]:
        """List readable ClickHouse objects: tables, views, and materialized views."""
        query = f"SELECT name FROM system.tables " f"WHERE database = '{database}'"
        rows = await self._query_json(query, database="system")
        return [r["name"] for r in rows if r.get("name")]

    async def _get_materialized_views(self, database: str) -> List[str]:
        """List materialized view names."""
        query = (
            f"SELECT name FROM system.tables "
            f"WHERE database = '{database}' AND engine = 'MaterializedView'"
        )
        rows = await self._query_json(query, database="system")
        return [r["name"] for r in rows if r.get("name")]

    async def _get_tables_and_views(self, database: str) -> List[str]:
        """List all tables, views, and materialized views."""
        query = f"SELECT name FROM system.tables " f"WHERE database = '{database}'"
        rows = await self._query_json(query, database="system")
        return [r["name"] for r in rows if r.get("name")]

    async def _get_table_list(self, database: str) -> List[str]:
        """Get the list of tables to process based on configuration.

        When wildcard (*) is used, tables, views, and materialized views are returned.
        When specific names are provided, tables, views, and materialized views are checked.
        """
        tables_cfg = self.config.get("tables", "*") or "*"

        if tables_cfg == "*":
            base = await self._get_tables(database)
            matviews = await self._get_materialized_views(database)
            combined = base + [m for m in matviews if m not in base]
            if matviews:
                self.logger.info(f"Including materialized views: {', '.join(matviews)}")
            return combined

        tables = [t.strip() for t in tables_cfg.split(",") if t.strip()]
        if not tables:
            base = await self._get_tables(database)
            matviews = await self._get_materialized_views(database)
            return base + [m for m in matviews if m not in base]

        # Validate against all available objects (tables + views + matviews)
        available = await self._get_tables_and_views(database)
        invalid = set(tables) - set(available)
        if invalid:
            raise ValueError(
                f"Tables/views not found in database '{database}': {', '.join(invalid)}"
            )

        return tables

    # ----------------------------------------------------------
    # Schema introspection
    # ----------------------------------------------------------

    async def _get_sorting_key(self, database: str, table: str) -> List[str]:
        """Get the sorting key columns for a ClickHouse table.

        The sorting key defines the physical ordering and serves as
        ClickHouse's equivalent of a primary key.
        """
        query = (
            f"SELECT sorting_key FROM system.tables "
            f"WHERE database = '{database}' AND name = '{table}'"
        )
        rows = await self._query_json(query, database="system")
        if not rows or not rows[0].get("sorting_key"):
            return []

        sorting_key_str = rows[0]["sorting_key"]
        # Parse comma-separated column names, skip expressions (contain parentheses)
        parts = [p.strip() for p in sorting_key_str.split(",")]
        columns = [p for p in parts if p and "(" not in p]
        return columns

    async def _get_table_info(self, database: str, table: str) -> Dict[str, Any]:
        """Get column names, types, and primary keys from system metadata."""
        query = (
            f"SELECT name, type, default_kind "
            f"FROM system.columns "
            f"WHERE database = '{database}' AND table = '{table}' "
            f"ORDER BY position"
        )
        rows = await self._query_json(query, database="system")
        columns = {
            r["name"]: {"ch_type": r["type"], "default": r.get("default_kind")}
            for r in rows
        }
        names = list(columns.keys())

        # 1. Try ClickHouse sorting key (physical primary key)
        sorting_key_cols = await self._get_sorting_key(database, table)
        # Verify all sorting key columns actually exist in the table
        valid_sk_cols = [c for c in sorting_key_cols if c in columns]
        if valid_sk_cols:
            table_key = self._get_table_key(database, table)
            self._sorting_keys[table_key] = valid_sk_cols
            return {"columns": columns, "primary_keys": valid_sk_cols}

        # 2. Heuristic fallbacks (like PostgreSQL)
        primary_keys: List[str] = []
        table_key = self._get_table_key(database, table)

        if "id" in names:
            primary_keys = ["id"]
            self.logger.debug(
                f"No sorting key for {table_key}. Using 'id' column for entity identification."
            )
        elif "uuid" in names:
            primary_keys = ["uuid"]
            self.logger.debug(
                f"No sorting key for {table_key}. Using 'uuid' column for entity identification."
            )
        elif "guid" in names:
            primary_keys = ["guid"]
            self.logger.debug(
                f"No sorting key for {table_key}. Using 'guid' column for entity identification."
            )
        else:
            id_columns = [col for col in names if col.endswith("_id")]
            if id_columns:
                primary_keys = [id_columns[0]]
                self.logger.debug(
                    f"No sorting key for {table_key}. "
                    f"Using '{id_columns[0]}' column for entity identification."
                )
            elif names:
                primary_keys = [names[0]]
                self.logger.warning(
                    f"No sorting key or id columns for {table_key}. "
                    f"Using first column '{names[0]}' for entity identification. "
                    f"This may not guarantee uniqueness."
                )

        return {"columns": columns, "primary_keys": primary_keys}

    async def _build_introspected_schemas(
        self, database: str, tables: List[str]
    ) -> Dict[str, DatabaseTable]:
        """Introspect and build DatabaseTable definitions."""
        result: Dict[str, DatabaseTable] = {}
        for table in tables:
            table_info = await self._get_table_info(database, table)
            table_key = self._get_table_key(database, table)
            columns: Dict[str, DatabaseColumn] = {}
            column_metadata: Dict[str, ColumnMetadata] = {}
            primary_keys = table_info["primary_keys"]
            text_like = ("string", "fixedstring", "uuid", "enum8", "enum16")

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
                ch_type = (col_meta.get("ch_type") or "String").lower()
                if ch_type.startswith("nullable("):
                    ch_type = ch_type[9:-1].strip()
                base_type = ch_type.split("(")[0]
                is_pk = col_name in primary_keys

                col_def = DatabaseColumn(
                    name=col_name,
                    column_type=base_type,
                    nullable=True,
                    default=None,
                    primary_key=is_pk,
                    foreign_key=None,
                )
                columns[col_name] = col_def

                embeddable = base_type in text_like or "string" in ch_type
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
                default_graph_node_type=f"DatabaseTableNode_{database}_{table}",
                create_entity_node=True,
                enable_llm_enrichment=False,
                index=EntityIndexConfig(
                    enabled=True,
                    fulltext_enabled=True,
                    priority_fields=[c for c in ("name", "title") if c in columns],
                ),
                columns=column_metadata,
            )

            table_def = DatabaseTable(
                table_name=table,
                schema_name=database,
                description=f"ClickHouse object {database}.{table} (introspected)",
                columns=columns,
                primary_keys=primary_keys,
                foreign_keys=[],
                table_metadata=table_metadata,
            )
            result[table_key] = table_def
        return result

    # ----------------------------------------------------------
    # Implicit foreign key inference
    # ----------------------------------------------------------

    def _infer_implicit_foreign_keys(self, all_tables: Dict[str, DatabaseTable]) -> int:
        """Infer FK relationships from column naming conventions.

        For databases without explicit FK constraints (like ClickHouse),
        detects implicit relationships by matching columns ending in ``_id``
        to existing tables (e.g. ``person_id`` -> ``persons.id``).

        Returns:
            Number of implicit FKs added.
        """
        count = 0
        alias_index: Dict[tuple[str | None, str], list[str]] = {}

        def aliases_for_table(name: str) -> set[str]:
            normalized = name.lower()
            aliases = {normalized}
            for prefix in ("public_", "vw_", "dim_", "fct_", "stg_", "brdg_"):
                if normalized.startswith(prefix):
                    aliases.add(normalized[len(prefix) :])
            expanded = set(aliases)
            for alias in aliases:
                if alias.endswith("ies"):
                    expanded.add(f"{alias[:-3]}y")
                elif alias.endswith(("ches", "shes", "sses", "xes", "zes")):
                    expanded.add(alias[:-2])
                elif alias.endswith("s") and not alias.endswith("ss"):
                    expanded.add(alias[:-1])
            return expanded

        def aliases_for_fk_base(name: str) -> set[str]:
            base = name.lower()
            bases = {base}
            if "_" in base:
                # home_studio_id, primary_member_id, etc. should still
                # resolve to studios/members when the qualifier is not a table.
                bases.add(base.rsplit("_", 1)[-1])
            aliases: set[str] = set()
            for item in bases:
                aliases.update({item, f"{item}s", f"{item}es"})
                if item.endswith("y"):
                    aliases.add(f"{item[:-1]}ies")
            return aliases

        for table_key, table_def in all_tables.items():
            schema = table_def.schema_name
            for alias in aliases_for_table(table_def.table_name):
                alias_index.setdefault((schema, alias), []).append(table_key)

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

                for alias in aliases_for_fk_base(base):
                    candidates = alias_index.get((schema, alias), [])
                    ref_key = next((key for key in candidates if key != table_key), None)
                    if not ref_key:
                        continue
                    ref_table = all_tables[ref_key]
                    pk_col = ref_table.primary_keys[0] if ref_table.primary_keys else "id"
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

    # ----------------------------------------------------------
    # LLM node type inference
    # ----------------------------------------------------------

    async def _infer_node_types_with_llm(  # noqa: C901
        self,
        database: str,
        introspected: Dict[str, DatabaseTable],
    ) -> None:
        """Use LLM to infer meaningful graph node types."""
        self.logger.info(
            "Skipping LLM schema inference for structured ClickHouse source"
        )
        return
        try:
            from contextd.platform.agent_orchestration.business_logic_extraction import (
                extract_business_logic_with_llm,
            )
        except ImportError:
            self.logger.debug("business_logic_extraction not available")
            return

        samples: Dict[str, List[Dict[str, Any]]] = {}
        foreign_keys_by_table: Dict[str, List[Dict[str, str]]] = {}
        column_types_by_table: Dict[str, Dict[str, str]] = {}

        for table_key, table_def in introspected.items():
            tbl = table_def.table_name
            sch = table_def.schema_name or database
            try:
                rows = await self._query_json(f"SELECT * FROM `{sch}`.`{tbl}` LIMIT 3")
                samples[table_key] = rows
            except Exception:
                samples[table_key] = []

            if table_def.foreign_keys:
                foreign_keys_by_table[table_key] = [
                    {
                        "column": fk.column,
                        "ref_table": fk.ref_table,
                        "ref_column": fk.ref_column,
                    }
                    for fk in table_def.foreign_keys
                ]

            if table_def.columns:
                column_types_by_table[table_key] = {
                    col_name: col_def.column_type
                    for col_name, col_def in table_def.columns.items()
                }

        if not any(samples.values()):
            return

        try:
            result = await extract_business_logic_with_llm(
                source_type="clickhouse",
                samples_by_entity_type=samples,
                foreign_keys_by_table=foreign_keys_by_table,
                column_types_by_table=column_types_by_table,
                logger_instance=logger,
            )
            if not result:
                return

            self._apply_llm_results(introspected, result)

        except Exception as e:
            self.logger.warning(f"LLM node type inference failed (using defaults): {e}")

    def _apply_llm_results(
        self,
        introspected: Dict[str, DatabaseTable],
        result: Any,
    ) -> None:
        """Apply LLM inference results to introspected schemas."""
        self._apply_llm_node_types(introspected, result)
        self._apply_llm_column_aliases(introspected, result)
        self._apply_llm_fk_edge_types(introspected, result)
        self._apply_llm_name_columns(introspected, result)
        self._apply_llm_search_config(introspected, result)

    def _apply_llm_node_types(
        self,
        introspected: Dict[str, DatabaseTable],
        result: Any,
    ) -> None:
        """Apply LLM-inferred node types."""
        for table_key, table_def in introspected.items():
            if not table_def.table_metadata:
                continue
            tbl = table_def.table_name
            inferred = result.table_node_types.get(tbl) or result.table_node_types.get(
                table_key
            )
            if inferred:
                table_def.table_metadata.default_graph_node_type = inferred
                self.logger.info(
                    f"LLM inferred node type " f"for {table_key}: {inferred}"
                )

    def _apply_llm_column_aliases(
        self,
        introspected: Dict[str, DatabaseTable],
        result: Any,
    ) -> None:
        """Apply LLM-inferred column aliases."""
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

    def _apply_llm_fk_edge_types(
        self,
        introspected: Dict[str, DatabaseTable],
        result: Any,
    ) -> None:
        """Apply LLM-inferred FK edge types."""
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
                table_def.table_metadata.llm_edge_labels = fk_edges

    def _apply_llm_name_columns(
        self,
        introspected: Dict[str, DatabaseTable],
        result: Any,
    ) -> None:
        """Apply LLM-inferred name columns to column metadata."""
        if not hasattr(result, "name_columns") or not result.name_columns:
            return
        for table_key, table_def in introspected.items():
            if not table_def.table_metadata:
                continue
            tbl = table_def.table_name
            name_col = result.name_columns.get(tbl) or result.name_columns.get(
                table_key
            )
            if not name_col:
                continue
            col_meta = table_def.table_metadata.columns.get(name_col)
            if col_meta:
                # Clear any existing is_name flags first
                for _, cm in table_def.table_metadata.columns.items():
                    cm.is_name = False
                col_meta.is_name = True
                self.logger.info(
                    f"LLM inferred name column " f"for {table_key}: {name_col}"
                )

    def _apply_llm_search_config(
        self,
        introspected: Dict[str, DatabaseTable],
        result: Any,
    ) -> None:
        """Auto-configure search from entity_property_shapes."""
        if not result.logic.entity_property_shapes:
            return
        for _table_key, table_def in introspected.items():
            if not table_def.table_metadata:
                continue
            tbl = table_def.table_name
            node_type = table_def.table_metadata.default_graph_node_type
            useful_keys = (
                result.logic.entity_property_shapes.get(node_type)
                or result.logic.entity_property_shapes.get(tbl)
                or []
            )
            for col_name in useful_keys:
                col_meta = table_def.table_metadata.columns.get(col_name)
                if col_meta and not col_meta.search.embeddable:
                    col_meta.search = SearchConfig(embeddable=True)

    # ----------------------------------------------------------
    # Data sampling for schema validation
    # ----------------------------------------------------------

    async def _sample_table_data(
        self,
        database: str,
        table: str,
        sample_size: int = 100,
    ) -> Dict[str, Any]:
        """Sample rows from a table to detect data patterns.

        Returns column-level statistics: null ratio, distinct count,
        and whether text columns contain JSON or enum-like values.
        """
        stats: Dict[str, Any] = {}
        try:
            select_list = await self._select_list_for_table(database, table)
            rows = await self._query_json(
                f"SELECT {select_list} FROM `{database}`.`{table}` LIMIT {sample_size}"
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
            self.logger.debug(f"Sampling {database}.{table} failed: {e}")

        return stats

    # ----------------------------------------------------------
    # Schema change detection
    # ----------------------------------------------------------

    async def _detect_schema_changes(  # noqa: C901
        self,
        database: str,
        tables: List[str],
        new_snapshot: List[Dict[str, Any]],
    ) -> None:
        """Compare new introspected schema against stored catalog.

        Logs added/removed/changed columns so operators can react
        to upstream schema evolution.
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
                    "No previous catalog found - " "first sync, skipping schema diff"
                )
                return

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

            self._log_schema_diff(old_map, new_map)

        except Exception as e:
            self.logger.warning(f"Schema change detection failed: {e}")

    def _log_schema_diff(
        self,
        old_map: Dict[str, Dict[str, str]],
        new_map: Dict[str, Dict[str, str]],
    ) -> None:
        """Log differences between old and new schema maps."""
        added_tables = set(new_map) - set(old_map)
        removed_tables = set(old_map) - set(new_map)
        common = set(old_map) & set(new_map)

        if added_tables:
            self.logger.info(
                "Schema change: new tables: " f"{', '.join(sorted(added_tables))}"
            )
        if removed_tables:
            self.logger.warning(
                "Schema change: removed tables: " f"{', '.join(sorted(removed_tables))}"
            )

        for tbl in sorted(common):
            old_cols = old_map[tbl]
            new_cols = new_map[tbl]
            added = set(new_cols) - set(old_cols)
            removed = set(old_cols) - set(new_cols)
            type_changed = [
                c for c in set(old_cols) & set(new_cols) if old_cols[c] != new_cols[c]
            ]
            if added:
                self.logger.info(
                    f"Schema change [{tbl}]: "
                    f"added columns: {', '.join(sorted(added))}"
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
                        f"from '{old_cols[c]}' to "
                        f"'{new_cols[c]}'"
                    )

    # ----------------------------------------------------------
    # Field catalog persistence
    # ----------------------------------------------------------

    async def _build_field_catalog_snapshot(
        self,
        database: str,
        tables: List[str],
        introspected: Dict[str, DatabaseTable],
    ) -> List[Dict[str, Any]]:
        """Build a full catalog snapshot for the given tables."""
        results: List[Dict[str, Any]] = []

        for table in tables:
            table_key = self._get_table_key(database, table)
            table_def = introspected.get(table_key)
            if not table_def:
                continue

            # Build column details from system.columns
            query = (
                f"SELECT name, type, default_kind, default_expression "
                f"FROM system.columns "
                f"WHERE database = '{database}' AND table = '{table}' "
                f"ORDER BY position"
            )
            col_rows = await self._query_json(query, database="system")

            # Build FK lookup from inferred FKs
            fk_map: Dict[str, ForeignKeyConfig] = {
                fk.column: fk for fk in table_def.foreign_keys
            }

            cols: List[Dict[str, Any]] = []
            for i, c in enumerate(col_rows):
                col_name = c["name"]
                ch_type = c.get("type", "String")
                base_type = ch_type.lower().split("(")[0]
                if base_type.startswith("nullable"):
                    # Extract inner type for nullable
                    inner = ch_type.lower()
                    if inner.startswith("nullable("):
                        inner = inner[9:-1].strip()
                    base_type = inner.split("(")[0]

                is_nullable = ch_type.lower().startswith("nullable(")
                fk = fk_map.get(col_name)

                # Parse enum values from type string
                enum_values = None
                if base_type in ("enum8", "enum16"):
                    enum_values = _ENUM_VALUES_RE.findall(ch_type)

                cols.append(
                    {
                        "column_name": col_name,
                        "data_type": base_type,
                        "udt_name": ch_type,
                        "is_nullable": is_nullable,
                        "default_value": c.get("default_expression"),
                        "ordinal_position": i + 1,
                        "is_primary_key": col_name in table_def.primary_keys,
                        "is_foreign_key": fk is not None,
                        "ref_schema": fk.ref_schema if fk else None,
                        "ref_table": fk.ref_table if fk else None,
                        "ref_column": fk.ref_column if fk else None,
                        "enum_values": enum_values,
                        "is_filterable": base_type not in ("json",),
                    }
                )

            recency_column = self._select_recency_column(cols)

            results.append(
                {
                    "schema_name": database,
                    "table_name": table,
                    "recency_column": recency_column,
                    "primary_keys": table_def.primary_keys,
                    "foreign_keys": [
                        {
                            "column": fk.column,
                            "ref_schema": fk.ref_schema,
                            "ref_table": fk.ref_table,
                            "ref_column": fk.ref_column,
                        }
                        for fk in table_def.foreign_keys
                    ],
                    "columns": cols,
                }
            )

        return results

    def _select_recency_column(self, columns: List[Dict[str, Any]]) -> Optional[str]:
        """Select a reasonable recency column from column metadata.

        Prefers timestamp/date types; prefers names containing 'updated', 'modified'.
        """
        if not columns:
            return None

        def is_ts(col: Dict[str, Any]) -> bool:
            dt = (col.get("data_type") or "").lower()
            return dt in {"datetime", "datetime64", "date"}

        candidates = [c for c in columns if is_ts(c)]
        if not candidates:
            return None

        name_scores: List[tuple] = []
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

        name_scores.sort(key=lambda x: (-x[0],))
        return name_scores[0][1] if name_scores else candidates[0]["column_name"]

    # ----------------------------------------------------------
    # Entity class creation & registration
    # ----------------------------------------------------------

    async def _create_entity_class(
        self, database: str, table: str
    ) -> Type[PolymorphicEntity]:
        table_key = self._get_table_key(database, table)
        if table_key in self.entity_classes:
            return self.entity_classes[table_key]

        registered_class = DatabaseEntityClassRegistry.get_entity_class(table_key)
        if registered_class:
            self.entity_classes[table_key] = registered_class
            return registered_class

        registry_schema = DatabaseSchemaRegistry.get_schema("clickhouse", table_key)
        if registry_schema:
            table_def = registry_schema
        elif table_key in self.schema_definitions:
            table_def = self.schema_definitions[table_key]
        else:
            table_def = None

        if table_def:
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
                    "python_type": CH_TYPE_MAP.get(col_def.column_type.lower(), Any),
                    "nullable": col_def.nullable,
                    "default": col_def.default,
                }
                column_mapping[original_name] = candidate
            self.column_field_mappings[table_key] = column_mapping

            all_registry_tables = DatabaseSchemaRegistry.get_all_schemas("clickhouse")
            all_tables = {**all_registry_tables, **self.schema_definitions}
            entity_class = self.schema_converter.convert_table_to_entity_class(
                table_def, column_mapping, all_tables
            )
            self.entity_classes[table_key] = entity_class
            await self._register_entity_class(
                table_key,
                entity_class,
                table_def.schema_name or database,
                table_def.table_name,
            )
            return entity_class

        table_info = await self._get_table_info(database, table)
        normalized_columns = {}
        column_mapping = {}
        for original_name, col_meta in table_info["columns"].items():
            base_name = self._normalize_model_field_name(original_name)
            candidate = base_name
            suffix = 1
            while candidate in normalized_columns:
                suffix += 1
                candidate = f"{base_name}_{suffix}"
            ch_type = (col_meta.get("ch_type") or "String").lower().split("(")[0]
            normalized_columns[candidate] = {
                "python_type": CH_TYPE_MAP.get(ch_type, Any),
                "nullable": True,
                "default": None,
            }
            column_mapping[original_name] = candidate
        self.column_field_mappings[table_key] = column_mapping

        entity_class = PolymorphicEntity.create_table_entity_class(
            table_name=table,
            schema_name=database,
            columns=normalized_columns,
            primary_keys=table_info["primary_keys"],
        )
        self.entity_classes[table_key] = entity_class
        await self._register_entity_class(table_key, entity_class, database, table)
        return entity_class

    async def _register_entity_class(
        self,
        table_key: str,
        entity_class: Type[PolymorphicEntity],
        schema_name: str,
        table_name: str,
    ) -> None:
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
        entity_name = f"DatabaseTable_{schema_name}_{table_name}"
        try:
            async with get_db_context() as db:
                from contextd import crud

                try:
                    entity_def = await crud.entity_definition.get_by_entity_class_name(
                        db, entity_class_name=entity_name
                    )
                    entity_definition_id = entity_def.id
                except Exception:
                    from contextd.db.init_db_native import RESERVED_TABLE_ENTITY_ID

                    entity_definition_id = RESERVED_TABLE_ENTITY_ID
        except Exception:
            from contextd.db.init_db_native import RESERVED_TABLE_ENTITY_ID

            entity_definition_id = RESERVED_TABLE_ENTITY_ID
        DatabaseEntityClassRegistry.register_entity_class(
            table_key, entity_class, entity_definition_id
        )

    # ----------------------------------------------------------
    # Entity ID generation & field conversion
    # ----------------------------------------------------------

    def _generate_entity_id(
        self,
        database: str,
        table: str,
        data: Dict[str, Any],
        primary_keys: List[str],
    ) -> str:
        table_key = self._get_table_key(database, table)
        pk_values = [str(data[pk]) for pk in primary_keys if pk in data]
        if pk_values:
            return f"{table_key}:" + ":".join(pk_values)
        row_hash = hashlib.md5(str(sorted(data.items())).encode()).hexdigest()[:16]
        return f"{table_key}:row_{row_hash}"

    def _ensure_entity_id_length(
        self, entity_id: str, database: str, table: str
    ) -> str:
        if len(entity_id) <= 2000:
            return entity_id
        entity_hash = hashlib.sha256(entity_id.encode()).hexdigest()
        table_key = self._get_table_key(database, table)
        return f"{table_key}:hashed_{entity_hash}"

    def _parse_json_fields(self, data: Dict[str, Any]) -> None:
        for key, value in list(data.items()):
            if isinstance(value, str):
                try:
                    data[key] = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    pass

    async def _convert_field_values(
        self,
        data: Dict[str, Any],
        model_fields: Dict[str, Any],
        table_key: str,
    ) -> Dict[str, Any]:
        processed = {}
        column_mapping = self.column_field_mappings.get(table_key, {})
        for field_name, field_value in data.items():
            model_field_name = column_mapping.get(
                field_name, self._normalize_model_field_name(field_name)
            )
            if model_field_name not in model_fields:
                continue
            if field_value is None:
                processed[model_field_name] = None
                continue
            field_info = model_fields[model_field_name]
            field_type = field_info.annotation
            if hasattr(field_type, "__origin__") and field_type.__origin__ is Union:
                union_args = getattr(field_type, "__args__", ())
                non_none = [a for a in union_args if a is not type(None)]
                if non_none:
                    field_type = non_none[0]
            if field_type is str and field_value is not None:
                processed[model_field_name] = str(field_value)
            else:
                processed[model_field_name] = field_value
        return processed

    async def _process_record_to_entity(
        self,
        record: Dict[str, Any],
        database: str,
        table: str,
        entity_class: Type[PolymorphicEntity],
        primary_keys: List[str],
    ) -> BaseEntity:
        self._parse_json_fields(record)
        entity_id = self._generate_entity_id(database, table, record, primary_keys)
        entity_id = self._ensure_entity_id_length(entity_id, database, table)
        table_key = self._get_table_key(database, table)
        processed = await self._convert_field_values(
            record, entity_class.model_fields, table_key
        )
        name_field = self.column_field_mappings.get(table_key, {}).get("name")
        entity_name = processed.get(name_field) if name_field else table
        return entity_class(
            entity_id=entity_id,
            breadcrumbs=[],
            name=entity_name or table,
            created_at=None,
            updated_at=None,
            **processed,
        )

    def _quote_identifier(self, identifier: str) -> str:
        """Quote a ClickHouse identifier for generated read-only SQL."""
        return f"`{identifier.replace('`', '``')}`"

    def _literal(self, value: Any) -> str:
        return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"

    def _normalize_ch_type(self, ch_type: str | None) -> str:
        normalized = (ch_type or "String").lower().strip()
        while normalized.startswith("nullable(") and normalized.endswith(")"):
            normalized = normalized[9:-1].strip()
        return normalized

    def _ch_type_base(self, ch_type: str | None) -> str:
        return self._normalize_ch_type(ch_type).split("(", 1)[0].strip()

    def _select_expr(self, column_name: str, ch_type: str | None) -> str:
        """Build a driver-safe projection for ClickHouse reads."""
        quoted = self._quote_identifier(column_name)
        # clickhouse-connect versions before native Time64 support raise during
        # decode. Casting preserves the value and keeps source sync type-safe.
        if self._ch_type_base(ch_type) in {"time", "time64"}:
            return f"toString({quoted}) AS {quoted}"
        return quoted

    async def _select_list_for_table(self, database: str, table: str) -> str:
        table_info = await self._get_table_info(database, table)
        columns = table_info.get("columns") or {}
        if not columns:
            return "*"
        return ", ".join(
            self._select_expr(column_name, column_meta.get("ch_type"))
            for column_name, column_meta in columns.items()
        )

    def _short_error(self, exc: Exception) -> str:
        message = str(exc).replace("\n", " ").strip()
        marker = "DB::Exception:"
        if marker in message:
            message = message.split(marker, 1)[1].strip()
        if len(message) > 180:
            message = f"{message[:177]}..."
        return message or exc.__class__.__name__

    def _serialize_cursor_value(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (date, time)):
            return value.isoformat()
        return str(value)

    async def _table_has_column(self, database: str, table: str, column: str) -> bool:
        rows = await self._query_json(
            "SELECT count() AS count FROM system.columns "
            f"WHERE database = {self._literal(database)} "
            f"AND table = {self._literal(table)} "
            f"AND name = {self._literal(column)}",
            database="system",
        )
        return bool(rows and int(rows[0].get("count") or 0) > 0)

    async def _get_column_type(self, database: str, table: str, column: str) -> str:
        cache_key = f"{database}.{table}.{column}"
        if cache_key not in self._column_type_cache:
            rows = await self._query_json(
                "SELECT type FROM system.columns "
                f"WHERE database = {self._literal(database)} "
                f"AND table = {self._literal(table)} "
                f"AND name = {self._literal(column)} "
                "LIMIT 1",
                database="system",
            )
            self._column_type_cache[cache_key] = str(
                (rows[0] if rows else {}).get("type") or ""
            )
        return self._column_type_cache[cache_key]

    async def _format_cursor_predicate_value(
        self, database: str, table: str, column: str, value: Any
    ) -> str:
        if isinstance(value, (int, float, Decimal)):
            return str(value)
        raw = str(value).strip()
        column_type = (await self._get_column_type(database, table, column)).lower()
        if not raw:
            return self._literal(raw)
        if column_type.startswith("nullable("):
            column_type = column_type[9:-1].strip()
        if column_type.startswith("datetime"):
            return f"parseDateTimeBestEffort({self._literal(raw)})"
        if column_type.startswith("date"):
            return f"toDate({self._literal(raw.split('T', 1)[0])})"
        if column_type.startswith(("int", "uint", "float", "decimal")):
            return raw
        return self._literal(raw)

    def _update_table_cursor(self, table_key: str, value: Any) -> None:
        if not self.cursor or value is None:
            return
        cursor_data = self.cursor.data or {}
        table_cursors = dict(cursor_data.get("table_cursors") or {})
        table_cursors[table_key] = self._serialize_cursor_value(value)
        self.cursor.update(table_cursors=table_cursors)

    # ----------------------------------------------------------
    # Table streaming
    # ----------------------------------------------------------

    async def _stream_table(
        self,
        database: str,
        table: str,
        entity_class: Type[PolymorphicEntity],
    ) -> AsyncGenerator[BaseEntity, None]:
        table_key = self._get_table_key(database, table)
        primary_keys = entity_class.model_fields[
            "primary_key_columns"
        ].default_factory()
        batch_size = 2000
        offset = 0
        total_records = 0
        select_list = await self._select_list_for_table(database, table)

        where_clause = ""
        cursor_field = self.config.get("cursor_field")
        has_cursor_column = False
        if cursor_field:
            has_cursor_column = await self._table_has_column(
                database, table, cursor_field
            )
            if has_cursor_column:
                table_cursors = (self.cursor.data if self.cursor else {}).get(
                    "table_cursors", {}
                )
                cursor_value = table_cursors.get(table_key)
                if cursor_value not in (None, ""):
                    where_clause = (
                        f"WHERE {self._quote_identifier(cursor_field)} > "
                        f"{await self._format_cursor_predicate_value(database, table, cursor_field, cursor_value)}"
                    )
            else:
                self.logger.warning(
                    f"Cursor field '{cursor_field}' was not found on {table_key}; "
                    "falling back to full table streaming."
                )

        # Use cursor field for incremental ordering when present.
        sorting_cols = self._sorting_keys.get(table_key, [])
        if has_cursor_column and cursor_field:
            order_clause = f"ORDER BY {self._quote_identifier(cursor_field)} ASC"
        elif sorting_cols:
            order_clause = "ORDER BY " + ", ".join(
                self._quote_identifier(c) for c in sorting_cols
            )
        else:
            order_clause = "ORDER BY tuple()"

        def fetch_batch(off: int, lim: int) -> List[Dict[str, Any]]:
            client = self._get_client()
            client.database = database
            q = (
                f"SELECT {select_list} FROM `{database}`.`{table}` "
                f"{where_clause} {order_clause} LIMIT {lim} OFFSET {off}"
            )
            result = client.query(q)
            if not result.column_names:
                return []
            return [
                dict(zip(result.column_names, row, strict=True))
                for row in result.result_set
            ]

        while True:
            rows = await asyncio.to_thread(fetch_batch, offset, batch_size)
            if not rows:
                break
            for row in rows:
                entity = await self._process_record_to_entity(
                    row, database, table, entity_class, primary_keys
                )
                yield entity
                if has_cursor_column and cursor_field:
                    self._update_table_cursor(table_key, row.get(cursor_field))
                total_records += 1

                if total_records % 5000 == 0:
                    self.logger.info(
                        f"Table {table_key}: Streamed {total_records} records"
                    )

            offset += len(rows)
            if len(rows) < batch_size:
                break

        self.logger.info(
            f"Table {table_key}: Completed streaming, {total_records} records"
        )

    # ----------------------------------------------------------
    # Main entry point
    # ----------------------------------------------------------

    async def generate_entities(  # noqa: C901
        self,
    ) -> AsyncGenerator[BaseEntity, None]:
        """Generate entities for all tables.

        Includes schema change detection, LLM inference,
        data sampling, and per-table error isolation.
        """
        table_results: Dict[str, str] = {}
        try:
            await self._connect()
            database = self.config.get("database", "default") or "default"
            tables = await self._get_table_list(database)

            self.logger.info(
                f"Found {len(tables)} table(s) in "
                f"database '{database}': {', '.join(tables)}"
            )

            # Clear registries for fresh sync
            DatabaseSchemaRegistry.clear_schemas("clickhouse")
            DatabaseEntityClassRegistry.clear()
            self.entity_classes.clear()
            self.logger.debug(
                "Cleared DatabaseSchemaRegistry, "
                "DatabaseEntityClassRegistry, "
                "and entity_classes cache for fresh sync"
            )

            # Introspect, infer FKs, run LLM, register schemas
            introspected = await self._build_introspected_schemas(database, tables)
            await self._enrich_schemas(database, introspected)

            DatabaseSchemaRegistry.register_schemas("clickhouse", introspected)
            self.logger.info(
                f"Loaded automatic schema for "
                f"{len(introspected)} table(s) "
                f"(graph + LLM enabled)"
            )

            # Data sampling for schema validation
            await self._run_data_sampling(database, tables)

            # Field catalog persistence & schema change detection
            await self._persist_catalog(database, tables, introspected)

            # Per-table streaming with error isolation
            async for entity in self._stream_all_tables(
                database, tables, table_results
            ):
                yield entity

            # Summary of per-table results
            self._log_sync_summary(tables, table_results)

        finally:
            self.logger.info("Closing ClickHouse connection")
            self._close_client()

    async def _enrich_schemas(
        self,
        database: str,
        introspected: Dict[str, DatabaseTable],
    ) -> None:
        """Infer implicit FKs and run LLM node type inference."""
        explicit_fk_count = sum(len(t.foreign_keys) for t in introspected.values())
        self.logger.debug(
            f"Introspected {len(introspected)} table(s) "
            f"with {explicit_fk_count} explicit FK(s)"
        )

        implicit_fk_count = self._infer_implicit_foreign_keys(introspected)
        if implicit_fk_count:
            self.logger.info(
                f"Inferred {implicit_fk_count} implicit "
                f"FK relationship(s) from column naming"
            )

        await self._infer_node_types_with_llm(database, introspected)

    async def _run_data_sampling(self, database: str, tables: List[str]) -> None:
        """Sample data from tables to detect JSON/enum patterns."""
        for tbl in tables:
            try:
                sample_stats = await self._sample_table_data(database, tbl)
                tkey = self._get_table_key(database, tbl)
                for col, stats in sample_stats.items():
                    if stats.get("likely_json"):
                        self.logger.info(f"[{tkey}] column '{col}' likely JSON")
                    if stats.get("likely_enum"):
                        vals = stats.get("enum_values", [])
                        self.logger.info(
                            f"[{tkey}] column " f"'{col}' likely enum: {vals}"
                        )
            except Exception as e:
                self.logger.debug(f"Sampling {tbl} failed: {e}")

    async def _persist_catalog(
        self,
        database: str,
        tables: List[str],
        introspected: Dict[str, DatabaseTable],
    ) -> None:
        """Persist field catalog and detect schema changes."""
        try:
            snapshot = await self._build_field_catalog_snapshot(
                database, tables, introspected
            )

            await self._detect_schema_changes(database, tables, snapshot)

            if getattr(self, "_organization_id", None) and getattr(
                self, "_source_connection_id", None
            ):
                async with get_db_context() as db:
                    await overwrite_catalog(
                        db=db,
                        organization_id=self._organization_id,
                        source_connection_id=(self._source_connection_id),
                        snapshot=snapshot,
                        logger=self.logger,
                    )
                    await db.commit()
        except Exception as e:
            self.logger.warning(f"Field catalog update failed: {e}")

    async def _stream_all_tables(
        self,
        database: str,
        tables: List[str],
        table_results: Dict[str, str],
    ) -> AsyncGenerator[BaseEntity, None]:
        """Stream entities from all tables with error isolation."""
        for i, table in enumerate(tables, 1):
            table_key = self._get_table_key(database, table)
            self.logger.info(f"Processing table {i}/{len(tables)}: " f"{table_key}")

            try:
                await self._ensure_client()

                if table_key not in self.entity_classes:
                    self.entity_classes[table_key] = await self._create_entity_class(
                        database, table
                    )
                entity_class = self.entity_classes[table_key]
                async for entity in self._stream_table(database, table, entity_class):
                    yield entity
                table_results[table_key] = "success"
            except Exception as e:
                table_results[table_key] = f"error: {e}"
                self.logger.error(
                    f"Table {table_key} failed: {e}. "
                    f"Continuing with remaining tables."
                )
                self._close_client()

    def _log_sync_summary(
        self,
        tables: List[str],
        table_results: Dict[str, str],
    ) -> None:
        """Log summary of per-table sync results."""
        ok = sum(1 for v in table_results.values() if v == "success")
        failed = len(table_results) - ok
        if failed:
            self.logger.warning(f"Sync completed: {ok} tables OK, " f"{failed} failed")
            for t, r in table_results.items():
                if r != "success":
                    self.logger.warning(f"  {t}: {r}")
            if ok == 0:
                raise ValueError(
                    "All selected ClickHouse tables failed during sync; "
                    "marking the sync job as failed instead of completing with zero data."
                )
        else:
            self.logger.info(
                "Successfully completed sync " f"for all {len(tables)} table(s)"
            )

    # ----------------------------------------------------------
    # Factory & validation
    # ----------------------------------------------------------

    @classmethod
    async def create(
        cls,
        credentials: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> "ClickHouseSource":
        """Create a new ClickHouse source instance."""
        instance = cls()
        credentials_config = (
            credentials.model_dump()
            if hasattr(credentials, "model_dump")
            else dict(credentials)
        )
        config = config or {}
        secure_value = config.get("secure", credentials_config.get("secure", True))
        if isinstance(secure_value, str):
            secure_value = secure_value.strip().lower() in {
                "1",
                "true",
                "yes",
                "y",
                "on",
            }
        instance.config = {
            **credentials_config,
            **config,
            "database": config.get("database")
            or credentials_config.get("database")
            or "default",
            "tables": config.get("tables") or credentials_config.get("tables") or "*",
            "secure": secure_value,
        }
        return instance

    async def validate(self) -> bool:
        """Verify ClickHouse credentials and database access."""
        try:
            await self._connect()
            database = self.config.get("database", "default") or "default"

            def check_db() -> List[Dict[str, Any]]:
                client = self._get_client()
                result = client.query(
                    f"SELECT name FROM system.databases WHERE name = '{database}'"
                )
                if not result.column_names or not result.result_set:
                    return []
                return [
                    dict(zip(result.column_names, row, strict=True))
                    for row in result.result_set
                ]

            rows = await asyncio.to_thread(check_db)
            if not rows:
                msg = (
                    f"Database '{database}' does not exist or is inaccessible. "
                    "Check the database name and that the user has access."
                )
                self.logger.error(msg)
                raise ValueError(msg)
            tables_cfg = (self.config or {}).get("tables", "*") or "*"
            if isinstance(tables_cfg, str) and tables_cfg != "*":
                requested = [t.strip() for t in tables_cfg.split(",") if t.strip()]
                if requested:
                    available = await self._get_tables_and_views(database)
                    missing = [t for t in requested if t not in available]
                    if missing:
                        msg = (
                            f"Tables not found in database '{database}': "
                            f"{', '.join(missing)}"
                        )
                        self.logger.error(msg)
                        raise ValueError(msg)
                    unreadable: List[str] = []
                    database_identifier = self._quote_identifier(database)
                    for table in requested:
                        try:
                            await self._query_json(
                                "SELECT count() AS row_count FROM "
                                f"{database_identifier}.{self._quote_identifier(table)} "
                            )
                        except Exception as exc:
                            unreadable.append(f"{table} ({self._short_error(exc)})")
                    if unreadable:
                        msg = (
                            "ClickHouse objects exist but cannot be queried: "
                            f"{'; '.join(unreadable)}"
                        )
                        self.logger.error(msg)
                        raise ValueError(msg)
            return True
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"ClickHouse validation failed: {e}")
            raise ValueError(
                f"ClickHouse connection failed: {str(e)}. "
                "Check host (e.g. xxx.clickhouse.cloud), user, "
                "password, and Secure (use true for ClickHouse Cloud)."
            ) from e
