"""Tests for graph explorer helper normalization."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

class _Auth0Stub:
    def __init__(self, *args, **kwargs) -> None:
        pass


sys.modules.setdefault("fastapi_auth0", SimpleNamespace(Auth0=_Auth0Stub, Auth0User=object))

from contextd.api.v1.endpoints.graph import _dedupe_logical_edges, _query_trace_decision_payload


def test_dedupe_logical_edges_collapses_reciprocal_related_to_rows() -> None:
    edges = [
        {
            "edge_id": "edge_a",
            "source_node_id": "public.studios:479",
            "target_node_id": "public.trainers:486",
            "relationship_type": "RELATED_TO",
            "properties": {"relation_type": "related_to"},
        },
        {
            "edge_id": "edge_b",
            "source_node_id": "public.trainers:486",
            "target_node_id": "public.studios:479",
            "relationship_type": "RELATED_TO",
            "properties": {"relation_type": "related_to"},
        },
    ]

    assert [edge["edge_id"] for edge in _dedupe_logical_edges(edges)] == ["edge_a"]


def test_dedupe_logical_edges_keeps_different_relationship_semantics() -> None:
    edges = [
        {
            "edge_id": "edge_a",
            "source_node_id": "a",
            "target_node_id": "b",
            "relationship_type": "RELATED_TO",
            "properties": {"relation_type": "home_studio"},
        },
        {
            "edge_id": "edge_b",
            "source_node_id": "b",
            "target_node_id": "a",
            "relationship_type": "RELATED_TO",
            "properties": {"relation_type": "class_location"},
        },
    ]

    assert [edge["edge_id"] for edge in _dedupe_logical_edges(edges)] == ["edge_a", "edge_b"]


def test_query_trace_payload_is_renderable_as_node_decision_audit() -> None:
    trace = SimpleNamespace(
        id="trace-row",
        query_id="qry_123",
        query_text="show the strongest relationships",
        recipe="rrf",
        path_used="graph_search",
        status="completed",
        decision_tree={
            "steps": [
                {"key": "parse_intent", "label": "Parse intent", "status": "done", "output": {"recipe": "rrf"}},
                {"key": "assemble_packet", "label": "Assemble packet", "status": "done", "output": {"token_estimate": 128}},
            ],
            "metrics": {"decisions": 1, "query_traces": 1, "drift_severity": "warning"},
            "feedback": {"target_weight": 1.2},
        },
        drift_context={"severity": "warning"},
        retrieved_node_ids=["public.studios:488"],
        retrieved_edge_ids=["edge_a"],
        token_estimate=128,
        latency_ms=4100,
        created_at=datetime(2026, 5, 6, 12, 0, 0),
    )

    payload = _query_trace_decision_payload(trace)

    assert payload["decision_type"] == "query_trace"
    assert payload["trace_kind"] == "query_decision_trace"
    assert payload["affected_refs"] == ["public.studios:488"]
    assert payload["decision_steps"] == 2
    assert len(payload["steps"]) == 2
    assert payload["steps"][1]["output"]["token_estimate"] == 128
    assert payload["metrics"]["query_traces"] == 1
    assert payload["drift_severity"] == "warning"
    assert payload["subject"] == "show the strongest relationships"
