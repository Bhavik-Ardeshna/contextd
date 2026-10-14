"""Tests for shared admin access helpers."""

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

from contextd.api.v1.endpoints.admin_access import (  # noqa: E402
    require_admin,
    require_admin_permission,
)
from contextd.core.shared_models import FeatureFlag  # noqa: E402


class LoggerStub:
    def debug(self, *_args, **_kwargs) -> None:
        pass

    def info(self, *_args, **_kwargs) -> None:
        pass


def _ctx(**overrides):
    base = {
        "has_user_context": False,
        "user": SimpleNamespace(
            is_admin=False,
            is_superuser=False,
            email="user@contextd.local",
        ),
        "is_api_key_auth": False,
        "has_feature": lambda _feature: False,
        "logger": LoggerStub(),
        "organization": SimpleNamespace(id=uuid4()),
        "auth_method": SimpleNamespace(value="api_key"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_require_admin_allows_admin_or_superuser() -> None:
    require_admin(
        _ctx(
            has_user_context=True,
            user=SimpleNamespace(
                is_admin=True,
                is_superuser=False,
                email="admin@contextd.local",
            ),
        )
    )
    require_admin(
        _ctx(
            has_user_context=True,
            user=SimpleNamespace(
                is_admin=False,
                is_superuser=True,
                email="super@contextd.local",
            ),
        )
    )


def test_require_admin_rejects_non_admin_user() -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_admin(_ctx(has_user_context=True))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Admin access required"


def test_require_admin_permission_allows_scoped_api_key() -> None:
    require_admin_permission(
        _ctx(
            is_api_key_auth=True,
            has_feature=lambda feature: feature == FeatureFlag.API_KEY_ADMIN_SYNC,
        ),
        FeatureFlag.API_KEY_ADMIN_SYNC,
    )


def test_require_admin_permission_names_required_api_key_scope() -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_admin_permission(
            _ctx(is_api_key_auth=True),
            FeatureFlag.API_KEY_ADMIN_SYNC,
        )

    assert exc_info.value.status_code == 403
    assert (
        exc_info.value.detail
        == "API key requires 'api_key_admin_sync' feature flag for admin access"
    )


def test_admin_router_registers_search_route() -> None:
    from contextd.api.v1.endpoints import admin

    route_paths = {route.path for route in admin.router.routes}

    assert "/collections/{readable_id}/search" in route_paths


def test_admin_router_registers_sync_routes() -> None:
    from contextd.api.v1.endpoints import admin

    route_paths = {route.path for route in admin.router.routes}

    assert "/resync/{sync_id}" in route_paths
    assert "/syncs" in route_paths
    assert "/sync-jobs/{job_id}/cancel" in route_paths
    assert "/syncs/{sync_id}/cancel" in route_paths
    assert "/syncs/{sync_id}" in route_paths
