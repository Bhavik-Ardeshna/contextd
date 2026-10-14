"""Context Intelligence endpoints: temporal, lineage, decisions, drift."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import schemas
from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.router import TrailingSlashRouter
from contextd.core.context_intelligence_service import context_intelligence_service
from contextd.db.session import get_db

router = TrailingSlashRouter()


@router.get("/databases/{readable_id}", response_model=schemas.ContextIntelligenceSummary)
async def get_database_context_intelligence(
    *,
    db: AsyncSession = Depends(get_db),
    readable_id: str,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.ContextIntelligenceSummary:
    """Return the native ContextD inspection lanes for a database."""
    summary = await context_intelligence_service.get_database_summary(
        db,
        readable_id=readable_id,
        ctx=ctx,
    )
    await db.commit()
    return summary


@router.post("/databases/{readable_id}/drift/detect", response_model=schemas.ContextIntelligenceSummary)
async def detect_database_context_drift(
    *,
    db: AsyncSession = Depends(get_db),
    readable_id: str,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.ContextIntelligenceSummary:
    """Evaluate source/Forge drift and persist native drift signals."""
    summary = await context_intelligence_service.detect_database_drift(
        db,
        readable_id=readable_id,
        ctx=ctx,
    )
    await db.commit()
    return summary


@router.post(
    "/databases/{readable_id}/feedback",
    response_model=schemas.ContextQueryFeedbackResponse,
)
async def submit_database_query_feedback(
    *,
    db: AsyncSession = Depends(get_db),
    readable_id: str,
    payload: schemas.ContextQueryFeedbackRequest,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.ContextQueryFeedbackResponse:
    """Persist answer feedback into the query trace and retrieval memory weights."""
    result = await context_intelligence_service.record_query_feedback(
        db,
        readable_id=readable_id,
        ctx=ctx,
        query_id=payload.query_id,
        rating=payload.rating,
        comment=payload.comment,
        retrieved_node_ids=payload.retrieved_node_ids,
        retrieved_edge_ids=payload.retrieved_edge_ids,
    )
    await db.commit()
    return schemas.ContextQueryFeedbackResponse(**result)
