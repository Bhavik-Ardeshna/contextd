"""Tests for source connection persistence helpers."""

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

from contextd.core import source_connection_persistence_helpers  # noqa: E402
from contextd.core.shared_models import ConnectionStatus  # noqa: E402
from contextd.core.source_connection_service_helpers import source_connection_helpers  # noqa: E402
from contextd.models.integration_credential import IntegrationType  # noqa: E402
from contextd.schemas.source_connection import AuthenticationMethod, OAuthType  # noqa: E402


def _ctx():
    return SimpleNamespace(organization=SimpleNamespace(id=uuid4()))


@pytest.mark.asyncio
async def test_get_collection_requires_collection_id() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await source_connection_helpers.get_collection(object(), "", _ctx())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Collection is required"


@pytest.mark.asyncio
async def test_create_connection_builds_active_source_connection(monkeypatch) -> None:
    captured = {}
    credential_id = uuid4()

    async def fake_create(db, *, obj_in, ctx, uow):
        captured.update({"db": db, "obj_in": obj_in, "ctx": ctx, "uow": uow})
        return obj_in

    monkeypatch.setattr(
        source_connection_persistence_helpers.crud.connection,
        "create",
        fake_create,
    )

    source = SimpleNamespace(short_name="github")
    result = await source_connection_helpers.create_connection(
        object(),
        "GitHub",
        source,
        credential_id,
        _ctx(),
        object(),
    )

    assert result.short_name == "github"
    assert result.integration_type == IntegrationType.SOURCE
    assert result.integration_credential_id == credential_id
    assert result.status == ConnectionStatus.ACTIVE


@pytest.mark.asyncio
async def test_create_integration_credential_encrypts_oauth_credentials(monkeypatch) -> None:
    captured = {}
    ctx = _ctx()

    async def fake_create(db, *, obj_in, ctx, uow):
        captured.update({"db": db, "obj_in": obj_in, "ctx": ctx, "uow": uow})
        return obj_in

    monkeypatch.setattr(
        source_connection_persistence_helpers.credentials,
        "encrypt",
        lambda value: f"encrypted:{value['access_token']}",
    )
    monkeypatch.setattr(
        source_connection_persistence_helpers.crud.integration_credential,
        "create",
        fake_create,
    )

    source = SimpleNamespace(
        name="GitHub",
        short_name="github",
        auth_config_class="GitHubAuthConfig",
        oauth_type=OAuthType.WITH_REFRESH,
    )

    result = await source_connection_helpers.create_integration_credential(
        object(),
        source,
        {"access_token": "token"},
        ctx,
        object(),
        auth_method=AuthenticationMethod.OAUTH_TOKEN,
    )

    assert result.name == f"GitHub - {ctx.organization.id}"
    assert result.integration_short_name == "github"
    assert result.integration_type == IntegrationType.SOURCE
    assert result.authentication_method == AuthenticationMethod.OAUTH_TOKEN
    assert result.oauth_type == OAuthType.WITH_REFRESH
    assert result.encrypted_credentials == "encrypted:token"


@pytest.mark.asyncio
async def test_create_source_connection_includes_auth_provider_fields(monkeypatch) -> None:
    captured = {}
    connection_id = uuid4()
    sync_id = uuid4()

    async def fake_create(db, *, obj_in, ctx, uow):
        captured.update({"db": db, "obj_in": obj_in, "ctx": ctx, "uow": uow})
        return obj_in

    monkeypatch.setattr(
        source_connection_persistence_helpers.crud.source_connection,
        "create",
        fake_create,
    )

    obj_in = SimpleNamespace(
        name="GitHub",
        description="Engineering repos",
        short_name="github",
    )

    result = await source_connection_helpers.create_source_connection(
        object(),
        obj_in,
        connection_id,
        "engineering",
        sync_id,
        {"repository": "contextd"},
        True,
        _ctx(),
        object(),
        auth_provider_id="provider",
        auth_provider_config={"workspace": "eng"},
    )

    assert result["name"] == "GitHub"
    assert result["short_name"] == "github"
    assert result["connection_id"] == connection_id
    assert result["readable_collection_id"] == "engineering"
    assert result["sync_id"] == sync_id
    assert result["is_authenticated"] is True
    assert result["readable_auth_provider_id"] == "provider"
    assert result["auth_provider_config"] == {"workspace": "eng"}
