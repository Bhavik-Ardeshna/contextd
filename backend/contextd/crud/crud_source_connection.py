"""Refactored CRUD operations for source connections with optimized queries."""

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from contextd.api.context import ApiContext
from contextd.core.shared_models import SourceConnectionStatus, SyncJobStatus
from contextd.models.connection import Connection
from contextd.models.source_connection import SourceConnection
from contextd.models.sync import Sync
from contextd.models.sync_job import SyncJob
from contextd.schemas.source_connection import (
    SourceConnectionUpdate,
)

from ._base_organization import CRUDBaseOrganization


class CRUDSourceConnection(
    CRUDBaseOrganization[SourceConnection, Dict[str, Any], SourceConnectionUpdate]
):
    """Refactored CRUD with optimized queries and clean abstractions.

    Key improvements:
    - Bulk fetching to avoid N+1 queries
    - Optimized joins for related data
    - Clean separation of concerns
    - No exposure of internal sync/job IDs
    """

    async def get_with_relations(
        self,
        db: AsyncSession,
        *,
        id: UUID,
        ctx: ApiContext,
        include_sync: bool = False,
        include_collection: bool = False,
        include_credential: bool = False,
    ) -> Optional[SourceConnection]:
        """Get source connection with optional eager loading of relations."""
        query = select(SourceConnection).where(
            and_(
                SourceConnection.id == id,
                SourceConnection.organization_id == ctx.organization.id,
            )
        )

        # Add eager loading based on requirements
        if include_sync:
            query = query.options(joinedload(SourceConnection.sync))
        if include_collection:
            query = query.options(joinedload(SourceConnection.sync).joinedload(Sync.collection))
        if include_credential:
            query = query.options(
                joinedload(SourceConnection.connection).joinedload(
                    Connection.integration_credential
                )
            )

        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def get_multi_with_stats(
        self,
        db: AsyncSession,
        *,
        ctx: ApiContext,
        collection_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get source connections with all necessary stats in minimal queries.

        Returns list of dictionaries with complete data for the list endpoint.
        """
        # 1. Get base source connections
        query = select(SourceConnection).where(
            SourceConnection.organization_id == ctx.organization.id
        )

        if collection_id:
            query = query.where(SourceConnection.readable_collection_id == collection_id)

        query = query.offset(skip).limit(limit).order_by(SourceConnection.created_at.desc())
        result = await db.execute(query)
        source_connections = list(result.scalars().all())

        if not source_connections:
            return []

        # 2. Bulk fetch all related data
        # These queries can run independently
        auth_methods = await self._fetch_auth_methods(db, source_connections)
        last_jobs = await self._fetch_last_jobs(db, source_connections)
        entity_counts = await self._fetch_entity_counts(db, source_connections)
        federated_search_flags = await self._fetch_federated_search_flags(db, source_connections)

        # 3. Combine into response dictionaries
        results = []
        for sc in source_connections:
            last_job = last_jobs.get(sc.id) or {}
            entity_count = entity_counts.get(sc.id, 0)
            if not entity_count and last_job:
                entity_count = (
                    (last_job.get("entities_inserted") or 0)
                    + (last_job.get("entities_updated") or 0)
                    - (last_job.get("entities_deleted") or 0)
                )
            drift_summary = (sc.config_fields or {}).get("drift") or {}
            last_successful_sync_at = (
                last_job.get("last_successful_completed_at")
                or (
                    last_job.get("completed_at")
                    if last_job.get("status") == SyncJobStatus.COMPLETED.value
                    else None
                )
            )
            results.append(
                {
                    # Base fields
                    "id": sc.id,
                    "name": sc.name,
                    "short_name": sc.short_name,
                    "readable_collection_id": sc.readable_collection_id,
                    "created_at": sc.created_at,
                    "modified_at": sc.modified_at,
                    "is_authenticated": sc.is_authenticated,
                    "readable_auth_provider_id": sc.readable_auth_provider_id,
                    "connection_init_session_id": sc.connection_init_session_id,
                    "is_active": getattr(sc, "is_active", True),
                    # Fetched data
                    "authentication_method": auth_methods.get(sc.id),
                    "last_job": last_job,
                    "last_job_status": last_job.get("status"),
                    "last_sync_started_at": last_job.get("started_at"),
                    "last_sync_at": last_successful_sync_at,
                    "entity_count": max(entity_count, 0),
                    "federated_search": federated_search_flags.get(sc.short_name, False),
                    "drift_status": drift_summary.get("status") or drift_summary.get("severity"),
                    "drift_summary": drift_summary,
                }
            )

        return results

    async def _attach_last_sync_info_bulk(
        self,
        db: AsyncSession,
        source_connections: List[SourceConnection],
    ) -> None:
        """Efficiently attach last sync job info to multiple connections."""
        sync_ids = [sc.sync_id for sc in source_connections if sc.sync_id]
        if not sync_ids:
            return

        # Get latest sync job for each sync in one query
        subq = (
            select(
                SyncJob.sync_id,
                SyncJob.id,
                SyncJob.status,
                SyncJob.started_at,
                SyncJob.completed_at,
                SyncJob.entities_inserted,
                SyncJob.entities_updated,
                SyncJob.entities_deleted,
                SyncJob.entities_kept,
                SyncJob.entities_skipped,
                SyncJob.error,
                func.row_number()
                .over(partition_by=SyncJob.sync_id, order_by=SyncJob.created_at.desc())
                .label("rn"),
            )
            .where(SyncJob.sync_id.in_(sync_ids))
            .subquery()
        )

        query = select(subq).where(subq.c.rn == 1)
        result = await db.execute(query)

        # Map sync_id to last job info
        last_jobs = {
            row.sync_id: {
                "id": row.id,
                "status": row.status,
                "started_at": row.started_at,
                "completed_at": row.completed_at,
                "duration_seconds": (
                    (row.completed_at - row.started_at).total_seconds()
                    if row.completed_at and row.started_at
                    else None
                ),
                "entities_inserted": row.entities_inserted or 0,
                "entities_updated": row.entities_updated or 0,
                "entities_deleted": row.entities_deleted or 0,
                "entities_kept": row.entities_kept or 0,
                "entities_skipped": row.entities_skipped or 0,
                "error": row.error,
            }
            for row in result
        }

        # Attach to source connections
        for sc in source_connections:
            if sc.sync_id and sc.sync_id in last_jobs:
                sc._last_sync_job = last_jobs[sc.sync_id]

                # Update status based on last job
                if not sc.is_authenticated:
                    sc.status = SourceConnectionStatus.PENDING_AUTH
                elif sc._last_sync_job["status"] == SyncJobStatus.FAILED:
                    sc.status = SourceConnectionStatus.ERROR
                elif sc._last_sync_job["status"] in (
                    SyncJobStatus.RUNNING,
                    SyncJobStatus.CANCELLING,
                ):
                    sc.status = SourceConnectionStatus.SYNCING
                else:
                    sc.status = SourceConnectionStatus.ACTIVE
            else:
                sc.status = SourceConnectionStatus.PENDING_SYNC

    async def _fetch_auth_methods(
        self, db: AsyncSession, source_conns: List[SourceConnection]
    ) -> Dict[UUID, str]:
        """Fetch authentication methods from credentials."""
        from contextd.models.connection import Connection
        from contextd.models.integration_credential import IntegrationCredential

        conn_ids = [sc.connection_id for sc in source_conns if sc.connection_id]
        if not conn_ids:
            return {}

        query = (
            select(SourceConnection.id, IntegrationCredential.authentication_method)
            .join(Connection, SourceConnection.connection_id == Connection.id)
            .join(
                IntegrationCredential,
                Connection.integration_credential_id == IntegrationCredential.id,
            )
            .where(SourceConnection.id.in_([sc.id for sc in source_conns]))
        )

        result = await db.execute(query)
        auth_methods = {}

        for row in result:
            # Store the raw authentication method string
            auth_methods[row[0]] = row[1]

        # Also check for auth provider connections
        for sc in source_conns:
            if hasattr(sc, "readable_auth_provider_id") and sc.readable_auth_provider_id:
                auth_methods[sc.id] = "auth_provider"

        return auth_methods

    async def _fetch_last_jobs(
        self, db: AsyncSession, source_conns: List[SourceConnection]
    ) -> Dict[UUID, Dict]:
        """Fetch last sync job for each connection."""
        sync_ids = [sc.sync_id for sc in source_conns if sc.sync_id]
        if not sync_ids:
            return {}

        # Use window function to get latest job per sync
        subq = (
            select(
                SyncJob.sync_id,
                SyncJob.status,
                SyncJob.started_at,
                SyncJob.completed_at,
                SyncJob.entities_inserted,
                SyncJob.entities_updated,
                SyncJob.entities_deleted,
                func.row_number()
                .over(partition_by=SyncJob.sync_id, order_by=SyncJob.created_at.desc())
                .label("rn"),
            )
            .where(SyncJob.sync_id.in_(sync_ids))
            .subquery()
        )

        query = select(subq).where(subq.c.rn == 1)
        result = await db.execute(query)

        completed_subq = (
            select(
                SyncJob.sync_id,
                SyncJob.id,
                SyncJob.completed_at,
                func.row_number()
                .over(
                    partition_by=SyncJob.sync_id,
                    order_by=[
                        SyncJob.completed_at.desc().nulls_last(),
                        SyncJob.created_at.desc(),
                    ],
                )
                .label("rn"),
            )
            .where(SyncJob.sync_id.in_(sync_ids))
            .where(SyncJob.status == SyncJobStatus.COMPLETED.value)
            .where(SyncJob.completed_at.isnot(None))
            .subquery()
        )
        completed_result = await db.execute(
            select(completed_subq).where(completed_subq.c.rn == 1)
        )
        last_success_by_sync = {
            row.sync_id: {
                "id": row.id,
                "completed_at": row.completed_at,
            }
            for row in completed_result
        }

        # Map to source connection IDs
        sync_to_sc = {sc.sync_id: sc.id for sc in source_conns if sc.sync_id}
        return {
            sync_to_sc[row.sync_id]: {
                "status": row.status,
                "started_at": row.started_at,
                "completed_at": row.completed_at,
                "last_successful_job_id": (
                    last_success_by_sync.get(row.sync_id, {}).get("id")
                ),
                "last_successful_completed_at": (
                    last_success_by_sync.get(row.sync_id, {}).get("completed_at")
                ),
                "entities_inserted": row.entities_inserted,
                "entities_updated": row.entities_updated,
                "entities_deleted": row.entities_deleted,
            }
            for row in result
            if row.sync_id in sync_to_sc
        }

    async def _fetch_entity_counts(
        self, db: AsyncSession, source_conns: List[SourceConnection]
    ) -> Dict[UUID, int]:
        """Fetch total entity counts.

        EntityCount is the fast path for sources that maintain typed count rows.
        Some structured database connectors emit normalized Entity rows directly
        before EntityCount materialization exists, so fall back to the entity table
        to keep operational views honest.
        """
        from contextd.models.entity import Entity
        from contextd.models.entity_count import EntityCount

        sync_ids = [sc.sync_id for sc in source_conns if sc.sync_id]
        if not sync_ids:
            return {}

        query = (
            select(EntityCount.sync_id, func.sum(EntityCount.count).label("total"))
            .where(EntityCount.sync_id.in_(sync_ids))
            .group_by(EntityCount.sync_id)
        )

        result = await db.execute(query)

        sync_to_sc = {sc.sync_id: sc.id for sc in source_conns if sc.sync_id}
        counts_by_sync: Dict[UUID, int] = {
            row.sync_id: int(row.total or 0) for row in result if row.sync_id in sync_to_sc
        }

        # EntityCount rows can be partial while a structured connector is replaying
        # or when an older sync used a dynamic entity class name. Compare them with
        # the live normalized entity rows and the latest completed job observation so
        # dashboard/source APIs never under-report a finished graph.
        live_result = await db.execute(
            select(Entity.sync_id, func.count(Entity.id).label("total"))
            .where(Entity.sync_id.in_(sync_ids))
            .group_by(Entity.sync_id)
        )
        for row in live_result:
            if row.sync_id in sync_to_sc:
                counts_by_sync[row.sync_id] = max(counts_by_sync.get(row.sync_id, 0), row.total or 0)

        state_totals = await self._fetch_sync_state_entity_totals(db, sync_ids)
        for sync_id, total in state_totals.items():
            if sync_id in sync_to_sc:
                counts_by_sync[sync_id] = max(counts_by_sync.get(sync_id, 0), total)

        job_totals = await self._fetch_job_entity_totals(db, sync_ids)
        for sync_id, total in job_totals.items():
            if sync_id in sync_to_sc:
                counts_by_sync[sync_id] = max(counts_by_sync.get(sync_id, 0), total)

        counts = {
            sync_to_sc[sync_id]: count
            for sync_id, count in counts_by_sync.items()
            if sync_id in sync_to_sc
        }

        return counts

    async def _fetch_sync_state_entity_totals(
        self, db: AsyncSession, sync_ids: List[UUID]
    ) -> Dict[UUID, int]:
        """Read merged entity totals from the latest sync state per sync."""
        if not sync_ids:
            return {}

        from contextd.models.sync_state import SyncState

        subq = (
            select(
                SyncState.sync_id,
                SyncState.state_data,
                func.row_number()
                .over(partition_by=SyncState.sync_id, order_by=SyncState.created_at.desc())
                .label("rn"),
            )
            .where(SyncState.sync_id.in_(sync_ids))
            .subquery()
        )
        result = await db.execute(select(subq).where(subq.c.rn == 1))

        totals: Dict[UUID, int] = {}
        for row in result:
            state_data = row.state_data if isinstance(row.state_data, dict) else {}
            statistics = state_data.get("statistics") if isinstance(state_data, dict) else {}
            if not isinstance(statistics, dict):
                continue
            total = int(statistics.get("total_entities") or 0)
            if total > 0:
                totals[row.sync_id] = total
        return totals

    async def _fetch_job_entity_totals(
        self, db: AsyncSession, sync_ids: List[UUID]
    ) -> Dict[UUID, int]:
        """Infer last known entity totals from completed sync jobs.

        EntityCount/Entity rows are the source of truth. This fallback covers
        graph-native structured connectors while count materialization catches up.
        It deliberately uses the latest non-zero observation so idempotent retries
        with zero deltas do not erase the visible current state.
        """
        if not sync_ids:
            return {}

        result = await db.execute(
            select(
                SyncJob.sync_id,
                SyncJob.entities_inserted,
                SyncJob.entities_updated,
                SyncJob.entities_deleted,
                SyncJob.entities_kept,
                SyncJob.entities_encountered,
            )
            .where(SyncJob.sync_id.in_(sync_ids))
            .where(SyncJob.status == SyncJobStatus.COMPLETED.value)
            .order_by(SyncJob.sync_id, SyncJob.created_at.desc())
        )

        totals: Dict[UUID, int] = {}
        for row in result:
            if row.sync_id in totals:
                continue
            encountered = row.entities_encountered if isinstance(row.entities_encountered, dict) else {}
            encountered_total = sum(
                int(value or 0) for value in encountered.values() if isinstance(value, (int, float))
            )
            observed_total = max(
                encountered_total,
                (row.entities_inserted or 0)
                + (row.entities_updated or 0)
                + (row.entities_kept or 0)
                - (row.entities_deleted or 0),
            )
            if observed_total > 0:
                totals[row.sync_id] = observed_total

        return totals

    async def _fetch_federated_search_flags(
        self, db: AsyncSession, source_conns: List[SourceConnection]
    ) -> Dict[str, bool]:
        """Fetch federated_search flags from Source table by short_name."""
        from contextd.models.source import Source

        short_names = {sc.short_name for sc in source_conns}
        if not short_names:
            return {}

        query = select(Source.short_name, Source.federated_search).where(
            Source.short_name.in_(short_names)
        )

        result = await db.execute(query)

        # Map short_name to federated_search flag
        return {row.short_name: row.federated_search or False for row in result}

    async def get_by_query_and_org(
        self,
        db: AsyncSession,
        ctx: ApiContext,
        **kwargs,
    ) -> Optional[SourceConnection]:
        """Get source connection by arbitrary query within organization scope."""
        query = select(SourceConnection).where(
            SourceConnection.organization_id == ctx.organization.id
        )

        for key, value in kwargs.items():
            if hasattr(SourceConnection, key):
                query = query.where(getattr(SourceConnection, key) == value)

        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def bulk_update_status(
        self,
        db: AsyncSession,
        *,
        ids: List[UUID],
        status: SourceConnectionStatus,
        ctx: ApiContext,
    ) -> int:
        """Bulk update status for multiple source connections."""
        query = select(SourceConnection).where(
            and_(
                SourceConnection.id.in_(ids),
                SourceConnection.organization_id == ctx.organization.id,
            )
        )

        result = await db.execute(query)
        source_connections = result.scalars().all()

        for sc in source_connections:
            sc.status = status

        await db.commit()
        return len(source_connections)

    async def get_schedule_info(
        self,
        db: AsyncSession,
        source_connection: SourceConnection,
    ) -> Optional[Dict[str, Any]]:
        """Get schedule information for a source connection."""
        if not source_connection.sync_id:
            return None

        sync = await db.get(Sync, source_connection.sync_id)
        if not sync:
            return None

        # Convert naive UTC datetime to timezone-aware for proper serialization
        next_run_at = None
        if sync.next_scheduled_run:
            from datetime import timezone

            # Database stores naive UTC, make it timezone-aware
            next_run_at = sync.next_scheduled_run.replace(tzinfo=timezone.utc)

        from sqlalchemy import select

        from contextd.models.sync_cursor import SyncCursor

        cursor = None
        cursor_result = await db.execute(
            select(SyncCursor).where(SyncCursor.sync_id == source_connection.sync_id)
        )
        cursor = cursor_result.scalar_one_or_none()
        sync_metadata = sync.sync_metadata or {}

        return {
            "cron_expression": sync.cron_schedule,
            "next_run_at": next_run_at,
            "is_continuous": bool(sync_metadata.get("continuous"))
            or sync.sync_type == "incremental",
            "cursor_field": sync_metadata.get("cursor_field")
            or (cursor.cursor_field if cursor else None),
            "cursor_value": cursor.cursor_data if cursor else None,
        }

    async def get_entity_states(
        self,
        db: AsyncSession,
        source_connection: SourceConnection,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get entity state information for a source connection.

        Uses EntityCount when available, then falls back to normalized Entity rows
        grouped by entity_type for structured-source syncs.
        """
        if not source_connection.sync_id:
            return []

        from contextd import crud
        from contextd.models.entity import Entity
        from contextd.models.sync_state import SyncState

        state_result = await db.execute(
            select(SyncState.state_data)
            .where(SyncState.sync_id == source_connection.sync_id)
            .where(SyncState.organization_id == source_connection.organization_id)
            .order_by(SyncState.created_at.desc())
            .limit(1)
        )
        state_data = state_result.scalar_one_or_none()
        if isinstance(state_data, dict):
            statistics = state_data.get("statistics") or {}
            entities_by_type = statistics.get("entities_by_type") if isinstance(statistics, dict) else {}
            if isinstance(entities_by_type, dict) and entities_by_type:
                return [
                    {
                        "entity_type": entity_type,
                        "total_count": int(total or 0),
                        "last_updated_at": None,
                        "sync_status": "synced",
                    }
                    for entity_type, total in sorted(
                        entities_by_type.items(),
                        key=lambda item: int(item[1] or 0),
                        reverse=True,
                    )[:limit]
                    if int(total or 0) > 0
                ]

        entity_counts = await crud.entity_count.get_counts_per_sync_and_type(
            db, source_connection.sync_id
        )
        if entity_counts:
            return [
                {
                    "entity_type": count.entity_definition_name,
                    "total_count": count.count,
                    "last_updated_at": count.modified_at,
                    "sync_status": "synced",
                }
                for count in entity_counts
            ]

        fallback_query = (
            select(
                Entity.entity_type,
                func.count(Entity.id).label("total"),
                func.max(Entity.modified_at).label("last_updated_at"),
            )
            .where(Entity.sync_id == source_connection.sync_id)
            .group_by(Entity.entity_type)
            .order_by(func.count(Entity.id).desc())
            .limit(limit)
        )
        result = await db.execute(fallback_query)

        return [
            {
                "entity_type": row.entity_type or "Entity",
                "total_count": row.total or 0,
                "last_updated_at": row.last_updated_at,
                "sync_status": "synced",
            }
            for row in result
        ]

    async def count_by_status(
        self,
        db: AsyncSession,
        *,
        ctx: ApiContext,
        collection_id: Optional[str] = None,
    ) -> Dict[SourceConnectionStatus, int]:
        """Count source connections by status."""
        query = (
            select(
                SourceConnection.status,
                func.count(SourceConnection.id).label("count"),
            )
            .where(SourceConnection.organization_id == ctx.organization.id)
            .group_by(SourceConnection.status)
        )

        if collection_id:
            query = query.where(SourceConnection.readable_collection_id == collection_id)

        result = await db.execute(query)
        return {row.status: row.count for row in result}

    async def get_for_collection(
        self,
        db: AsyncSession,
        *,
        readable_collection_id: str,
        ctx: ApiContext,
        skip: int = 0,
        limit: int = 100,
    ) -> List[SourceConnection]:
        """Get all source connections for a collection."""
        query = select(SourceConnection).where(
            and_(
                SourceConnection.readable_collection_id == readable_collection_id,
                SourceConnection.organization_id == ctx.organization.id,
            )
        )
        query = query.offset(skip).limit(limit).order_by(SourceConnection.created_at.desc())
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_by_sync_id(
        self,
        db: AsyncSession,
        *,
        sync_id: UUID,
        ctx: ApiContext,
    ) -> Optional[SourceConnection]:
        """Get a source connection by sync ID."""
        query = select(SourceConnection).where(
            and_(
                SourceConnection.sync_id == sync_id,
                SourceConnection.organization_id == ctx.organization.id,
            )
        )
        result = await db.execute(query)
        source_connection = result.scalar_one_or_none()
        if not source_connection:
            return None

        await self._validate_organization_access(ctx, source_connection.organization_id)
        return source_connection


# Singleton instance
source_connection = CRUDSourceConnection(SourceConnection)
