"""Tests for source connection schedule helpers."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.core.source_connection_service import SourceConnectionService  # noqa: E402


class LoggerStub:
    def info(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass


def _ctx():
    return SimpleNamespace(logger=LoggerStub())


def _source(*, supports_continuous: bool):
    return SimpleNamespace(short_name="github", supports_continuous=supports_continuous)


def test_explicit_null_schedule_disables_default_schedule() -> None:
    service = SourceConnectionService()
    obj_in = SimpleNamespace(schedule=SimpleNamespace(cron=None))

    assert (
        service._determine_schedule_for_source(obj_in, _source(supports_continuous=True), _ctx())
        is None
    )


def test_continuous_source_defaults_to_five_minute_schedule() -> None:
    service = SourceConnectionService()
    obj_in = SimpleNamespace(schedule=None)

    assert (
        service._determine_schedule_for_source(obj_in, _source(supports_continuous=True), _ctx())
        == "*/5 * * * *"
    )


def test_non_continuous_source_rejects_minute_level_schedule() -> None:
    service = SourceConnectionService()

    with pytest.raises(HTTPException) as exc_info:
        service._validate_cron_schedule_for_source(
            "*/5 * * * *", _source(supports_continuous=False), _ctx()
        )

    assert exc_info.value.status_code == 400
    assert "does not support continuous syncs" in exc_info.value.detail


def test_non_continuous_source_allows_hourly_schedule() -> None:
    service = SourceConnectionService()

    service._validate_cron_schedule_for_source(
        "0 * * * *", _source(supports_continuous=False), _ctx()
    )
