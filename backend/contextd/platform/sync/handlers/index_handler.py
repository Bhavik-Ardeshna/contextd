"""Index handler for entity-level indexing.

This handler processes entities for semantic and fulltext search:
1. Builds indexable text from embeddable fields
2. Updates Neo4j fulltext indexes (via fulltext service)

The handler integrates with the existing sync pipeline and can be
enabled/disabled via IndexConfig.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from contextd.platform.configs.index import IndexConfig, get_index_config
from contextd.platform.contexts.sync import SyncContext
from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._metadata import EntityMetadata, build_metadata_from_fields
from contextd.platform.entities._normalized import NormalizedEntity
from contextd.platform.graph.utils.json_flattener import (
    build_indexable_text,
    flatten_for_neo4j,
)

logger = logging.getLogger(__name__)


class IndexHandler:
    """Handler for entity-level indexing operations.

    Responsibilities:
    - Extract embeddable fields from entities
    - Build text representation for embedding
    - Track indexed entities for cleanup

    Design Notes:
    - Graceful degradation: indexing failures don't fail the sync
    - Batched processing for efficiency
    - Semantic merge stores canonical profile embeddings in Postgres
      (`entity_canonical_profile.embedding_json`); graph search uses Neo4j fulltext
      and graph traversal as the live retrieval path.
    """

    def __init__(
        self,
        index_config: Optional[IndexConfig] = None,
        batch_size: int = 50,
    ):
        """Initialize index handler.

        Args:
            index_config: Index configuration (uses default if not provided)
            batch_size: Batch size for index preparation
        """
        self._config = index_config or get_index_config()
        self._batch_size = batch_size

        # Track entities indexed in this sync (for cleanup)
        self._indexed_entity_ids: List[str] = []

        # Cache for entity metadata
        self._metadata_cache: Dict[str, EntityMetadata] = {}

    @property
    def name(self) -> str:
        """Handler name for logging."""
        return "IndexHandler"

    @property
    def is_enabled(self) -> bool:
        """Check if indexing is enabled."""
        return self._config.enabled

    async def process_entities(
        self,
        entities: List[BaseEntity],
        sync_context: SyncContext,
        normalized_entities: Optional[Dict[str, NormalizedEntity]] = None,
    ) -> Dict[str, Any]:
        """Process entities for indexing.

        Main entry point for the handler.

        Args:
            entities: Entities to index
            sync_context: Sync context
            normalized_entities: Optional normalized entity cache

        Returns:
            Statistics about indexing operations
        """
        if not self.is_enabled or not entities:
            sync_context.logger.debug(
                f"[IndexHandler] Skipping - enabled={self.is_enabled}, entities={len(entities) if entities else 0}"
            )
            return {"status": "skipped", "reason": "indexing_disabled" if not self.is_enabled else "no_entities"}

        sync_context.logger.info(
            f"🔍 [IndexHandler] Starting entity indexing for {len(entities)} entities "
            f"(fulltext={self._config.fulltext_enabled})"
        )

        stats = {
            "total_entities": len(entities),
            "indexed_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "fulltext_indexed": 0,
        }

        try:
            # Process in batches
            for i in range(0, len(entities), self._batch_size):
                batch = entities[i:i + self._batch_size]
                batch_stats = await self._process_batch(
                    batch, sync_context, normalized_entities
                )

                # Aggregate stats
                stats["indexed_count"] += batch_stats.get("indexed", 0)
                stats["skipped_count"] += batch_stats.get("skipped", 0)
                stats["failed_count"] += batch_stats.get("failed", 0)
                stats["fulltext_indexed"] += batch_stats.get("fulltext_indexed", 0)

            stats["status"] = "success"

            sync_context.logger.info(
                f"[IndexHandler] Processed {stats['total_entities']} entities: "
                f"{stats['indexed_count']} indexed, "
                f"{stats['skipped_count']} skipped, "
                f"{stats['failed_count']} failed"
            )

        except Exception as e:
            logger.error(f"Index processing failed: {e}", exc_info=True)
            stats["status"] = "error"
            stats["error"] = str(e)

        return stats

    async def _process_batch(
        self,
        entities: List[BaseEntity],
        sync_context: SyncContext,
        normalized_entities: Optional[Dict[str, NormalizedEntity]] = None,
    ) -> Dict[str, int]:
        """Process a batch of entities.

        Args:
            entities: Batch of entities
            sync_context: Sync context
            normalized_entities: Optional normalized entity cache

        Returns:
            Batch statistics
        """
        stats = {"indexed": 0, "skipped": 0, "failed": 0, "fulltext_indexed": 0}

        # Prepare entities for indexing
        indexable_data = []

        for entity in entities:
            try:
                result = self._prepare_entity_for_indexing(
                    entity, sync_context, normalized_entities
                )
                if result:
                    indexable_data.append(result)
                else:
                    stats["skipped"] += 1
            except Exception as e:
                logger.warning(f"Failed to prepare entity {entity.entity_id} for indexing: {e}")
                stats["failed"] += 1

        if not indexable_data:
            return stats

        # Update fulltext indexes (if enabled)
        if self._config.fulltext_enabled:
            try:
                fulltext_count = await self._update_fulltext_index(
                    indexable_data, sync_context
                )
                stats["fulltext_indexed"] = fulltext_count
                stats["indexed"] += fulltext_count
                if fulltext_count:
                    self._indexed_entity_ids.extend(item["entity_id"] for item in indexable_data)
            except Exception as e:
                logger.warning(f"Failed to update fulltext index: {e}")

        return stats

    def _prepare_entity_for_indexing(
        self,
        entity: BaseEntity,
        sync_context: SyncContext,
        normalized_entities: Optional[Dict[str, NormalizedEntity]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Prepare a single entity for indexing.

        Args:
            entity: Entity to prepare
            sync_context: Sync context
            normalized_entities: Optional normalized entity cache

        Returns:
            Dict with indexing data or None if entity should be skipped
        """
        entity_type = entity.__class__.__name__
        entity_id = entity.entity_id

        # Get entity metadata (cached)
        metadata = self._get_entity_metadata(entity)

        # Check if indexing is enabled for this entity
        if not metadata.index.enabled:
            return None

        # Get indexable fields
        indexable_fields = metadata.get_indexable_fields()
        if not indexable_fields:
            return None

        # Build properties dict from entity
        properties = self._extract_entity_properties(entity)

        # Build indexable text
        indexable_text = build_indexable_text(
            properties=properties,
            fields=indexable_fields,
            separator="\n",
            include_field_names=True,
        )

        if not indexable_text.strip():
            return None

        # Flatten properties for Neo4j fulltext
        flattened_properties = flatten_for_neo4j(properties)

        # Get name for display
        name = getattr(entity, "name", None) or entity_id

        # Build normalized entity data if available
        normalized_data = None
        if normalized_entities and entity_id in normalized_entities:
            normalized = normalized_entities[entity_id]
            normalized_data = normalized.model_dump(mode="json")

        # Connector (source_type) for filtering by @connector in graph chat
        source_type = None
        if normalized_data:
            source_type = normalized_data.get("source_type")
        if not source_type:
            source_type = getattr(sync_context.connection, "short_name", None)

        return {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "node_id": entity_id,  # For graph traversal linking
            "name": name,
            "indexable_text": indexable_text,
            "indexable_fields": indexable_fields,
            "properties": properties,
            "flattened_properties": flattened_properties,
            "normalized_data": normalized_data,
            "source_type": source_type or "",
            "organization_id": str(sync_context.organization_id),
            "collection_id": str(sync_context.collection_id),
            "sync_id": str(sync_context.sync_id),
            "created_at": getattr(entity, "created_at", None),
            "updated_at": getattr(entity, "updated_at", None) or datetime.utcnow(),
        }

    def _get_entity_metadata(self, entity: BaseEntity) -> EntityMetadata:
        """Get metadata for an entity type (cached).

        Args:
            entity: Entity to get metadata for

        Returns:
            EntityMetadata for the entity type
        """
        entity_type = entity.__class__.__name__

        if entity_type not in self._metadata_cache:
            # Check if entity class has _entity_metadata attached (for database entities, etc.)
            if hasattr(entity.__class__, "_entity_metadata"):
                attached_metadata = entity.__class__._entity_metadata
                if attached_metadata and isinstance(attached_metadata, EntityMetadata):
                    self._metadata_cache[entity_type] = attached_metadata
                    return attached_metadata

            # Fallback: Build metadata from entity fields
            self._metadata_cache[entity_type] = build_metadata_from_fields(
                entity.__class__.model_fields
            )

        return self._metadata_cache[entity_type]

    def _extract_entity_properties(self, entity: BaseEntity) -> Dict[str, Any]:
        """Extract properties from an entity.

        Args:
            entity: Entity to extract from

        Returns:
            Dictionary of properties
        """
        # Use model_dump for clean extraction
        try:
            # Exclude system fields
            exclude_fields = {
                "contextd_system_metadata",
                "textual_representation",
            }

            return entity.model_dump(
                mode="json",
                exclude=exclude_fields,
                exclude_none=True,
            )
        except Exception:
            # Fallback to __dict__
            return {
                k: v for k, v in entity.__dict__.items()
                if not k.startswith("_") and v is not None
            }

    async def _update_fulltext_index(
        self,
        indexable_data: List[Dict[str, Any]],
        sync_context: SyncContext,
    ) -> int:
        """Update Neo4j fulltext indexes.

        This ensures the fulltext index exists and includes the indexed fields.
        The actual node data is already in Neo4j from the graph pipeline.

        Args:
            indexable_data: Prepared entity data
            sync_context: Sync context

        Returns:
            Number of entities with fulltext coverage
        """
        from contextd.platform.graph.fulltext_service import FulltextService

        try:
            readable_collection_id = getattr(
                getattr(sync_context, "collection", None),
                "readable_id",
                None,
            )
            fulltext_service = await FulltextService.create(
                organization_id=sync_context.organization_id,
                readable_collection_id=readable_collection_id,
            )
        except Exception as e:
            logger.warning(f"Could not create fulltext service: {e}")
            return 0

        # Group entities by type
        entities_by_type: Dict[str, List[str]] = {}
        for item in indexable_data:
            entity_type = item["entity_type"]
            if entity_type not in entities_by_type:
                entities_by_type[entity_type] = []
            entities_by_type[entity_type].append(item["entity_id"])

        count = 0

        # Ensure fulltext index exists for each entity type
        for entity_type, entity_ids in entities_by_type.items():
            # Get indexable fields for this type (from first entity of this type)
            fields = next(
                (item["indexable_fields"] for item in indexable_data
                 if item["entity_type"] == entity_type),
                []
            )

            if not fields:
                continue

            try:
                # Create or update fulltext index
                await fulltext_service.ensure_fulltext_index(
                    node_type=entity_type,
                    fields=fields,
                )
                count += len(entity_ids)
            except Exception as e:
                logger.warning(f"Failed to update fulltext index for {entity_type}: {e}")

        return count

    async def cleanup_orphaned_indexes(
        self,
        orphan_entity_ids: List[str],
        sync_context: SyncContext,
    ) -> int:
        """Clean up index entries for orphaned entities.

        Neo4j fulltext entries are removed automatically when graph nodes are deleted.

        Args:
            orphan_entity_ids: Entity IDs that are no longer present
            sync_context: Sync context

        Returns:
            Number of entries cleaned up
        """
        if not orphan_entity_ids:
            return 0

        cleaned_count = 0

        sync_context.logger.info(
            f"🗑️ [IndexHandler] Cleaning up {len(orphan_entity_ids)} orphaned index entries"
        )

        # Neo4j fulltext: no explicit cleanup needed. The ft_* properties are on
        # the GraphNode, so deleting the node removes the indexed values.

        sync_context.logger.info(
            f"[IndexHandler] Completed orphan cleanup: {cleaned_count} index entries removed"
        )

        return cleaned_count

    def get_indexed_entity_ids(self) -> List[str]:
        """Get list of entity IDs indexed in this sync.

        Returns:
            List of indexed entity IDs
        """
        return self._indexed_entity_ids.copy()


# Factory function for creating handler
def create_index_handler(
    index_config: Optional[IndexConfig] = None,
    batch_size: Optional[int] = None,
) -> IndexHandler:
    """Create an index handler instance.

    Args:
        index_config: Optional index configuration
        batch_size: Batch size for embedding/upsert (default from settings.SYNC_INDEX_BATCH_SIZE or 50)

    Returns:
        IndexHandler instance
    """
    if batch_size is None:
        from contextd.core.config import settings
        batch_size = getattr(settings, "SYNC_INDEX_BATCH_SIZE", 50)
    return IndexHandler(index_config=index_config, batch_size=batch_size)
