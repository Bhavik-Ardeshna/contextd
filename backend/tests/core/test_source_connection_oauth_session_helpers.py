"""Tests for source connection OAuth session helpers."""

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

from contextd.core import source_connection_oauth_session_helpers  # noqa: E402
from contextd.core.source_connection_service_helpers import source_connection_helpers  # noqa: E402


def _ctx():
    return SimpleNamespace()


@pytest.mark.asyncio
async def test_create_proxy_url_uses_redirect_session_code(monkeypatch) -> None:
    redirect_session_id = uuid4()

    async def fake_generate_unique_code(_db, *, length):
        assert length == 8
        return "abc123xy"

    async def fake_create(_db, *, code, final_url, expires_at, ctx, uow):
        assert code == "abc123xy"
        assert final_url == "https://provider.example/oauth"
        assert expires_at is not None
        assert ctx is not None
        assert uow is None
        return SimpleNamespace(id=redirect_session_id)

    monkeypatch.setattr(
        source_connection_oauth_session_helpers.redirect_session,
        "generate_unique_code",
        fake_generate_unique_code,
    )
    monkeypatch.setattr(
        source_connection_oauth_session_helpers.redirect_session,
        "create",
        fake_create,
    )

    proxy_url, _expires_at, returned_id = await source_connection_helpers.create_proxy_url(
        object(),
        "https://provider.example/oauth",
        _ctx(),
    )

    assert proxy_url.endswith("/source-connections/authorize/abc123xy")
    assert returned_id == redirect_session_id


@pytest.mark.asyncio
async def test_exchange_oauth2_code_passes_template_and_pkce_overrides(monkeypatch) -> None:
    captured = {}

    async def fake_exchange_authorization_code_for_token_with_redirect(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(access_token="token")

    monkeypatch.setattr(
        source_connection_oauth_session_helpers.oauth2_service,
        "exchange_authorization_code_for_token_with_redirect",
        fake_exchange_authorization_code_for_token_with_redirect,
    )

    result = await source_connection_helpers.exchange_oauth2_code(
        "salesforce",
        "code",
        {
            "oauth_redirect_uri": "https://api.example/callback",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "template_configs": {"instance_url": "example.my.salesforce.com"},
            "code_verifier": "verifier",
        },
        _ctx(),
    )

    assert result.access_token == "token"
    assert captured["source_short_name"] == "salesforce"
    assert captured["code"] == "code"
    assert captured["redirect_uri"] == "https://api.example/callback"
    assert captured["client_id"] == "client-id"
    assert captured["client_secret"] == "client-secret"
    assert captured["template_configs"] == {"instance_url": "example.my.salesforce.com"}
    assert captured["code_verifier"] == "verifier"
