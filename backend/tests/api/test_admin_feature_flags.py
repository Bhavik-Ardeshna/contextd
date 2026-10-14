"""Tests for admin feature flag helpers."""

from __future__ import annotations

import os

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.api.v1.endpoints.admin_feature_flags import (  # noqa: E402
    serialize_available_feature_flags,
)
from contextd.core.shared_models import FeatureFlag  # noqa: E402


def test_serialize_available_feature_flags_matches_enum_contract() -> None:
    assert serialize_available_feature_flags() == [
        {"name": flag.name, "value": flag.value} for flag in FeatureFlag
    ]


def test_admin_router_registers_feature_flag_routes() -> None:
    from contextd.api.v1.endpoints import admin

    route_paths = {route.path for route in admin.router.routes}

    assert "/feature-flags" in route_paths
    assert "/organizations/{organization_id}/feature-flags/{flag}/enable" in route_paths
    assert "/organizations/{organization_id}/feature-flags/{flag}/disable" in route_paths
