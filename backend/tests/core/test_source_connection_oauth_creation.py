"""Tests for OAuth source connection creation helpers."""

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
from contextd.schemas.source_connection import OAuthBrowserAuthentication  # noqa: E402


def _ctx():
    return SimpleNamespace()


@pytest.mark.asyncio
async def test_oauth1_byoc_requires_consumer_credentials() -> None:
    service = SourceConnectionService()
    obj_in = SimpleNamespace(authentication=OAuthBrowserAuthentication())

    with pytest.raises(HTTPException) as exc_info:
        await service._create_with_oauth1_byoc(
            object(),
            obj_in=obj_in,
            oauth_settings=object(),
            ctx=_ctx(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "OAuth1 BYOC requires consumer_key and consumer_secret"


@pytest.mark.asyncio
async def test_oauth2_byoc_requires_client_credentials() -> None:
    service = SourceConnectionService()
    obj_in = SimpleNamespace(authentication=OAuthBrowserAuthentication())

    with pytest.raises(HTTPException) as exc_info:
        await service._create_with_oauth2_byoc(
            object(),
            obj_in=obj_in,
            oauth_settings=object(),
            ctx=_ctx(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "OAuth2 BYOC requires client_id and client_secret"
