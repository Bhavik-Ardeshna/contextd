"""Refactored source connections API endpoints with clean abstractions."""

from typing import List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api import deps
from contextd.api.context import ApiContext
from contextd.api.router import TrailingSlashRouter
from contextd.core.guard_rail_service import GuardRailService
from contextd.core.shared_models import ActionType
from contextd.core.source_connection_service import source_connection_service
from contextd.db.session import get_db

router = TrailingSlashRouter()


# OAuth callback endpoints
@router.get("/callback")
async def oauth_callback(
    *,
    db: AsyncSession = Depends(get_db),
    # OAuth2 parameters
    state: Optional[str] = Query(None, description="OAuth2 state parameter"),
    code: Optional[str] = Query(None, description="OAuth2 authorization code"),
    # OAuth1 parameters
    oauth_token: Optional[str] = Query(None, description="OAuth1 token parameter"),
    oauth_verifier: Optional[str] = Query(None, description="OAuth1 verifier"),
) -> Response:
    """Handle OAuth callback from user after they have authenticated with an OAuth provider.

    Supports both OAuth1 and OAuth2 callbacks:
    - OAuth2: Uses state + code parameters
    - OAuth1: Uses oauth_token + oauth_verifier parameters

    Completes the OAuth flow and redirects to the configured URL.
    This endpoint does not require authentication as it's accessed by users
    who are connecting their source.
    """
    # Determine OAuth1 vs OAuth2 based on parameters
    if oauth_token and oauth_verifier:
        # OAuth1 callback
        source_conn = await source_connection_service.complete_oauth1_callback(
            db,
            oauth_token=oauth_token,
            oauth_verifier=oauth_verifier,
        )
    elif state and code:
        # OAuth2 callback
        source_conn = await source_connection_service.complete_oauth2_callback(
            db,
            state=state,
            code=code,
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid OAuth callback: missing required parameters. "
                "Expected either (state + code) for OAuth2 or "
                "(oauth_token + oauth_verifier) for OAuth1"
            ),
        )

    # Redirect to the app with success
    redirect_url = source_conn.auth.redirect_url

    if not redirect_url:
        # Fallback to app URL if redirect_url is not set
        from contextd.core.config import settings

        redirect_url = settings.app_url

    connection_id = source_conn.id

    # Parse the redirect URL to preserve existing query parameters
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(redirect_url)
    query_params = parse_qs(parsed.query, keep_blank_values=True)

    # Add success parameters (using frontend-expected param names)
    query_params["status"] = ["success"]
    query_params["source_connection_id"] = [str(connection_id)]

    # Reconstruct the URL with all query parameters
    new_query = urlencode(query_params, doseq=True)
    final_url = urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
    )

    return Response(
        status_code=303,
        headers={"Location": final_url},
    )


@router.post("/", response_model=schemas.SourceConnection)
async def create(
    *,
    db: AsyncSession = Depends(get_db),
    source_connection_in: schemas.SourceConnectionCreate,
    ctx: ApiContext = Depends(deps.get_context),
    guard_rail: GuardRailService = Depends(deps.get_guard_rail_service),
) -> schemas.SourceConnection:
    """Create a new source connection.

    The authentication configuration determines the flow:
    - DirectAuthentication: Immediate creation with provided credentials
    - OAuthBrowserAuthentication: Returns shell with authentication URL
    - OAuthTokenAuthentication: Immediate creation with provided token
    - AuthProviderAuthentication: Using external auth provider

    BYOC (Bring Your Own Client) is detected when client_id and client_secret
    are provided in OAuthBrowserAuthentication.

    sync_immediately defaults:
    - True for: direct, oauth_token, auth_provider
    - False for: oauth_browser, oauth_byoc (these sync after authentication)
    """
    # Check if organization is allowed to create a source connection
    await guard_rail.is_allowed(ActionType.SOURCE_CONNECTIONS)

    # If sync_immediately is True or None (will be defaulted), check if we can process entities
    # Note: We check even for None because it may default to True based on auth method
    if source_connection_in.sync_immediately:
        await guard_rail.is_allowed(ActionType.ENTITIES)

    result = await source_connection_service.create(
        db,
        obj_in=source_connection_in,
        ctx=ctx,
    )

    return result


@router.get("/", response_model=List[schemas.SourceConnectionListItem])
async def list(
    *,
    db: AsyncSession = Depends(get_db),
    ctx: ApiContext = Depends(deps.get_context),
    collection: Optional[str] = Query(None, description="Filter by collection readable ID"),
    collection_id: Optional[str] = Query(
        None,
        description="Alias for collection. Filters by collection readable ID.",
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> List[schemas.SourceConnectionListItem]:
    """List source connections with minimal fields for performance."""
    if collection and collection_id and collection != collection_id:
        raise HTTPException(
            status_code=400,
            detail="Use either collection or collection_id; both filters must match when provided.",
        )
    readable_collection_id = collection or collection_id
    return await source_connection_service.list(
        db,
        ctx=ctx,
        readable_collection_id=readable_collection_id,
        skip=skip,
        limit=limit,
    )


@router.get("/{source_connection_id}", response_model=schemas.SourceConnection)
async def get(
    *,
    db: AsyncSession = Depends(get_db),
    source_connection_id: UUID,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.SourceConnection:
    """Get a source connection with optional depth expansion."""
    result = await source_connection_service.get(
        db,
        id=source_connection_id,
        ctx=ctx,
    )
    return result


@router.patch("/{source_connection_id}", response_model=schemas.SourceConnection)
async def update(
    *,
    db: AsyncSession = Depends(get_db),
    source_connection_id: UUID,
    source_connection_in: schemas.SourceConnectionUpdate,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.SourceConnection:
    """Update a source connection.

    Updateable fields:
    - name, description
    - config_fields
    - cron_schedule
    - auth_fields (direct auth only)
    """
    return await source_connection_service.update(
        db,
        id=source_connection_id,
        obj_in=source_connection_in,
        ctx=ctx,
    )


@router.post(
    "/{source_connection_id}/drift/accept",
    response_model=schemas.SourceConnection,
)
async def accept_drift_baseline(
    *,
    db: AsyncSession = Depends(get_db),
    source_connection_id: UUID,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.SourceConnection:
    """Accept the current config/schema observation as the drift baseline."""
    source_connection = await crud.source_connection.get(
        db,
        id=source_connection_id,
        ctx=ctx,
    )
    if not source_connection:
        raise HTTPException(status_code=404, detail="Source connection not found")

    from contextd.core.source_drift_service import source_drift_service

    await source_drift_service.accept_current_baseline(
        db=db,
        source_connection=source_connection,
        ctx=ctx,
    )
    await db.commit()
    await db.refresh(source_connection)
    return await source_connection_service.get(
        db,
        id=source_connection_id,
        ctx=ctx,
    )


@router.delete("/{source_connection_id}", response_model=schemas.SourceConnection)
async def delete(
    *,
    db: AsyncSession = Depends(get_db),
    source_connection_id: UUID,
    ctx: ApiContext = Depends(deps.get_context),
    guard_rail: GuardRailService = Depends(deps.get_guard_rail_service),
) -> schemas.SourceConnection:
    """Delete a source connection and all related data."""
    result = await source_connection_service.delete(
        db,
        id=source_connection_id,
        ctx=ctx,
    )

    return result


@router.post("/{source_connection_id}/run", response_model=schemas.SourceConnectionJob)
async def run(
    *,
    db: AsyncSession = Depends(get_db),
    source_connection_id: UUID,
    ctx: ApiContext = Depends(deps.get_context),
    guard_rail: GuardRailService = Depends(deps.get_guard_rail_service),
    force_full_sync: bool = Query(
        False,
        description=(
            "Force a full sync ignoring cursor data instead of waiting for the daily cleanup "
            "schedule. Only allowed for continuous syncs."
        ),
    ),
) -> schemas.SourceConnectionJob:
    """Trigger a sync run for a source connection.

    Runs are always executed through Temporal workflow engine.

    Args:
        db: Database session
        source_connection_id: ID of the source connection to run
        ctx: API context with organization and user information
        guard_rail: Guard rail service for usage limits
        force_full_sync: If True, forces a full sync with orphaned entity cleanup
                        for continuous syncs. Raises 400 error if used on
                        non-continuous syncs (which are always full syncs).
    """
    # Check if organization is allowed to process entities
    await guard_rail.is_allowed(ActionType.ENTITIES)

    run = await source_connection_service.run(
        db,
        id=source_connection_id,
        ctx=ctx,
        force_full_sync=force_full_sync,
    )
    return run


@router.get("/{source_connection_id}/jobs", response_model=List[schemas.SourceConnectionJob])
async def get_source_connection_jobs(
    *,
    db: AsyncSession = Depends(get_db),
    source_connection_id: UUID,
    ctx: ApiContext = Depends(deps.get_context),
    limit: int = Query(100, ge=1, le=1000),
) -> List[schemas.SourceConnectionJob]:
    """Get sync jobs for a source connection."""
    return await source_connection_service.get_jobs(
        db,
        id=source_connection_id,
        ctx=ctx,
        limit=limit,
    )


@router.post(
    "/{source_connection_id}/jobs/{job_id}/cancel",
    response_model=schemas.SourceConnectionJob,
)
async def cancel_job(
    *,
    db: AsyncSession = Depends(get_db),
    source_connection_id: UUID,
    job_id: UUID,
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.SourceConnectionJob:
    """Cancel a running sync job for a source connection.

    This endpoint requests cancellation and marks the job as CANCELLING.
    The workflow updates the final status to CANCELLED when it processes
    the cancellation request.
    """
    return await source_connection_service.cancel_job(
        db,
        source_connection_id=source_connection_id,
        job_id=job_id,
        ctx=ctx,
    )


@router.post("/{source_connection_id}/make-continuous", response_model=schemas.SourceConnection)
async def make_continuous(
    *,
    db: AsyncSession = Depends(get_db),
    source_connection_id: UUID,
    cursor_field: Optional[str] = Query(None, description="Field to use for incremental sync"),
    ctx: ApiContext = Depends(deps.get_context),
) -> schemas.SourceConnection:
    """Convert source connection to continuous sync mode.

    Only available for sources that support incremental sync.
    """
    return await source_connection_service.make_continuous(
        db,
        id=source_connection_id,
        cursor_field=cursor_field,
        ctx=ctx,
    )


@router.get("/{source_connection_id}/sync-id", include_in_schema=False)
async def get_sync_id(
    *,
    db: AsyncSession = Depends(get_db),
    source_connection_id: UUID,
    ctx: ApiContext = Depends(deps.get_context),
) -> dict:
    """Get the sync_id for a source connection.

    This is a private endpoint not documented in Fern.
    Used internally for Temporal sync testing and debugging.
    """
    source_connection = await crud.source_connection.get(
        db,
        id=source_connection_id,
        ctx=ctx,
    )

    if not source_connection.sync_id:
        raise HTTPException(status_code=404, detail="No sync found for this source connection")

    return {"sync_id": str(source_connection.sync_id)}


@router.get("/authorize/{code}")
async def authorize_redirect(
    *,
    db: AsyncSession = Depends(get_db),
    code: str,
) -> Response:
    """Proxy redirect to OAuth provider.

    This endpoint is used to provide a short-lived, user-friendly URL
    that redirects to the actual OAuth provider authorization page.
    This endpoint does not require authentication as it's accessed by users
    who are not yet authenticated with the platform.
    """
    from contextd.crud import redirect_session

    redirect_info = await redirect_session.get_by_code(db, code=code)
    if not redirect_info:
        raise HTTPException(status_code=404, detail="Authorization link expired or invalid")

    # Redirect to the OAuth provider
    return Response(
        status_code=303,
        headers={"Location": redirect_info.final_url},
    )


@router.get(
    "/{source_connection_id}/schema",
    response_model=dict,
)
async def introspect_schema(
    *,
    db: AsyncSession = Depends(get_db),
    source_connection_id: UUID,
    ctx: ApiContext = Depends(deps.get_context),
) -> dict:
    """Introspect the database schema for a source connection.

    Returns available tables with their columns, types,
    primary keys, and foreign keys. Used by the frontend
    to let users select which tables/columns to sync.

    Only works for database-type sources (PostgreSQL, etc.).
    """
    source_conn = await crud.source_connection.get(
        db,
        id=source_connection_id,
        ctx=ctx,
    )
    if not source_conn:
        raise HTTPException(
            status_code=404,
            detail="Source connection not found",
        )

    db_sources = {
        "postgresql", "clickhouse", "mysql",
        "oracle", "sqlserver", "sqlite",
    }
    if source_conn.short_name not in db_sources:
        raise HTTPException(
            status_code=400,
            detail=(
                "Schema introspection is only "
                "available for database sources"
            ),
        )

    # Get decrypted credentials
    from contextd.core import credentials as cred_util

    if not source_conn.connection_id:
        raise HTTPException(
            status_code=400,
            detail="Source connection has no credentials",
        )

    connection = await crud.connection.get(
        db, id=source_conn.connection_id, ctx=ctx
    )
    if (
        not connection
        or not connection.integration_credential_id
    ):
        raise HTTPException(
            status_code=400,
            detail="No credentials found",
        )

    int_cred = await crud.integration_credential.get(
        db,
        id=connection.integration_credential_id,
        ctx=ctx,
    )
    if not int_cred:
        raise HTTPException(
            status_code=400,
            detail="Integration credential not found",
        )

    raw_creds = cred_util.decrypt(
        int_cred.encrypted_credentials
    )

    if source_conn.short_name == "postgresql":
        from contextd.platform.sources.postgresql import (
            PostgreSQLSource,
        )

        # Merge config_fields into credentials
        auth_fields = raw_creds
        if source_conn.config_fields:
            auth_fields = {
                **raw_creds,
                **source_conn.config_fields,
            }

        source = await PostgreSQLSource.create(auth_fields)
        try:
            await source._connect()
            schema_name = (
                source.config.get("schema", "public")
                or "public"
            )
            tables = await source._get_table_list(
                schema_name
            )
            result = {
                "schema": schema_name,
                "tables": [],
            }
            for table in tables:
                info = await source._get_table_info(
                    schema_name, table
                )
                cols = []
                for cname, cmeta in info[
                    "columns"
                ].items():
                    cols.append({
                        "name": cname,
                        "type": cmeta.get(
                            "pg_type", "unknown"
                        ),
                        "nullable": cmeta.get(
                            "nullable", True
                        ),
                        "is_primary_key": (
                            cname
                            in info["primary_keys"]
                        ),
                    })
                result["tables"].append({
                    "name": table,
                    "columns": cols,
                    "primary_keys": info[
                        "primary_keys"
                    ],
                })
            return result
        finally:
            if source.conn:
                await source.conn.close()
                source.conn = None
    else:
        raise HTTPException(
            status_code=501,
            detail=(
                f"Schema introspection not yet "
                f"implemented for "
                f"{source_conn.short_name}"
            ),
        )
