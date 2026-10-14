"""Field-level hash computation for granular change detection.

Computes individual hashes for each embeddable field in an entity,
enabling Phase 2 to detect which specific fields changed.
"""

import hashlib
import json
from typing import Any, Dict

from contextd.platform.entities._base import BaseEntity


class FieldLevelHasher:
    """Computes hashes for individual entity fields.

    This enables granular change detection at the field level, allowing
    Phase 2 to determine exactly which fields changed between sync runs.

    Example:
        >>> hasher = FieldLevelHasher()
        >>> entity = TaskEntity(name="Task 1", description="Do something")
        >>> field_hashes = hasher.compute_field_hashes(entity)
        >>> # field_hashes = {"name": "abc123...", "description": "def456..."}
    """

    def compute_field_hashes(self, entity: BaseEntity) -> Dict[str, str]:
        """Compute hash for each embeddable field in the entity.

        Only fields marked with embeddable=True in ContextDField are hashed.
        This focuses on user-visible, searchable content rather than internal IDs.

        Args:
            entity: Entity to compute field hashes for

        Returns:
            Dictionary mapping field_name to SHA256 hash hex digest

        Example:
            >>> entity = TaskEntity(
            ...     name="Task 1",
            ...     description="Important task",
            ...     external_id="123"  # Not embeddable
            ... )
            >>> hashes = hasher.compute_field_hashes(entity)
            >>> # Returns: {"name": "hash1", "description": "hash2"}
            >>> # Note: external_id is excluded (not embeddable)
        """
        field_hashes = {}

        for field_name, field_info in entity.model_fields.items():
            # Only hash embeddable fields
            if not self._is_embeddable(field_info):
                continue

            # Get field value
            value = getattr(entity, field_name, None)

            # Skip None values (they don't contribute to content)
            if value is None:
                continue

            # Compute hash for this field
            field_hashes[field_name] = self._hash_value(value)

        return field_hashes

    def _is_embeddable(self, field_info: Any) -> bool:
        """Check if a field is marked as embeddable.

        Args:
            field_info: Pydantic FieldInfo object

        Returns:
            True if field has embeddable=True in its metadata
        """
        json_extra = field_info.json_schema_extra
        if json_extra and isinstance(json_extra, dict):
            return json_extra.get("embeddable", False)
        return False

    def _hash_value(self, value: Any) -> str:
        """Compute SHA256 hash of a field value.

        Handles different types with stable serialization:
        - Primitives: str, int, float, bool
        - Collections: list, dict
        - Complex objects: converted to string

        Args:
            value: Field value to hash

        Returns:
            SHA256 hash hex digest
        """
        # Serialize value to stable JSON representation
        serialized = self._serialize_value(value)

        # Convert to JSON string with sorted keys for stability
        json_str = json.dumps(serialized, sort_keys=True, separators=(",", ":"))

        # Compute SHA256 hash
        return hashlib.sha256(json_str.encode()).hexdigest()

    def _serialize_value(self, value: Any) -> Any:
        """Serialize a value to a stable representation for hashing.

        Args:
            value: Value to serialize

        Returns:
            Serialized value with stable ordering
        """
        if isinstance(value, dict):
            # Sort dict keys for stable ordering
            return {k: self._serialize_value(v) for k, v in sorted(value.items())}
        elif isinstance(value, (list, tuple)):
            # Preserve list/tuple order
            return [self._serialize_value(item) for item in value]
        elif isinstance(value, (str, int, float, bool, type(None))):
            # Primitives are already stable
            return value
        else:
            # Complex objects: convert to string
            # This handles datetime, UUID, custom objects, etc.
            return str(value)


# Singleton instance for convenience
field_hasher = FieldLevelHasher()
