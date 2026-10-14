"""Data structures for state comparison.

Defines types used for comparing entity states between sync runs
to detect field-level changes for graph event generation.
"""

from dataclasses import dataclass
from typing import Dict, List, Literal
from uuid import UUID

from contextd.platform.entities._base import BaseEntity


@dataclass
class FieldChange:
    """Represents a change to a single field.

    Attributes:
        field_name: Name of the field that changed
        previous_hash: Hash of the field value in previous sync (empty if new)
        current_hash: Hash of the field value in current sync
        change_type: Type of change (created, modified, deleted)
    """

    field_name: str
    previous_hash: str
    current_hash: str
    change_type: Literal["created", "modified", "deleted"]


@dataclass
class EntityComparison:
    """Represents comparison result for a single entity.

    Attributes:
        entity: The current entity being compared
        entity_definition_id: UUID of the entity definition
        entity_changed: Whether the entity has any changes
        changed_fields: Dictionary mapping field names to their changes
        comparison_type: Overall classification of the comparison
    """

    entity: BaseEntity
    entity_definition_id: UUID
    entity_changed: bool
    changed_fields: Dict[str, FieldChange]
    comparison_type: Literal["new", "modified", "unchanged", "deleted"]


@dataclass
class StateComparisonResult:
    """Complete result of comparing current entities with previous state.

    Attributes:
        new_entities: Entities that didn't exist in previous sync
        modified_entities: Entities with field-level changes
        deleted_entities: Entity IDs that existed before but not now
        unchanged_entities: Entities with no changes
    """

    new_entities: List[EntityComparison]
    modified_entities: List[EntityComparison]
    deleted_entities: List[str]  # entity_ids
    unchanged_entities: List[EntityComparison]
