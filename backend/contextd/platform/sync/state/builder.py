"""State builder for creating comprehensive sync state snapshots.

Aggregates entity data during sync execution and builds a complete
state object containing entity hashes, field hashes, relationships,
and statistics.
"""

from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional, Set, Tuple
from uuid import UUID

from contextd.platform.entities._base import BaseEntity
from contextd.platform.sync.state.field_hasher import field_hasher
from contextd.schemas.sync_state import (
    EntityStateSnapshot,
    EntityTypeState,
    SyncMetadata,
    SyncStateData,
    SyncStatistics,
)

if TYPE_CHECKING:
    from contextd.platform.contexts.sync import SyncContext


class SyncStateBuilder:
    """Builds comprehensive state snapshots during sync execution.

    This service aggregates entity data as entities are processed through
    the sync pipeline, then builds a complete state object at sync completion.

    The state object contains:
    - Entity-level hashes for change detection
    - Field-level hashes for granular comparison
    - Entity relationships and breadcrumbs
    - Sync statistics and metadata

    Usage:
        >>> builder = SyncStateBuilder()
        >>> # During sync, record each entity
        >>> await builder.record_entity(entity, entity_definition_id, "INSERT")
        >>> # At sync completion, build final state
        >>> state_data = await builder.build_state(sync_context)
    """

    def __init__(self):
        """Initialize the state builder with empty state."""
        # Entity states grouped by entity type
        # Structure: {entity_type: {entity_id: EntityStateSnapshot}}
        self._entity_states: Dict[str, Dict[str, EntityStateSnapshot]] = defaultdict(dict)
        self._deleted_entity_keys: Set[Tuple[str, str]] = set()

        # Statistics tracking
        self._stats = {
            "inserted": 0,
            "updated": 0,
            "deleted": 0,
            "kept": 0,
        }

    async def record_entity(
        self,
        entity: BaseEntity,
        entity_definition_id: UUID,
        action_type: str,
    ) -> None:
        """Record an entity's state during sync processing.

        This method is called for each entity processed through the pipeline,
        capturing its hash, field hashes, relationships, and metadata.

        Args:
            entity: The entity being processed
            entity_definition_id: Entity definition ID from entity_map
            action_type: Action type (INSERT, UPDATE, DELETE, KEEP)

        Note:
            This method modifies internal state and should be called
            for every entity processed during sync.
        """
        # Extract entity type and ID
        entity_type = entity.__class__.__name__
        entity_id = entity.entity_id

        # Get entity hash (should already be computed by HashComputer)
        entity_hash = (
            entity.contextd_system_metadata.hash
            if entity.contextd_system_metadata
            else ""
        )

        # Compute field-level hashes
        field_hashes = field_hasher.compute_field_hashes(entity)

        # Extract timestamps
        created_at = self._extract_timestamp(entity, "created_at")
        modified_at = self._extract_timestamp(entity, "modified_at")

        # Extract breadcrumbs
        breadcrumbs = []
        if hasattr(entity, "breadcrumbs") and entity.breadcrumbs:
            breadcrumbs = [
                {
                    "entity_id": bc.entity_id,
                    "name": bc.name,
                    "entity_type": bc.entity_type,
                }
                for bc in entity.breadcrumbs
            ]

        # Extract relationships (parent references)
        relationships = self._extract_relationships(entity)

        # Update statistics
        action_key = action_type.lower()
        if action_key in self._stats:
            self._stats[action_key] += 1

        if action_key == "delete":
            self._deleted_entity_keys.add((str(entity_definition_id), entity_id))
            return

        # Create entity state snapshot
        snapshot = EntityStateSnapshot(
            hash=entity_hash,
            entity_definition_id=entity_definition_id,
            created_at=created_at,
            modified_at=modified_at,
            breadcrumbs=breadcrumbs,
            field_hashes=field_hashes,
            relationships=relationships,
        )

        # Store in entity states
        self._entity_states[entity_type][entity_id] = snapshot

    async def build_state(self, sync_context: "SyncContext") -> SyncStateData:
        """Build the final state object from accumulated entity data.

        This method is called at sync completion to create the comprehensive
        state snapshot that will be persisted to the database.

        Args:
            sync_context: Sync context with job/sync metadata

        Returns:
            Complete SyncStateData object ready for persistence

        Example:
            >>> state_data = await builder.build_state(sync_context)
            >>> # state_data contains all entity states, statistics, metadata
        """
        # Build entity type states
        entity_states = {}
        for entity_type, entities in self._entity_states.items():
            entity_states[entity_type] = EntityTypeState(entities=dict(entities))

        cursor_had_data_at_start = self._cursor_had_data_at_start(sync_context)
        snapshot_mode = self._snapshot_mode(sync_context, cursor_had_data_at_start)
        snapshot_is_complete = snapshot_mode == "full"
        merge_base_sync_state_id: Optional[str] = None

        if snapshot_mode == "incremental_delta":
            previous_merge_base = await self._load_previous_state(sync_context)
            if previous_merge_base:
                previous_state, merge_base_sync_state_id = previous_merge_base
                entity_states = self._merge_previous_state(
                    current_states=entity_states,
                    previous_state=previous_state,
                    sync_context=sync_context,
                )
                snapshot_mode = "incremental_merged"
                snapshot_is_complete = True
            else:
                sync_context.logger.warning(
                    "Incremental sync produced a delta but no complete merge base was "
                    "available; saving the state as incomplete and preserving the "
                    "existing graph snapshot."
                )

        # Build sync metadata after merge classification so downstream graph commit
        # can distinguish complete snapshots from cursor deltas.
        sync_metadata = SyncMetadata(
            sync_job_id=str(sync_context.sync_job.id),
            sync_id=str(sync_context.sync.id),
            started_at=sync_context.sync_job.started_at.isoformat() if sync_context.sync_job.started_at else None,
            completed_at=datetime.utcnow().isoformat(),  # Current time as completion (ISO format)
            force_full_sync=sync_context.force_full_sync,
            cursor_had_data_at_start=cursor_had_data_at_start,
            snapshot_mode=snapshot_mode,
            snapshot_is_complete=snapshot_is_complete,
            merge_base_sync_state_id=merge_base_sync_state_id,
        )

        # Calculate statistics
        total_entities = sum(len(type_state.entities) for type_state in entity_states.values())
        entities_by_type = {
            entity_type: len(type_state.entities)
            for entity_type, type_state in entity_states.items()
        }

        statistics = SyncStatistics(
            total_entities=total_entities,
            entities_by_type=entities_by_type,
            entities_inserted=self._stats["inserted"],
            entities_updated=self._stats["updated"],
            entities_deleted=self._stats["deleted"],
            entities_kept=self._stats["kept"],
        )

        # Build complete state data
        state_data = SyncStateData(
            version="1.0",
            sync_metadata=sync_metadata,
            entity_states=entity_states,
            statistics=statistics,
        )

        return state_data

    async def _should_merge_previous_state(self, sync_context: "SyncContext") -> bool:
        """Return True when this run is a cursor delta, not a full snapshot."""
        if sync_context.force_full_sync:
            return False
        source_supports_continuous = bool(
            getattr(sync_context.source_instance, "_supports_continuous", False)
        )
        cursor = getattr(sync_context, "cursor", None)
        had_cursor_data_at_start = bool(
            cursor and getattr(cursor, "had_cursor_data_at_start", False)
        )
        return source_supports_continuous and had_cursor_data_at_start

    def _cursor_had_data_at_start(self, sync_context: "SyncContext") -> bool:
        cursor = getattr(sync_context, "cursor", None)
        return bool(cursor and getattr(cursor, "had_cursor_data_at_start", False))

    def _snapshot_mode(
        self,
        sync_context: "SyncContext",
        cursor_had_data_at_start: bool,
    ) -> str:
        """Classify whether the current run is a full snapshot or cursor delta."""
        if sync_context.force_full_sync:
            return "full"
        source_supports_continuous = bool(
            getattr(sync_context.source_instance, "_supports_continuous", False)
        )
        if not source_supports_continuous:
            return "full"
        if not cursor_had_data_at_start:
            return "full"
        return "incremental_delta"

    async def _load_previous_state(
        self,
        sync_context: "SyncContext",
    ) -> Optional[Tuple[SyncStateData, str]]:
        """Load the prior persisted state for incremental snapshot merging."""
        try:
            from contextd import crud
            from contextd.db.session import get_db_context

            async with get_db_context() as db:
                candidates = await crud.sync_state.get_all_by_sync_id(
                    db=db,
                    sync_id=sync_context.sync.id,
                    ctx=sync_context.ctx,
                    limit=100,
                )
            previous = self._select_merge_base(candidates)
            if not previous or not previous.state_data:
                return None
            if isinstance(previous.state_data, SyncStateData):
                return previous.state_data, str(previous.id)
            return SyncStateData.model_validate(previous.state_data), str(previous.id)
        except Exception as exc:
            sync_context.logger.warning(
                f"Could not merge previous sync state; saving current delta only: {exc}",
                exc_info=True,
            )
            return None

    def _select_merge_base(self, candidates: list[Any]) -> Optional[Any]:
        """Select the latest complete state that can anchor an incremental delta.

        New states carry explicit `snapshot_is_complete` metadata. Historical
        states did not, so the migration path is intentionally conservative:
        forced full states are trusted, otherwise the largest historical state is
        used only when no explicit complete marker exists.
        """
        candidates = sorted(
            candidates,
            key=self._sync_state_created_at_sort_key,
            reverse=True,
        )
        explicit_complete: list[Any] = []
        forced_full: list[Any] = []
        unknown: list[Any] = []

        for candidate in candidates:
            state_data = getattr(candidate, "state_data", None)
            if not state_data:
                continue
            metadata = self._raw_sync_metadata(state_data)
            if metadata is None:
                unknown.append(candidate)
                continue
            has_complete_marker = (
                "snapshot_is_complete" in metadata or "snapshot_mode" in metadata
            )
            if has_complete_marker:
                mode = str(metadata.get("snapshot_mode") or "").lower()
                complete = metadata.get("snapshot_is_complete")
                if complete is True or mode in {"full", "incremental_merged"}:
                    explicit_complete.append(candidate)
                continue
            if metadata.get("force_full_sync") is True:
                forced_full.append(candidate)
                continue
            unknown.append(candidate)

        if explicit_complete:
            return explicit_complete[0]
        if forced_full:
            return forced_full[0]
        if not unknown:
            return None

        best_unknown = max(
            unknown,
            key=lambda candidate: int(getattr(candidate, "entity_count", 0) or 0),
        )
        if int(getattr(best_unknown, "entity_count", 0) or 0) <= 0:
            return None
        return best_unknown

    @staticmethod
    def _sync_state_created_at_sort_key(candidate: Any) -> float:
        created_at = getattr(candidate, "created_at", None)
        if isinstance(created_at, datetime):
            return created_at.timestamp()
        return 0.0

    @staticmethod
    def _raw_sync_metadata(state_data: Any) -> Optional[Dict[str, Any]]:
        if isinstance(state_data, SyncStateData):
            return state_data.sync_metadata.model_dump(mode="json")
        if not isinstance(state_data, dict):
            return None
        metadata = state_data.get("sync_metadata")
        return metadata if isinstance(metadata, dict) else None

    def _merge_previous_state(
        self,
        *,
        current_states: Dict[str, EntityTypeState],
        previous_state: SyncStateData,
        sync_context: "SyncContext",
    ) -> Dict[str, EntityTypeState]:
        """Merge an incremental run into the last complete state snapshot."""
        observed_keys = {
            (str(snapshot.entity_definition_id), entity_id)
            for type_state in current_states.values()
            for entity_id, snapshot in type_state.entities.items()
        }
        deleted_keys = set(self._deleted_entity_keys)

        for entity_type, previous_type_state in previous_state.entity_states.items():
            target = current_states.setdefault(entity_type, EntityTypeState())
            for entity_id, snapshot in previous_type_state.entities.items():
                key = (str(snapshot.entity_definition_id), entity_id)
                if key in observed_keys or key in deleted_keys:
                    continue
                target.entities[entity_id] = snapshot

        if deleted_keys:
            for type_state in current_states.values():
                for entity_id, snapshot in list(type_state.entities.items()):
                    key = (str(snapshot.entity_definition_id), entity_id)
                    if key in deleted_keys:
                        type_state.entities.pop(entity_id, None)

        merged_total = sum(len(type_state.entities) for type_state in current_states.values())
        sync_context.logger.info(
            "Merged incremental sync state with previous snapshot: "
            f"{merged_total} total entities"
        )
        return current_states

    def _extract_timestamp(self, entity: BaseEntity, field_name: str) -> Optional[str]:
        """Extract a timestamp field from an entity and convert to ISO format.

        Args:
            entity: Entity to extract from
            field_name: Name of the timestamp field

        Returns:
            ISO format timestamp string or None if not present
        """
        value = getattr(entity, field_name, None)
        if isinstance(value, datetime):
            return value.isoformat()
        return None

    def _extract_relationships(self, entity: BaseEntity) -> Dict[str, str]:
        """Extract parent/child relationships from an entity.

        Looks for common parent reference patterns like:
        - parent_id, parent_type
        - workspace_id, project_id
        - Any field ending in "_id"

        Args:
            entity: Entity to extract relationships from

        Returns:
            Dictionary of relationship metadata
        """
        relationships = {}

        # Common parent reference patterns
        parent_fields = [
            "parent_id",
            "parent_type",
            "workspace_id",
            "project_id",
            "task_id",
            "issue_id",
        ]

        for field_name in parent_fields:
            value = getattr(entity, field_name, None)
            if value is not None:
                relationships[field_name] = str(value)

        return relationships

    def get_entity_count(self) -> int:
        """Get the total number of entities recorded.

        Returns:
            Total count of entities in state
        """
        return sum(len(entities) for entities in self._entity_states.values())

    def get_statistics(self) -> Dict[str, int]:
        """Get current statistics.

        Returns:
            Dictionary of statistics (inserted, updated, deleted, kept)
        """
        return self._stats.copy()
