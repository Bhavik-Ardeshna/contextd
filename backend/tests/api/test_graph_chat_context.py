"""Tests for graph chat context helpers."""

from __future__ import annotations

import os

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.api.v1.endpoints.graph_chat_context import (  # noqa: E402
    _empty_context_response,
    _node_ids_from_search_results,
)


def test_node_ids_from_search_results_skips_missing_ids() -> None:
    assert _node_ids_from_search_results(
        [
            {"node_id": "n1"},
            {"entity_id": "missing"},
            {"node_id": ""},
            {"node_id": "n2"},
        ]
    ) == ["n1", "n2"]


def test_empty_context_response_matches_public_contract() -> None:
    response = _empty_context_response()

    assert response.context == "No relevant information found in the knowledge graph."
    assert response.token_estimate == 10
    assert response.node_count == 0
    assert response.edge_count == 0
    assert response.truncated is False
    assert response.search_results == []
