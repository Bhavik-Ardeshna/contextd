"""PII masking policy applied before ContextD graph/index persistence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._metadata import GraphEdgeConfig

MASKED_VALUE = "[masked]"
MASKED_FIELDS_PROPERTY = "_contextd_masked_fields"
MASKING_POLICY_PROPERTY = "_contextd_masking_policy"

_PII_HINTS = (
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

_PROTECTED_FIELDS = {
    "entity_id",
    "breadcrumbs",
    "contextd_system_metadata",
    "table_name",
    "schema_name",
    "primary_key_columns",
    "source_object",
    "source_schema",
}


@dataclass(frozen=True)
class MaskDecision:
    field: str
    labels: tuple[str, ...]
    reason: str
    strategy: str = "redact"


@dataclass(frozen=True)
class PiiMaskPolicy:
    masked_fields: Mapping[str, tuple[str, ...]]
    patterns: tuple[str, ...]

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> "PiiMaskPolicy":
        scope = (config or {}).get("scope") if isinstance(config, Mapping) else None
        if not isinstance(scope, Mapping):
            scope = {}

        raw_masked_fields = scope.get("masked_fields") or {}
        masked_fields: dict[str, tuple[str, ...]] = {}
        if isinstance(raw_masked_fields, Mapping):
            for object_name, fields in raw_masked_fields.items():
                if not object_name:
                    continue
                normalized_fields = _normalize_field_list(fields)
                if normalized_fields:
                    key = _normalize_key(str(object_name))
                    masked_fields[key] = tuple(normalized_fields)

        raw_patterns = scope.get("exclude_masks") or []
        patterns = tuple(
            str(item).strip().lower()
            for item in raw_patterns
            if str(item).strip()
        )
        return cls(masked_fields=masked_fields, patterns=patterns)

    @property
    def enabled(self) -> bool:
        return bool(self.masked_fields or self.patterns)

    def decision_for(self, entity: BaseEntity, field_name: str) -> MaskDecision | None:
        if field_name in _PROTECTED_FIELDS or field_name.startswith("_"):
            return None
        if self._is_key_or_relationship_field(entity, field_name):
            return None

        object_keys = _entity_object_keys(entity)
        normalized_field = _field_key(field_name)
        for object_key in object_keys:
            fields = self.masked_fields.get(object_key)
            if fields and normalized_field in fields:
                return MaskDecision(
                    field=field_name,
                    labels=tuple(_labels_for_field(field_name)),
                    reason="scope_mask",
                )

        if self._matches_pattern(entity, field_name):
            return MaskDecision(
                field=field_name,
                labels=tuple(_labels_for_field(field_name)),
                reason="pattern_mask",
            )
        return None

    def _matches_pattern(self, entity: BaseEntity, field_name: str) -> bool:
        if not self.patterns:
            return False
        field = field_name.lower()
        object_names = _entity_object_keys(entity) or ("",)
        candidates = {field}
        for object_name in object_names:
            if object_name:
                candidates.add(f"{object_name}.{field}")
                candidates.add(f"{object_name.split('.')[-1]}.{field}")
        for pattern in self.patterns:
            normalized_pattern = pattern.replace(" ", "").lower()
            if any(fnmatchcase(candidate, normalized_pattern) for candidate in candidates):
                return True
        return False

    @staticmethod
    def _is_key_or_relationship_field(entity: BaseEntity, field_name: str) -> bool:
        primary_keys = {
            _field_key(str(value))
            for value in (getattr(entity, "primary_key_columns", None) or [])
        }
        if _field_key(field_name) in primary_keys:
            return True
        entity_metadata = getattr(entity.__class__, "_entity_metadata", None)
        field_meta = getattr(entity_metadata, "fields", {}).get(field_name) if entity_metadata else None
        return bool(field_meta and isinstance(getattr(field_meta, "graph", None), GraphEdgeConfig))


def apply_pii_masking(entities: Iterable[BaseEntity], *, config: Mapping[str, Any] | None) -> int:
    """Redact scoped PII fields in-place before hashing, indexing, and graph commit."""
    policy = PiiMaskPolicy.from_config(config)
    if not policy.enabled:
        return 0

    masked_count = 0
    for entity in entities:
        entity_masked: dict[str, dict[str, Any]] = {}
        for field_name in list(entity.model_fields.keys()):
            value = getattr(entity, field_name, None)
            if value in (None, ""):
                continue
            decision = policy.decision_for(entity, field_name)
            if not decision:
                continue
            labels = decision.labels or tuple(_labels_for_field(field_name)) or ("pii",)
            setattr(entity, field_name, _masked_value(labels))
            entity_masked[field_name] = {
                "strategy": decision.strategy,
                "labels": list(labels),
                "reason": decision.reason,
            }
            masked_count += 1

        if entity_masked and entity.contextd_system_metadata:
            entity.contextd_system_metadata.masked_fields = entity_masked
    return masked_count


def _masked_value(labels: Iterable[str]) -> str:
    label = next((str(item) for item in labels if item), "pii")
    return f"[masked:{label}]"


def _normalize_field_list(fields: Any) -> list[str]:
    if isinstance(fields, str):
        items = fields.replace("\n", ",").split(",")
    elif isinstance(fields, Iterable):
        items = fields
    else:
        items = [fields]
    normalized = []
    for item in items:
        value = _field_key(str(item))
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _normalize_key(value: str) -> str:
    return value.strip().lower()


def _field_key(value: str) -> str:
    return _normalize_key(value).rstrip("_")


def _entity_object_keys(entity: BaseEntity) -> tuple[str, ...]:
    table = str(getattr(entity, "table_name", "") or "").strip()
    schema = str(getattr(entity, "schema_name", "") or "").strip()
    keys = []
    for value in (table, f"{schema}.{table}" if schema and table else ""):
        normalized = _normalize_key(value)
        if normalized and normalized not in keys:
            keys.append(normalized)
    return tuple(keys)


def _labels_for_field(field_name: str) -> list[str]:
    lowered = field_name.lower()
    labels = []
    for needle, label in _PII_HINTS:
        if needle in lowered and label not in labels:
            labels.append(label)
    return labels
