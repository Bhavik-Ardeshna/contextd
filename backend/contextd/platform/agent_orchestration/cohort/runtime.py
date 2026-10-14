"""Shared runtime helpers for cohort GLM orchestration."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from contextd.api.context import ApiContext

MAX_COHORT_CUTOFF_ITER = 3
COHORT_CUTOFF_EPS = 1e-4


async def resolve_vector_size(
    vector_size: Optional[int],
    *,
    collection_id: UUID,
    ctx: ApiContext,
) -> int:
    """Resolve collection vector size once for cohort executor calls."""
    if vector_size is not None:
        return vector_size

    from contextd import crud
    from contextd.db.session import get_db_context

    async with get_db_context() as db:
        coll = await crud.collection.get(db, id=collection_id, ctx=ctx)
        return getattr(coll, "vector_size", 1536) if coll else 1536


def zero_div_retry_hint(err_txt: str) -> str:
    """Extra instructions when sandbox hit ZeroDivisionError (Python or echoed Cypher issue)."""
    if "ZeroDivisionError" not in err_txt:
        return ""
    return (
        " Division: in Python use only **safe_div** / **safe_mean** (no bare `/`). "
        "In Cypher, guard **(max-min)** when max=min with **CASE WHEN ... THEN 0.0 ... END**."
    )
