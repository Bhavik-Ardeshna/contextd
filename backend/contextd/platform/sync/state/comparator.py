"""State comparison service for detecting entity changes.

Compares current entity state with previous sync state to identify
field-level changes for graph event generation.
"""

from typing import Dict, List, Optional
from uuid import UUID

from contextd.platform.contexts.sync import SyncContext
from contextd.db.init_db_native import RESERVED_TABLE_ENTITY_ID
from contextd.platform.entities._base import BaseEntity, PolymorphicEntity
from contextd.platform.sync.state.comparison_types import (
    EntityComparison,
    FieldChange,
    StateComparisonResult,
)
from contextd.schemas.sync_state import EntityStateSnapshot, SyncState


class StateComparator:
    """Compares entity states to detect changes.

    Performs entity-level hash comparison first for quick filtering,
    then field-level hash comparison for changed entities to identify
    specific field changes.
    """

    async def compare_states(
        self,
        current_entities: List[BaseEntity],
        previous_state: Optional[SyncState],
        sync_context: SyncContext,
    ) -> StateComparisonResult:
        """Compare current entities against previous state.

        Args:
            current_entities: Entities from current sync run
            previous_state: State from previous sync (None for first sync)
            sync_context: Sync context with entity_map

        Returns:
            StateComparisonResult with categorized entity comparisons
        """
        new_entities: List[EntityComparison] = []
        modified_entities: List[EntityComparison] = []
        unchanged_entities: List[EntityComparison] = []

        # If no previous state, all entities are new
        if not previous_state or not previous_state.state_data:
            for entity in current_entities:
                entity_definition_id = self._get_entity_definition_id(
                    entity, sync_context
                )
                new_entities.append(
                    EntityComparison(
                        entity=entity,
                        entity_definition_id=entity_definition_id,
                        entity_changed=True,
                        changed_fields={},  # All fields are new
                        comparison_type="new",
                    )
                )

            return StateComparisonResult(
                new_entities=new_entities,
                modified_entities=[],
                deleted_entities=[],
                unchanged_entities=[],
            )

        # Build lookup of previous entity states
        previous_snapshots = self._build_previous_snapshots_lookup(previous_state)

        # Compare each current entity
        for entity in current_entities:
            entity_definition_id = self._get_entity_definition_id(
                entity, sync_context
            )
            entity_type = entity.__class__.__name__
            entity_id = entity.entity_id

            # Check if entity existed in previous state
            previous_snapshot = previous_snapshots.get(entity_type, {}).get(entity_id)

            if not previous_snapshot:
                # New entity
                new_entities.append(
                    EntityComparison(
                        entity=entity,
                        entity_definition_id=entity_definition_id,
                        entity_changed=True,
                        changed_fields={},
                        comparison_type="new",
                    )
                )
                continue

            # Entity existed - compare hashes
            comparison = await self.compare_entity(
                entity, previous_snapshot, entity_definition_id
            )

            if comparison.entity_changed:
                modified_entities.append(comparison)
            else:
                unchanged_entities.append(comparison)

        # Detect deleted entities (in previous but not current)
        current_entity_ids = {
            (e.__class__.__name__, e.entity_id) for e in current_entities
        }
        deleted_entity_ids = []

        for entity_type, entities in previous_snapshots.items():
            for entity_id in entities.keys():
                if (entity_type, entity_id) not in current_entity_ids:
                    deleted_entity_ids.append(entity_id)

        sync_context.logger.info(
            f"State comparison: {len(new_entities)} new, "
            f"{len(modified_entities)} modified, "
            f"{len(unchanged_entities)} unchanged, "
            f"{len(deleted_entity_ids)} deleted"
        )

        return StateComparisonResult(
            new_entities=new_entities,
            modified_entities=modified_entities,
            deleted_entities=deleted_entity_ids,
            unchanged_entities=unchanged_entities,
        )

    async def compare_entity(
        self,
        current_entity: BaseEntity,
        previous_snapshot: EntityStateSnapshot,
        entity_definition_id: UUID,
    ) -> EntityComparison:
        """Compare a single entity against its previous snapshot.

        Args:
            current_entity: Current entity from sync
            previous_snapshot: Snapshot from previous sync
            entity_definition_id: Entity definition ID

        Returns:
            EntityComparison with change details
        """
        # Get current entity hash
        current_hash = (
            current_entity.contextd_system_metadata.hash
            if current_entity.contextd_system_metadata
            else ""
        )
        previous_hash = previous_snapshot.hash

        # Quick entity-level comparison
        if current_hash == previous_hash:
            # No changes
            return EntityComparison(
                entity=current_entity,
                entity_definition_id=entity_definition_id,
                entity_changed=False,
                changed_fields={},
                comparison_type="unchanged",
            )

        # Entity changed - perform field-level comparison
        changed_fields = self._compare_field_hashes(
            current_entity, previous_snapshot
        )

        return EntityComparison(
            entity=current_entity,
            entity_definition_id=entity_definition_id,
            entity_changed=True,
            changed_fields=changed_fields,
            comparison_type="modified",
        )

    def _compare_field_hashes(
        self,
        current_entity: BaseEntity,
        previous_snapshot: EntityStateSnapshot,
    ) -> Dict[str, FieldChange]:
        """Compare field-level hashes to identify specific changes.

        Args:
            current_entity: Current entity
            previous_snapshot: Previous snapshot

        Returns:
            Dictionary mapping field names to FieldChange objects
        """
        from contextd.platform.sync.state.field_hasher import field_hasher

        # Get current field hashes
        current_field_hashes = field_hasher.compute_field_hashes(current_entity)
        previous_field_hashes = previous_snapshot.field_hashes or {}

        changed_fields: Dict[str, FieldChange] = {}

        # Find modified and new fields
        for field_name, current_hash in current_field_hashes.items():
            previous_hash = previous_field_hashes.get(field_name, "")

            if previous_hash == "":
                # New field (didn't exist before or was None)
                changed_fields[field_name] = FieldChange(
                    field_name=field_name,
                    previous_hash="",
                    current_hash=current_hash,
                    change_type="created",
                )
            elif current_hash != previous_hash:
                # Modified field
                changed_fields[field_name] = FieldChange(
                    field_name=field_name,
                    previous_hash=previous_hash,
                    current_hash=current_hash,
                    change_type="modified",
                )

        # Find deleted fields (existed before but not now)
        for field_name, previous_hash in previous_field_hashes.items():
            if field_name not in current_field_hashes:
                changed_fields[field_name] = FieldChange(
                    field_name=field_name,
                    previous_hash=previous_hash,
                    current_hash="",
                    change_type="deleted",
                )

        return changed_fields

    def _build_previous_snapshots_lookup(
        self, previous_state: SyncState
    ) -> Dict[str, Dict[str, EntityStateSnapshot]]:
        """Build lookup dictionary from previous state.

        Args:
            previous_state: Previous sync state

        Returns:
            Nested dict: {entity_type: {entity_id: snapshot}}
        """
        lookup: Dict[str, Dict[str, EntityStateSnapshot]] = {}

        if not previous_state.state_data:
            return lookup

        # Handle both Pydantic model and dict (JSONB from database)
        if isinstance(previous_state.state_data, dict):
            # state_data is a plain dict from JSONB
            entity_states_dict = previous_state.state_data.get("entity_states", {})
            if not entity_states_dict:
                return lookup

            for entity_type, type_state in entity_states_dict.items():
                # type_state is also a dict with "entities" key
                if isinstance(type_state, dict):
                    entities = type_state.get("entities", {})
                    # Convert dict snapshots to EntityStateSnapshot objects
                    lookup[entity_type] = {
                        entity_id: EntityStateSnapshot(**snapshot_data)
                        if isinstance(snapshot_data, dict)
                        else snapshot_data
                        for entity_id, snapshot_data in entities.items()
                    }
                else:
                    lookup[entity_type] = type_state.entities
        else:
            # state_data is a Pydantic SyncStateData model
            if not previous_state.state_data.entity_states:
                return lookup

            for entity_type, type_state in previous_state.state_data.entity_states.items():
                lookup[entity_type] = type_state.entities

        return lookup

    def _get_entity_definition_id(
        self, entity: BaseEntity, sync_context: SyncContext
    ) -> UUID:
        """Get entity definition ID from entity_map.

        Args:
            entity: Entity to get definition ID for
            sync_context: Sync context with entity_map

        Returns:
            Entity definition UUID

        Raises:
            ValueError: If entity class not found in entity_map
        """
        entity_class = entity.__class__
        entity_definition_id = sync_context.entity_map.get(entity_class)

        if not entity_definition_id:
            # Fallback: check dynamically registered database entity classes
            from contextd.platform.configs.database.entity_registry import (
                DatabaseEntityClassRegistry,
            )

            entity_definition_id = DatabaseEntityClassRegistry.get_entity_definition_id(
                entity_class
            )

            if not entity_definition_id:
                table_key = None
                schema_name = getattr(entity, "schema_name", None)
                table_name = getattr(entity, "table_name", None)
                if schema_name and table_name:
                    table_key = f"{schema_name}.{table_name}"

                if table_key:
                    registered_class = DatabaseEntityClassRegistry.get_entity_class(
                        table_key
                    )
                    if registered_class:
                        entity_definition_id = (
                            DatabaseEntityClassRegistry.get_entity_definition_id(
                                registered_class
                            )
                        )
                        if entity_definition_id:
                            DatabaseEntityClassRegistry.register_entity_class(
                                table_key, entity_class, entity_definition_id
                            )

            if entity_definition_id:
                # Add to entity_map for future lookups
                sync_context.entity_map[entity_class] = entity_definition_id
            else:
                # Database table entities are generated dynamically per source
                # instance/run. When concurrent runs create an equivalent class
                # object that is not the same Python identity as the registered
                # class, use the reserved polymorphic table definition instead
                # of failing the whole sync.
                if isinstance(entity, PolymorphicEntity):
                    entity_definition_id = RESERVED_TABLE_ENTITY_ID
                    sync_context.entity_map[entity_class] = entity_definition_id
                    return entity_definition_id

                # Still not found - raise error
                raise ValueError(
                    f"Entity class {entity_class.__name__} not found in entity_map or registry. "
                    f"Available types: {list(sync_context.entity_map.keys())}"
                )

        return entity_definition_id
