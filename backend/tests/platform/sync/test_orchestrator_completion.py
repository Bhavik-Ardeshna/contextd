"""Tests for sync finalization ordering and retry safety."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.platform.sync.exceptions import SyncFailureError
from contextd.platform.sync.orchestrator import SyncOrchestrator


class _Logger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str, *args, **kwargs) -> None:
        self.messages.append(str(message))

    def warning(self, message: str, *args, **kwargs) -> None:
        self.messages.append(str(message))

    def error(self, message: str, *args, **kwargs) -> None:
        self.messages.append(str(message))


class _DbContext:
    def __init__(self, db) -> None:
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _stats() -> SimpleNamespace:
    return SimpleNamespace(inserted=1, updated=2, deleted=0, kept=3, skipped=0)


def _sync_context() -> SimpleNamespace:
    return SimpleNamespace(
        should_batch=True,
        batch_size=100,
        max_batch_latency_ms=500,
        logger=_Logger(),
        entity_tracker=SimpleNamespace(get_stats=_stats),
        cursor=SimpleNamespace(cursor_data={"cursor": "next"}, cursor_field=None),
        execution_config=None,
        force_full_sync=False,
        sync=SimpleNamespace(id=uuid4()),
        sync_job=SimpleNamespace(id=uuid4(), started_at=None),
        ctx=SimpleNamespace(),
        state_builder=SimpleNamespace(),
    )


def _orchestrator(context: SimpleNamespace) -> SyncOrchestrator:
    return SyncOrchestrator(
        entity_pipeline=SimpleNamespace(),
        worker_pool=SimpleNamespace(),
        stream=SimpleNamespace(),
        sync_context=context,
    )


@pytest.mark.asyncio
async def test_complete_sync_saves_state_before_cursor(monkeypatch) -> None:
    """Cursor advancement happens after durable sync finalization artifacts."""
    context = _sync_context()
    orchestrator = _orchestrator(context)
    events: list[str] = []

    async def save_state() -> None:
        events.append("state")

    async def save_cursor() -> None:
        events.append("cursor")

    monkeypatch.setattr(orchestrator, "_save_state_snapshot", save_state)
    monkeypatch.setattr(orchestrator, "_save_cursor_data", save_cursor)

    with patch(
        "contextd.platform.sync.orchestrator.sync_job_service.update_status",
        AsyncMock(),
    ), patch(
        "contextd.analytics.business_events.track_sync_completed",
        MagicMock(),
    ):
        await orchestrator._complete_sync()

    assert events[:2] == ["state", "cursor"]


@pytest.mark.asyncio
async def test_save_cursor_data_failure_fails_sync() -> None:
    """A cursor write failure must not allow the sync job to complete."""
    context = _sync_context()
    orchestrator = _orchestrator(context)

    with patch(
        "contextd.platform.sync.orchestrator.get_db_context",
        return_value=_DbContext(SimpleNamespace()),
    ), patch(
        "contextd.platform.sync.orchestrator.sync_cursor_service.create_or_update_cursor",
        AsyncMock(side_effect=RuntimeError("database unavailable")),
    ):
        with pytest.raises(SyncFailureError, match="Failed to save cursor data"):
            await orchestrator._save_cursor_data()

    assert any("Failed to save cursor data" in message for message in context.logger.messages)


@pytest.mark.asyncio
async def test_save_cursor_data_respects_skip_cursor_updates() -> None:
    """Replay/admin execution configs can explicitly disable cursor advancement."""
    context = _sync_context()
    context.execution_config = SimpleNamespace(skip_cursor_updates=True)
    orchestrator = _orchestrator(context)

    with patch(
        "contextd.platform.sync.orchestrator.sync_cursor_service.create_or_update_cursor",
        AsyncMock(),
    ) as create_or_update_cursor:
        await orchestrator._save_cursor_data()

    create_or_update_cursor.assert_not_awaited()
    assert any("Skipping cursor update" in message for message in context.logger.messages)
