"""Tests for GLM runtime traversal conversion helpers."""

from contextd.platform.agent_orchestration.runtime.traversal import (
    notebook_to_traversal_result,
)
from contextd.platform.agent_orchestration.types import NotebookState


def test_notebook_to_traversal_result_rehydrates_large_data_sidecar() -> None:
    notebook = NotebookState(
        current_knowledge=[
            {
                "type": "cypher_result",
                "cypher": "MATCH (n) RETURN n",
                "large_data_ref": "cypher_0_0",
                "row_count": 2,
            }
        ],
        missing_information=[],
        execution_history=[],
    )
    sidecar = {
        "cypher_0_0": [
            {
                "node_id": "public.persons:1",
                "name": "Ada Lovelace",
                "details": {"primary_email": "ada@example.test"},
            },
            {
                "node_id": "public.orders:2",
                "status": "paid",
                "properties": {"total": 42},
            },
        ]
    }

    result = notebook_to_traversal_result(notebook, large_data_by_ref=sidecar)

    assert result.stats == {"source": "notebook", "node_count": 2, "edge_count": 0}
    assert [node.node_id for node in result.nodes] == [
        "public.persons:1",
        "public.orders:2",
    ]
    assert result.nodes[0].node_type == "PersonNode"
    assert result.nodes[0].properties["primary_email"] == "ada@example.test"
    assert result.nodes[1].node_type == "OrdersTableEntity"
    assert result.nodes[1].properties["total"] == 42


def test_notebook_to_traversal_result_prefers_full_node_info() -> None:
    notebook = NotebookState(
        current_knowledge=[
            {
                "rows": [
                    {
                        "node_id": "public.persons:1",
                        "name": "Ada",
                    }
                ]
            },
            {
                "node_id": "public.persons:1",
                "node_type": "PersonNode",
                "name": "Ada Lovelace",
                "properties": {
                    "first_name": "Ada",
                    "last_name": "Lovelace",
                    "primary_email": "ada@example.test",
                },
            },
        ],
        missing_information=[],
        execution_history=[],
    )

    result = notebook_to_traversal_result(notebook)

    assert len(result.nodes) == 1
    assert result.nodes[0].name == "Ada Lovelace"
    assert result.nodes[0].properties["last_name"] == "Lovelace"
