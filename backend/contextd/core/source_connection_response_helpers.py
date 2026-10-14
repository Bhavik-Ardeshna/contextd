"""Response and read-model helpers for source connection service."""

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api.context import ApiContext
from contextd.core.config import settings as core_settings
from contextd.core.shared_models import SourceConnectionStatus, SyncJobStatus
from contextd.models.source_connection import SourceConnection
from contextd.models.sync import Sync
from contextd.models.sync_job import SyncJob
from contextd.schemas.source_connection import AuthenticationMethod, SourceConnectionJob


class SourceConnectionResponseHelpersMixin:
    """Read-side helpers for building source connection API responses."""

    def determine_auth_method(self, source_conn: Any) -> AuthenticationMethod:
        """Determine authentication method from existing database fields.

        This is a wrapper around the shared function for backward compatibility.
        """
        from contextd.schemas.source_connection import determine_auth_method

        return determine_auth_method(source_conn)

    def compute_status(
        self, source_conn: Any, last_job_status: Optional[SyncJobStatus] = None
    ) -> SourceConnectionStatus:
        """Compute status from current state.

        This is a wrapper around the shared function for backward compatibility.
        """
        from contextd.schemas.source_connection import compute_status

        return compute_status(source_conn, last_job_status)

    async def build_source_connection_response(  # noqa: C901
        self,
        db: AsyncSession,
        source_conn: SourceConnection,
        ctx: ApiContext,
    ) -> schemas.SourceConnection:
        """Build complete source connection response object.

        Args:
            db: Database session
            source_conn: Source connection object
            ctx: API context
        """
        from contextd.schemas.source_connection import compute_status, determine_auth_method

        # Build authentication details
        actual_auth_method = None

        # First check if this is an auth provider connection
        if (
            hasattr(source_conn, "readable_auth_provider_id")
            and source_conn.readable_auth_provider_id
        ):
            actual_auth_method = schemas.AuthenticationMethod.AUTH_PROVIDER
        # Otherwise, load the connection and its credential to get the actual auth method
        elif source_conn.connection_id:
            from contextd.crud import connection as crud_connection
            from contextd.crud import integration_credential as crud_credential

            # Load the connection
            connection = await crud_connection.get(db, id=source_conn.connection_id, ctx=ctx)
            if connection and connection.integration_credential_id:
                # Load the credential
                credential = await crud_credential.get(
                    db, id=connection.integration_credential_id, ctx=ctx
                )
                if credential and hasattr(credential, "authentication_method"):
                    # Map the stored authentication method string to the API enum
                    auth_method_str = credential.authentication_method
                    if auth_method_str == "oauth_token":
                        actual_auth_method = schemas.AuthenticationMethod.OAUTH_TOKEN
                    elif auth_method_str == "oauth_browser":
                        actual_auth_method = schemas.AuthenticationMethod.OAUTH_BROWSER
                    elif auth_method_str == "oauth_byoc":
                        actual_auth_method = schemas.AuthenticationMethod.OAUTH_BYOC
                    elif auth_method_str == "direct":
                        actual_auth_method = schemas.AuthenticationMethod.DIRECT
                    elif auth_method_str == "auth_provider":
                        actual_auth_method = schemas.AuthenticationMethod.AUTH_PROVIDER

        # Fall back to the deprecated method if we couldn't determine from credential
        if actual_auth_method is None:
            actual_auth_method = determine_auth_method(source_conn)

        auth_info = {
            "method": actual_auth_method,
            "authenticated": source_conn.is_authenticated,
        }

        # Add authenticated timestamp
        if source_conn.is_authenticated:
            auth_info["authenticated_at"] = source_conn.created_at

        # Add auth provider info
        if (
            hasattr(source_conn, "readable_auth_provider_id")
            and source_conn.readable_auth_provider_id
        ):
            auth_info["provider_id"] = source_conn.readable_auth_provider_id
            auth_info["provider_readable_id"] = source_conn.readable_auth_provider_id

        # Add OAuth pending info
        if (
            hasattr(source_conn, "connection_init_session_id")
            and source_conn.connection_init_session_id
        ):
            from sqlalchemy.orm import selectinload

            from contextd.models import ConnectionInitSession

            # Explicitly load with the redirect_session relationship
            stmt = (
                select(ConnectionInitSession)
                .where(ConnectionInitSession.id == source_conn.connection_init_session_id)
                .where(ConnectionInitSession.organization_id == ctx.organization.id)
                .options(selectinload(ConnectionInitSession.redirect_session))
            )
            result = await db.execute(stmt)
            init_session = result.scalar_one_or_none()
            if init_session:
                # Get redirect URL from overrides
                if init_session.overrides:
                    redirect_url = init_session.overrides.get("redirect_url")
                    if redirect_url:
                        auth_info["redirect_url"] = redirect_url

                # Get auth URL from linked redirect session
                if init_session.redirect_session and not source_conn.is_authenticated:
                    # Construct the auth URL from the redirect session
                    auth_info["auth_url"] = (
                        f"{core_settings.api_url}/source-connections/authorize/"
                        f"{init_session.redirect_session.code}"
                    )
                    auth_info["auth_url_expires"] = init_session.redirect_session.expires_at

        # Check for auth URL (set during OAuth flow creation as temporary attribute)
        elif hasattr(source_conn, "authentication_url") and source_conn.authentication_url:
            auth_info["auth_url"] = source_conn.authentication_url
            if hasattr(source_conn, "authentication_url_expiry"):
                auth_info["auth_url_expires"] = source_conn.authentication_url_expiry

        auth = schemas.AuthenticationDetails(**auth_info)

        # Fetch schedule info if sync exists
        schedule = None
        if hasattr(source_conn, "sync_id") and source_conn.sync_id:
            try:
                schedule_info = await crud.source_connection.get_schedule_info(db, source_conn)
                if schedule_info:
                    schedule = schemas.ScheduleDetails(
                        cron=schedule_info.get("cron_expression"),
                        next_run=schedule_info.get("next_run_at"),
                        continuous=schedule_info.get("is_continuous", False),
                        cursor_field=schedule_info.get("cursor_field"),
                        cursor_value=schedule_info.get("cursor_value"),
                    )
            except Exception as e:
                ctx.logger.warning(f"Failed to get schedule info: {e}")

        # Fetch sync details if sync exists
        sync_details = None
        if hasattr(source_conn, "sync_id") and source_conn.sync_id:
            try:
                from contextd.core.sync_service import sync_service as _sync_service

                job = await _sync_service.get_last_sync_job(
                    db, ctx=ctx, sync_id=source_conn.sync_id
                )
                if job:
                    # Build SyncJobDetails
                    duration_seconds = None
                    if job.completed_at and job.started_at:
                        duration_seconds = (job.completed_at - job.started_at).total_seconds()

                    # Calculate entity metrics
                    entities_inserted = getattr(job, "entities_inserted", 0) or 0
                    entities_updated = getattr(job, "entities_updated", 0) or 0
                    entities_deleted = getattr(job, "entities_deleted", 0) or 0
                    entities_skipped = getattr(job, "entities_skipped", 0) or 0

                    entities_failed = entities_skipped

                    last_job = schemas.SyncJobDetails(
                        id=job.id,
                        status=job.status,
                        started_at=getattr(job, "started_at", None),
                        completed_at=getattr(job, "completed_at", None),
                        duration_seconds=duration_seconds,
                        entities_inserted=entities_inserted,
                        entities_updated=entities_updated,
                        entities_deleted=entities_deleted,
                        entities_failed=entities_failed,
                        error=getattr(job, "error", None),
                    )

                    # Create SyncDetails
                    sync_details = schemas.SyncDetails(
                        total_runs=1,  # Simplified - we only have last job
                        successful_runs=1 if job.status == SyncJobStatus.COMPLETED else 0,
                        failed_runs=1 if job.status == SyncJobStatus.FAILED else 0,
                        last_job=last_job,
                    )

            except Exception as e:
                ctx.logger.warning(f"Failed to get sync details: {e}")

        # Fetch entity summary if sync exists
        entities = None
        if hasattr(source_conn, "sync_id") and source_conn.sync_id:
            try:
                entity_counts = await crud.entity_count.get_counts_per_sync_and_type(
                    db, source_conn.sync_id
                )

                if entity_counts:
                    total_entities = sum(count_data.count for count_data in entity_counts)
                    by_type = {}
                    for count_data in entity_counts:
                        by_type[count_data.entity_definition_name] = schemas.EntityTypeStats(
                            count=count_data.count,
                            last_updated=count_data.modified_at,
                        )

                    entities = schemas.EntitySummary(
                        total_entities=total_entities,
                        by_type=by_type,
                    )
                else:
                    from contextd.models.entity import Entity

                    fallback_stmt = (
                        select(
                            Entity.entity_type,
                            func.count(Entity.id).label("count"),
                            func.max(Entity.modified_at).label("last_updated"),
                        )
                        .where(Entity.sync_id == source_conn.sync_id)
                        .group_by(Entity.entity_type)
                        .order_by(func.count(Entity.id).desc())
                    )
                    fallback_result = await db.execute(fallback_stmt)
                    by_type = {
                        (row.entity_type or "Entity"): schemas.EntityTypeStats(
                            count=row.count or 0,
                            last_updated=row.last_updated,
                            sync_status="synced",
                        )
                        for row in fallback_result
                    }
                    if by_type:
                        entities = schemas.EntitySummary(
                            total_entities=sum(item.count for item in by_type.values()),
                            by_type=by_type,
                        )
                    else:
                        entities = await self._fetch_job_entity_summary(
                            db,
                            sync_id=source_conn.sync_id,
                        )
            except Exception as e:
                ctx.logger.warning(f"Failed to get entity summary: {e}")

        # Compute status based on last job
        last_job_status = None
        if sync_details and sync_details.last_job:
            last_job_status = sync_details.last_job.status

        # Get federated_search from source model
        federated_search = False
        try:
            source_model = await crud.source.get_by_short_name(db, source_conn.short_name)
            if source_model:
                federated_search = getattr(source_model, "federated_search", False)
        except Exception as e:
            ctx.logger.warning(f"Failed to get federated_search for {source_conn.short_name}: {e}")

        # Build and return the complete response
        drift = (source_conn.config_fields or {}).get("drift") if hasattr(
            source_conn, "config_fields"
        ) else None
        return schemas.SourceConnection(
            id=source_conn.id,
            name=source_conn.name,
            description=source_conn.description,
            short_name=source_conn.short_name,
            readable_collection_id=source_conn.readable_collection_id,
            status=compute_status(source_conn, last_job_status),
            created_at=source_conn.created_at,
            modified_at=source_conn.modified_at,
            auth=auth,
            config=source_conn.config_fields if hasattr(source_conn, "config_fields") else None,
            schedule=schedule,
            sync=sync_details,
            sync_id=getattr(source_conn, "sync_id", None),
            entities=entities,
            federated_search=federated_search,
            drift=drift,
        )

    def compute_status_from_data(
        self,
        is_authenticated: bool,
        is_active: bool = True,
        last_job_status: Optional[SyncJobStatus] = None,
    ) -> SourceConnectionStatus:
        """Compute status from provided data without accessing ORM object."""
        from contextd.core.shared_models import SourceConnectionStatus

        if not is_authenticated:
            return SourceConnectionStatus.PENDING_AUTH

        # Check if manually disabled
        if not is_active:
            return SourceConnectionStatus.INACTIVE

        # Check last job status
        if last_job_status:
            if last_job_status == SyncJobStatus.RUNNING:
                return SourceConnectionStatus.SYNCING
            elif last_job_status == SyncJobStatus.FAILED:
                return SourceConnectionStatus.ERROR

        return SourceConnectionStatus.ACTIVE

    async def bulk_fetch_last_sync_info(
        self, db: AsyncSession, sync_ids: List[UUID], ctx: ApiContext
    ) -> Dict[UUID, Dict[str, Any]]:
        """Bulk fetch last sync information including job status."""
        # Get last sync jobs with their status
        subq = (
            select(
                SyncJob.sync_id,
                SyncJob.status,
                SyncJob.completed_at,
                func.row_number()
                .over(partition_by=SyncJob.sync_id, order_by=SyncJob.created_at.desc())
                .label("rn"),
            )
            .where(SyncJob.sync_id.in_(sync_ids))
            .subquery()
        )

        query = select(subq).where(subq.c.rn == 1)
        result = await db.execute(query)

        # Get next scheduled runs
        syncs = await db.execute(select(Sync).where(Sync.id.in_(sync_ids)))
        sync_schedules = {s.id: s.next_scheduled_run for s in syncs.scalars()}

        return {
            row.sync_id: {
                "last_sync_at": row.completed_at,
                "next_sync_at": sync_schedules.get(row.sync_id),
                "last_job_status": row.status,
            }
            for row in result
        }

    async def _fetch_job_entity_summary(
        self,
        db: AsyncSession,
        *,
        sync_id: UUID,
    ) -> Optional[schemas.EntitySummary]:
        """Infer the last known entity summary from completed sync jobs.

        The normal read path uses EntityCount or Entity rows. Structured
        connectors can commit directly to the graph before those rows exist, so
        this fallback keeps source/detail pages aligned with the graph state.
        """
        result = await db.execute(
            select(
                SyncJob.entities_inserted,
                SyncJob.entities_updated,
                SyncJob.entities_deleted,
                SyncJob.entities_kept,
                SyncJob.entities_encountered,
                SyncJob.completed_at,
            )
            .where(SyncJob.sync_id == sync_id)
            .where(SyncJob.status == SyncJobStatus.COMPLETED.value)
            .order_by(SyncJob.created_at.desc())
        )

        for row in result:
            encountered = row.entities_encountered if isinstance(row.entities_encountered, dict) else {}
            by_type = {
                str(entity_type): schemas.EntityTypeStats(
                    count=int(count or 0),
                    last_updated=row.completed_at,
                    sync_status="synced",
                )
                for entity_type, count in encountered.items()
                if isinstance(count, (int, float)) and int(count or 0) > 0
            }
            if by_type:
                return schemas.EntitySummary(
                    total_entities=sum(item.count for item in by_type.values()),
                    by_type=by_type,
                )

            observed_total = (
                (row.entities_inserted or 0)
                + (row.entities_updated or 0)
                + (row.entities_kept or 0)
                - (row.entities_deleted or 0)
            )
            if observed_total > 0:
                return schemas.EntitySummary(
                    total_entities=observed_total,
                    by_type={
                        "Entity": schemas.EntityTypeStats(
                            count=observed_total,
                            last_updated=row.completed_at,
                            sync_status="synced",
                        )
                    },
                )

        return None

    async def bulk_fetch_entity_counts(
        self, db: AsyncSession, sync_ids: List[UUID], ctx: ApiContext
    ) -> Dict[UUID, int]:
        """Bulk fetch total entity counts from EntityCount table."""
        from contextd.models.entity_count import EntityCount

        query = (
            select(EntityCount.sync_id, func.sum(EntityCount.count).label("total_count"))
            .where(EntityCount.sync_id.in_(sync_ids))
            .group_by(EntityCount.sync_id)
        )
        result = await db.execute(query)
        return {row.sync_id: row.total_count or 0 for row in result}

    def sync_job_to_source_connection_job(
        self, job: Any, source_connection_id: UUID
    ) -> SourceConnectionJob:
        """Convert sync job to source connection job."""
        return SourceConnectionJob(
            id=job.id,
            source_connection_id=source_connection_id,
            status=job.status,
            started_at=job.started_at,
            completed_at=job.completed_at,
            duration_seconds=(
                (job.completed_at - job.started_at).total_seconds()
                if job.completed_at and job.started_at
                else None
            ),
            entities_inserted=getattr(job, "entities_inserted", 0),
            entities_updated=getattr(job, "entities_updated", 0),
            entities_deleted=getattr(job, "entities_deleted", 0),
            entities_failed=getattr(job, "entities_failed", 0),
            error=job.error if hasattr(job, "error") else None,
        )
