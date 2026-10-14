"""Unit coverage for structured source setup helper behavior."""

from __future__ import annotations

import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.api.v1.endpoints.source_setup_drafts import (  # noqa: E402
    _apply_scope_to_config,
    _clickhouse_config,
    _infer_postgres_entity,
    _schedule_config,
)
from contextd.schemas.source_connection_setup_draft import (
    SourceSetupScheduleRequest,
)  # noqa: E402


def test_schedule_with_cursor_is_incremental_even_on_hourly_cadence() -> None:
    schedule = SourceSetupScheduleRequest(cadence="hourly", cursor_field="updated_at")

    config = _schedule_config(schedule)

    assert config is not None
    assert config.cron == "0 * * * *"
    assert config.continuous is True
    assert config.cursor_field == "updated_at"


def test_scope_selected_objects_becomes_authoritative_table_filter() -> None:
    config = _apply_scope_to_config(
        "postgresql",
        {"tables": "*"},
        {"selected_objects": ["public.users", "orders", "orders"]},
    )

    assert config["tables"] == "users,orders"


def test_entity_inference_handles_es_plural_names() -> None:
    assert _infer_postgres_entity("classes") == "Class"
    assert _infer_postgres_entity("statuses") == "Status"


def test_empty_scope_cannot_finalize_to_all_tables() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _apply_scope_to_config("clickhouse", {"tables": "*"}, {"selected_objects": []})

    assert exc_info.value.status_code == 400


def test_clickhouse_config_normalizes_types() -> None:
    config = _clickhouse_config(
        {"host": "ch.example.com", "port": "8443", "secure": "false"},
        {"database": "analytics", "tables": "events,sessions"},
    )

    assert config["port"] == 8443
    assert config["secure"] is False
    assert config["table_filter"] == ["events", "sessions"]
