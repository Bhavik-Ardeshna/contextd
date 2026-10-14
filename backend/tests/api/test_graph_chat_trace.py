"""Tests for graph chat trace-neighborhood helpers."""

from __future__ import annotations

import os

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.api.v1.endpoints.graph_chat_schemas import (  # noqa: E402
    NeighborhoodRequest,
)
from contextd.api.v1.endpoints.graph_chat_trace import (  # noqa: E402
    _build_neighborhood_response,
    _build_sample_query_plan,
    _build_samples,
    _clean_trace_properties,
    _parse_props,
)


def test_build_sample_query_plan_sanitizes_filter_key_and_clamps_limits() -> None:
    query, params, depth, neighbor_cap = _build_sample_query_plan(
        NeighborhoodRequest.model_construct(
            node_type="Person",
            filter_key="specialty`) MATCH (x",
            filter_value="running",
            sample_limit=50,
            depth=10,
            neighbor_cap=900,
        ),
        organization_id="org_1",
    )

    assert "specialtyMATCHx" in query
    assert "$filter_value" in query
    assert params == {
        "organization_id": "org_1",
        "node_type": "Person",
        "sample_limit": 25,
        "filter_value": "running",
    }
    assert depth == 3
    assert neighbor_cap == 500


def test_parse_and_clean_trace_properties_are_payload_safe() -> None:
    assert _parse_props('{"name": "Ada"}') == {"name": "Ada"}
    assert _parse_props("{bad json") == {}
    assert _clean_trace_properties(
        {
            "name": "Ada",
            "_raw": "drop",
            "empty": "",
            "large": "x" * 2001,
            "ok": ["one"],
        }
    ) == {"name": "Ada", "ok": ["one"]}


def test_build_samples_skips_records_without_node_id() -> None:
    samples, sample_ids = _build_samples(
        [
            {"node_id": "n1", "node_type": "Person", "properties": '{"name": "Ada"}'},
            {"node_type": "Person", "properties": "{}"},
        ],
        lambda record: record,
    )

    assert sample_ids == ["n1"]
    assert samples == [
        {
            "node_id": "n1",
            "node_type": "Person",
            "name": "Ada",
            "properties": {"name": "Ada"},
        }
    ]


def test_build_neighborhood_response_filters_edges_and_properties() -> None:
    response = _build_neighborhood_response(
        samples=[{"node_id": "n1"}],
        sample_ids=["n1"],
        depth=2,
        row={
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "Person",
                    "properties": {
                        "name": "Ada",
                        "_internal": "drop",
                        "blob": "x" * 2001,
                    },
                },
                {"node_id": "n2", "node_type": "Team", "properties": {"title": "Core"}},
            ],
            "edges": [
                {"source_id": "n1", "target_id": "n2", "relationship_type": None},
                {"source_id": "n1", "target_id": "missing", "relationship_type": "IGNORED"},
                {"source_id": "n1", "target_id": "n2", "relationship_type": None},
            ],
        },
    )

    assert [node["node_id"] for node in response.nodes] == ["n1", "n2"]
    assert response.nodes[0]["properties"] == {"name": "Ada"}
    assert response.nodes[0]["is_seed"] is True
    assert response.edges == [
        {"source_id": "n1", "target_id": "n2", "relationship_type": "RELATES_TO"}
    ]
    assert response.stats == {
        "sample_count": 1,
        "depth": 2,
        "node_count": 2,
        "edge_count": 1,
    }
