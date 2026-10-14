"""Unit coverage for native ContextD intelligence helpers."""

from __future__ import annotations

import os

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.core.context_intelligence_service import ContextIntelligenceService
from contextd.platform.sync.graph.commit_service import GraphCommitService


def test_context_intelligence_edge_refs_match_graph_commit_ids() -> None:
    """Native temporal/lineage rows must address the same edge IDs stored in Neo4j."""
    service = ContextIntelligenceService()
    commit_service = GraphCommitService(neo4j_driver=object())

    assert service._edge_ref("public.studios:1", "public.members:2", "RELATED_TO") == (
        commit_service._generate_edge_id("public.studios:1", "public.members:2", "RELATED_TO")
    )
    assert service._edge_ref(
        "public.studios:1",
        "public.members:2",
        "RELATED_TO",
        collection_id="customer-360",
    ) == commit_service._generate_edge_id(
        "public.studios:1",
        "public.members:2",
        "RELATED_TO",
        readable_collection_id="customer-360",
    )
    assert service._edge_ref(
        "public.studios:1",
        "public.members:2",
        "RELATED_TO",
        collection_id="customer-360",
    ) != service._edge_ref(
        "public.studios:1",
        "public.members:2",
        "RELATED_TO",
        collection_id="finance-360",
    )


def test_feedback_weight_uses_neutral_centered_ema() -> None:
    """Ratings should move memory gently: 3 is neutral, 5 boosts, 1 demotes."""
    service = ContextIntelligenceService()

    assert service._feedback_target_weight(1) == 0.5
    assert service._feedback_target_weight(3) == 1.0
    assert service._feedback_target_weight(5) == 1.5
    assert service._feedback_ema_weight(1.0, target_weight=1.5, alpha=0.10) == 1.05
    assert service._feedback_ema_weight(1.0, target_weight=0.5, alpha=0.10) == 0.95
