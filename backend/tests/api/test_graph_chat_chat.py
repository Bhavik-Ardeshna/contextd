"""Tests for main graph chat helpers."""

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

from contextd.api.v1.endpoints.graph_chat_chat import (  # noqa: E402
    build_graph_chat_context_metadata,
    determine_graph_chat_path_used,
)


def test_determine_graph_chat_path_used_classifies_retrieval_path() -> None:
    assert (
        determine_graph_chat_path_used(
            use_glm_agents=False,
            glm_notebook_state=None,
        )
        == "graph_search"
    )
    assert (
        determine_graph_chat_path_used(
            use_glm_agents=True,
            glm_notebook_state=None,
        )
        == "glm_deterministic"
    )
    assert (
        determine_graph_chat_path_used(
            use_glm_agents=True,
            glm_notebook_state=object(),
        )
        == "glm_non_deterministic"
    )


def test_build_graph_chat_context_metadata_matches_public_contract() -> None:
    traversal_result = SimpleNamespace(nodes=[object(), object()], edges=[object()])

    metadata = build_graph_chat_context_metadata(
        traversal_result=traversal_result,
        search_results=[{"node_id": "n1"}],
        context_for_prompt="1234567890",
        max_depth=3,
        use_glm_agents=True,
        glm_notebook_state=object(),
        queries_trace=[{"row_count": 2}, {"row_count": 5}],
        collection_ids_for_schema=["collection-one"],
        resolved_collection_name="Collection One",
        source_types=["notion"],
        collection_mention="missing",
        mention_diagnostic="not found",
    )

    assert metadata == {
        "node_count": 2,
        "edge_count": 1,
        "search_result_count": 1,
        "token_estimate": 3,
        "max_depth": 3,
        "path_used": "glm_non_deterministic",
        "queries": [{"row_count": 2}, {"row_count": 5}],
        "total_rows": 7,
        "collection_id": "collection-one",
        "collection_name": "Collection One",
        "source_types": ["notion"],
        "mention_unresolved": "missing",
    }


def test_build_graph_chat_context_metadata_handles_empty_context() -> None:
    metadata = build_graph_chat_context_metadata(
        traversal_result=None,
        search_results=[],
        context_for_prompt="empty",
        max_depth=1,
        use_glm_agents=False,
        glm_notebook_state=None,
        queries_trace=[],
        collection_ids_for_schema=[],
        resolved_collection_name=None,
        source_types=[],
        collection_mention=None,
        mention_diagnostic=None,
    )

    assert metadata["node_count"] == 0
    assert metadata["edge_count"] == 0
    assert metadata["search_result_count"] == 0
    assert metadata["token_estimate"] == 1
    assert metadata["path_used"] == "graph_search"
    assert metadata["total_rows"] == 0
    assert metadata["collection_id"] is None
    assert metadata["mention_unresolved"] is None
