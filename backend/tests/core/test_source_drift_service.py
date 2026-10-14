"""Unit coverage for ContextD source drift metadata."""

from __future__ import annotations

import os

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.core.source_drift_service import (
    apply_config_update,
    build_initial_drift_state,
    evaluate_drift,
    fingerprint_catalog_snapshot,
)


def _catalog(columns: list[dict]) -> list[dict]:
    return [
        {
            "schema_name": "public",
            "table_name": "users",
            "recency_column": "updated_at",
            "primary_keys": ["id"],
            "foreign_keys": [],
            "columns": columns,
        }
    ]


def test_initial_drift_is_clean_and_redacts_secret_config_changes() -> None:
    initial = build_initial_drift_state(
        {"tables": "*", "password": "first-secret"},
        now="2026-05-01T00:00:00Z",
    )

    checked = evaluate_drift(
        current_config={"tables": "*", "password": "rotated-secret"},
        previous_drift=initial,
        now="2026-05-01T00:01:00Z",
    )

    assert checked["status"] == "clean"
    assert checked["config"]["changed"] is False


def test_config_update_preserves_drift_and_marks_changed_config() -> None:
    existing = {
        "tables": "*",
        "drift": build_initial_drift_state(
            {"tables": "*"},
            now="2026-05-01T00:00:00Z",
        ),
    }

    updated = apply_config_update(existing, {"tables": "users"})

    assert updated["drift"]["status"] == "changed"
    assert updated["drift"]["config"]["changed"] is True
    assert updated["drift"]["summary"]["config_changed"] is True


def test_legacy_config_update_uses_existing_config_as_baseline() -> None:
    updated = apply_config_update({"tables": "*"}, {"tables": "users"})

    assert updated["drift"]["status"] == "changed"
    assert updated["drift"]["config"]["changed"] is True
    assert updated["drift"]["baseline"]["config"]["hash"] != updated["drift"]["current"][
        "config"
    ]["hash"]


def test_first_catalog_observation_promotes_setup_discovery_to_clean_baseline() -> None:
    initial = build_initial_drift_state(
        {"tables": "*"},
        discovery_snapshot={
            "source_identity": {"Database": "neondb"},
            "objects": [
                {
                    "name": "users",
                    "type": "table",
                    "columns": 2,
                    "foreign_keys": 0,
                    "inferred_entity": "User",
                    "selected": True,
                }
            ],
        },
        now="2026-05-01T00:00:00Z",
    )

    checked = evaluate_drift(
        current_config={"tables": "*"},
        previous_drift=initial,
        current_schema=fingerprint_catalog_snapshot(
            _catalog(
                [
                    {"column_name": "id", "data_type": "integer", "is_primary_key": True},
                    {"column_name": "email", "data_type": "text"},
                ]
            )
        ),
        now="2026-05-01T00:01:00Z",
    )

    assert checked["status"] == "clean"
    assert checked["baseline"]["schema"]["source"] == "field_catalog"


def test_schema_drift_detects_removed_and_changed_fields_as_critical() -> None:
    baseline_schema = fingerprint_catalog_snapshot(
        _catalog(
            [
                {"column_name": "id", "data_type": "integer", "is_primary_key": True},
                {"column_name": "email", "data_type": "text"},
                {"column_name": "age", "data_type": "integer"},
            ]
        )
    )
    initial = evaluate_drift(
        current_config={"tables": "*"},
        current_schema=baseline_schema,
        reset_baseline=True,
        now="2026-05-01T00:00:00Z",
    )

    checked = evaluate_drift(
        current_config={"tables": "*"},
        previous_drift=initial,
        current_schema=fingerprint_catalog_snapshot(
            _catalog(
                [
                    {"column_name": "id", "data_type": "bigint", "is_primary_key": True},
                    {"column_name": "email", "data_type": "text"},
                ]
            )
        ),
        allow_schema_baseline_promotion=False,
        now="2026-05-01T00:02:00Z",
    )

    assert checked["status"] == "changed"
    assert checked["severity"] == "critical"
    assert checked["schema"]["changes"]["removed_fields"] == {"public.users": ["age"]}
    assert checked["schema"]["changes"]["changed_fields"] == {"public.users": ["id"]}
