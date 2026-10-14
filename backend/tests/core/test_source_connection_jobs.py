"""Tests for source connection job helpers."""

from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.core import source_connection_jobs  # noqa: E402
from contextd.core.source_connection_service import SourceConnectionService  # noqa: E402
from contextd.core.sync_service import SyncService  # noqa: E402


class LoggerStub:
    def info(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass


def _ctx():
    return SimpleNamespace(logger=LoggerStub())


@pytest.mark.asyncio
async def test_get_jobs_returns_empty_for_connection_without_sync(monkeypatch) -> None:
    service = SourceConnectionService()
    source_connection_id = uuid4()

    async def fake_get(_db, *, id, ctx):
        assert id == source_connection_id
        assert ctx is not None
        return SimpleNamespace(id=source_connection_id, sync_id=None)

    monkeypatch.setattr(source_connection_jobs.crud.source_connection, "get", fake_get)

    assert await service.get_jobs(object(), id=source_connection_id, ctx=_ctx()) == []


@pytest.mark.asyncio
async def test_cancel_job_requires_connection_sync(monkeypatch) -> None:
    service = SourceConnectionService()
    source_connection_id = uuid4()

    async def fake_get(_db, *, id, ctx):
        assert id == source_connection_id
        assert ctx is not None
        return SimpleNamespace(id=source_connection_id, sync_id=None)

    monkeypatch.setattr(source_connection_jobs.crud.source_connection, "get", fake_get)

    with pytest.raises(HTTPException) as exc_info:
        await service.cancel_job(
            object(),
            source_connection_id=source_connection_id,
            job_id=uuid4(),
            ctx=_ctx(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Source connection has no associated sync"


@pytest.mark.asyncio
async def test_list_all_sync_jobs_uses_repo_scope_and_pagination(monkeypatch) -> None:
    service = SyncService()
    seen = {}

    async def fake_get_all_jobs(_db, *, skip, limit, status):
        seen.update({"skip": skip, "limit": limit, "status": status})
        return ["job"]

    monkeypatch.setattr(source_connection_jobs.crud.sync_job, "get_all_jobs", fake_get_all_jobs)

    assert await service.list_sync_jobs(
        object(),
        ctx=_ctx(),
        skip=3,
        limit=7,
        status=["failed"],
    ) == ["job"]
    assert seen == {"skip": 3, "limit": 7, "status": ["FAILED"]}


@pytest.mark.asyncio
async def test_list_sync_jobs_uses_sync_scope_and_pagination(monkeypatch) -> None:
    service = SyncService()
    sync_id = uuid4()
    seen = {}

    async def fake_get_all_by_sync_id(_db, *, sync_id: UUID, skip, limit, status):
        seen.update({"sync_id": sync_id, "skip": skip, "limit": limit, "status": status})
        return ["job"]

    monkeypatch.setattr(
        source_connection_jobs.crud.sync_job,
        "get_all_by_sync_id",
        fake_get_all_by_sync_id,
    )

    assert await service.list_sync_jobs(
        object(),
        ctx=_ctx(),
        sync_id=sync_id,
        skip=2,
        limit=5,
        status=["running"],
    ) == ["job"]
    assert seen == {"sync_id": sync_id, "skip": 2, "limit": 5, "status": ["RUNNING"]}
