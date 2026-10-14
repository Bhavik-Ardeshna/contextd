"""Tests for Temporal schedule service behavior."""

from __future__ import annotations

import os

os.environ.setdefault("FIRST_SUPERUSER", "admin@example.com")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-for-tests-only-32")
os.environ.setdefault("STATE_SECRET", "test-state-secret-for-tests-only-32")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

import pytest
from temporalio.service import RPCError, RPCStatusCode

from contextd.platform.temporal import schedule_service as schedule_service_module
from contextd.platform.temporal.schedule_service import (
    TemporalScheduleService,
    is_minute_level_cron,
    schedule_type_for_cron,
)


class _MissingScheduleHandle:
    async def describe(self):
        raise RPCError("sql: no rows in result set", RPCStatusCode.NOT_FOUND, b"")


class _MissingScheduleClient:
    def get_schedule_handle(self, schedule_id: str):
        return _MissingScheduleHandle()


class _RecordingLogger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def info(self, message: str) -> None:
        self.messages.append(("info", message))

    def warning(self, message: str) -> None:
        self.messages.append(("warning", message))

    def error(self, message: str) -> None:
        self.messages.append(("error", message))


@pytest.mark.asyncio
async def test_missing_temporal_schedule_is_not_logged_as_error(monkeypatch) -> None:
    service = TemporalScheduleService()
    logger = _RecordingLogger()

    async def fake_get_client():
        return _MissingScheduleClient()

    monkeypatch.setattr(service, "_get_client", fake_get_client)
    monkeypatch.setattr(schedule_service_module, "logger", logger)

    result = await service.check_schedule_exists_and_running("sync-missing")

    assert result == {"exists": False, "running": False, "schedule_info": None}
    assert (
        "info",
        "Schedule sync-missing does not exist in Temporal",
    ) in logger.messages
    assert all(level != "error" for level, _message in logger.messages)


@pytest.mark.parametrize(
    ("cron_expression", "expected"),
    [
        ("* * * * *", True),
        ("*/5 * * * *", True),
        ("*/59 * * * *", True),
        ("0 * * * *", False),
        ("15 * * * *", False),
        ("0 2 * * *", False),
        ("*/60 * * * *", False),
    ],
)
def test_minute_level_cron_classification(cron_expression: str, expected: bool) -> None:
    assert is_minute_level_cron(cron_expression) is expected


@pytest.mark.parametrize(
    ("cron_expression", "expected"),
    [
        ("*/15 * * * *", "minute"),
        ("0 * * * *", "regular"),
        ("30 1 * * *", "regular"),
    ],
)
def test_schedule_type_for_cron(cron_expression: str, expected: str) -> None:
    assert schedule_type_for_cron(cron_expression) == expected
