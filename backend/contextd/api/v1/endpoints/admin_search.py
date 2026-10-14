"""Admin search endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import schemas
from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.router import TrailingSlashRouter
from contextd.api.v1.endpoints.admin_access import require_admin_permission
from contextd.core.exceptions import NotFoundException
from contextd.core.shared_models import FeatureFlag as FeatureFlagEnum

router = TrailingSlashRouter()


@router.post("/collections/{readable_id}/search", response_model=schemas.SearchResponse)
async def admin_search_collection(
    readable_id: str,
    search_request: schemas.SearchRequest,
    db: AsyncSession = Depends(deps.get_db),
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.SearchResponse:
    """Admin-only: Search any collection regardless of organization.

    This endpoint allows admins or API keys with `api_key_admin_sync` permission
    to search collections across organizations for support purposes.

    Args:
        readable_id: The readable ID of the collection to search
        search_request: The search request parameters
        db: Database session
        ctx: API context

    Returns:
        SearchResponse with results

    Raises:
        HTTPException: If not admin or collection not found
    """
    import time

    from sqlalchemy import select as sa_select

    from contextd.models.collection import Collection
    from contextd.search.orchestrator import orchestrator

    require_admin_permission(ctx, FeatureFlagEnum.API_KEY_ADMIN_SYNC)

    result = await db.execute(sa_select(Collection).where(Collection.readable_id == readable_id))
    collection = result.scalar_one_or_none()

    if not collection:
        raise NotFoundException(f"Collection '{readable_id}' not found")

    ctx.logger.info(f"Admin searching collection {readable_id} (org: {collection.organization_id})")

    start_time = time.monotonic()

    dest_instance = await _create_admin_search_destination(
        collection_id=collection.id,
        organization_id=collection.organization_id,
        vector_size=collection.vector_size,
        ctx=ctx,
    )

    search_context = await _build_admin_search_context(
        db=db,
        collection=collection,
        readable_id=readable_id,
        search_request=search_request,
        destination=dest_instance,
        ctx=ctx,
    )

    ctx.logger.debug("Executing admin search")
    response, state = await orchestrator.run(ctx, search_context)

    duration_ms = (time.monotonic() - start_time) * 1000

    ctx.logger.info(
        f"Admin search completed for collection {readable_id}: "
        f"{len(response.results)} results in {duration_ms:.2f}ms"
    )

    return response


async def _create_admin_search_destination(
    collection_id: UUID,
    organization_id: UUID,
    vector_size: int,
    ctx: ApiContext,
):
    """Create destination instance for admin search.

    Args:
        collection_id: Collection UUID
        organization_id: Organization UUID
        vector_size: Vector dimensions
        ctx: API context

    Returns:
        Destination instance
    """
    from types import SimpleNamespace

    from contextd.search.factory import factory

    collection = SimpleNamespace(
        id=collection_id,
        organization_id=organization_id,
        vector_size=vector_size,
        readable_id=str(collection_id),
    )
    return await factory._get_destination_for_collection(db=None, collection=collection, ctx=ctx)


async def _build_admin_search_context(
    db: AsyncSession,
    collection,
    readable_id: str,
    search_request: schemas.SearchRequest,
    destination,
    ctx: ApiContext,
):
    """Build search context with custom destination for admin search.

    This mirrors the factory.build() but allows overriding the destination.
    """
    from contextd.search.factory import (
        SearchContext,
        factory,
    )

    params = factory._apply_defaults_and_validate(search_request)

    federated_sources = await factory.get_federated_sources(db, collection, ctx)
    has_federated_sources = bool(federated_sources)
    has_indexed_sources = await factory._has_indexed_sources(db, collection, ctx)

    requires_embedding = getattr(destination, "_requires_client_embedding", True)
    supports_temporal = getattr(destination, "_supports_temporal_relevance", True)
    supports_filters = getattr(destination, "_supports_user_filters", True)

    ctx.logger.info(
        f"[AdminSearch] Destination: {destination.__class__.__name__}, "
        f"requires_client_embedding: {requires_embedding}, "
        f"supports_temporal_relevance: {supports_temporal}, "
        f"supports_user_filters: {supports_filters}"
    )

    if search_request.filter is not None and not supports_filters:
        raise HTTPException(
            status_code=422,
            detail="Configured search backend does not support metadata filters",
        )
    if search_request.interpret_filters is True and not supports_filters:
        raise HTTPException(
            status_code=422,
            detail="Configured search backend does not support natural-language filter interpretation",
        )

    if not has_federated_sources and not has_indexed_sources:
        raise ValueError("Collection has no sources")

    vector_size = collection.vector_size
    if vector_size is None:
        raise ValueError(f"Collection {collection.readable_id} has no vector_size set.")

    api_keys = factory._get_available_api_keys()
    providers = factory._create_provider_for_each_operation(
        api_keys,
        params,
        has_federated_sources,
        has_indexed_sources,
        ctx,
        vector_size,
        requires_client_embedding=requires_embedding,
        supports_filters=supports_filters,
    )

    from contextd.search.emitter import EventEmitter

    emitter = EventEmitter(request_id=ctx.request_id, stream=False)

    temporal_supporting_sources = None
    if params["temporal_weight"] > 0 and has_indexed_sources and supports_temporal:
        try:
            temporal_supporting_sources = await factory._get_temporal_supporting_sources(
                db, collection, ctx, emitter
            )
        except Exception as exc:
            raise ValueError(f"Failed to check temporal relevance support: {exc}") from exc
    elif params["temporal_weight"] > 0 and not supports_temporal:
        ctx.logger.info(
            "[AdminSearch] Skipping temporal relevance: destination does not support it"
        )
        temporal_supporting_sources = []

    operations = factory._build_operations(
        params,
        providers,
        federated_sources,
        has_indexed_sources,
        search_request,
        temporal_supporting_sources,
        vector_size,
        destination=destination,
        requires_client_embedding=requires_embedding,
        db=db,
        ctx=ctx,
    )

    return SearchContext(
        request_id=ctx.request_id,
        collection_id=collection.id,
        readable_collection_id=readable_id,
        stream=False,
        vector_size=vector_size,
        offset=params["offset"],
        limit=params["limit"],
        emitter=emitter,
        query=search_request.query,
        **operations,
    )
