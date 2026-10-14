"""ContextD search metadata key helpers."""

from __future__ import annotations

from typing import Any
from uuid import UUID

CONTEXTD_SYSTEM_METADATA_KEY = "contextd_system_metadata"
CONTEXTD_COLLECTION_ID_KEY = "contextd_collection_id"

SYSTEM_METADATA_FIELD_NAMES = frozenset(
    {
        "chunk_index",
        "db_created_at",
        "db_entity_id",
        "db_updated_at",
        "entity_type",
        "hash",
        "original_entity_id",
        "source_name",
        "storage_blob_name",
        "sync_id",
        "sync_job_id",
    }
)


def contextd_system_metadata_path(field_name: str) -> str:
    """Return the canonical nested ContextD system metadata path."""
    return f"{CONTEXTD_SYSTEM_METADATA_KEY}.{field_name}"


def canonical_payload_key(key: str) -> str:
    """Map a public/filter key to the canonical ContextD payload key."""
    if key == CONTEXTD_COLLECTION_ID_KEY:
        return CONTEXTD_COLLECTION_ID_KEY

    if key.startswith(f"{CONTEXTD_SYSTEM_METADATA_KEY}."):
        return key

    if key in SYSTEM_METADATA_FIELD_NAMES:
        return contextd_system_metadata_path(key)

    return key


def add_contextd_payload_metadata(
    payload: dict[str, Any],
    *,
    collection_id: UUID | str | None = None,
    system_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply the canonical ContextD metadata payload shape."""
    if collection_id is not None:
        payload[CONTEXTD_COLLECTION_ID_KEY] = str(collection_id)

    if system_metadata is None:
        internal_metadata = payload.pop("contextd_system_metadata", None)
        if isinstance(internal_metadata, dict):
            system_metadata = internal_metadata

    if system_metadata is not None:
        payload[CONTEXTD_SYSTEM_METADATA_KEY] = system_metadata

    return payload


def get_system_metadata_field(
    payload: dict[str, Any],
    field_name: str,
    default: Any = None,
) -> Any:
    """Read a system metadata field from the canonical ContextD payload."""
    metadata = payload.get(CONTEXTD_SYSTEM_METADATA_KEY)
    if isinstance(metadata, dict) and field_name in metadata:
        return metadata[field_name]
    return default


def contextd_match_condition(key: str, match: dict[str, Any]) -> dict[str, Any]:
    """Build a match condition with a canonical ContextD key."""
    return {"key": canonical_payload_key(key), "match": match}


def collection_id_match_condition(collection_id: UUID | str) -> dict[str, Any]:
    """Build a ContextD collection-id match condition."""
    return contextd_match_condition(CONTEXTD_COLLECTION_ID_KEY, {"value": str(collection_id)})


def system_metadata_match_condition(
    field_name: str,
    match: dict[str, Any],
) -> dict[str, Any]:
    """Build a ContextD system metadata match condition."""
    return contextd_match_condition(contextd_system_metadata_path(field_name), match)


def normalize_filter_keys_to_contextd(filter_dict: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize filter condition keys to ContextD names."""
    if not filter_dict:
        return filter_dict
    return _map_filter_conditions(filter_dict)


def _map_filter_conditions(value: Any) -> Any:
    if isinstance(value, list):
        return [_map_filter_conditions(item) for item in value]

    if isinstance(value, dict):
        mapped = {key: _map_filter_conditions(item) for key, item in value.items()}
        key = mapped.get("key")
        if isinstance(key, str):
            mapped["key"] = canonical_payload_key(key)
        return mapped

    return value
