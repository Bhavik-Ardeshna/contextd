"""Tests for graph search endpoint helpers."""

from __future__ import annotations

import os

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.api.v1.endpoints.graph_chat_graph_search import (  # noqa: E402
    build_graph_search_response,
)
from contextd.search.operations.graph_search import GraphSearch  # noqa: E402


class TraversalResultStub:
    start_node_ids = ["n1"]
    stats = {"node_count": 1}

    def to_dict(self) -> dict:
        return {
            "nodes": [{"node_id": "n1"}],
            "edges": [{"from_node_id": "n1", "to_node_id": "n2"}],
        }


def test_build_graph_search_response_includes_edges_when_requested() -> None:
    response = build_graph_search_response(
        traversal_result=TraversalResultStub(),
        search_results=[{"node_id": "n1", "score": 0.9}],
        include_edges=True,
    )

    assert response.nodes == [{"node_id": "n1"}]
    assert response.edges == [{"from_node_id": "n1", "to_node_id": "n2"}]
    assert response.search_results == [{"node_id": "n1", "score": 0.9}]
    assert response.start_node_ids == ["n1"]
    assert response.stats == {"node_count": 1}


def test_build_graph_search_response_can_return_nodes_only() -> None:
    response = build_graph_search_response(
        traversal_result=TraversalResultStub(),
        search_results=[],
        include_edges=False,
    )

    assert response.nodes == [{"node_id": "n1"}]
    assert response.edges == []


def test_build_graph_search_response_handles_empty_traversal() -> None:
    response = build_graph_search_response(
        traversal_result=None,
        search_results=[{"node_id": "seed"}],
        include_edges=True,
    )

    assert response.nodes == []
    assert response.edges == []
    assert response.search_results == [{"node_id": "seed"}]
    assert response.start_node_ids == []
    assert response.stats == {}


def test_graph_search_default_keeps_low_scoring_fulltext_matches() -> None:
    search = GraphSearch(
        collection_id="00000000-0000-0000-0000-000000000001",
        organization_id="00000000-0000-0000-0000-000000000002",
    )

    assert search.min_score == 0.0


def test_graph_search_filters_fulltext_results_by_connector() -> None:
    search = GraphSearch(
        collection_id="00000000-0000-0000-0000-000000000001",
        organization_id="00000000-0000-0000-0000-000000000002",
        source_type_filter="gmail",
    )

    filtered = search._filter_by_source_type(
        [
            {"node_id": "msg_1", "properties": {"source_type": "gmail"}},
            {"node_id": "row_1", "properties": {"source_type": "postgresql"}},
            {"node_id": "msg_2", "source_type": "GMAIL", "properties": {}},
        ]
    )

    assert [result["node_id"] for result in filtered] == ["msg_1", "msg_2"]
