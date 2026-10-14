"""Semantic entity merge (alias + vector + LLM judge) for unstructured connectors."""

from __future__ import annotations

from typing import Any

__all__ = ["SemanticEntityMergeService"]


def __getattr__(name: str) -> Any:
    if name == "SemanticEntityMergeService":
        from contextd.platform.sync.semantic_merge.semantic_entity_merge_service import (
            SemanticEntityMergeService,
        )

        return SemanticEntityMergeService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
