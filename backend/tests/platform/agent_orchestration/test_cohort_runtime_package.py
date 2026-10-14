"""Tests for cohort runtime package boundaries."""

import os
from typing import Any, cast
from uuid import uuid4

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.platform.agent_orchestration.cohort.cutoff import CohortCutoffResult
from contextd.platform.agent_orchestration.cohort.listing import run_cohort_glm
from contextd.platform.agent_orchestration.cohort.runtime import (
    resolve_vector_size,
    zero_div_retry_hint,
)
from contextd.platform.agent_orchestration.cohort.scoring import run_cohort_scoring_glm
from contextd.platform.agent_orchestration.orchestrator import (
    run_cohort_glm as legacy_run_cohort_glm,
)
from contextd.platform.agent_orchestration.orchestrator import (
    run_cohort_scoring_glm as legacy_run_cohort_scoring_glm,
)
from contextd.platform.agent_orchestration.types import NotebookState


def test_cohort_package_exports_runtime_entrypoints() -> None:
    assert run_cohort_glm is legacy_run_cohort_glm
    assert run_cohort_scoring_glm is legacy_run_cohort_scoring_glm


async def test_resolve_vector_size_returns_explicit_value_without_db() -> None:
    vector_size = await resolve_vector_size(
        768,
        collection_id=uuid4(),
        ctx=cast(Any, object()),
    )

    assert vector_size == 768


def test_zero_div_retry_hint_is_specific_to_zero_division() -> None:
    assert zero_div_retry_hint("syntax error") == ""
    assert "safe_div" in zero_div_retry_hint("ZeroDivisionError: division by zero")


def test_cutoff_result_carries_rows_and_notebook() -> None:
    result = CohortCutoffResult(
        cypher_query="MATCH (n) RETURN n.node_id AS node_id",
        rows=[{"node_id": "public.people:1", "final_score": 0.8}],
        cutoff_value=0.7,
        cutoff_rationale="top decile",
        iterations_used=1,
        notebook_state=NotebookState(),
        warning=None,
    )

    assert result.rows[0]["node_id"] == "public.people:1"
    assert result.notebook_state.current_knowledge == []
