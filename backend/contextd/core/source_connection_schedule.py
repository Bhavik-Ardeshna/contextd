"""Scheduling helpers for source connection service."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException

from contextd import crud, schemas
from contextd.api.context import ApiContext


class SourceConnectionScheduleMixin:
    """Schedule selection and update helpers for source connections."""

    def _get_default_daily_cron_schedule(self, ctx: ApiContext) -> str:
        """Generate a default daily cron schedule based on current UTC time.

        Returns:
            A cron expression for daily execution at the current UTC time.
        """
        from datetime import timezone

        now_utc = datetime.now(timezone.utc)
        minute = now_utc.minute
        hour = now_utc.hour
        # Format: minute hour day_of_month month day_of_week
        # e.g., "30 14 * * *" = run at 14:30 every day
        cron_schedule = f"{minute} {hour} * * *"
        ctx.logger.info(
            f"No cron schedule provided, defaulting to daily at {hour:02d}:{minute:02d} UTC"
        )
        return cron_schedule

    def _get_default_continuous_cron_schedule(self, ctx: ApiContext) -> str:
        """Get default cron schedule for continuous sources.

        Returns:
            A cron expression for 5-minute intervals.
        """
        ctx.logger.info("Continuous source defaulting to 5-minute schedule")
        return "*/5 * * * *"

    def _determine_schedule_for_source(
        self, obj_in: Any, source: schemas.Source, ctx: ApiContext
    ) -> Optional[str]:
        """Determine the appropriate schedule based on source type and input.

        Args:
            obj_in: The source connection creation input
            source: The source model
            ctx: API context

        Returns:
            CRON schedule string or None if no schedule should be created
        """
        # Check if schedule has a cron value first
        if hasattr(obj_in, "schedule") and obj_in.schedule and hasattr(obj_in.schedule, "cron"):
            # If cron is explicitly None, no schedule
            if obj_in.schedule.cron is None:
                ctx.logger.info("Schedule cron explicitly set to null, no schedule will be created")
                return None
            return obj_in.schedule.cron

        # For auth provider connections, schedule is typically omitted and becomes None
        # We should still create default schedules for these
        # The only way to explicitly disable schedule is to pass schedule: {cron: null}

        # Determine defaults based on source type
        if getattr(source, "supports_continuous", False):
            return self._get_default_continuous_cron_schedule(ctx)
        else:
            # For regular sources, default to daily
            return self._get_default_daily_cron_schedule(ctx)

    def _validate_cron_schedule_for_source(
        self, cron_schedule: str, source: schemas.Source, ctx: ApiContext
    ) -> None:
        """Validate CRON schedule based on source capabilities.

        Args:
            cron_schedule: The CRON expression to validate
            source: The source model
            ctx: API context

        Raises:
            HTTPException: If the schedule is invalid for the source
        """
        import re

        if not cron_schedule:
            return

        # Parse the CRON expression to check if it's minute-level
        # We need to distinguish between:
        # - "*/N * * * *" where N < 60 - runs every N minutes (minute-level)
        # - "* * * * *" - runs every minute (minute-level)
        # - "0 * * * *" - runs at minute 0 of every hour (hourly, not minute-level)
        # - "30 2 * * *" - runs at 2:30 AM daily (daily, not minute-level)

        # Check for patterns that run more frequently than hourly
        # Pattern 1: */N where N < 60 (e.g., */5, */15, */30)
        interval_pattern = r"^\*/([1-5]?[0-9]) \* \* \* \*$"
        match = re.match(interval_pattern, cron_schedule)

        if match:
            interval = int(match.group(1))
            if interval < 60:
                # This is sub-hourly (minute-level)
                if not source.supports_continuous:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Source '{source.short_name}' does not support continuous syncs. "
                        f"Minimum schedule interval is 1 hour (e.g., '0 * * * *' for hourly).",
                    )
                # For continuous sources, sub-hourly is allowed
                ctx.logger.info(
                    f"Source '{source.short_name}' supports continuous syncs, "
                    f"allowing minute-level schedule: {cron_schedule}"
                )
                return

        # Pattern 2: * * * * * (every minute)
        if cron_schedule == "* * * * *":
            if not source.supports_continuous:
                raise HTTPException(
                    status_code=400,
                    detail=f"Source '{source.short_name}' does not support continuous syncs. "
                    f"Minimum schedule interval is 1 hour (e.g., '0 * * * *' for hourly).",
                )
            ctx.logger.info(
                f"Source '{source.short_name}' supports continuous syncs, "
                f"allowing every-minute schedule: {cron_schedule}"
            )

        # All other patterns (including "0 * * * *" for hourly) are allowed

    async def _create_temporal_schedule_if_needed(
        self,
        uow,
        cron_schedule: Optional[str],
        sync_id: Optional[UUID],
        ctx: ApiContext,
    ) -> None:
        """Create Temporal schedule if we have both a cron schedule and sync_id.

        Args:
            uow: Unit of work
            cron_schedule: CRON expression
            sync_id: Sync ID
            ctx: API context
        """
        if cron_schedule and sync_id:
            from contextd.platform.temporal.schedule_service import temporal_schedule_service

            await temporal_schedule_service.create_or_update_schedule(
                sync_id=sync_id,
                cron_schedule=cron_schedule,
                db=uow.session,
                ctx=ctx,
                uow=uow,
            )

    async def _handle_schedule_update(
        self,
        uow,
        source_conn,
        update_data: dict,
        ctx: ApiContext,
    ) -> None:
        """Handle schedule updates for a source connection.

        This method handles three cases:
        1. Updating an existing sync's schedule
        2. Creating a new sync when adding a schedule to a connection without one
        3. Removing a schedule (setting cron to None)

        Args:
            uow: Unit of work
            source_conn: Source connection being updated
            update_data: Update data dictionary (modified in place)
            ctx: API context
        """
        if "schedule" not in update_data:
            return

        # If schedule is None, treat it as removing the schedule
        if update_data["schedule"] is None:
            new_cron = None
        else:
            new_cron = update_data["schedule"].get("cron")

        if source_conn.sync_id:
            # Update existing sync's schedule
            if new_cron:
                # Get the source to validate schedule
                source = await self._get_and_validate_source(uow.session, source_conn.short_name)
                self._validate_cron_schedule_for_source(new_cron, source, ctx)
            await self._update_sync_schedule(
                uow.session,
                source_conn.sync_id,
                new_cron,
                ctx,
                uow,
            )
        elif new_cron:
            # No sync exists but we're adding a schedule - create a new sync
            # Get the source to validate schedule
            source = await self._get_and_validate_source(uow.session, source_conn.short_name)
            self._validate_cron_schedule_for_source(new_cron, source, ctx)

            # Check if connection_id exists (might be None for OAuth flows)
            if not source_conn.connection_id:
                ctx.logger.warning(
                    f"Cannot create schedule for SC {source_conn.id} without connection_id"
                )
                # Skip schedule creation for connections without connection_id
                del update_data["schedule"]
                return

            # Get the collection
            collection = await self._get_collection(
                uow.session, source_conn.readable_collection_id, ctx
            )

            # Create a new sync with the schedule
            sync, _ = await self._create_sync_without_schedule(
                uow.session,
                source_conn.name,
                source_conn.connection_id,
                collection.id,
                collection.readable_id,
                new_cron,
                False,  # Don't run immediately on update
                ctx,
                uow,
            )

            # Apply the sync_id update to the source connection now
            # so that temporal_schedule_service can find it
            source_conn = await crud.source_connection.update(
                uow.session,
                db_obj=source_conn,
                obj_in={"sync_id": sync.id},
                ctx=ctx,
                uow=uow,
            )
            await uow.session.flush()

            # Create the Temporal schedule
            from contextd.platform.temporal.schedule_service import (
                temporal_schedule_service,
            )

            await temporal_schedule_service.create_or_update_schedule(
                sync_id=sync.id,
                cron_schedule=new_cron,
                db=uow.session,
                ctx=ctx,
                uow=uow,
            )

        if "schedule" in update_data:
            del update_data["schedule"]
