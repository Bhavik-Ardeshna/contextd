"""Tests for graph chat synthesis helpers."""

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

from contextd.api.v1.endpoints.graph_chat_synthesis import (  # noqa: E402
    append_count_hint,
    append_notebook_context_sections,
    build_chart_specs_from_notebook,
    build_graph_chat_search_system_prompt,
    build_graph_chat_system_prompt,
    build_queries_trace,
    build_tool_errors_section,
)


def test_append_notebook_context_sections_adds_cypher_analysis_and_chart_data() -> None:
    state = SimpleNamespace(
        current_knowledge=[
            {"cypher": "MATCH (n) RETURN n", "row_count": 2},
            {
                "source": "p_agent",
                "summary": "Two open tasks.",
                "charts": [
                    {
                        "type": "chart",
                        "title": "Tasks by status",
                        "chart_type": "bar",
                        "data": [{"label": "open", "value": 2}],
                    }
                ],
            },
        ]
    )

    context, has_charts = append_notebook_context_sections("base", state)

    assert has_charts is True
    assert "How the data was obtained" in context
    assert "MATCH (n) RETURN n" in context
    assert "Two open tasks." in context
    assert "Tasks by status" in context
    assert '{"title": "Tasks by status"' in context
    assert "Data scope" in context


def test_append_count_hint_uses_chart_wording_when_chart_context_exists() -> None:
    chart_hint = append_count_hint("context", 3, has_p_agent_charts=True)

    assert "chart series and aggregates" in chart_hint
    assert "subgraph lists about 3 entities" in chart_hint
    assert "exactly 3 entities" in append_count_hint("context", 3)
    assert append_count_hint("No relevant information found", 3) == "No relevant information found"
    assert append_count_hint("context", 0) == "context"


def test_build_tool_errors_section_collects_execution_notes_and_item_errors() -> None:
    state = SimpleNamespace(
        current_knowledge=[
            {"type": "execution_note", "errors": ["bad exists()"]},
            {"cypher": "MATCH (n)", "error": "timeout"},
        ]
    )

    section = build_tool_errors_section(state)

    assert "TOOL EXECUTION NOTES" in section
    assert "- bad exists()" in section
    assert "- timeout" in section


def test_chart_specs_and_queries_trace_are_ui_safe() -> None:
    state = SimpleNamespace(
        current_knowledge=[
            {
                "source": "p_agent",
                "charts": [
                    {
                        "type": "chart",
                        "chart_type": "pie",
                        "title": "Revenue",
                        "data": [{"label": "A", "value": object()}],
                        "config": {"legend": True},
                    },
                    {"type": "note", "title": "skip"},
                ],
            },
            {"cypher": "MATCH (n)", "rows": [{}, {}], "error": ""},
            {"type": "execution_note", "cypher": "MATCH ignored"},
        ]
    )

    chart_specs, p_agent_count = build_chart_specs_from_notebook(state)
    queries_trace = build_queries_trace(state)

    assert p_agent_count == 1
    assert len(chart_specs) == 1
    assert chart_specs[0].chart_type == "pie"
    assert chart_specs[0].data[0]["value"].startswith("<object object")
    assert queries_trace == [{"cypher": "MATCH (n)", "row_count": 2, "error": None}]


def test_system_prompt_variants_keep_chart_guidance_on_full_chat_only() -> None:
    full_prompt = build_graph_chat_system_prompt(
        context_for_prompt="context",
        entity_count=4,
        relationship_count=2,
        tool_errors_section="tool notes",
    )
    search_prompt = build_graph_chat_search_system_prompt(
        context_for_prompt="context",
        entity_count=4,
        relationship_count=2,
    )

    assert "tool notes" in full_prompt
    assert "Chart data" in full_prompt
    assert "Charts and visualizations" in full_prompt
    assert "Chart data" not in search_prompt
    assert "Charts and visualizations" not in search_prompt
