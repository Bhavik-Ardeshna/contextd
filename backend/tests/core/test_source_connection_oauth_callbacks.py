"""Tests for source connection OAuth callback helpers."""

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

from contextd.core import source_connection_oauth_callbacks  # noqa: E402
from contextd.core.source_connection_service import SourceConnectionService  # noqa: E402
from contextd.models.connection_init_session import ConnectionInitStatus  # noqa: E402


@pytest.mark.asyncio
async def test_oauth1_callback_requires_existing_session(monkeypatch) -> None:
    service = SourceConnectionService()

    async def fake_get_by_oauth_token_no_auth(_db, *, oauth_token):
        assert oauth_token == "request-token"
        return None

    monkeypatch.setattr(
        source_connection_oauth_callbacks.connection_init_session,
        "get_by_oauth_token_no_auth",
        fake_get_by_oauth_token_no_auth,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.complete_oauth1_callback(
            object(),
            oauth_token="request-token",
            oauth_verifier="verifier",
        )

    assert exc_info.value.status_code == 404
    assert "OAuth1 session not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_oauth2_callback_requires_existing_session(monkeypatch) -> None:
    service = SourceConnectionService()

    async def fake_get_by_state_no_auth(_db, *, state):
        assert state == "state-token"
        return None

    monkeypatch.setattr(
        source_connection_oauth_callbacks.connection_init_session,
        "get_by_state_no_auth",
        fake_get_by_state_no_auth,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.complete_oauth2_callback(object(), state="state-token", code="code")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "OAuth2 session not found or expired"


@pytest.mark.asyncio
async def test_oauth2_callback_rejects_non_pending_session(monkeypatch) -> None:
    service = SourceConnectionService()

    async def fake_get_by_state_no_auth(_db, *, state):
        assert state == "state-token"
        return SimpleNamespace(status=ConnectionInitStatus.COMPLETED)

    monkeypatch.setattr(
        source_connection_oauth_callbacks.connection_init_session,
        "get_by_state_no_auth",
        fake_get_by_state_no_auth,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.complete_oauth2_callback(object(), state="state-token", code="code")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "OAuth session already completed"
