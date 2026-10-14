"""Tests for source connection CRUD helpers."""

from __future__ import annotations

import os
from datetime import datetime, timezone
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

from contextd.core import source_connection_crud_operations  # noqa: E402
from contextd.core.shared_models import SourceConnectionStatus  # noqa: E402
from contextd.core.source_connection_service import SourceConnectionService  # noqa: E402
from contextd.schemas.source_connection import AuthenticationMethod  # noqa: E402


def _ctx():
    return SimpleNamespace()


@pytest.mark.asyncio
async def test_get_requires_existing_source_connection(monkeypatch) -> None:
    service = SourceConnectionService()
    source_connection_id = uuid4()

    async def fake_get(_db, *, id, ctx):
        assert id == source_connection_id
        assert ctx is not None
        return None

    monkeypatch.setattr(source_connection_crud_operations.crud.source_connection, "get", fake_get)

    with pytest.raises(HTTPException) as exc_info:
        await service.get(object(), id=source_connection_id, ctx=_ctx())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Source connection not found"


@pytest.mark.asyncio
async def test_list_maps_stats_to_source_connection_items(monkeypatch) -> None:
    service = SourceConnectionService()
    source_connection_id = uuid4()
    now = datetime.now(timezone.utc)

    async def fake_get_multi_with_stats(_db, *, ctx, collection_id, skip, limit):
        assert ctx is not None
        assert collection_id == "engineering"
        assert skip == 5
        assert limit == 10
        return [
            {
                "id": source_connection_id,
                "name": "GitHub",
                "short_name": "github",
                "readable_collection_id": "engineering",
                "created_at": now,
                "modified_at": now,
                "is_authenticated": True,
                "authentication_method": "direct",
                "entity_count": 42,
                "is_active": True,
                "last_job": {"status": "running"},
            }
        ]

    monkeypatch.setattr(
        source_connection_crud_operations.crud.source_connection,
        "get_multi_with_stats",
        fake_get_multi_with_stats,
    )

    items = await service.list(
        object(),
        ctx=_ctx(),
        readable_collection_id="engineering",
        skip=5,
        limit=10,
    )

    assert len(items) == 1
    assert items[0].id == source_connection_id
    assert items[0].entity_count == 42
    assert items[0].auth_method == AuthenticationMethod.DIRECT
    assert items[0].status == SourceConnectionStatus.SYNCING
