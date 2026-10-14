"""Tests for graph traversal endpoint helpers."""

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

from contextd.api.v1.endpoints.graph_chat_schemas import TraverseRequest  # noqa: E402
from contextd.api.v1.endpoints.graph_chat_traversal import (  # noqa: E402
    build_traversal_config,
    build_traverse_response,
    resolve_traversal_direction,
)
from contextd.platform.graph.traversal import TraversalDirection  # noqa: E402


def test_resolve_traversal_direction_defaults_unknown_values_to_both() -> None:
    assert resolve_traversal_direction("outgoing") == TraversalDirection.OUTGOING
    assert resolve_traversal_direction("incoming") == TraversalDirection.INCOMING
    assert resolve_traversal_direction("both") == TraversalDirection.BOTH
    assert resolve_traversal_direction("sideways") == TraversalDirection.BOTH


def test_build_traversal_config_maps_request_fields() -> None:
    config = build_traversal_config(
        TraverseRequest(
            node_ids=["n1"],
            max_depth=3,
            direction="outgoing",
            relationship_types=["RELATES_TO"],
            node_limit=25,
            include_properties=False,
        )
    )

    assert config.max_depth == 3
    assert config.direction == TraversalDirection.OUTGOING
    assert config.relationship_types == ["RELATES_TO"]
    assert config.node_limit == 25
    assert config.include_properties is False


def test_build_traverse_response_matches_public_contract() -> None:
    response = build_traverse_response(
        SimpleNamespace(
            nodes=[
                SimpleNamespace(
                    node_id="n1",
                    node_type="Person",
                    name="Ada",
                    properties={"role": "engineer"},
                    depth=0,
                )
            ],
            edges=[
                SimpleNamespace(
                    from_node_id="n1",
                    to_node_id="n2",
                    relationship_type="KNOWS",
                    properties={"since": 2024},
                )
            ],
            start_node_ids=["n1"],
            stats={"node_count": 1},
        )
    )

    assert response.nodes == [
        {
            "node_id": "n1",
            "node_type": "Person",
            "name": "Ada",
            "properties": {"role": "engineer"},
            "depth": 0,
        }
    ]
    assert response.edges == [
        {
            "from_node_id": "n1",
            "to_node_id": "n2",
            "relationship_type": "KNOWS",
            "properties": {"since": 2024},
        }
    ]
    assert response.start_node_ids == ["n1"]
    assert response.stats == {"node_count": 1}
