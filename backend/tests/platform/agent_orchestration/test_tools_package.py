"""Tests for GLM graph tools package exports and Cypher guards."""

import pytest

from contextd.platform.agent_orchestration.tools import graph_sql, node_info, retrieve_node
from contextd.platform.agent_orchestration.tools.cypher import (
    _normalize_cypher_row,
    _validate_read_only_cypher,
)


def test_tools_package_keeps_public_executor_imports() -> None:
    assert callable(graph_sql)
    assert callable(node_info)
    assert callable(retrieve_node)


def test_cypher_guard_ignores_literals_and_comments() -> None:
    _validate_read_only_cypher(
        """
        MATCH (n:GraphNode)
        WHERE n.name IN ['Drop-in', "Delete me not"]
        // CREATE should be ignored in a comment
        RETURN n
        """
    )


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (n) DELETE n",
        "MATCH (n) SET n.name = 'Ada'",
        "CALL db.labels()",
    ],
)
def test_cypher_guard_blocks_writes_and_disallowed_db_calls(query: str) -> None:
    with pytest.raises(ValueError):
        _validate_read_only_cypher(query)


def test_cypher_guard_allows_fulltext_db_calls() -> None:
    _validate_read_only_cypher(
        "CALL db.index.fulltext.queryNodes('nodeText', 'ada') YIELD node RETURN node"
    )


def test_normalize_cypher_row_parses_property_bags() -> None:
    assert _normalize_cypher_row(
        {
            "node_id": "public.people:1",
            "details": '{"name": "Ada"}',
            "status": "active",
        }
    ) == {
        "node_id": "public.people:1",
        "details": {"name": "Ada"},
        "status": "active",
    }
