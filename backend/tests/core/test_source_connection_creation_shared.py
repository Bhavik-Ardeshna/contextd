"""Tests for shared source connection creation helpers."""

from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.core import source_connection_creation_shared  # noqa: E402
from contextd.core.source_connection_service import SourceConnectionService  # noqa: E402


class LoggerStub:
    def info(self, *_args, **_kwargs) -> None:
        pass


def _ctx():
    return SimpleNamespace(logger=LoggerStub())


@pytest.mark.asyncio
async def test_get_and_validate_source_raises_for_missing_source(monkeypatch) -> None:
    service = SourceConnectionService()

    async def fake_get_by_short_name(_db, *, short_name):
        assert short_name == "missing"
        return None

    monkeypatch.setattr(
        source_connection_creation_shared.crud.source,
        "get_by_short_name",
        fake_get_by_short_name,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service._get_and_validate_source(object(), "missing")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Source 'missing' not found"


@pytest.mark.asyncio
async def test_handle_sync_creation_skips_when_schedule_and_immediate_sync_are_disabled(
    monkeypatch,
) -> None:
    service = SourceConnectionService()
    monkeypatch.setattr(service, "_get_source_class", lambda _class_name: type("Source", (), {}))

    obj_in = SimpleNamespace(
        name="GitHub",
        schedule=SimpleNamespace(cron=None),
        sync_immediately=False,
    )
    source = SimpleNamespace(
        class_name="GithubSource",
        short_name="github",
        supports_continuous=False,
    )
    uow = SimpleNamespace(session=object())

    result = await service._handle_sync_creation(
        uow,
        obj_in,
        source,
        connection_id=uuid4(),
        collection_id=uuid4(),
        collection_readable_id="engineering",
        ctx=_ctx(),
    )

    assert result == (None, None, None)
