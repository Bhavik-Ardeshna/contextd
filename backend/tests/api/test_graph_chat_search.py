"""Tests for deterministic graph chat search helpers."""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.api.v1.endpoints.graph_chat_search import (  # noqa: E402
    build_search_context_metadata,
)


def test_build_search_context_metadata_counts_context_surface() -> None:
    traversal_result = SimpleNamespace(nodes=[object(), object()], edges=[object()])

    metadata = build_search_context_metadata(
        traversal_result=traversal_result,
        search_results=[{"node_id": "n1"}, {"node_id": "n2"}],
        context_for_prompt="1234567890",
        max_depth=2,
    )

    assert metadata == {
        "node_count": 2,
        "edge_count": 1,
        "search_result_count": 2,
        "token_estimate": 3,
        "max_depth": 2,
    }


def test_build_search_context_metadata_handles_empty_traversal() -> None:
    metadata = build_search_context_metadata(
        traversal_result=None,
        search_results=[],
        context_for_prompt="empty",
        max_depth=1,
    )

    assert metadata["node_count"] == 0
    assert metadata["edge_count"] == 0
    assert metadata["search_result_count"] == 0
    assert metadata["token_estimate"] == 1
