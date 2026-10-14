"""Native source drift tracking for ContextD source connections."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, Mapping, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from contextd.api.context import ApiContext
from contextd.models.source_connection import SourceConnection

DRIFT_VERSION = 1

SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "auth",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
)

CONFIG_IGNORED_KEYS = {"drift"}

DEFAULT_POLICY = {
    "check_on_sync": True,
    "preserve_baseline_until_accept": True,
    "auto_promote_first_catalog": True,
    "auto_apply_additive": False,
    "block_on_breaking": False,
}


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _is_secret_key(key: str) -> bool:
    normalized = key.lower()
    return any(fragment in normalized for fragment in SECRET_KEY_FRAGMENTS)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _normalize_for_hash(value: Any, *, parent_key: str | None = None) -> Any:
    value = _jsonable(value)
    if isinstance(value, Mapping):
        normalized: Dict[str, Any] = {}
        for item_key, item in sorted(value.items(), key=lambda entry: str(entry[0])):
            key = str(item_key)
            if key in CONFIG_IGNORED_KEYS:
                continue
            if _is_secret_key(key):
                normalized[key] = "<redacted>"
                continue
            normalized[key] = _normalize_for_hash(item, parent_key=key)
        return normalized
    if isinstance(value, list):
        normalized_items = [
            _normalize_for_hash(item, parent_key=parent_key) for item in value
        ]
        return sorted(normalized_items, key=_sort_key)
    return value


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        _normalize_for_hash(value),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _clean_config(config: Mapping[str, Any] | None) -> Dict[str, Any]:
    payload = dict(config or {})
    payload.pop("drift", None)
    return payload


def _config_fingerprint(config: Mapping[str, Any] | None) -> Dict[str, Any]:
    normalized = _normalize_for_hash(_clean_config(config))
    return {
        "source": "source_connection_config",
        "hash": _stable_hash(normalized),
        "keys": sorted(normalized.keys()),
    }


def _empty_schema_fingerprint(source: str = "not_available") -> Dict[str, Any]:
    return {
        "source": source,
        "hash": None,
        "object_count": 0,
        "field_count": 0,
        "objects": {},
    }


def fingerprint_discovery_snapshot(
    discovery_snapshot: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """Build a compact schema fingerprint from a setup discovery snapshot."""
    if not discovery_snapshot:
        return _empty_schema_fingerprint()

    objects: Dict[str, Dict[str, Any]] = {}
    for item in discovery_snapshot.get("objects") or []:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        payload = {
            "type": item.get("type") or "object",
            "columns": int(item.get("columns") or 0),
            "foreign_keys": int(item.get("foreign_keys") or 0),
            "inferred_entity": item.get("inferred_entity"),
            "selected": bool(item.get("selected", True)),
        }
        objects[name] = {
            "hash": _stable_hash(payload),
            "fields": {},
            "field_count": payload["columns"],
        }

    identity = discovery_snapshot.get("source_identity") or {}
    payload = {"identity": identity, "objects": objects}
    return {
        "source": "setup_discovery",
        "hash": _stable_hash(payload) if objects or identity else None,
        "object_count": len(objects),
        "field_count": sum(item.get("field_count", 0) for item in objects.values()),
        "objects": objects,
    }


def fingerprint_catalog_snapshot(
    snapshot: Iterable[Mapping[str, Any]] | None,
) -> Dict[str, Any]:
    """Build a compact schema fingerprint from the persisted field catalog shape."""
    objects: Dict[str, Dict[str, Any]] = {}
    for table in snapshot or []:
        schema_name = str(table.get("schema_name") or "").strip()
        table_name = str(table.get("table_name") or "").strip()
        if not table_name:
            continue
        key = f"{schema_name}.{table_name}" if schema_name else table_name

        fields: Dict[str, str] = {}
        for column in table.get("columns") or []:
            if not isinstance(column, Mapping):
                continue
            column_name = str(column.get("column_name") or "").strip()
            if not column_name:
                continue
            column_payload = {
                "data_type": column.get("data_type"),
                "udt_name": column.get("udt_name"),
                "is_nullable": bool(column.get("is_nullable", True)),
                "default_value": column.get("default_value"),
                "is_primary_key": bool(column.get("is_primary_key", False)),
                "is_foreign_key": bool(column.get("is_foreign_key", False)),
                "ref_schema": column.get("ref_schema"),
                "ref_table": column.get("ref_table"),
                "ref_column": column.get("ref_column"),
                "enum_values": column.get("enum_values"),
            }
            fields[column_name] = _stable_hash(column_payload)

        table_payload = {
            "primary_keys": table.get("primary_keys") or [],
            "foreign_keys": table.get("foreign_keys") or [],
            "fields": fields,
            "recency_column": table.get("recency_column"),
        }
        objects[key] = {
            "hash": _stable_hash(table_payload),
            "fields": fields,
            "field_count": len(fields),
        }

    return {
        "source": "field_catalog",
        "hash": _stable_hash({"objects": objects}) if objects else None,
        "object_count": len(objects),
        "field_count": sum(item.get("field_count", 0) for item in objects.values()),
        "objects": objects,
    }


def _compare_schema(
    baseline: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    baseline = baseline or _empty_schema_fingerprint()
    current = current or _empty_schema_fingerprint()
    if not baseline.get("hash") or not current.get("hash"):
        return {
            "status": "unknown",
            "changed": False,
            "changes": {
                "added_objects": [],
                "removed_objects": [],
                "changed_objects": [],
                "added_fields": {},
                "removed_fields": {},
                "changed_fields": {},
            },
        }

    old_objects = baseline.get("objects") or {}
    new_objects = current.get("objects") or {}
    added_objects = sorted(set(new_objects) - set(old_objects))
    removed_objects = sorted(set(old_objects) - set(new_objects))
    changed_objects = sorted(
        key
        for key in set(old_objects) & set(new_objects)
        if old_objects[key].get("hash") != new_objects[key].get("hash")
    )

    added_fields: Dict[str, list[str]] = {}
    removed_fields: Dict[str, list[str]] = {}
    changed_fields: Dict[str, list[str]] = {}
    for key in changed_objects:
        old_fields = old_objects[key].get("fields") or {}
        new_fields = new_objects[key].get("fields") or {}
        if not old_fields and not new_fields:
            continue
        added = sorted(set(new_fields) - set(old_fields))
        removed = sorted(set(old_fields) - set(new_fields))
        changed = sorted(
            field
            for field in set(old_fields) & set(new_fields)
            if old_fields[field] != new_fields[field]
        )
        if added:
            added_fields[key] = added
        if removed:
            removed_fields[key] = removed
        if changed:
            changed_fields[key] = changed

    changed = bool(
        added_objects
        or removed_objects
        or changed_objects
        or added_fields
        or removed_fields
        or changed_fields
    )
    return {
        "status": "changed" if changed else "clean",
        "changed": changed,
        "changes": {
            "added_objects": added_objects,
            "removed_objects": removed_objects,
            "changed_objects": changed_objects,
            "added_fields": added_fields,
            "removed_fields": removed_fields,
            "changed_fields": changed_fields,
        },
    }


def _severity(config_changed: bool, schema_comparison: Mapping[str, Any]) -> str:
    if schema_comparison.get("status") == "unknown":
        return "warning" if config_changed else "clean"
    changes = schema_comparison.get("changes") or {}
    if (
        changes.get("removed_objects")
        or changes.get("removed_fields")
        or changes.get("changed_fields")
    ):
        return "critical"
    if config_changed or changes.get("changed_objects"):
        return "warning"
    if changes.get("added_objects") or changes.get("added_fields"):
        return "info"
    return "clean"


def _summary(
    config_changed: bool,
    schema_comparison: Mapping[str, Any],
    current_schema: Mapping[str, Any],
) -> Dict[str, Any]:
    changes = schema_comparison.get("changes") or {}
    return {
        "config_changed": config_changed,
        "objects_added": len(changes.get("added_objects") or []),
        "objects_removed": len(changes.get("removed_objects") or []),
        "objects_changed": len(changes.get("changed_objects") or []),
        "fields_added": sum(len(items) for items in (changes.get("added_fields") or {}).values()),
        "fields_removed": sum(
            len(items) for items in (changes.get("removed_fields") or {}).values()
        ),
        "fields_changed": sum(
            len(items) for items in (changes.get("changed_fields") or {}).values()
        ),
        "objects_observed": int(current_schema.get("object_count") or 0),
        "fields_observed": int(current_schema.get("field_count") or 0),
    }


def evaluate_drift(
    *,
    current_config: Mapping[str, Any] | None,
    previous_drift: Mapping[str, Any] | None = None,
    current_schema: Mapping[str, Any] | None = None,
    discovery_snapshot: Mapping[str, Any] | None = None,
    checked_by: str = "sync",
    reset_baseline: bool = False,
    allow_schema_baseline_promotion: bool = True,
    now: str | None = None,
) -> Dict[str, Any]:
    """Evaluate drift against the stored baseline and return a full drift block."""
    checked_at = now or _utc_iso()
    policy = {
        **DEFAULT_POLICY,
        **((previous_drift or {}).get("policy") or {}),
    }
    config_fp = _config_fingerprint(current_config)
    schema_fp = current_schema or fingerprint_discovery_snapshot(discovery_snapshot)

    previous_drift = dict(previous_drift or {})
    baseline = deepcopy(previous_drift.get("baseline") or {})
    baseline_config = baseline.get("config") or config_fp
    baseline_schema = baseline.get("schema") or schema_fp

    should_promote_schema = (
        reset_baseline
        or (
            allow_schema_baseline_promotion
            and policy.get("auto_promote_first_catalog", True)
            and schema_fp.get("hash")
            and schema_fp.get("source") == "field_catalog"
            and baseline_schema.get("source") in {None, "not_available", "setup_discovery"}
        )
    )
    if reset_baseline:
        baseline_config = config_fp
    if should_promote_schema:
        baseline_schema = schema_fp

    config_changed = bool(
        baseline_config.get("hash")
        and config_fp.get("hash")
        and baseline_config.get("hash") != config_fp.get("hash")
    )
    schema_comparison = _compare_schema(baseline_schema, schema_fp)
    severity = _severity(config_changed, schema_comparison)
    status = "unknown"
    if severity == "clean":
        status = "clean"
    elif severity in {"info", "warning", "critical"}:
        status = "changed"

    summary = _summary(config_changed, schema_comparison, schema_fp)
    return {
        "version": DRIFT_VERSION,
        "status": status,
        "severity": severity,
        "policy": policy,
        "baseline": {
            "config": baseline_config,
            "schema": baseline_schema,
        },
        "current": {
            "config": config_fp,
            "schema": schema_fp,
        },
        "config": {
            "status": "changed" if config_changed else "clean",
            "changed": config_changed,
            "baseline_hash": baseline_config.get("hash"),
            "current_hash": config_fp.get("hash"),
        },
        "schema": {
            **schema_comparison,
            "baseline_hash": baseline_schema.get("hash"),
            "current_hash": schema_fp.get("hash"),
            "baseline_source": baseline_schema.get("source"),
            "current_source": schema_fp.get("source"),
        },
        "summary": summary,
        "last_checked_at": checked_at,
        "checked_by": checked_by,
    }


def build_initial_drift_state(
    config: Mapping[str, Any] | None,
    *,
    discovery_snapshot: Mapping[str, Any] | None = None,
    now: str | None = None,
) -> Dict[str, Any]:
    return evaluate_drift(
        current_config=config,
        discovery_snapshot=discovery_snapshot,
        checked_by="setup_finalize" if discovery_snapshot else "connection_create",
        now=now,
    )


def ensure_initial_config_drift(
    config: Mapping[str, Any] | None,
    *,
    discovery_snapshot: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    payload = dict(config or {})
    if not payload.get("drift"):
        payload["drift"] = build_initial_drift_state(
            payload,
            discovery_snapshot=discovery_snapshot,
        )
    return payload


def initialize_config_drift(
    config: Mapping[str, Any] | None,
    *,
    discovery_snapshot: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    payload = dict(config or {})
    payload["drift"] = build_initial_drift_state(
        payload,
        discovery_snapshot=discovery_snapshot,
    )
    return payload


def apply_config_update(
    existing_config: Mapping[str, Any] | None,
    new_config: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """Merge a config update while preserving and re-evaluating drift metadata."""
    existing_payload = _clean_config(existing_config)
    existing_drift = dict((existing_config or {}).get("drift") or {})
    if not existing_drift:
        existing_drift = build_initial_drift_state(
            existing_payload,
        )
    payload = dict(new_config or {})
    current_schema = (existing_drift.get("current") or {}).get("schema")
    payload["drift"] = evaluate_drift(
        current_config=payload,
        previous_drift=existing_drift,
        current_schema=current_schema,
        checked_by="config_update",
        allow_schema_baseline_promotion=False,
    )
    return payload


class SourceDriftService:
    """Persistence facade for source drift metadata stored on source connections."""

    def ensure_initial_config_drift(
        self,
        config: Mapping[str, Any] | None,
        *,
        discovery_snapshot: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return ensure_initial_config_drift(
            config,
            discovery_snapshot=discovery_snapshot,
        )

    def initialize_config_drift(
        self,
        config: Mapping[str, Any] | None,
        *,
        discovery_snapshot: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return initialize_config_drift(
            config,
            discovery_snapshot=discovery_snapshot,
        )

    def apply_config_update(
        self,
        existing_config: Mapping[str, Any] | None,
        new_config: Mapping[str, Any] | None,
    ) -> Dict[str, Any]:
        return apply_config_update(existing_config, new_config)

    async def record_catalog_observation(
        self,
        *,
        db: AsyncSession,
        organization_id: UUID | str,
        source_connection_id: UUID | str,
        snapshot: Iterable[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        source_connection = await self._get_source_connection(
            db,
            organization_id=organization_id,
            source_connection_id=source_connection_id,
        )
        if not source_connection:
            return None

        config = dict(source_connection.config_fields or {})
        current_config = _clean_config(config)
        drift = evaluate_drift(
            current_config=current_config,
            previous_drift=config.get("drift"),
            current_schema=fingerprint_catalog_snapshot(snapshot),
            checked_by="field_catalog",
            allow_schema_baseline_promotion=True,
        )
        config["drift"] = drift
        source_connection.config_fields = config
        if drift.get("status") == "changed":
            from contextd.core.context_forge_service import context_forge_service

            await context_forge_service.mark_source_mapping_drift(
                db,
                source_connection=source_connection,
                drift=drift,
            )
        from contextd.core.context_intelligence_service import context_intelligence_service

        await context_intelligence_service.sync_source_drift_signals(
            db,
            source_connection=source_connection,
        )
        await db.flush()
        return drift

    async def record_sync_checkpoint(
        self,
        *,
        db: AsyncSession,
        organization_id: UUID | str,
        sync_id: UUID | str,
        source_connection_id: UUID | str | None = None,
        sync_job_id: UUID | str | None = None,
        cursor_data: Mapping[str, Any] | None = None,
        force_full_sync: bool = False,
        entity_stats: Mapping[str, Any] | None = None,
        reset_baseline: bool = False,
    ) -> Optional[Dict[str, Any]]:
        source_connection = await self._get_source_connection(
            db,
            organization_id=organization_id,
            source_connection_id=source_connection_id,
            sync_id=sync_id,
        )
        if not source_connection:
            return None

        config = dict(source_connection.config_fields or {})
        existing_drift = dict(config.get("drift") or {})
        current_schema = (existing_drift.get("current") or {}).get("schema")
        drift = evaluate_drift(
            current_config=_clean_config(config),
            previous_drift=existing_drift,
            current_schema=current_schema,
            checked_by="sync_checkpoint",
            reset_baseline=reset_baseline,
            allow_schema_baseline_promotion=False,
        )
        drift["sync_checkpoint"] = {
            "sync_id": str(sync_id),
            "sync_job_id": str(sync_job_id) if sync_job_id else None,
            "force_full_sync": bool(force_full_sync),
            "cursor_keys": sorted((cursor_data or {}).keys()),
            "cursor_saved": bool(cursor_data),
            "entity_stats": dict(entity_stats or {}),
            "recorded_at": _utc_iso(),
        }
        config["drift"] = drift
        source_connection.config_fields = config
        if drift.get("status") == "changed":
            from contextd.core.context_forge_service import context_forge_service

            await context_forge_service.mark_source_mapping_drift(
                db,
                source_connection=source_connection,
                drift=drift,
            )
        from contextd.core.context_intelligence_service import context_intelligence_service

        await context_intelligence_service.sync_source_drift_signals(
            db,
            source_connection=source_connection,
        )
        await db.flush()
        return drift

    async def accept_current_baseline(
        self,
        *,
        db: AsyncSession,
        source_connection: SourceConnection,
        ctx: ApiContext,
    ) -> Dict[str, Any]:
        await self._validate_source_connection_access(source_connection, ctx)
        config = dict(source_connection.config_fields or {})
        existing_drift = dict(config.get("drift") or {})
        drift = evaluate_drift(
            current_config=_clean_config(config),
            previous_drift=existing_drift,
            current_schema=(existing_drift.get("current") or {}).get("schema"),
            checked_by="baseline_accept",
            reset_baseline=True,
            allow_schema_baseline_promotion=True,
        )
        config["drift"] = drift
        source_connection.config_fields = config
        from contextd.core.context_intelligence_service import context_intelligence_service

        await context_intelligence_service.sync_source_drift_signals(
            db,
            source_connection=source_connection,
        )
        await db.flush()
        return drift

    async def _validate_source_connection_access(
        self,
        source_connection: SourceConnection,
        ctx: ApiContext,
    ) -> None:
        if str(source_connection.organization_id) != str(ctx.organization.id):
            from contextd.core.exceptions import PermissionException

            raise PermissionException("Source connection is not in this organization")

    async def _get_source_connection(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID | str,
        source_connection_id: UUID | str | None = None,
        sync_id: UUID | str | None = None,
    ) -> SourceConnection | None:
        stmt = select(SourceConnection).where(
            SourceConnection.organization_id == UUID(str(organization_id))
        )
        if source_connection_id:
            stmt = stmt.where(SourceConnection.id == UUID(str(source_connection_id)))
        elif sync_id:
            stmt = stmt.where(SourceConnection.sync_id == UUID(str(sync_id)))
        else:
            return None

        result = await db.execute(stmt.limit(1))
        return result.scalar_one_or_none()


source_drift_service = SourceDriftService()
