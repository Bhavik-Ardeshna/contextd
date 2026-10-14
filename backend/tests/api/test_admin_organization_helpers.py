"""Tests for admin organization helper functions."""

from __future__ import annotations

import os
from types import SimpleNamespace

from sqlalchemy import select

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.api.v1.endpoints.admin_organization_helpers import (  # noqa: E402
    build_sort_subqueries,
    get_sort_column,
)
from contextd.models.organization import Organization  # noqa: E402
from contextd.models.organization_billing import OrganizationBilling  # noqa: E402


def test_get_sort_column_maps_known_columns_and_defaults() -> None:
    assert get_sort_column("billing_plan", {}) is OrganizationBilling.billing_plan
    assert get_sort_column("name", {}) is Organization.name
    assert get_sort_column("missing", {}) is Organization.created_at


def test_get_sort_column_uses_requested_subquery_columns() -> None:
    user_count = object()
    source_connection_count = object()
    last_active_at = object()

    assert (
        get_sort_column(
            "user_count",
            {"user_count_subq": SimpleNamespace(c=SimpleNamespace(user_count=user_count))},
        )
        is user_count
    )
    assert (
        get_sort_column(
            "source_connection_count",
            {
                "source_connection_count_subq": SimpleNamespace(
                    c=SimpleNamespace(source_connection_count=source_connection_count)
                )
            },
        )
        is source_connection_count
    )
    assert (
        get_sort_column(
            "last_active_at",
            {"max_active_subq": SimpleNamespace(c=SimpleNamespace(max_last_active=last_active_at))},
        )
        is last_active_at
    )


def test_build_sort_subqueries_adds_expected_subquery_key() -> None:
    _, subqueries = build_sort_subqueries(select(Organization), "user_count")

    assert "user_count_subq" in subqueries


def test_admin_router_registers_organization_routes() -> None:
    from contextd.api.v1.endpoints import admin

    route_paths = {route.path for route in admin.router.routes}

    assert "/organizations" in route_paths
    assert "/organizations/{organization_id}/add-self" in route_paths
    assert "/organizations/{organization_id}/upgrade-to-enterprise" in route_paths
    assert "/organizations/create-enterprise" in route_paths
