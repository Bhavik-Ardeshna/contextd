"""Source setup draft API.

This route backs the target five-step setup wizard. It intentionally stores
configuration, test output, discovery snapshots, scope, and schedule separately
from the finalized source connection so users can move through structured
database onboarding without committing credentials or kicking off sync too early.
"""

import asyncio
import time
from typing import Any, Dict, Iterable
from uuid import UUID

import asyncpg
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.router import TrailingSlashRouter
from contextd.core.context_forge_service import context_forge_service
from contextd.core.datetime_utils import utc_now_naive
from contextd.core.guard_rail_service import GuardRailService
from contextd.core.shared_models import ActionType
from contextd.core.source_connection_service import source_connection_service
from contextd.db.session import get_db
from contextd.models.source_connection import SourceConnection as SourceConnectionModel
from contextd.models.source_connection_setup_draft import SourceConnectionSetupDraft
from contextd.schemas.source_connection import (
    DirectAuthentication,
    ScheduleConfig,
    SourceConnectionCreate,
)

router = TrailingSlashRouter()

SECRET_KEYS = {
    "password",
    "passphrase",
    "private_key",
    "private_key_passphrase",
    "client_secret",
    "token",
    "access_token",
    "refresh_token",
}

FINALIZABLE_PROVIDERS = {"postgresql", "clickhouse"}
CADENCE_TO_CRON = {
    "every_5_min": "*/5 * * * *",
    "every_15_min": "*/15 * * * *",
    "hourly": "0 * * * *",
    "daily": "0 0 * * *",
}


def _normalize_provider(provider: str) -> str:
    value = provider.strip().lower().replace("-", "_")
    aliases = {
        "postgres": "postgresql",
        "pg": "postgresql",
        "snowflake_warehouse": "snowflake",
    }
    return aliases.get(value, value)


def _provider_config(provider: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    safe = _safe_config(payload)
    if provider == "postgresql":
        schema = safe.get("db_schema") or safe.get("schema") or "public"
        return {
            **safe,
            "schema": schema,
            "db_schema": schema,
            "tables": safe.get("tables") or "*",
        }
    if provider == "clickhouse":
        return {
            **safe,
            "database": safe.get("database") or "default",
            "tables": safe.get("tables") or "*",
        }
    return safe


def _is_continuous_schedule(schedule: schemas.SourceSetupScheduleRequest) -> bool:
    """Treat an explicit cursor field as incremental regardless of cadence."""
    cron = CADENCE_TO_CRON.get(schedule.cadence, schedule.cadence)
    return bool(schedule.cursor_field) or cron.startswith("*/") or cron == "* * * * *"


def _schedule_config(
    schedule: schemas.SourceSetupScheduleRequest | None,
) -> ScheduleConfig | None:
    if not schedule:
        return None
    cron = CADENCE_TO_CRON.get(schedule.cadence, schedule.cadence)
    return ScheduleConfig(
        cron=cron,
        continuous=_is_continuous_schedule(schedule),
        cursor_field=schedule.cursor_field or None,
    )


def _sync_metadata(
    schedule: schemas.SourceSetupScheduleRequest | None,
) -> Dict[str, Any]:
    if not schedule:
        return {}
    cron = CADENCE_TO_CRON.get(schedule.cadence, schedule.cadence)
    return {
        "cadence": schedule.cadence,
        "cron": cron,
        "continuous": _is_continuous_schedule(schedule),
        "cursor_field": schedule.cursor_field,
        "backfill_window": schedule.backfill_window,
        "dead_letter_behavior": schedule.dead_letter_behavior,
    }


async def _get_existing_source_connection_for_target(
    db: AsyncSession,
    *,
    target_collection_id: str,
    ctx: ApiContext,
) -> SourceConnectionModel | None:
    result = await db.execute(
        select(SourceConnectionModel)
        .where(SourceConnectionModel.organization_id == ctx.organization.id)
        .where(SourceConnectionModel.readable_collection_id == target_collection_id)
        .order_by(SourceConnectionModel.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _is_recoverable_finalize_connection(
    source_connection: SourceConnectionModel,
    *,
    provider: str,
    connection_name: str,
    config: Dict[str, Any],
) -> bool:
    if source_connection.short_name != provider or source_connection.name != connection_name:
        return False
    existing_config = source_connection.config_fields or {}
    comparable_keys = (
        "host",
        "port",
        "database",
        "schema",
        "db_schema",
        "user",
        "tables",
    )
    for key in comparable_keys:
        if key not in existing_config:
            continue
        expected_value = config.get(key)
        if expected_value in (None, ""):
            continue
        existing_value = existing_config.get(key)
        if str(existing_value or "") != str(expected_value or ""):
            return False
    return True


def _safe_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key.lower() not in SECRET_KEYS and value not in (None, "")
    }


def _auth_summary(
    provider: str, credentials: Dict[str, Any], config: Dict[str, Any]
) -> Dict[str, Any]:
    merged = {**config, **credentials}
    if provider == "snowflake":
        return {
            "account": merged.get("account"),
            "database": merged.get("database"),
            "schema": merged.get("schema"),
            "warehouse": merged.get("warehouse"),
            "role": merged.get("role"),
            "user": merged.get("user"),
            "secret_present": bool(merged.get("private_key") or merged.get("password")),
        }
    return {
        "host": merged.get("host"),
        "port": merged.get("port"),
        "database": merged.get("database"),
        "schema": merged.get("db_schema") or merged.get("schema"),
        "user": merged.get("user") or merged.get("username"),
        "secret_present": bool(merged.get("password") or merged.get("private_key")),
    }


async def _get_draft(
    db: AsyncSession, draft_id: UUID, ctx: ApiContext
) -> SourceConnectionSetupDraft:
    result = await db.execute(
        select(SourceConnectionSetupDraft).where(
            SourceConnectionSetupDraft.id == draft_id,
            SourceConnectionSetupDraft.organization_id == ctx.organization.id,
        )
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Source setup draft not found")
    return draft


def _fake_latency(provider: str, config: Dict[str, Any]) -> int:
    seed = f"{provider}:{config.get('host') or config.get('account') or ''}:{config.get('database') or ''}"
    return 24 + (sum(ord(char) for char in seed) % 64)


def _normalize_table_filter(value: Any) -> list[str] | None:
    if value in (None, "", "*"):
        return None
    if isinstance(value, str):
        items = [item.strip() for item in value.replace("\n", ",").split(",")]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        items = [str(value).strip()]
    names = [item for item in items if item and item != "*"]
    return names or None


def _table_filter_to_config_value(names: Iterable[str] | None) -> str:
    filtered = [
        name.split(".")[-1].strip() for name in names or [] if name and name != "*"
    ]
    return ",".join(dict.fromkeys(filtered)) if filtered else "*"


def _scope_selected_objects(scope: Dict[str, Any] | None) -> list[str] | None:
    if not scope:
        return None
    selected = scope.get("selected_objects")
    if selected is None:
        return None
    names = _normalize_table_filter(selected)
    if not names:
        raise HTTPException(
            status_code=400,
            detail="Select at least one source object before finalizing",
        )
    return names


def _apply_scope_to_config(
    provider: str, config: Dict[str, Any], scope: Dict[str, Any] | None
) -> Dict[str, Any]:
    selected = _scope_selected_objects(scope)
    if not selected:
        return config
    if provider in {"postgresql", "clickhouse"}:
        return {**config, "tables": _table_filter_to_config_value(selected)}
    return config


def _postgres_config(
    credentials: Dict[str, Any], config: Dict[str, Any]
) -> Dict[str, Any]:
    merged = {**config, **credentials}
    port_value = merged.get("port") or 5432
    try:
        port = int(port_value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="PostgreSQL port must be a number"
        ) from exc

    postgres_config = {
        "host": (merged.get("host") or "").strip(),
        "port": port,
        "database": (merged.get("database") or "").strip(),
        "user": (merged.get("user") or merged.get("username") or "").strip(),
        "password": merged.get("password") or "",
        "schema": (merged.get("db_schema") or merged.get("schema") or "public").strip()
        or "public",
        "tables": merged.get("tables") or "*",
        "sslmode": (merged.get("sslmode") or "").strip().lower(),
        "dbt_project": merged.get("dbt_project") or "",
    }
    missing = [
        label
        for key, label in (
            ("host", "host"),
            ("database", "database"),
            ("user", "user"),
            ("password", "password"),
        )
        if not postgres_config[key]
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required PostgreSQL fields: {', '.join(missing)}",
        )
    postgres_config["table_filter"] = _normalize_table_filter(postgres_config["tables"])
    return postgres_config


def _parse_bool(value: Any, default: bool = True) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise HTTPException(status_code=400, detail="Secure must be true or false")


def _clickhouse_config(
    credentials: Dict[str, Any], config: Dict[str, Any]
) -> Dict[str, Any]:
    merged = {**config, **credentials}
    port_value = merged.get("port") or 8443
    try:
        port = int(port_value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="ClickHouse port must be a number"
        ) from exc

    clickhouse_config = {
        "host": (merged.get("host") or "").strip(),
        "port": port,
        "database": (merged.get("database") or "default").strip() or "default",
        "user": (merged.get("user") or merged.get("username") or "default").strip()
        or "default",
        "password": merged.get("password") or "",
        "secure": _parse_bool(merged.get("secure"), default=True),
        "tables": merged.get("tables") or "*",
        "dbt_project": merged.get("dbt_project") or "",
    }
    if not clickhouse_config["host"]:
        raise HTTPException(
            status_code=400, detail="Missing required ClickHouse field: host"
        )
    clickhouse_config["table_filter"] = _normalize_table_filter(
        clickhouse_config["tables"]
    )
    return clickhouse_config


def _clickhouse_literal(value: Any) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _clickhouse_identifier(value: Any) -> str:
    return "`" + str(value).replace("`", "``") + "`"


def _short_clickhouse_error(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    marker = "DB::Exception:"
    if marker in message:
        message = message.split(marker, 1)[1].strip()
    if len(message) > 180:
        message = f"{message[:177]}..."
    return message or exc.__class__.__name__


def _clickhouse_rows(result: Any) -> list[dict[str, Any]]:
    if not result.column_names or not result.result_set:
        return []
    return [
        dict(zip(result.column_names, row, strict=True)) for row in result.result_set
    ]


async def _connect_clickhouse(config: Dict[str, Any]) -> Any:
    try:
        import clickhouse_connect
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="ClickHouse connector dependency is not installed in this backend image",
        ) from exc

    def create_client() -> Any:
        return clickhouse_connect.get_client(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["database"],
            secure=config["secure"],
        )

    try:
        return await asyncio.to_thread(create_client)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"ClickHouse connection failed: {exc}"
        ) from exc


def _postgres_ssl_mode(config: Dict[str, Any]) -> str | bool | None:
    sslmode = config.get("sslmode")
    if sslmode == "disable":
        return False
    if sslmode in {"allow", "prefer", "require", "verify-ca", "verify-full"}:
        return sslmode
    host = str(config.get("host") or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    return "require"


async def _connect_postgres(config: Dict[str, Any]) -> asyncpg.Connection:
    host = "127.0.0.1" if config["host"].lower() == "localhost" else config["host"]
    try:
        return await asyncpg.connect(
            host=host,
            port=config["port"],
            database=config["database"],
            user=config["user"],
            password=config["password"],
            ssl=_postgres_ssl_mode(config),
            timeout=15.0,
            command_timeout=30.0,
            server_settings={"jit": "off"},
        )
    except asyncpg.InvalidPasswordError as exc:
        raise HTTPException(
            status_code=400, detail="PostgreSQL authentication failed"
        ) from exc
    except asyncpg.InvalidCatalogNameError as exc:
        raise HTTPException(
            status_code=400, detail="PostgreSQL database was not found"
        ) from exc
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise HTTPException(
            status_code=400, detail="PostgreSQL connection timed out"
        ) from exc
    except (OSError, asyncpg.PostgresError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"PostgreSQL connection failed ({exc.__class__.__name__})",
        ) from exc


def _human_count(value: int) -> str:
    if value >= 1_000_000:
        return f"~{value / 1_000_000:.1f} M"
    if value >= 1_000:
        return f"~{value / 1_000:.1f} K"
    return str(value)


def _duration_estimate(rows: int) -> str:
    if rows <= 0:
        return "ready after first run"
    if rows < 100_000:
        return "~3 min"
    if rows < 1_000_000:
        return "~8 min"
    if rows < 10_000_000:
        return "~18 min"
    return "~35 min"


def _infer_postgres_entity(table_name: str) -> str:
    prefix = ""
    clean_name = table_name
    for candidate, label in (
        ("fct_", " · Fact"),
        ("dim_", ""),
        ("stg_", " · staging"),
        ("brdg_", " · bridge"),
    ):
        if clean_name.startswith(candidate):
            clean_name = clean_name[len(candidate) :]
            prefix = label
            break
    words = [part for part in clean_name.replace("-", "_").split("_") if part]
    if words and words[-1].endswith("ies"):
        words[-1] = f"{words[-1][:-3]}y"
    elif words and words[-1] == "statuses":
        words[-1] = "status"
    elif words and words[-1].endswith(("ches", "shes", "sses", "xes", "zes")):
        words[-1] = words[-1][:-2]
    elif words and words[-1].endswith("s") and not words[-1].endswith("ss"):
        words[-1] = words[-1][:-1]
    entity = "".join(word.capitalize() for word in words) or table_name
    return f"{entity}{prefix}"


def _pii_labels_for_column(column: str) -> list[str]:
    hints = (
        ("email", "email"),
        ("phone", "phone"),
        ("name", "name"),
        ("address", "address"),
        ("ssn", "ssn"),
        ("dob", "birth_date"),
        ("birth", "birth_date"),
        ("password", "password"),
        ("secret", "secret"),
        ("token", "token"),
        ("free_text", "free_text"),
        ("comment", "free_text"),
        ("note", "free_text"),
    )
    labels: list[str] = []
    lowered = column.lower()
    for needle, label in hints:
        if needle in lowered and label not in labels:
            labels.append(label)
    return labels


def _pii_labels(columns: list[str]) -> list[str]:
    labels: list[str] = []
    for column in columns:
        for label in _pii_labels_for_column(column):
            if label not in labels:
                labels.append(label)
    return labels


async def _test_postgres_connection(
    credentials: Dict[str, Any], config: Dict[str, Any]
) -> schemas.SourceSetupTestResult:
    pg_config = _postgres_config(credentials, config)
    started = time.perf_counter()
    conn = await _connect_postgres(pg_config)
    try:
        await conn.fetchval("SELECT 1;")
        schema_exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = $1);",
            pg_config["schema"],
        )
        if not schema_exists:
            raise HTTPException(
                status_code=400,
                detail=f"PostgreSQL schema '{pg_config['schema']}' was not found or is not visible",
            )
        has_usage = await conn.fetchval(
            "SELECT has_schema_privilege($1, 'USAGE');",
            pg_config["schema"],
        )
        object_count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = $1
              AND table_type IN ('BASE TABLE', 'VIEW')
              AND (
                $2::text[] IS NULL
                OR table_name = ANY($2::text[])
                OR (table_schema || '.' || table_name) = ANY($2::text[])
              );
            """,
            pg_config["schema"],
            pg_config["table_filter"],
        )
        permissions = ["CONNECT", "INFORMATION_SCHEMA"]
        if has_usage:
            permissions.append("USAGE")
        if object_count:
            permissions.append("SELECT")
        status = "passed" if has_usage and object_count else "warning"
        message = (
            f"Connected to PostgreSQL and found {object_count} visible schema object"
            f"{'' if object_count == 1 else 's'}."
        )
        if not object_count:
            message = (
                "Connected to PostgreSQL, but no matching tables or views were visible."
            )
        return schemas.SourceSetupTestResult(
            status=status,
            latency_ms=max(1, round((time.perf_counter() - started) * 1000)),
            permissions=permissions,
            object_count=object_count,
            dbt_model_count=0,
            message=message,
            checked_at=utc_now_naive(),
        )
    finally:
        await conn.close()


async def _test_clickhouse_connection(
    credentials: Dict[str, Any], config: Dict[str, Any]
) -> schemas.SourceSetupTestResult:
    ch_config = _clickhouse_config(credentials, config)
    started = time.perf_counter()
    client = await _connect_clickhouse(ch_config)
    try:

        def run_checks() -> int:
            ping = client.query("SELECT 1 AS ok")
            if not ping.result_set or ping.result_set[0][0] != 1:
                raise ValueError("ClickHouse ping failed")

            database_literal = _clickhouse_literal(ch_config["database"])
            db_rows = _clickhouse_rows(
                client.query(
                    "SELECT name FROM system.databases "
                    f"WHERE name = {database_literal}"
                )
            )
            if not db_rows:
                raise ValueError(
                    f"Database '{ch_config['database']}' does not exist or is inaccessible"
                )

            filter_sql = ""
            if ch_config["table_filter"]:
                literals = ", ".join(
                    _clickhouse_literal(item.split(".")[-1])
                    for item in ch_config["table_filter"]
                )
                filter_sql = f" AND name IN ({literals})"
            rows = _clickhouse_rows(
                client.query(
                    "SELECT name FROM system.tables "
                    f"WHERE database = {database_literal}{filter_sql}"
                )
            )
            if ch_config["table_filter"]:
                found = {str(row["name"]) for row in rows}
                missing = [
                    item
                    for item in ch_config["table_filter"]
                    if item.split(".")[-1] not in found
                ]
                if missing:
                    raise ValueError(
                        f"Tables not found in database '{ch_config['database']}': "
                        f"{', '.join(missing)}"
                    )
                unreadable: list[str] = []
                database_identifier = _clickhouse_identifier(ch_config["database"])
                for table_name in sorted(found):
                    try:
                        client.query(
                            "SELECT count() AS row_count FROM "
                            f"{database_identifier}.{_clickhouse_identifier(table_name)} "
                        )
                    except Exception as exc:
                        unreadable.append(
                            f"{table_name} ({_short_clickhouse_error(exc)})"
                        )
                if unreadable:
                    raise ValueError(
                        "ClickHouse objects exist but cannot be queried: "
                        f"{'; '.join(unreadable)}"
                    )
            return len(rows)

        object_count = await asyncio.to_thread(run_checks)
        status = "passed" if object_count else "warning"
        message = (
            f"Connected to ClickHouse and found {object_count} schema object"
            f"{'' if object_count == 1 else 's'}."
        )
        if not object_count:
            message = (
                "Connected to ClickHouse, but no matching tables or views were visible."
            )
        return schemas.SourceSetupTestResult(
            status=status,
            latency_ms=max(1, round((time.perf_counter() - started) * 1000)),
            permissions=["SELECT", "SYSTEM.TABLES", "SYSTEM.COLUMNS"],
            object_count=object_count,
            dbt_model_count=0,
            message=message,
            checked_at=utc_now_naive(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"ClickHouse test failed: {exc}"
        ) from exc
    finally:
        await asyncio.to_thread(client.close)


async def _discover_postgres(
    credentials: Dict[str, Any], config: Dict[str, Any]
) -> schemas.SourceSetupDiscovery:
    pg_config = _postgres_config(credentials, config)
    conn = await _connect_postgres(pg_config)
    try:
        rows = await conn.fetch(
            """
            WITH scoped_tables AS (
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = $1
                  AND table_type IN ('BASE TABLE', 'VIEW')
                  AND (
                    $2::text[] IS NULL
                    OR table_name = ANY($2::text[])
                    OR (table_schema || '.' || table_name) = ANY($2::text[])
                  )
            ),
            col_counts AS (
                SELECT
                    table_schema,
                    table_name,
                    COUNT(*)::int AS column_count,
                    ARRAY_AGG(column_name ORDER BY ordinal_position) AS column_names
                FROM information_schema.columns
                WHERE table_schema = $1
                GROUP BY table_schema, table_name
            ),
            fk_counts AS (
                SELECT table_schema, table_name, COUNT(*)::int AS foreign_key_count
                FROM information_schema.table_constraints
                WHERE table_schema = $1
                  AND constraint_type = 'FOREIGN KEY'
                GROUP BY table_schema, table_name
            )
            SELECT
                st.table_name,
                st.table_type,
                COALESCE(GREATEST(pg_class.reltuples::bigint, 0), 0) AS estimated_rows,
                COALESCE(col_counts.column_count, 0) AS column_count,
                COALESCE(fk_counts.foreign_key_count, 0) AS foreign_key_count,
                COALESCE(col_counts.column_names, ARRAY[]::text[]) AS column_names
            FROM scoped_tables st
            LEFT JOIN pg_namespace
                ON pg_namespace.nspname = st.table_schema
            LEFT JOIN pg_class
                ON pg_class.relnamespace = pg_namespace.oid
               AND pg_class.relname = st.table_name
            LEFT JOIN col_counts
                ON col_counts.table_schema = st.table_schema
               AND col_counts.table_name = st.table_name
            LEFT JOIN fk_counts
                ON fk_counts.table_schema = st.table_schema
               AND fk_counts.table_name = st.table_name
            ORDER BY estimated_rows DESC, st.table_name ASC
            LIMIT 25;
            """,
            pg_config["schema"],
            pg_config["table_filter"],
        )
        metrics = await conn.fetchrow(
            """
            WITH scoped_tables AS (
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema = $1
                  AND table_type IN ('BASE TABLE', 'VIEW')
                  AND (
                    $2::text[] IS NULL
                    OR table_name = ANY($2::text[])
                    OR (table_schema || '.' || table_name) = ANY($2::text[])
                  )
            ),
            fk_counts AS (
                SELECT COUNT(*)::int AS total_foreign_keys
                FROM information_schema.table_constraints tc
                INNER JOIN scoped_tables st
                    ON st.table_schema = tc.table_schema
                   AND st.table_name = tc.table_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
            )
            SELECT
                COUNT(*)::int AS table_count,
                COALESCE(SUM(GREATEST(pg_class.reltuples::bigint, 0)), 0)::bigint
                    AS estimated_rows,
                (SELECT total_foreign_keys FROM fk_counts)::int AS foreign_key_count
            FROM scoped_tables st
            LEFT JOIN pg_namespace
                ON pg_namespace.nspname = st.table_schema
            LEFT JOIN pg_class
                ON pg_class.relnamespace = pg_namespace.oid
               AND pg_class.relname = st.table_name;
            """,
            pg_config["schema"],
            pg_config["table_filter"],
        )
        table_names = [str(record["table_name"]) for record in rows]
        field_map: dict[str, list[schemas.DiscoveredField]] = {
            table_name: [] for table_name in table_names
        }
        primary_key_map: dict[str, list[str]] = {table_name: [] for table_name in table_names}
        foreign_key_map: dict[str, list[dict[str, Any]]] = {
            table_name: [] for table_name in table_names
        }
        if table_names:
            column_rows = await conn.fetch(
                """
                WITH pk_columns AS (
                    SELECT
                        kcu.table_schema,
                        kcu.table_name,
                        kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_schema = kcu.constraint_schema
                     AND tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                     AND tc.table_name = kcu.table_name
                    WHERE tc.table_schema = $1
                      AND tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_name = ANY($2::text[])
                ),
                fk_columns AS (
                    SELECT
                        kcu.table_schema,
                        kcu.table_name,
                        kcu.column_name,
                        ccu.table_schema AS ref_schema,
                        ccu.table_name AS ref_table,
                        ccu.column_name AS ref_column
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_schema = kcu.constraint_schema
                     AND tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                     AND tc.table_name = kcu.table_name
                    JOIN information_schema.constraint_column_usage ccu
                      ON ccu.constraint_schema = tc.constraint_schema
                     AND ccu.constraint_name = tc.constraint_name
                    WHERE tc.table_schema = $1
                      AND tc.constraint_type = 'FOREIGN KEY'
                      AND tc.table_name = ANY($2::text[])
                )
                SELECT
                    c.table_name,
                    c.column_name,
                    c.data_type,
                    c.udt_name,
                    (c.is_nullable = 'YES') AS nullable,
                    c.ordinal_position,
                    pk.column_name IS NOT NULL AS primary_key,
                    fk.column_name IS NOT NULL AS foreign_key,
                    fk.ref_schema,
                    fk.ref_table,
                    fk.ref_column
                FROM information_schema.columns c
                LEFT JOIN pk_columns pk
                  ON pk.table_schema = c.table_schema
                 AND pk.table_name = c.table_name
                 AND pk.column_name = c.column_name
                LEFT JOIN fk_columns fk
                  ON fk.table_schema = c.table_schema
                 AND fk.table_name = c.table_name
                 AND fk.column_name = c.column_name
                WHERE c.table_schema = $1
                  AND c.table_name = ANY($2::text[])
                ORDER BY c.table_name, c.ordinal_position;
                """,
                pg_config["schema"],
                table_names,
            )
            for column in column_rows:
                table_name = str(column["table_name"])
                field = schemas.DiscoveredField(
                    name=str(column["column_name"]),
                    data_type=str(column["data_type"] or column["udt_name"] or ""),
                    nullable=bool(column["nullable"]),
                    primary_key=bool(column["primary_key"]),
                    foreign_key=bool(column["foreign_key"]),
                    ref_schema=column["ref_schema"],
                    ref_table=column["ref_table"],
                    ref_column=column["ref_column"],
                    pii=_pii_labels_for_column(str(column["column_name"])),
                )
                field_map.setdefault(table_name, []).append(field)
                if field.primary_key:
                    primary_key_map.setdefault(table_name, []).append(field.name)
                if field.foreign_key:
                    foreign_key_map.setdefault(table_name, []).append(
                        {
                            "column": field.name,
                            "ref_schema": field.ref_schema,
                            "ref_table": field.ref_table,
                            "ref_column": field.ref_column,
                        }
                    )
        discovered = [
            schemas.DiscoveredObject(
                name=record["table_name"],
                type="view" if record["table_type"] == "VIEW" else "table",
                rows=record["estimated_rows"],
                columns=record["column_count"],
                foreign_keys=record["foreign_key_count"],
                inferred_entity=_infer_postgres_entity(record["table_name"]),
                pii=_pii_labels(list(record["column_names"] or [])),
                selected=True,
                fields=field_map.get(str(record["table_name"]), []),
                primary_keys=primary_key_map.get(str(record["table_name"]), []),
                foreign_key_details=foreign_key_map.get(str(record["table_name"]), []),
            )
            for record in rows
        ]
        cursor_priority = (
            "updated_at",
            "modified_at",
            "last_modified",
            "created_at",
            "inserted_at",
            "created_on",
        )
        cursor_coverage: dict[str, int] = {
            candidate: 0 for candidate in cursor_priority
        }
        for record in rows:
            columns = {str(column).lower() for column in (record["column_names"] or [])}
            for candidate in cursor_priority:
                if candidate in columns:
                    cursor_coverage[candidate] += 1
        default_cursor_field = next(
            (
                candidate
                for candidate in cursor_priority
                if cursor_coverage[candidate] > 0
            ),
            None,
        )
        total_rows = int(metrics["estimated_rows"] or 0)
        table_count = int(metrics["table_count"] or 0)
        foreign_key_count = int(metrics["foreign_key_count"] or 0)
        return schemas.SourceSetupDiscovery(
            source_identity={
                "Host": pg_config["host"],
                "Port": pg_config["port"],
                "Database": pg_config["database"],
                "Schema": pg_config["schema"],
                "Role": pg_config["user"],
                "dbt project": pg_config["dbt_project"] or "not attached",
            },
            objects=discovered,
            totals={
                "tables": table_count,
                "shown": len(discovered),
                "foreign_keys": foreign_key_count,
                "dbt_models": 0,
            },
            sync_estimate={
                "rows": _human_count(total_rows),
                "entities": _human_count(total_rows),
                "embeddings": f"{_human_count(total_rows)} · 1024d",
                "storage": f"~{max(0.1, total_rows * 0.00000016):.1f} GB",
                "first_sync": _duration_estimate(total_rows),
                "incremental": "every 15 min",
                "default_cursor_field": default_cursor_field or "",
                "cursor_coverage": cursor_coverage,
            },
            generated_at=utc_now_naive(),
        )
    finally:
        await conn.close()


async def _discover_clickhouse(
    credentials: Dict[str, Any], config: Dict[str, Any]
) -> schemas.SourceSetupDiscovery:
    ch_config = _clickhouse_config(credentials, config)
    client = await _connect_clickhouse(ch_config)
    try:

        def run_discovery() -> tuple[list[dict[str, Any]], dict[str, Any]]:
            database_literal = _clickhouse_literal(ch_config["database"])
            filter_sql = ""
            if ch_config["table_filter"]:
                literals = ", ".join(
                    _clickhouse_literal(item.split(".")[-1])
                    for item in ch_config["table_filter"]
                )
                filter_sql = f" AND t.name IN ({literals})"

            rows = _clickhouse_rows(
                client.query(
                    """
                    SELECT
                        t.name AS table_name,
                        t.engine AS engine,
                        ifNull(t.total_rows, 0) AS estimated_rows,
                        count(c.name) AS column_count,
                        groupArray(c.name) AS column_names
                    FROM system.tables t
                    LEFT JOIN system.columns c
                        ON c.database = t.database
                       AND c.table = t.name
                    WHERE t.database = {database}
                    {filter_sql}
                    GROUP BY t.name, t.engine, t.total_rows
                    ORDER BY estimated_rows DESC, t.name ASC
                    LIMIT 25
                    """.format(
                        database=database_literal, filter_sql=filter_sql
                    )
                )
            )
            database_identifier = _clickhouse_identifier(ch_config["database"])
            unreadable: list[str] = []
            for row in rows:
                table_name = str(row["table_name"])
                try:
                    client.query(
                        "SELECT count() AS row_count FROM "
                        f"{database_identifier}.{_clickhouse_identifier(table_name)} "
                    )
                    engine = str(row.get("engine") or "")
                    if "view" in engine.lower():
                        count_rows = _clickhouse_rows(
                            client.query(
                                "SELECT count() AS row_count FROM "
                                f"{database_identifier}.{_clickhouse_identifier(table_name)}"
                            )
                        )
                        if count_rows:
                            row["estimated_rows"] = int(
                                count_rows[0].get("row_count") or 0
                            )
                except Exception as exc:
                    unreadable.append(
                        f"{table_name} ({_short_clickhouse_error(exc)})"
                    )
            if unreadable:
                raise ValueError(
                    "ClickHouse objects exist but cannot be queried: "
                    f"{'; '.join(unreadable)}"
                )
            metric_rows = _clickhouse_rows(
                client.query(
                    """
                    SELECT
                        count() AS table_count,
                        sum(ifNull(total_rows, 0)) AS estimated_rows
                    FROM system.tables t
                    WHERE t.database = {database}
                    {filter_sql}
                    """.format(
                        database=database_literal, filter_sql=filter_sql
                    )
                )
            )
            metrics = (
                metric_rows[0]
                if metric_rows
                else {"table_count": 0, "estimated_rows": 0}
            )
            if rows:
                # system.tables.total_rows is usually zero for logical views. Use the
                # readable-object checks above as the estimate when they are more specific.
                metrics["estimated_rows"] = sum(
                    int(row.get("estimated_rows") or 0) for row in rows
                )
            return rows, metrics

        rows, metrics = await asyncio.to_thread(run_discovery)
        cursor_priority = (
            "updated_at",
            "event_time",
            "timestamp",
            "created_at",
            "created_on",
            "date",
        )
        cursor_coverage: dict[str, int] = {
            candidate: 0 for candidate in cursor_priority
        }
        discovered: list[schemas.DiscoveredObject] = []
        for row in rows:
            columns = [
                str(column) for column in row.get("column_names") or [] if column
            ]
            column_set = {column.lower() for column in columns}
            for candidate in cursor_priority:
                if candidate in column_set:
                    cursor_coverage[candidate] += 1
            table_name = str(row["table_name"])
            engine = str(row.get("engine") or "")
            object_type = (
                "materialized_view"
                if engine == "MaterializedView"
                else "view"
                if "view" in engine.lower()
                else "table"
            )
            discovered.append(
                schemas.DiscoveredObject(
                    name=table_name,
                    type=object_type,
                    rows=int(row.get("estimated_rows") or 0),
                    columns=int(row.get("column_count") or 0),
                    foreign_keys=0,
                    inferred_entity=_infer_postgres_entity(table_name),
                    pii=_pii_labels(columns),
                    selected=True,
                    fields=[
                        schemas.DiscoveredField(
                            name=column,
                            data_type=None,
                            nullable=True,
                            primary_key=column.lower() in {"id", f"{table_name.lower()}_id"},
                            foreign_key=column.lower().endswith("_id")
                            and column.lower() not in {"id", f"{table_name.lower()}_id"},
                            pii=_pii_labels_for_column(column),
                        )
                        for column in columns
                    ],
                )
            )

        default_cursor_field = next(
            (
                candidate
                for candidate in cursor_priority
                if cursor_coverage[candidate] > 0
            ),
            None,
        )
        total_rows = int(metrics.get("estimated_rows") or 0)
        table_count = int(metrics.get("table_count") or 0)
        return schemas.SourceSetupDiscovery(
            source_identity={
                "Host": ch_config["host"],
                "Port": ch_config["port"],
                "Database": ch_config["database"],
                "Secure": str(ch_config["secure"]).lower(),
                "Role": ch_config["user"],
                "dbt project": ch_config["dbt_project"] or "not attached",
            },
            objects=discovered,
            totals={
                "tables": table_count,
                "shown": len(discovered),
                "foreign_keys": 0,
                "dbt_models": 0,
            },
            sync_estimate={
                "rows": _human_count(total_rows),
                "entities": _human_count(total_rows),
                "embeddings": f"{_human_count(total_rows)} · 1024d",
                "storage": f"~{max(0.1, total_rows * 0.00000016):.1f} GB",
                "first_sync": _duration_estimate(total_rows),
                "incremental": "every 15 min",
                "default_cursor_field": default_cursor_field or "",
                "cursor_coverage": cursor_coverage,
            },
            generated_at=utc_now_naive(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"ClickHouse discovery failed: {exc}"
        ) from exc
    finally:
        await asyncio.to_thread(client.close)


def _fixture_discovery(
    provider: str, config: Dict[str, Any]
) -> schemas.SourceSetupDiscovery:
    generated_at = utc_now_naive()
    if provider == "snowflake":
        account = config.get("account") or "lattice.us-east-2"
        database = config.get("database") or "LATTICE_DW"
        schema = config.get("schema") or "PROD_CORE"
        objects = [
            ("dim_customers", 1_420_000, 18, 2, "Customer", ["email"]),
            ("dim_products", 28_402, 22, 3, "Product", []),
            ("dim_orders", 2_420_000, 24, 3, "Order", []),
            ("fct_order_lines", 8_400_000, 14, 3, "OrderLine · Fact", []),
            ("fct_revenue_daily", 14_200_000, 9, 1, "RevenueSample · TS", []),
            ("fct_returns", 184_000, 12, 3, "Return · Episode", []),
            ("fct_payments", 2_400_000, 10, 2, "Payment", []),
            ("brdg_order_promo", 412_000, 5, 2, "junction → uses_promo", []),
            ("stg_invoice_lines", 4_800_000, 18, 0, "no PK · review", []),
        ]
        return schemas.SourceSetupDiscovery(
            source_identity={
                "Account": account,
                "Database": database,
                "Schema": schema,
                "Warehouse": config.get("warehouse") or "ANALYTICS_WH",
                "Role": config.get("role") or "CONTEXTD_READER",
                "dbt project": config.get("dbt_project") or "not attached",
            },
            objects=[
                schemas.DiscoveredObject(
                    name=name,
                    rows=rows,
                    columns=cols,
                    foreign_keys=fks,
                    inferred_entity=entity,
                    pii=pii,
                    selected=name != "stg_invoice_lines",
                )
                for name, rows, cols, fks, entity, pii in objects
            ],
            totals={"tables": 64, "shown": 9, "foreign_keys": 218, "dbt_models": 142},
            sync_estimate={
                "rows": "~28.5 M",
                "entities": "~2.6 M",
                "embeddings": "~2.6 M · 1024d",
                "storage": "~4.2 GB",
                "first_sync": "~38 min",
                "incremental": "every 15 min",
            },
            generated_at=generated_at,
        )

    if provider == "clickhouse":
        database = config.get("database") or "default"
        objects = [
            ("events", 18_400_000, 18, 0, "Event · Fact", ["free_text"]),
            ("sessions", 3_200_000, 12, 0, "Session", []),
            ("members", 840_000, 16, 0, "Member", ["email", "name"]),
            ("orders", 2_100_000, 20, 0, "Order", []),
            ("order_items", 6_700_000, 11, 0, "OrderItem · Fact", []),
            ("feature_usage_daily", 12_200_000, 9, 0, "FeatureUsageDaily · TS", []),
        ]
        return schemas.SourceSetupDiscovery(
            source_identity={
                "Host": config.get("host") or "cluster.clickhouse.cloud",
                "Port": config.get("port") or 8443,
                "Database": database,
                "Secure": str(config.get("secure", True)),
                "Role": config.get("user") or "default",
                "dbt project": config.get("dbt_project") or "not attached",
            },
            objects=[
                schemas.DiscoveredObject(
                    name=name,
                    rows=rows,
                    columns=cols,
                    foreign_keys=fks,
                    inferred_entity=entity,
                    pii=pii,
                    selected=True,
                )
                for name, rows, cols, fks, entity, pii in objects
            ],
            totals={
                "tables": 26,
                "shown": len(objects),
                "foreign_keys": 0,
                "dbt_models": 0,
            },
            sync_estimate={
                "rows": "~43.4 M",
                "entities": "~3.7 M",
                "embeddings": "~3.7 M · 1024d",
                "storage": "~6.0 GB",
                "first_sync": "~42 min",
                "incremental": "hourly",
            },
            generated_at=generated_at,
        )

    schema = config.get("db_schema") or config.get("schema") or "public"
    database = config.get("database") or "appdb"
    objects = [
        ("customers", 245_192, 16, 2, "Customer", ["email", "name"]),
        ("accounts", 82_440, 14, 1, "Account", []),
        ("contacts", 391_850, 18, 3, "Contact", ["email"]),
        ("orders", 1_820_000, 19, 4, "Order", []),
        ("order_items", 6_900_000, 12, 3, "OrderLine · Fact", []),
        ("events", 12_400_000, 10, 1, "Event · Episode", ["free_text"]),
        ("subscriptions", 92_128, 13, 2, "Subscription", []),
        ("account_contacts", 144_840, 4, 2, "junction → has_contact", []),
        ("audit_log", 4_700_000, 8, 0, "Episode · review", ["free_text"]),
    ]
    return schemas.SourceSetupDiscovery(
        source_identity={
            "Host": config.get("host") or "db.internal",
            "Port": config.get("port") or 5432,
            "Database": database,
            "Schema": schema,
            "Role": config.get("user") or "contextd_reader",
            "dbt project": config.get("dbt_project") or "not attached",
        },
        objects=[
            schemas.DiscoveredObject(
                name=name,
                rows=rows,
                columns=cols,
                foreign_keys=fks,
                inferred_entity=entity,
                pii=pii,
                selected=name != "audit_log",
            )
            for name, rows, cols, fks, entity, pii in objects
        ],
        totals={"tables": 40, "shown": 9, "foreign_keys": 200, "dbt_models": 0},
        sync_estimate={
            "rows": "~26.7 M",
            "entities": "~1.9 M",
            "embeddings": "~1.9 M · 1024d",
            "storage": "~3.1 GB",
            "first_sync": "~24 min",
            "incremental": "every 15 min",
        },
        generated_at=generated_at,
    )


@router.post("/", response_model=schemas.SourceConnectionSetupDraft)
async def create_draft(
    *,
    db: AsyncSession = Depends(get_db),
    draft_in: schemas.SourceConnectionSetupDraftCreate,
    ctx: ApiContext = Depends(deps.get_context),
) -> SourceConnectionSetupDraft:
    """Create a setup draft for the source setup wizard."""
    provider = _normalize_provider(draft_in.provider_short_name)
    draft = SourceConnectionSetupDraft(
        provider_short_name=provider,
        target_collection_id=draft_in.target_collection_id,
        connection_name=draft_in.connection_name,
        description=draft_in.description,
        current_step=draft_in.current_step,
        status="draft",
        auth_method=draft_in.auth_method,
        config=_safe_config(draft_in.config or {}),
        organization_id=ctx.organization.id,
        created_by_email=ctx.tracking_email if ctx.has_user_context else None,
        modified_by_email=ctx.tracking_email if ctx.has_user_context else None,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return draft


@router.get("/{draft_id}", response_model=schemas.SourceConnectionSetupDraft)
async def get_draft(
    *,
    db: AsyncSession = Depends(get_db),
    draft_id: UUID,
    ctx: ApiContext = Depends(deps.get_context),
) -> SourceConnectionSetupDraft:
    """Get a setup draft."""
    return await _get_draft(db, draft_id, ctx)


@router.patch("/{draft_id}", response_model=schemas.SourceConnectionSetupDraft)
async def update_draft(
    *,
    db: AsyncSession = Depends(get_db),
    draft_id: UUID,
    draft_in: schemas.SourceConnectionSetupDraftUpdate,
    ctx: ApiContext = Depends(deps.get_context),
) -> SourceConnectionSetupDraft:
    """Update setup draft state."""
    draft = await _get_draft(db, draft_id, ctx)
    payload = draft_in.model_dump(exclude_unset=True)
    if "provider_short_name" in payload:
        payload["provider_short_name"] = _normalize_provider(
            payload["provider_short_name"]
        )
    if "config" in payload and payload["config"] is not None:
        payload["config"] = _safe_config(payload["config"])
    for key, value in payload.items():
        setattr(draft, key, value)
    if ctx.has_user_context:
        draft.modified_by_email = ctx.tracking_email
    await db.commit()
    await db.refresh(draft)
    return draft


@router.post("/{draft_id}/test", response_model=schemas.SourceSetupTestResult)
async def test_draft(
    *,
    db: AsyncSession = Depends(get_db),
    draft_id: UUID,
    test_in: schemas.SourceSetupTestRequest,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.SourceSetupTestResult:
    """Validate auth/config shape and persist a test summary."""
    draft = await _get_draft(db, draft_id, ctx)
    provider = _normalize_provider(draft.provider_short_name)
    safe_config = _safe_config({**test_in.config, **test_in.credentials})
    if provider == "postgresql":
        result = await _test_postgres_connection(test_in.credentials, test_in.config)
    elif provider == "clickhouse":
        result = await _test_clickhouse_connection(test_in.credentials, test_in.config)
    else:
        latency_ms = _fake_latency(provider, safe_config)
        dbt_models = (
            142 if provider == "snowflake" and safe_config.get("dbt_project") else 0
        )
        object_count = (
            64 if provider == "snowflake" else 26 if provider == "clickhouse" else 40
        )
        result = schemas.SourceSetupTestResult(
            status="passed",
            latency_ms=latency_ms,
            permissions=["SELECT", "USAGE", "INFORMATION_SCHEMA"],
            object_count=object_count,
            dbt_model_count=dbt_models,
            message=(
                f"Connection shape validated. {object_count} schema objects are ready "
                "for discovery."
            ),
            checked_at=utc_now_naive(),
        )
    draft.auth_method = test_in.auth_method
    draft.auth_summary = _auth_summary(provider, test_in.credentials, test_in.config)
    draft.config = safe_config
    draft.target_collection_id = (
        test_in.target_collection_id or draft.target_collection_id
    )
    draft.connection_name = test_in.connection_name or draft.connection_name
    draft.test_result = result.model_dump(mode="json")
    draft.current_step = "test"
    draft.status = "tested"
    if ctx.has_user_context:
        draft.modified_by_email = ctx.tracking_email
    await db.commit()
    return result


@router.post("/{draft_id}/discover", response_model=schemas.SourceSetupDiscovery)
async def discover_draft(
    *,
    db: AsyncSession = Depends(get_db),
    draft_id: UUID,
    discover_in: schemas.SourceSetupDiscoverRequest,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.SourceSetupDiscovery:
    """Persist a source discovery snapshot for the setup draft."""
    draft = await _get_draft(db, draft_id, ctx)
    provider = _normalize_provider(draft.provider_short_name)
    safe_config = _safe_config(
        {**(draft.config or {}), **discover_in.config, **discover_in.credentials}
    )
    if provider == "postgresql":
        discovery = await _discover_postgres(discover_in.credentials, safe_config)
    elif provider == "clickhouse":
        discovery = await _discover_clickhouse(discover_in.credentials, safe_config)
    else:
        discovery = _fixture_discovery(provider, safe_config)
    artifact = await context_forge_service.upsert_draft_mapping(
        db,
        draft=draft,
        discovery_snapshot=discovery.model_dump(mode="json"),
        ctx=ctx,
    )
    discovery.forge_mapping_id = artifact.id
    discovery.graph_preview = artifact.graph_preview
    draft.config = safe_config
    draft.discovery_snapshot = discovery.model_dump(mode="json")
    draft.current_step = "discover"
    draft.status = "discovered"
    if ctx.has_user_context:
        draft.modified_by_email = ctx.tracking_email
    await db.commit()
    return discovery


@router.post("/{draft_id}/scope", response_model=schemas.SourceConnectionSetupDraft)
async def save_scope(
    *,
    db: AsyncSession = Depends(get_db),
    draft_id: UUID,
    scope_in: schemas.SourceSetupScopeRequest,
    ctx: ApiContext = Depends(deps.get_context),
) -> SourceConnectionSetupDraft:
    """Persist selected source objects and masking settings."""
    draft = await _get_draft(db, draft_id, ctx)
    draft.scope = scope_in.model_dump(mode="json")
    draft.current_step = "scope"
    if ctx.has_user_context:
        draft.modified_by_email = ctx.tracking_email
    await db.commit()
    await db.refresh(draft)
    return draft


@router.post("/{draft_id}/schedule", response_model=schemas.SourceConnectionSetupDraft)
async def save_schedule(
    *,
    db: AsyncSession = Depends(get_db),
    draft_id: UUID,
    schedule_in: schemas.SourceSetupScheduleRequest,
    ctx: ApiContext = Depends(deps.get_context),
) -> SourceConnectionSetupDraft:
    """Persist schedule and cursor settings."""
    draft = await _get_draft(db, draft_id, ctx)
    draft.schedule = schedule_in.model_dump(mode="json")
    draft.current_step = "schedule"
    draft.status = "ready"
    if ctx.has_user_context:
        draft.modified_by_email = ctx.tracking_email
    await db.commit()
    await db.refresh(draft)
    return draft


@router.post("/{draft_id}/finalize", response_model=schemas.SourceConnection)
async def finalize_draft(
    *,
    db: AsyncSession = Depends(get_db),
    draft_id: UUID,
    finalize_in: schemas.SourceSetupFinalizeRequest,
    ctx: ApiContext = Depends(deps.get_context),
    guard_rail: GuardRailService = Depends(deps.get_guard_rail_service),
) -> schemas.SourceConnection:
    """Create the real source connection, encrypted credentials, sync, and schedule."""
    draft = await _get_draft(db, draft_id, ctx)
    provider = _normalize_provider(draft.provider_short_name)

    if provider not in FINALIZABLE_PROVIDERS:
        raise HTTPException(
            status_code=501,
            detail=(
                f"{provider} setup can be drafted, tested, and discovered, "
                "but final sync wiring is not available yet."
            ),
        )

    if draft.finalized_source_connection_id:
        return await source_connection_service.get(
            db,
            id=draft.finalized_source_connection_id,
            ctx=ctx,
        )

    await guard_rail.is_allowed(ActionType.SOURCE_CONNECTIONS)
    if finalize_in.sync_immediately:
        await guard_rail.is_allowed(ActionType.ENTITIES)

    schedule = finalize_in.schedule or (
        schemas.SourceSetupScheduleRequest(**draft.schedule) if draft.schedule else None
    )
    scope = (
        finalize_in.scope.model_dump(mode="json") if finalize_in.scope else draft.scope
    )
    target_collection_id = (
        finalize_in.target_collection_id or draft.target_collection_id
    )
    connection_name = (
        finalize_in.connection_name or draft.connection_name or f"{provider}-connection"
    )
    draft_description = draft.description
    draft_discovery_snapshot = draft.discovery_snapshot
    if not target_collection_id:
        raise HTTPException(
            status_code=400, detail="Target context database is required"
        )

    merged_config = {
        **(draft.config or {}),
        **finalize_in.config,
        **finalize_in.credentials,
    }
    config = _provider_config(provider, merged_config)
    config = _apply_scope_to_config(provider, config, scope)
    if schedule:
        config["cursor_field"] = schedule.cursor_field
        config["schedule"] = _sync_metadata(schedule)
    if scope:
        config["scope"] = scope

    if provider == "postgresql":
        # Keep finalization honest: validate the live DB once more before
        # creating encrypted credentials and scheduling a sync.
        await _test_postgres_connection(finalize_in.credentials, config)
    elif provider == "clickhouse":
        await _test_clickhouse_connection(finalize_in.credentials, config)

    existing_source_connection = await _get_existing_source_connection_for_target(
        db,
        target_collection_id=target_collection_id,
        ctx=ctx,
    )
    if existing_source_connection:
        if not _is_recoverable_finalize_connection(
            existing_source_connection,
            provider=provider,
            connection_name=connection_name,
            config=config,
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "This context database already has a source connection. "
                    "Only one connection per database is supported in this phase."
                ),
            )
        source_connection_model = existing_source_connection
    else:
        await source_connection_service.ensure_single_connection_slot(
            db,
            readable_collection_id=target_collection_id,
            ctx=ctx,
        )
        source_connection_in = SourceConnectionCreate(
            name=connection_name,
            short_name=provider,
            readable_collection_id=target_collection_id,
            description=draft_description,
            config=config,
            schedule=_schedule_config(schedule),
            sync_immediately=finalize_in.sync_immediately,
            authentication=DirectAuthentication(credentials=finalize_in.credentials),
        )
        source_connection = await source_connection_service.create(
            db,
            obj_in=source_connection_in,
            ctx=ctx,
        )
        draft = await _get_draft(db, draft_id, ctx)
        source_connection_model = await crud.source_connection.get(
            db,
            id=source_connection.id,
            ctx=ctx,
        )

    if not source_connection_model:
        raise HTTPException(status_code=500, detail="Source connection was not created")

    source_connection_id = source_connection_model.id
    if source_connection_model:
        from contextd.core.source_drift_service import source_drift_service

        source_connection_model.config_fields = (
            source_drift_service.initialize_config_drift(
                source_connection_model.config_fields,
                discovery_snapshot=draft_discovery_snapshot,
            )
        )
        await context_forge_service.promote_draft_mapping_to_source(
            db,
            setup_draft_id=draft_id,
            source_connection=source_connection_model,
            discovery_snapshot=draft_discovery_snapshot,
            drift_snapshot=(source_connection_model.config_fields or {}).get("drift"),
            ctx=ctx,
        )
        await db.flush()

    draft.auth_method = finalize_in.auth_method
    draft.auth_summary = _auth_summary(provider, finalize_in.credentials, config)
    draft.config = _safe_config(config)
    draft.target_collection_id = target_collection_id
    draft.connection_name = connection_name
    draft.scope = scope
    draft.schedule = schedule.model_dump(mode="json") if schedule else None
    draft.current_step = "schedule"
    draft.status = "finalized"
    draft.finalized_source_connection_id = source_connection_id
    if ctx.has_user_context:
        draft.modified_by_email = ctx.tracking_email
    await db.commit()

    return await source_connection_service.get(
        db,
        id=source_connection_id,
        ctx=ctx,
    )
