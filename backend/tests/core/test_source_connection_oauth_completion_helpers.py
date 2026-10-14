"""Tests for source connection OAuth completion helpers."""

from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.core import source_connection_oauth_completion_helpers  # noqa: E402
from contextd.core.source_connection_service_helpers import source_connection_helpers  # noqa: E402


class LoggerStub:
    def info(self, *_args, **_kwargs) -> None:
        pass


def _ctx():
    return SimpleNamespace(logger=LoggerStub())


@pytest.mark.asyncio
async def test_get_connection_for_source_connection_requires_connection_id() -> None:
    source_connection = SimpleNamespace(id=uuid4(), connection_id=None)

    with pytest.raises(ValueError) as exc_info:
        await source_connection_helpers.get_connection_for_source_connection(
            object(), source_connection, _ctx()
        )

    assert "has no connection_id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_connection_for_source_connection_rejects_missing_connection(monkeypatch) -> None:
    connection_id = uuid4()
    source_connection = SimpleNamespace(id=uuid4(), connection_id=connection_id)

    async def fake_get(*, db, id, ctx):
        assert db is not None
        assert id == connection_id
        assert ctx is not None
        return None

    monkeypatch.setattr(
        source_connection_oauth_completion_helpers.crud.connection,
        "get",
        fake_get,
    )

    with pytest.raises(ValueError) as exc_info:
        await source_connection_helpers.get_connection_for_source_connection(
            object(), source_connection, _ctx()
        )

    assert f"Connection {connection_id} not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_complete_oauth2_connection_updates_salesforce_instance_url(monkeypatch) -> None:
    captured = {}
    init_session = SimpleNamespace(
        id=uuid4(),
        short_name="salesforce",
        payload={},
        overrides={},
    )

    async def fake_get_by_short_name(_db, *, short_name):
        assert short_name == "salesforce"
        return SimpleNamespace(
            name="Salesforce",
            short_name="salesforce",
            auth_config_class="SalesforceAuthConfig",
        )

    async def fake_common(
        db,
        source,
        source_conn_shell,
        init_session_id,
        payload,
        auth_fields,
        auth_method_to_save,
        is_oauth1,
        ctx,
    ):
        captured.update(
            {
                "db": db,
                "source": source,
                "source_conn_shell": source_conn_shell,
                "init_session_id": init_session_id,
                "payload": payload,
                "auth_fields": auth_fields,
                "auth_method_to_save": auth_method_to_save,
                "is_oauth1": is_oauth1,
                "ctx": ctx,
            }
        )
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(
        source_connection_oauth_completion_helpers.crud.source,
        "get_by_short_name",
        fake_get_by_short_name,
    )
    monkeypatch.setattr(
        source_connection_helpers,
        "_complete_oauth_connection_common",
        fake_common,
    )

    token_response = SimpleNamespace(
        model_dump=lambda: {
            "access_token": "token",
            "instance_url": "https://example.my.salesforce.com",
        }
    )

    await source_connection_helpers.complete_oauth2_connection(
        object(),
        SimpleNamespace(readable_collection_id="engineering"),
        init_session,
        token_response,
        _ctx(),
    )

    assert captured["payload"]["config"]["instance_url"] == "example.my.salesforce.com"
    assert captured["auth_fields"]["access_token"] == "token"
    assert captured["is_oauth1"] is False
