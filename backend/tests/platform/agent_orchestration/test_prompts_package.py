"""Tests for GLM prompt package exports and prompt assembly guards."""

from contextd.platform.agent_orchestration import prompts
from contextd.platform.agent_orchestration.prompts.a_agent import get_a_agent_system_prompt
from contextd.platform.agent_orchestration.prompts.p_agent import get_p_agent_system_prompt
from contextd.platform.agent_orchestration.prompts.r_agent import (
    build_r_agent_user_message,
)
from contextd.platform.agent_orchestration.types import ExecutionRecord, NotebookState


def test_prompts_package_keeps_public_import_surface() -> None:
    assert callable(prompts.get_r_agent_system_prompt)
    assert callable(prompts.get_a_agent_system_prompt)
    assert callable(prompts.get_p_agent_system_prompt)
    assert callable(prompts.build_r_agent_user_message)
    assert "Graph schema" in prompts.CYPHER_GRAPH_CONTRACT


def test_a_agent_pruned_schema_uses_anonymous_relationship_examples() -> None:
    prompt = get_a_agent_system_prompt(
        pruned_schema="Node: GmailMessage\nProperties: subject, sender"
    )

    assert "Anonymous relationships" in prompt
    assert "Node: GmailMessage" in prompt
    assert "-[]-" in prompt
    assert "-[*..5]-" in prompt
    assert "-[:RELATES_TO" not in prompt


def test_r_agent_user_message_uses_structured_manifest() -> None:
    notebook = NotebookState(
        current_knowledge=[
            {
                "cypher": "MATCH (n:GraphNode) RETURN count(n) AS total",
                "intent": "Count graph nodes",
                "rows": [{"total": 4}],
                "columns": ["total"],
            }
        ],
        missing_information=["Need customer detail"],
        execution_history=[
            ExecutionRecord(
                tool_or_step="run_cypher",
                input_summary="count graph nodes",
                output_summary="1 row",
                timestamp_iso="2026-04-25T00:00:00Z",
            )
        ],
    )

    message = build_r_agent_user_message(
        "How many records are there?",
        notebook,
        user_email="ada@example.test",
        user_name="Ada",
    )

    assert "## System Context" in message
    assert "Requesting User Email: ada@example.test" in message
    assert "Cypher Result [Intent: Count graph nodes]" in message
    assert "Need customer detail" in message
    assert "run_cypher: in=count graph nodes out=1 row" in message


def test_p_agent_prompt_includes_predefined_chart_tools() -> None:
    prompt = get_p_agent_system_prompt()

    assert "emit_chart" in prompt
    assert "chart_from_columns" in prompt
