"""Sync state publisher for Redis pubsub updates.

This module handles publishing entity state to Redis pubsub.
It reads state from EntityTracker and publishes to:
- sync_job channel (simple progress stats)
- sync_job_state channel (detailed breakdown)

Separated from EntityTracker to follow single responsibility principle:
- EntityTracker: tracks state (pure data)
- SyncStatePublisher: publishes state (side effects)
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from contextd.core.pubsub import core_pubsub
from contextd.core.redis_client import redis_client
from contextd.core.shared_models import SyncJobStatus
from contextd.schemas.sync_pubsub import (
    EntityStateUpdate,
    SyncCompleteMessage,
    SyncProgressUpdate,
)

if TYPE_CHECKING:
    from contextd.core.logging import ContextualLogger
    from contextd.platform.sync.pipeline.entity_tracker import EntityTracker


class SyncStatePublisher:
    """Publishes sync state to Redis pubsub.

    Reads current state from EntityTracker and publishes to Redis.
    Handles throttling via thresholds.
    """

    def __init__(
        self,
        job_id: UUID,
        sync_id: UUID,
        entity_tracker: "EntityTracker",
        logger: "ContextualLogger",
        publish_threshold: int = 3,
    ):
        """Initialize the state publisher.

        Args:
            job_id: The sync job ID
            sync_id: The sync ID
            entity_tracker: The entity tracker to read state from
            logger: Contextual logger
            publish_threshold: Number of operations before publishing progress
        """
        self.job_id = job_id
        self.sync_id = sync_id
        self._tracker = entity_tracker
        self.logger = logger
        self._publish_threshold = publish_threshold

        # Publishing state
        self._last_published_ops = 0
        self._last_status_update_ops = 0
        self._status_update_interval = 50
        self._start_time = asyncio.get_running_loop().time()

    async def check_and_publish(self) -> None:
        """Check thresholds and publish progress if needed."""
        stats = self._tracker.get_stats()
        total_ops = stats.total_operations

        # Check progress threshold
        if total_ops - self._last_published_ops >= self._publish_threshold:
            await self.publish_progress()
            self._last_published_ops = total_ops

        # Check log interval
        if total_ops - self._last_status_update_ops >= self._status_update_interval:
            self._log_status_update(stats)
            self._last_status_update_ops = total_ops

    async def publish_progress(self) -> None:
        """Publish simple progress stats to sync_job channel.

        This replicates the legacy SyncProgress._publish behavior.
        """
        stats = self._tracker.get_stats()

        # Create progress update model
        update = SyncProgressUpdate(
            inserted=stats.inserted,
            updated=stats.updated,
            deleted=stats.deleted,
            kept=stats.kept,
            skipped=stats.skipped,
            last_update_timestamp=datetime.now(timezone.utc).isoformat(),
        )

        data = update.model_dump()

        # Publish to sync_job
        await core_pubsub.publish("sync_job", self.job_id, data)

        # Store snapshot for cleanup job
        snapshot_key = f"sync_progress_snapshot:{self.job_id}"
        await redis_client.client.setex(
            snapshot_key,
            1800,  # 30 min TTL
            json.dumps(data),
        )

        # Also publish detailed state occasionally?
        # For now, let's keep them somewhat coupled or caller decides.
        # Ideally, we publish state less frequently than progress.
        # But for simplicity, let's publish state whenever we publish progress
        # to keep the UI fully in sync.
        await self.publish_state()

    async def publish_state(self) -> None:
        """Publish detailed entity state to sync_job_state channel."""
        counts_named = self._tracker.get_named_counts()
        total_entities = self._tracker.get_total_entities()

        state = EntityStateUpdate(
            job_id=self.job_id,
            sync_id=self.sync_id,
            entity_counts=counts_named,
            total_entities=total_entities,
            job_status=SyncJobStatus.RUNNING,
        )

        try:
            await core_pubsub.publish("sync_job_state", self.job_id, state.model_dump_json())
        except Exception as e:
            self.logger.error(f"Failed to publish entity state: {e}")

    async def publish_completion(
        self,
        status: SyncJobStatus,
        error: Optional[str] = None,
    ) -> None:
        """Publish final sync completion state.

        Publishes to BOTH channels to ensure final state is consistent.
        """
        # 1. Publish final progress (sync_job)
        stats = self._tracker.get_stats()
        update = SyncProgressUpdate(
            inserted=stats.inserted,
            updated=stats.updated,
            deleted=stats.deleted,
            kept=stats.kept,
            skipped=stats.skipped,
            status=status,
            last_update_timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await core_pubsub.publish("sync_job", self.job_id, update.model_dump())

        # 2. Publish final state (sync_job_state)
        counts_named = self._tracker.get_named_counts()
        total_entities = self._tracker.get_total_entities()
        total_operations = self._tracker.get_total_operations()

        is_complete = status == SyncJobStatus.COMPLETED
        is_failed = status == SyncJobStatus.FAILED
        error_msg = error if error else ("Sync failed" if is_failed else None)

        completion_msg = SyncCompleteMessage(
            job_id=self.job_id,
            sync_id=self.sync_id,
            is_complete=is_complete,
            is_failed=is_failed,
            final_counts=counts_named,
            total_entities=total_entities,
            total_operations=total_operations,
            final_status=status,
            error=error_msg,
        )

        try:
            await core_pubsub.publish(
                "sync_job_state", self.job_id, completion_msg.model_dump_json()
            )
        except Exception as e:
            self.logger.error(f"Failed to publish completion message: {e}")

        # Log final summary
        self._log_final_summary(status, stats, total_entities)

    def _log_status_update(self, stats) -> None:
        """Log periodic status update."""
        elapsed = asyncio.get_running_loop().time() - self._start_time
        rate = stats.total_operations / elapsed if elapsed > 0 else 0

        self.logger.info(
            f"📊 Progress: {stats.total_operations} ops ({rate:.1f}/s) | "
            f"Ins: {stats.inserted} Upd: {stats.updated} Del: {stats.deleted} "
            f"Kep: {stats.kept} Skp: {stats.skipped}"
        )

    def _log_final_summary(self, status: SyncJobStatus, stats, total_entities: int) -> None:
        """Log final summary."""
        status_map = {
            SyncJobStatus.COMPLETED: ("✅", "completed"),
            SyncJobStatus.CANCELLED: ("🚫", "cancelled"),
            SyncJobStatus.FAILED: ("❌", "failed"),
        }
        emoji, text = status_map.get(status, ("❓", status.value))

        ops_summary = (
            f"I:{stats.inserted} U:{stats.updated} D:{stats.deleted} "
            f"K:{stats.kept} S:{stats.skipped}"
        )
        self.logger.info(
            f"{emoji} Sync {text} | Total entities: {total_entities} | "
            f"Ops: {stats.total_operations} ({ops_summary})"
        )
