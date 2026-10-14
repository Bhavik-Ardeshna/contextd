"""Tests for source connection validation helpers."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, Field

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.core import source_connection_validation_helpers  # noqa: E402
from contextd.core.source_connection_service_helpers import source_connection_helpers  # noqa: E402


class LoggerStub:
    def warning(self, *_args, **_kwargs) -> None:
        pass


class ExampleConfig(BaseModel):
    visible: str
    advanced: str | None = Field(
        None,
        title="Advanced",
        json_schema_extra={"feature_flag": "advanced_sources"},
    )


def _ctx(enabled_features=None):
    return SimpleNamespace(
        organization=SimpleNamespace(enabled_features=enabled_features or []),
        logger=LoggerStub(),
    )


def test_as_mapping_accepts_key_value_pairs() -> None:
    result = source_connection_helpers._as_mapping([{"key": "workspace", "value": "contextd"}])

    assert result == {"workspace": "contextd"}


@pytest.mark.asyncio
async def test_validate_auth_fields_requires_known_source(monkeypatch) -> None:
    async def fake_get_by_short_name(_db, *, short_name):
        assert short_name == "missing"
        return None

    monkeypatch.setattr(
        source_connection_validation_helpers.crud.source,
        "get_by_short_name",
        fake_get_by_short_name,
    )

    with pytest.raises(HTTPException) as exc_info:
        await source_connection_helpers.validate_auth_fields(object(), "missing", {}, _ctx())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Source 'missing' not found"


@pytest.mark.asyncio
async def test_validate_config_fields_rejects_disabled_feature_flag(monkeypatch) -> None:
    async def fake_get_by_short_name(_db, *, short_name):
        assert short_name == "github"
        return SimpleNamespace(config_class="ExampleConfig")

    monkeypatch.setattr(
        source_connection_validation_helpers.crud.source,
        "get_by_short_name",
        fake_get_by_short_name,
    )
    monkeypatch.setattr(
        source_connection_validation_helpers.resource_locator,
        "get_config",
        lambda _config_class: ExampleConfig,
    )

    with pytest.raises(HTTPException) as exc_info:
        await source_connection_helpers.validate_config_fields(
            object(),
            "github",
            {"visible": "ok", "advanced": "blocked"},
            _ctx(enabled_features=[]),
        )

    assert exc_info.value.status_code == 403
    assert "advanced_sources" in exc_info.value.detail


@pytest.mark.asyncio
async def test_validate_config_fields_returns_plain_dict_when_feature_enabled(
    monkeypatch,
) -> None:
    async def fake_get_by_short_name(_db, *, short_name):
        assert short_name == "github"
        return SimpleNamespace(config_class="ExampleConfig")

    monkeypatch.setattr(
        source_connection_validation_helpers.crud.source,
        "get_by_short_name",
        fake_get_by_short_name,
    )
    monkeypatch.setattr(
        source_connection_validation_helpers.resource_locator,
        "get_config",
        lambda _config_class: ExampleConfig,
    )

    result = await source_connection_helpers.validate_config_fields(
        object(),
        "github",
        {"visible": "ok", "advanced": "allowed"},
        _ctx(enabled_features=["advanced_sources"]),
    )

    assert result == {"visible": "ok", "advanced": "allowed"}
