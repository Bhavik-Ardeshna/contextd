"""Tests for GLM sandbox executor runtime helpers."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from contextd.platform.agent_orchestration.runtime import executor as executor_module
from contextd.platform.agent_orchestration.runtime import p_agent
from contextd.platform.agent_orchestration.runtime.settings import (
    LARGE_DATA_ROW_THRESHOLD,
    MAX_P_AGENT_DATASETS_PER_ROUND,
)
from contextd.platform.agent_orchestration.types import NotebookState


@pytest.mark.asyncio
async def test_run_executor_moves_large_cypher_rows_to_sidecar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"node_id": f"public.people:{idx}", "name": f"Person {idx}"}
        for idx in range(LARGE_DATA_ROW_THRESHOLD + 1)
    ]

    async def fake_graph_sql(*args, **kwargs):
        return rows

    monkeypatch.setattr(executor_module, "graph_sql", fake_graph_sql)
    notebook, errors, sidecar = await executor_module.run_executor(
        'run_cypher("MATCH (n) RETURN n")',
        NotebookState(),
        organization_id=uuid4(),
        collection_id=uuid4(),
        vector_size=1536,
        ctx=SimpleNamespace(request_id="req-test"),
        plan_steps=["Inspect people"],
    )

    assert errors == []
    assert len(notebook.current_knowledge) == 1
    item = notebook.current_knowledge[0]
    assert item["type"] == "cypher_result"
    assert item["row_count"] == len(rows)
    assert item["columns"] == ["node_id", "name"]
    assert item["intent"] == "Inspect people"
    assert sidecar[item["large_data_ref"]] == rows


@pytest.mark.asyncio
async def test_run_executor_records_sandbox_errors() -> None:
    notebook, errors, sidecar = await executor_module.run_executor(
        "1 / 0",
        NotebookState(),
        organization_id=uuid4(),
        collection_id=uuid4(),
        vector_size=1536,
        ctx=SimpleNamespace(request_id="req-test"),
    )

    assert sidecar == {}
    assert errors == ["ZeroDivisionError: division by zero"]
    assert notebook.current_knowledge[-1] == {
        "type": "execution_note",
        "note": "Python sandbox or Cypher execution failed.",
        "errors": errors,
    }


def test_list_cypher_datasets_for_p_agent_caps_explicit_mode() -> None:
    datasets = [(f"RETURN {idx}", [{"count": idx}]) for idx in range(10)]

    selected = p_agent.list_cypher_datasets_for_p_agent(datasets, use_p=True)

    assert selected == datasets[:MAX_P_AGENT_DATASETS_PER_ROUND]


def test_list_cypher_datasets_for_p_agent_picks_large_or_aggregate_data() -> None:
    large_rows = [{"name": str(idx)} for idx in range(LARGE_DATA_ROW_THRESHOLD + 1)]
    aggregate_rows = [{"status": "paid", "count": 3}]

    assert p_agent.list_cypher_datasets_for_p_agent(
        [("small", [{"name": "Ada"}]), ("large", large_rows)],
        use_p=False,
    ) == [("large", large_rows)]
    assert p_agent.list_cypher_datasets_for_p_agent(
        [("small", [{"name": "Ada"}]), ("aggregate", aggregate_rows)],
        use_p=False,
    ) == [("aggregate", aggregate_rows)]


@pytest.mark.asyncio
async def test_run_p_executor_collects_stdout_and_charts() -> None:
    stdout, stderr, charts, errors = await p_agent.run_p_executor(
        """
print(len(df))
emit_chart({
    "type": "chart",
    "chart_type": "bar",
    "title": "People",
    "data": [{"label": "A", "count": 2}],
})
""",
        [{"name": "Ada"}],
    )

    assert stdout.strip() == "1"
    assert stderr == ""
    assert errors == []
    assert charts == [
        {
            "type": "chart",
            "chart_type": "bar",
            "title": "People",
            "data": [{"label": "A", "count": 2, "value": 2, "name": "A"}],
            "config": None,
        }
    ]
