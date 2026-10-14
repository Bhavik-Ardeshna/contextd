"""Tests for graph chat helper modules."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.api.v1.endpoints import graph_chat  # noqa: E402
from contextd.api.v1.endpoints.graph_chat_presenters import (  # noqa: E402
    _build_entity_references,
    _build_subgraph,
    _chart_data_snippet_for_llm_prompt,
    _sanitize_chart_data,
)
from contextd.api.v1.endpoints.graph_chat_retrieval import (  # noqa: E402
    _parse_connector_ignoring_search,
)
from contextd.api.v1.endpoints.graph_chat_schemas import (  # noqa: E402
    ChatRequest,
    GraphSearchRequest,
)


def test_graph_chat_endpoint_keeps_schema_import_surface() -> None:
    assert graph_chat.ChatRequest is ChatRequest
    assert graph_chat.router.routes


def test_graph_search_schema_enforces_search_limit_bounds() -> None:
    with pytest.raises(ValidationError):
        GraphSearchRequest(query="find customers", search_limit=0)


def test_chart_data_snippet_serializes_only_chart_specs() -> None:
    snippet = _chart_data_snippet_for_llm_prompt(
        [
            {
                "type": "chart",
                "title": "Orders",
                "chart_type": "bar",
                "data": [{"label": "open", "value": 3}, "skip"],
            },
            {"type": "note", "title": "ignored"},
        ]
    )

    rows = [json.loads(line) for line in snippet.splitlines()]
    assert rows == [
        {
            "title": "Orders",
            "chart_type": "bar",
            "data": [{"label": "open", "value": 3}],
        }
    ]


def test_sanitize_chart_data_converts_values_to_json_safe_scalars() -> None:
    class CustomValue:
        def __str__(self) -> str:
            return "custom"

    assert _sanitize_chart_data([{"count": CustomValue()}, []]) == [{"count": "custom"}]


def test_build_entity_references_prefers_search_results_and_skips_rows() -> None:
    refs = _build_entity_references(
        [
            {
                "node_id": "public.tasks:1",
                "name": "Task 1",
                "node_type": "Unknown",
                "payload": {"status": "open", "description": "Fix API"},
                "score": 0.9,
            }
        ],
        [
            SimpleNamespace(
                node_id="public.tasks:1",
                node_type="Task",
                name="Task 1 duplicate",
                properties={},
            ),
            SimpleNamespace(
                node_id="row_0",
                node_type="Row",
                name="Aggregate row",
                properties={},
            ),
            SimpleNamespace(
                node_id="public.people:2",
                node_type="PersonEntity",
                name="Ada",
                properties={"priority": "high", "_internal": "drop"},
            ),
        ],
        organization_id="org_1",
    )

    assert [ref.node_id for ref in refs] == ["public.tasks:1", "public.people:2"]
    assert refs[0].entity_type == "Task"
    assert refs[0].properties == {"status": "open", "description": "Fix API"}
    assert refs[1].source == "person"


def test_build_subgraph_filters_oversized_and_internal_properties() -> None:
    traversal_result = SimpleNamespace(
        nodes=[
            SimpleNamespace(
                node_id="public.tasks:1",
                node_type="Unknown",
                name="Task 1",
                depth=0,
                properties={
                    "name": "Task 1",
                    "status": "open",
                    "_private": "drop",
                    "blob": "x" * 2001,
                },
            )
        ],
        edges=[
            SimpleNamespace(
                from_node_id="public.tasks:1",
                to_node_id="public.people:2",
                relationship_type="ASSIGNED_TO",
            )
        ],
    )

    subgraph = _build_subgraph(
        traversal_result,
        [{"node_id": "public.tasks:1"}],
    )

    assert subgraph.center_node_ids == ["public.tasks:1"]
    assert subgraph.nodes[0].node_type == "Task"
    assert subgraph.nodes[0].properties == {"name": "Task 1", "status": "open"}
    assert subgraph.nodes[0].is_primary is True
    assert subgraph.edges[0].label == "assigned to"


def test_parse_connector_ignores_search_directive() -> None:
    assert _parse_connector_ignoring_search("@search show revenue @gmail") == "gmail"
    assert _parse_connector_ignoring_search("@search show revenue") is None
