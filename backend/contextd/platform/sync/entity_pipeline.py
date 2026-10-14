"""Entity pipeline - orchestrates entity processing through sync stages.

Lifecycle:
1. Entities produced by source
2. Batched and submitted to pipeline
3. TRACKED in EntityTracker (first thing - dedup + encounter tracking)
4. NORMALIZED to canonical format (optional - extracts nested data)
5. Hash computed
6. Action resolved (INSERT/UPDATE/DELETE/KEEP)
7. Actions dispatched to handlers (handlers process content as needed)
8. Orphan cleanup dispatched through handlers at sync end
"""

import asyncio
from collections import defaultdict

# Import index handler types for optional indexing
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from contextd.core.shared_models import ContextDFieldFlag
from contextd.platform.contexts import SyncContext
from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._normalized import NormalizedEntity
from contextd.platform.sync.actions import (
    EntityActionBatch,
    EntityActionDispatcher,
    EntityActionResolver,
)
from contextd.platform.sync.exceptions import SyncFailureError
from contextd.platform.sync.graph import GraphEventBatch, GraphEventGenerator
from contextd.platform.sync.graph.event_normalizer import GraphEventNormalizer
from contextd.platform.sync.graph.llm_enrichment_service import LLMEnrichmentService
from contextd.platform.sync.normalizers import get_normalizer_for_entity
from contextd.platform.sync.pii_masking import apply_pii_masking
from contextd.platform.sync.pipeline.cleanup_service import cleanup_service
from contextd.platform.sync.pipeline.entity_tracker import EntityTracker
from contextd.platform.sync.pipeline.hash_computer import hash_computer
from contextd.platform.sync.state.comparator import StateComparator

if TYPE_CHECKING:
    from contextd.platform.sync.handlers.index_handler import IndexHandler


class EntityPipeline:
    """Pipeline for processing entities with stateful tracking across sync lifecycle.

    Uses dependency injection for all major components, configured at factory time.
    """

    def __init__(
        self,
        entity_tracker: EntityTracker,
        action_resolver: EntityActionResolver,
        action_dispatcher: EntityActionDispatcher,
        state_comparator: StateComparator | None = None,
        event_generator: GraphEventGenerator | None = None,
        use_graph_events: bool = False,
        use_entity_normalization: bool = True,
        index_handler: Optional["IndexHandler"] = None,
        use_entity_indexing: bool = False,
    ):
        """Initialize pipeline with injected dependencies.

        Args:
            entity_tracker: Centralized entity state tracker
            action_resolver: Resolves entities to actions
            action_dispatcher: Dispatches actions to handlers
            state_comparator: State comparator for graph events (optional)
            event_generator: Graph event generator (optional)
            use_graph_events: Whether to use graph event generation (Phase 2)
            use_entity_normalization: Whether to normalize entities to canonical format
            index_handler: Handler for entity-level indexing (optional)
            use_entity_indexing: Whether to enable entity-level indexing
        """
        self._tracker = entity_tracker
        self._resolver = action_resolver
        self._dispatcher = action_dispatcher
        self._state_comparator = state_comparator
        self._event_generator = event_generator
        self._use_graph_events = use_graph_events
        self._use_entity_normalization = use_entity_normalization
        self._event_normalizer = GraphEventNormalizer()  # NEW: Event normalization layer

        # Index handler for entity-level indexing (vector + fulltext)
        self._index_handler = index_handler
        self._use_entity_indexing = use_entity_indexing

        # Cache for normalized entities (entity_id -> NormalizedEntity)
        self._normalized_cache: Dict[str, NormalizedEntity] = {}

        # Cache for previous sync state to avoid redundant DB queries per batch
        self._previous_state_loaded = False
        self._previous_state = None
        self._previous_state_lock = None
        # Log once per sync if semantic merge is enabled but graph pipeline is off
        self._semantic_merge_skip_logged = False

    # -------------------------------------------------------------------------
    # Public API - Called from Orchestrator
    # -------------------------------------------------------------------------

    async def process(
        self,
        entities: List[BaseEntity],
        sync_context: SyncContext,
    ) -> None:
        """Process a batch of entities through the full pipeline.

        Args:
            entities: Entities to process
            sync_context: Sync context with all required components
        """
        # Phase 1: Track and deduplicate (FIRST - before any processing)
        unique_entities = await self._track_and_dedupe(entities, sync_context)
        if not unique_entities:
            return

        # Phase 2: Prepare entities (populate fields, enrich metadata, compute hash)
        await self._prepare_entities(unique_entities, sync_context)

        from contextd.core.config import settings as _settings_for_merge

        _short_name = getattr(sync_context.connection, "short_name", "") or ""
        _graph_pipeline_on = (
            self._use_graph_events
            and self._state_comparator is not None
            and self._event_generator is not None
        )
        if (
            _settings_for_merge.SEMANTIC_MERGE_ENABLED
            and not _graph_pipeline_on
            and not self._semantic_merge_skip_logged
        ):
            self._semantic_merge_skip_logged = True
            sync_context.logger.info(
                "[SemanticMerge] Not running (connector=%s): merge runs inside the graph-event "
                "pipeline. Set USE_GRAPH_EVENTS=true in the worker/backend environment; also set "
                "SEMANTIC_MERGE_ENABLED=true (PersonNode merge runs for all connectors; global "
                "entity merge remains unstructured-only per SEMANTIC_MERGE_STRUCTURED_CONNECTORS).",
                _short_name,
            )

        # Run graph event pipeline first (if enabled)
        if self._use_graph_events and self._state_comparator and self._event_generator:
            # NEW: Graph event generation pipeline (state comparison + event generation)
            await self._process_with_graph_events(unique_entities, sync_context)

        # Always run action resolution pipeline to persist entities to database
        # This ensures entities show up in the UI regardless of graph event setting
        await self._process_with_actions(unique_entities, sync_context)

        # Run entity-level indexing (if enabled)
        # This creates vector embeddings and fulltext indexes for semantic/hybrid search
        if self._use_entity_indexing and self._index_handler:
            await self._process_entity_indexing(unique_entities, sync_context)

    async def _process_with_actions(
        self,
        unique_entities: List[BaseEntity],
        sync_context: SyncContext,
    ) -> None:
        """Process entities using traditional action resolution.

        Args:
            unique_entities: Unique entities to process
            sync_context: Sync context
        """
        # Phase 3: Resolve actions (includes bulk DB lookup)
        batch = await self._resolver.resolve(unique_entities, sync_context)

        # Phase 3.5: Record entities in state builder for comprehensive state snapshot
        await self._record_entities_in_state(batch, sync_context)

        # Phase 4: Early exit for KEEP-only batches
        if not batch.has_mutations:
            await self._handle_keep_only_batch(batch, sync_context)
            return

        # Phase 5: Dispatch to the live persistence path. Entity search indexing
        # runs separately through IndexHandler.
        await self._dispatcher.dispatch_to_postgres_only(batch, sync_context)

        # Phase 6: Update tracker with successes → triggers pubsub
        await self._update_tracker(batch, sync_context)

        # Phase 7: Progressive cleanup: delete temp files after successful processing
        await self._cleanup_temp_files_for_batch(batch, sync_context)

    async def _process_with_graph_events(
        self,
        unique_entities: List[BaseEntity],
        sync_context: SyncContext,
    ) -> GraphEventBatch:
        """Process entities using graph event generation (Phase 2).

        Pipeline:
        1. LLM enrichment (extract entities from unstructured content)
        2. Semantic merge (canonical IDs + alias DB / vector / LLM judge) on normalized entities
        3. Load previous state from database
        4. Compare current entities with previous state
        5. Generate graph events for changed fields
        6. Normalize events (ensure consistent schema)
        7. Record entities in state builder
        8. Dispatch events to graph destination handler

        Args:
            unique_entities: Unique entities to process
            sync_context: Sync context

        Returns:
            GraphEventBatch with generated events
        """
        # Reset node deduplicator at start of each batch to ensure correct CREATE/UPDATE decisions
        # NOTE: Within a single sync, we want deduplication to work across batches
        # So we only reset once at the start of the sync run, not per batch
        # The reset happens in the factory when creating a new GraphEventGenerator

        # ========================================
        # Phase 3: LLM Enrichment (NEW)
        # ========================================
        entities_needing_llm = self._detect_llm_enabled_entities(unique_entities, sync_context)
        if entities_needing_llm:
            sync_context.logger.info(
                f"[LLM Enrichment] Detected {len(entities_needing_llm)} entities "
                f"with LLM extraction enabled"
            )
            try:
                enriched_entities = await self._llm_enrichment_phase(
                    entities_needing_llm,
                    sync_context
                )
                # Merge enriched data back into entity map
                entity_map = {e.entity_id: e for e in unique_entities}
                for enriched in enriched_entities:
                    entity_map[enriched.entity_id] = enriched
                unique_entities = list(entity_map.values())

                sync_context.logger.info(
                    f"[LLM Enrichment] Successfully enriched "
                    f"{len(enriched_entities)} entities"
                )

                # CRITICAL: Update normalized entity cache with LLM extractions
                # Normalization runs BEFORE LLM enrichment, so the cached normalized
                # entities don't have LLM extractions yet. This updates them.
                self.update_normalized_with_llm_extractions(
                    enriched_entities, sync_context
                )
            except Exception as e:
                sync_context.logger.error(
                    f"[LLM Enrichment] Enrichment phase failed: {e}. "
                    f"Continuing with structured events only.",
                    exc_info=True
                )
                # Continue without LLM enrichment (graceful degradation)

        # Semantic merge (alias DB + vector + LLM judge) for unstructured connectors
        from contextd.core.config import settings as _settings

        _short = getattr(sync_context.connection, "short_name", "") or ""
        if _settings.SEMANTIC_MERGE_ENABLED:
            from contextd.db.session import get_db_context
            from contextd.platform.sync.semantic_merge import SemanticEntityMergeService

            _with_norm = [
                _e for _e in unique_entities if self.get_normalized_entity(_e.entity_id)
            ]
            sync_context.logger.info(
                "[SemanticMerge] Phase start (after LLM enrichment, before state load): "
                "normalized_entities=%s connector=%s shadow_mode=%s",
                len(_with_norm),
                _short,
                _settings.SEMANTIC_MERGE_SHADOW_MODE,
            )
            _svc = SemanticEntityMergeService()
            # One short-lived session per source entity. Connection-level errors (e.g. asyncpg
            # TimeoutError) can invalidate a session in ways SAVEPOINT rollback does not fix;
            # reusing the same session caused PendingRollbackError on the next entity.
            _merge_committed = 0
            for _e in _with_norm:
                _ne = self.get_normalized_entity(_e.entity_id)
                if not _ne:
                    continue
                try:
                    async with get_db_context() as _db:
                        merged_ne = await _svc.apply_to_normalized_entities(
                            _db, _ne, sync_context
                        )
                        await _db.commit()
                        self._normalized_cache[_e.entity_id] = merged_ne
                        _merge_committed += 1
                except Exception as merge_exc:
                    sync_context.logger.error(
                        "[SemanticMerge] Failed for entity %s: %s",
                        _ne.entity_id,
                        merge_exc,
                        exc_info=True,
                    )
            sync_context.logger.info(
                "[SemanticMerge] Phase complete: committed merge for %s/%s entities",
                _merge_committed,
                len(_with_norm),
            )

        # Phase 4: Load previous state
        previous_state = await self._load_previous_state(sync_context)

        # Phase 5: Compare states to detect changes
        comparison_result = await self._state_comparator.compare_states(
            current_entities=unique_entities,
            previous_state=previous_state,
            sync_context=sync_context,
        )

        # Phase 6: Generate graph events from normalized entities
        # Include unchanged entities to ensure graph consistency (self-healing).
        # If nodes were manually deleted from Neo4j, they will be recreated
        # because Neo4j MERGE operations are idempotent.
        sync_context.logger.info(
            f"Generating graph events for all entities: "
            f"{len(comparison_result.new_entities)} new, "
            f"{len(comparison_result.modified_entities)} modified, "
            f"{len(comparison_result.unchanged_entities)} unchanged "
            f"(ensuring graph consistency)"
        )
        event_batch = GraphEventBatch()

        for entity_comparison in (
            comparison_result.new_entities
            + comparison_result.modified_entities
            + comparison_result.unchanged_entities
        ):
            entity = entity_comparison.entity
            entity_definition_id = entity_comparison.entity_definition_id

            # Get normalized entity from cache
            normalized_entity = self.get_normalized_entity(entity.entity_id)

            if normalized_entity:
                from contextd.platform.sync.semantic_merge.semantic_entity_merge_service import (
                    SemanticEntityMergeService,
                )

                folded = SemanticEntityMergeService.fold_llm_person_extractions_into_people(
                    normalized_entity
                )
                self._normalized_cache[entity.entity_id] = folded
                events = await self._event_generator.generate_events_from_normalized(
                    folded, entity_definition_id, sync_context
                )
            else:
                # Normalization failed - log warning and skip event generation
                sync_context.logger.warning(
                    f"No normalized entity found for {entity.entity_id}, "
                    f"skipping graph event generation. Ensure normalizer is registered "
                    f"for entity type: {entity.__class__.__name__}"
                )
                continue

            event_batch.add_events(entity.entity_id, events)

        # Phase 7: Events are already normalized from generate_events_from_normalized
        # Just collect them
        normalized_batch = event_batch

        # Log event generation summary
        all_events = normalized_batch.get_all_events()
        sync_context.logger.info(
            f"📊 Generated {len(all_events)} graph events: "
            f"{len(normalized_batch.node_events)} nodes, "
            f"{len(normalized_batch.edge_events)} edges, "
            f"{len(normalized_batch.metadata_events)} metadata"
        )

        # Phase 8: Record entities in state builder
        await self._record_comparisons_in_state(comparison_result, sync_context)

        # Phase 9: Dispatch events to graph destination handler
        # This will store events in DB and return JSON for UI display
        await self._dispatch_graph_events(normalized_batch, sync_context)

        return normalized_batch

    async def _process_entity_indexing(
        self,
        entities: List[BaseEntity],
        sync_context: SyncContext,
    ) -> Dict[str, Any]:
        """Process entities for indexing.

        This phase creates:
        1. Fulltext indexes in Neo4j for text matching

        Runs after graph events are generated so node IDs are available
        for linking search results to graph nodes.

        Args:
            entities: Entities to index
            sync_context: Sync context

        Returns:
            Statistics about indexing operations
        """
        if not self._index_handler:
            return {"status": "skipped", "reason": "no_handler"}

        try:
            # Get normalized entities for richer indexing
            normalized_entities = self.get_all_normalized_entities()

            # Process entities through index handler
            stats = await self._index_handler.process_entities(
                entities=entities,
                sync_context=sync_context,
                normalized_entities=normalized_entities,
            )

            sync_context.logger.info(
                f"🔍 Entity indexing complete: "
                f"{stats.get('indexed_count', 0)} indexed, "
                f"{stats.get('vector_stored', 0)} vectors, "
                f"{stats.get('fulltext_indexed', 0)} fulltext"
            )

            return stats

        except Exception as e:
            # Graceful degradation - don't fail sync if indexing fails
            sync_context.logger.error(
                f"Entity indexing failed (continuing sync): {e}",
                exc_info=True
            )
            return {"status": "error", "error": str(e)}

    async def cleanup_orphaned_entities(self, sync_context: SyncContext) -> None:
        """Remove entities from database/destinations that were not encountered during sync.

        Called at the end of sync to clean up entities that exist in the database
        but were not seen during this sync run (deleted at source).

        Dispatches to the live cleanup path:
        - ARF storage;
        - PostgreSQL metadata;
        - entity-level search indexes when enabled.

        Args:
            sync_context: Sync context
        """
        # Get orphan entity IDs grouped by definition
        orphans_by_definition = await self._identify_orphans(sync_context)
        if not orphans_by_definition:
            return

        # Flatten for dispatcher (it just needs all IDs)
        all_orphan_ids = [
            entity_id for entity_ids in orphans_by_definition.values() for entity_id in entity_ids
        ]

        # Generate DELETE graph events for orphaned entities (if graph events enabled)
        if self._use_graph_events:
            await self._generate_delete_graph_events(orphans_by_definition, sync_context)

        # Chunk-vector destination cleanup is intentionally outside the default
        # live path. Entity-level search indexes are cleaned below.
        await self._dispatcher.dispatch_orphan_cleanup_postgres_only(all_orphan_ids, sync_context)

        # Clean up orphaned index entries (if indexing enabled)
        if self._use_entity_indexing and self._index_handler:
            try:
                await self._index_handler.cleanup_orphaned_indexes(
                    orphan_entity_ids=all_orphan_ids,
                    sync_context=sync_context,
                )
            except Exception as e:
                sync_context.logger.warning(
                    f"Failed to cleanup orphaned index entries: {e}"
                )

        # Update tracker with orphan deletion counts per definition
        for definition_id, entity_ids in orphans_by_definition.items():
            await sync_context.entity_tracker.record_deletes(definition_id, len(entity_ids))

    async def cleanup_temp_files(self, sync_context: SyncContext) -> None:
        """Remove entire sync_job_id directory (final cleanup safety net).

        Called in orchestrator's finally block to ensure cleanup happens even if
        pipeline fails.

        Args:
            sync_context: Sync context with source and logger
        """
        await cleanup_service.cleanup_temp_files(sync_context)

    # -------------------------------------------------------------------------
    # Phase 1: Track and Deduplicate
    # -------------------------------------------------------------------------

    async def _track_and_dedupe(
        self,
        entities: List[BaseEntity],
        sync_context: SyncContext,
    ) -> List[BaseEntity]:
        """Track entities and filter duplicates.

        This is the FIRST operation in the pipeline. Tracking must happen before
        any other processing to ensure accurate encounter tracking for orphan detection.

        Args:
            entities: Raw entities from source
            sync_context: Sync context

        Returns:
            List of unique (non-duplicate) entities
        """
        # Populate base fields first (needed for entity_id)
        for entity in entities:
            self._populate_base_entity_fields_from_flags(entity)

        # Track and filter duplicates
        unique = []
        skipped_count = 0

        for entity in entities:
            is_new = await self._tracker.track_entity(
                entity.__class__.__name__,
                entity.entity_id,
            )
            if is_new:
                unique.append(entity)
            else:
                skipped_count += 1
                sync_context.logger.debug(
                    f"Skipping duplicate: {entity.__class__.__name__}[{entity.entity_id}]"
                )

        if skipped_count > 0:
            await self._tracker.record_skipped(skipped_count)
            sync_context.logger.debug(
                f"Filtered {skipped_count} duplicates from batch of {len(entities)}"
            )

        # Update progress with encounter counts
        # This is now handled implicitly by track_entity but we might want to
        # update the detailed state publisher if we want real-time encounter stats
        # For now, we rely on the next batch processing to trigger publish

        if not unique:
            sync_context.logger.debug("All entities in batch were duplicates")

        return unique

    # -------------------------------------------------------------------------
    # Phase 2: Prepare Entities
    # -------------------------------------------------------------------------

    async def _prepare_entities(
        self,
        entities: List[BaseEntity],
        sync_context: SyncContext,
    ) -> None:
        """Prepare entities: enrich metadata, normalize, and compute hashes.

        Args:
            entities: Unique entities to prepare
            sync_context: Sync context
        """
        # Set source_name and other early metadata BEFORE normalization so that
        # normalizers (e.g. DatabaseEntityNormalizer) see the correct source and
        # write it into NormalizedEntity.source_type. That value is stored in the
        # graph and used when sampling for business logic; if we normalize first,
        # DB entities get source_type="database" and sampling by connector short_name
        # finds no nodes/edges.
        await self._enrich_early_metadata(entities, sync_context)

        masked_count = apply_pii_masking(
            entities,
            config=getattr(sync_context.source_instance, "config", None),
        )
        if masked_count:
            sync_context.logger.info(
                "Applied ContextD masking policy to %s field values before graph indexing",
                masked_count,
            )

        # Normalize entities to canonical format (extracts nested data)
        if self._use_entity_normalization:
            await self._normalize_entities(entities, sync_context)

        # Compute content hashes
        await hash_computer.compute_for_batch(entities, sync_context)

    async def _normalize_entities(
        self,
        entities: List[BaseEntity],
        sync_context: SyncContext,
    ) -> None:
        """Normalize entities to canonical format.

        Transforms connector-specific entities into NormalizedEntity format,
        extracting nested data like people, tags, and relationships.

        The normalized entities are cached for later use (e.g., graph building).

        Args:
            entities: Entities to normalize
            sync_context: Sync context
        """
        normalized_count = 0

        for entity in entities:
            try:
                # Get appropriate normalizer for this entity type
                normalizer = get_normalizer_for_entity(entity)

                # Normalize the entity
                normalized = normalizer.normalize(entity)

                # Cache the normalized entity for later use
                self._normalized_cache[entity.entity_id] = normalized

                # Store reference on original entity for easy access
                entity._normalized = normalized

                normalized_count += 1

            except Exception as e:
                sync_context.logger.warning(
                    f"Failed to normalize entity {entity.__class__.__name__}[{entity.entity_id}]: {e}"
                )
                # Continue processing even if normalization fails
                continue

        if normalized_count > 0:
            sync_context.logger.debug(
                f"📊 Normalized {normalized_count}/{len(entities)} entities to canonical format"
            )

    def get_normalized_entity(self, entity_id: str) -> Optional[NormalizedEntity]:
        """Get cached normalized entity by ID.

        Args:
            entity_id: Entity ID

        Returns:
            NormalizedEntity if cached, None otherwise
        """
        return self._normalized_cache.get(entity_id)

    def get_all_normalized_entities(self) -> Dict[str, NormalizedEntity]:
        """Get all cached normalized entities.

        Returns:
            Dict mapping entity_id to NormalizedEntity
        """
        return self._normalized_cache.copy()

    def update_normalized_with_llm_extractions(
        self,
        enriched_entities: List[BaseEntity],
        sync_context: SyncContext,
    ) -> int:
        """Update cached normalized entities with LLM extractions.

        This is called AFTER LLM enrichment completes, since normalization runs
        before enrichment but LLM extractions are only available afterward.

        Args:
            enriched_entities: Entities that have been enriched with LLM extractions
            sync_context: Sync context for logging

        Returns:
            Number of normalized entities updated with LLM extractions
        """
        from contextd.platform.sync.normalizers import get_normalizer_for_entity

        updated_count = 0

        for entity in enriched_entities:
            if entity.entity_id not in self._normalized_cache:
                continue

            # Get the cached normalized entity
            normalized = self._normalized_cache[entity.entity_id]

            # Get normalizer for this entity type
            normalizer = get_normalizer_for_entity(entity)
            if not normalizer:
                continue

            # Convert LLM extractions to refs (now that entity has _llm_extracted_entities)
            llm_refs = normalizer.convert_llm_extractions_to_refs(entity)

            if llm_refs:
                # Update the cached normalized entity with LLM extractions
                # NormalizedEntity is immutable (frozen=True), so we create a new one
                self._normalized_cache[entity.entity_id] = NormalizedEntity(
                    entity_id=normalized.entity_id,
                    entity_type=normalized.entity_type,
                    source_type=normalized.source_type,
                    name=normalized.name,
                    description=normalized.description,
                    content=normalized.content,
                    web_url=normalized.web_url,
                    people=normalized.people,
                    tags=normalized.tags,
                    relations=normalized.relations,
                    status=normalized.status,
                    priority=normalized.priority,
                    custom_fields=normalized.custom_fields,
                    llm_extractions=llm_refs,  # Updated with LLM extractions
                    created_at=normalized.created_at,
                    updated_at=normalized.updated_at,
                    due_at=normalized.due_at,
                    completed_at=normalized.completed_at,
                    properties=normalized.properties,
                    breadcrumb_ids=normalized.breadcrumb_ids,
                    breadcrumb_names=normalized.breadcrumb_names,
                )
                updated_count += 1

        if updated_count > 0:
            sync_context.logger.info(
                f"[LLM Extractions] Updated {updated_count} normalized entities "
                f"with LLM extractions"
            )

        return updated_count

    # -------------------------------------------------------------------------
    # Graph Event Pipeline Helpers (Phase 2)
    # -------------------------------------------------------------------------

    async def _load_previous_state(self, sync_context: SyncContext):
        """Load previous sync state for comparison (cached per pipeline).

        Args:
            sync_context: Sync context

        Returns:
            Previous SyncState or None if this is the first sync
        """
        # Return cached state if already loaded
        if self._previous_state_loaded:
            return self._previous_state

        # Initialize lock lazily to ensure it is created within the correct async event loop
        if self._previous_state_lock is None:
            self._previous_state_lock = asyncio.Lock()

        async with self._previous_state_lock:
            # Check again inside the lock
            if self._previous_state_loaded:
                return self._previous_state

            from contextd import crud
            from contextd.db.session import get_db_context

            async with get_db_context() as db:
                previous_state = await crud.sync_state.get_latest_by_sync_id(
                    db=db,
                    sync_id=sync_context.sync.id,
                    ctx=sync_context.ctx,
                )

            if previous_state:
                sync_context.logger.info(
                    f"📂 Loaded previous state from {previous_state.created_at}"
                )
            else:
                sync_context.logger.info("📂 No previous state found - treating all entities as new")

            self._previous_state = previous_state
            self._previous_state_loaded = True

            return self._previous_state

    async def _record_comparisons_in_state(
        self,
        comparison_result,
        sync_context: SyncContext,
    ) -> None:
        """Record entity comparisons in state builder.

        Args:
            comparison_result: StateComparisonResult
            sync_context: Sync context
        """
        # Record new entities
        for entity_comparison in comparison_result.new_entities:
            await sync_context.state_builder.record_entity(
                entity=entity_comparison.entity,
                entity_definition_id=entity_comparison.entity_definition_id,
                action_type="INSERT",
            )

        # Record modified entities
        for entity_comparison in comparison_result.modified_entities:
            await sync_context.state_builder.record_entity(
                entity=entity_comparison.entity,
                entity_definition_id=entity_comparison.entity_definition_id,
                action_type="UPDATE",
            )

        # Record unchanged entities
        for entity_comparison in comparison_result.unchanged_entities:
            await sync_context.state_builder.record_entity(
                entity=entity_comparison.entity,
                entity_definition_id=entity_comparison.entity_definition_id,
                action_type="KEEP",
            )

    async def _dispatch_graph_events(
        self,
        event_batch: GraphEventBatch,
        sync_context: SyncContext,
    ) -> None:
        """Dispatch graph events to graph destination handler.

        Two-Phase Commit Architecture:
        - Phase 1 (this method): Store events in PostgreSQL with status='pending'
        - Phase 2 (GraphCommitService): Atomic commit to Neo4j after all batches complete

        This eliminates race conditions by ensuring all events are collected
        before any Neo4j writes occur.

        Args:
            event_batch: Batch of generated graph events
            sync_context: Sync context
        """
        # Import here to avoid circular dependency
        from contextd.platform.sync.handlers.graph_destination import (
            GraphDestinationHandler,
        )

        # Create handler with normalized entities cache for UI rendering
        handler = GraphDestinationHandler(
            sync_context=sync_context,
            normalized_entities=self._normalized_cache,
        )

        # Process events (stores in DB with normalized data)
        # Phase 1: Events go to PostgreSQL with commit_status='pending'
        # Phase 2: Neo4j commit happens in SyncOrchestrator._commit_graph_events_if_enabled()
        result = await handler.process_events(event_batch)

        # Store result in sync context for later retrieval
        if not hasattr(sync_context, 'graph_event_results'):
            sync_context.graph_event_results = []
        sync_context.graph_event_results.append(result)

        sync_context.logger.info(
            f"✅ Stored {result['total_events']} graph events in database (pending Phase 2 commit)"
        )

    # -------------------------------------------------------------------------
    # Phase 3.5: Record Entities in State Builder
    # -------------------------------------------------------------------------

    async def _record_entities_in_state(
        self,
        batch: EntityActionBatch,
        sync_context: SyncContext,
    ) -> None:
        """Record all entities in state builder for comprehensive state snapshot.

        This captures entity hashes, field hashes, relationships, and metadata
        for each entity processed during sync. The state builder will compile
        this into a complete state object at sync completion.

        Args:
            batch: EntityActionBatch with all resolved actions
            sync_context: Sync context with state_builder
        """
        # Record INSERT actions
        for action in batch.inserts:
            await sync_context.state_builder.record_entity(
                entity=action.entity,
                entity_definition_id=action.entity_definition_id,
                action_type="INSERT",
            )

        # Record UPDATE actions
        for action in batch.updates:
            await sync_context.state_builder.record_entity(
                entity=action.entity,
                entity_definition_id=action.entity_definition_id,
                action_type="UPDATE",
            )

        # Record DELETE actions
        for action in batch.deletes:
            await sync_context.state_builder.record_entity(
                entity=action.entity,
                entity_definition_id=action.entity_definition_id,
                action_type="DELETE",
            )

        # Record KEEP actions
        for action in batch.keeps:
            await sync_context.state_builder.record_entity(
                entity=action.entity,
                entity_definition_id=action.entity_definition_id,
                action_type="KEEP",
            )

    # -------------------------------------------------------------------------
    # Phase 4: Handle KEEP-only batches
    # -------------------------------------------------------------------------

    async def _handle_keep_only_batch(
        self,
        batch: EntityActionBatch,
        sync_context: SyncContext,
    ) -> None:
        """Handle batch where all entities are KEEP (unchanged).

        Args:
            batch: EntityActionBatch with only KEEP actions
            sync_context: Sync context
        """
        if batch.keeps:
            # We record kept entities and trigger publish
            await self._tracker.record_kept(len(batch.keeps))
            await sync_context.state_publisher.check_and_publish()

            sync_context.logger.debug(
                f"All {len(batch.keeps)} entities unchanged - skipping pipeline"
            )

    # -------------------------------------------------------------------------
    # Phase 6: Update Entity Tracker
    # -------------------------------------------------------------------------

    async def _update_tracker(
        self,
        batch: EntityActionBatch,
        sync_context: SyncContext,
    ) -> None:
        """Update entity tracker with successful operations.

        Triggers pubsub updates via SyncStatePublisher.

        Args:
            batch: EntityActionBatch that was successfully processed
            sync_context: Sync context
        """
        # Collect counts by entity definition
        inserts_by_def: Dict[UUID, int] = defaultdict(int)
        updates_by_def: Dict[UUID, int] = defaultdict(int)
        deletes_by_def: Dict[UUID, int] = defaultdict(int)
        entity_names: Dict[UUID, str] = {}

        for action in batch.inserts:
            inserts_by_def[action.entity_definition_id] += 1
            entity_names[action.entity_definition_id] = action.entity_type

        for action in batch.updates:
            updates_by_def[action.entity_definition_id] += 1
            entity_names[action.entity_definition_id] = action.entity_type

        for action in batch.deletes:
            deletes_by_def[action.entity_definition_id] += 1
            entity_names[action.entity_definition_id] = action.entity_type

        # Update tracker in one call (includes kept/skipped from global stats)
        await self._tracker.record_batch_results(
            inserts_by_def=inserts_by_def,
            updates_by_def=updates_by_def,
            deletes_by_def=deletes_by_def,
            keeps_count=len(batch.keeps),
            entity_names=entity_names,
        )

        # Trigger pubsub update
        await sync_context.state_publisher.check_and_publish()

    # -------------------------------------------------------------------------
    # Orphan Identification
    # -------------------------------------------------------------------------

    async def _identify_orphans(self, sync_context: SyncContext) -> Dict[UUID, List[str]]:
        """Identify orphaned entity IDs (in DB but not encountered), grouped by definition.

        Args:
            sync_context: Sync context

        Returns:
            Dict mapping entity_definition_id to list of orphaned entity IDs
        """
        from contextd import crud
        from contextd.db.session import get_db_context

        # Get all encountered IDs
        encountered_ids = self._tracker.get_all_encountered_ids_flat()

        # Get all stored entity IDs for this sync
        async with get_db_context() as db:
            stored_entities = await crud.entity.get_by_sync_id(db=db, sync_id=sync_context.sync.id)

        # Find orphans grouped by definition
        orphans_by_definition: Dict[UUID, List[str]] = defaultdict(list)
        for entity in stored_entities:
            if entity.entity_id not in encountered_ids:
                orphans_by_definition[entity.entity_definition_id].append(entity.entity_id)

        total_orphans = sum(len(ids) for ids in orphans_by_definition.values())
        if total_orphans:
            sync_context.logger.info(
                f"🔍 Identified {total_orphans} orphaned entities "
                f"across {len(orphans_by_definition)} definitions "
                f"out of {len(stored_entities)} stored"
            )

        return dict(orphans_by_definition)

    # -------------------------------------------------------------------------
    # Temp File Cleanup
    # -------------------------------------------------------------------------

    async def _cleanup_temp_files_for_batch(
        self,
        batch: EntityActionBatch,
        sync_context: SyncContext,
    ) -> None:
        """Clean up temp files for processed batch.

        Args:
            batch: EntityActionBatch that was processed
            sync_context: Sync context
        """
        # Build a pseudo-partitions dict for compatibility with CleanupService
        partitions = {
            "inserts": [a.entity for a in batch.inserts],
            "updates": [a.entity for a in batch.updates],
        }
        await cleanup_service.cleanup_processed_files(partitions, sync_context)

    # -------------------------------------------------------------------------
    # Helper Methods (unchanged from original)
    # -------------------------------------------------------------------------

    def _get_flagged_field_value(self, entity: BaseEntity, flag_name: str) -> Any:
        """Extract value of field marked with specified flag."""
        flag_key = flag_name.value if hasattr(flag_name, "value") else flag_name

        for field_name, field_info in entity.model_fields.items():
            json_extra = field_info.json_schema_extra
            if json_extra and isinstance(json_extra, dict):
                if json_extra.get(flag_key):
                    return getattr(entity, field_name, None)

        return None

    async def _generate_delete_graph_events(
        self,
        orphans_by_definition: Dict[UUID, List[str]],
        sync_context: SyncContext,
    ) -> None:
        """Generate DELETE graph events for orphaned entities.

        Args:
            orphans_by_definition: Dict mapping entity_definition_id to list of orphaned entity IDs
            sync_context: Sync context
        """
        from datetime import datetime
        from uuid import uuid4

        from contextd.platform.sync.graph.event_batch import GraphEventBatch
        from contextd.schemas.graph_event import NodeEventPayload, TypedGraphEvent

        if not orphans_by_definition:
            return

        # Create a batch of DELETE events
        event_batch = GraphEventBatch()

        # Get reverse mapping: entity_definition_id -> entity_type_name
        entity_type_names = {}
        for entity_class, entity_def_id in sync_context.entity_map.items():
            entity_type_names[entity_def_id] = entity_class.__name__

        # Generate NODE_DELETE events for each orphaned entity
        for entity_definition_id, entity_ids in orphans_by_definition.items():
            entity_type = entity_type_names.get(entity_definition_id, "UnknownEntity")

            for entity_id in entity_ids:
                # Create NODE_DELETE event
                delete_event = TypedGraphEvent(
                    event_id=uuid4(),
                    event_type="NODE_DELETE",
                    entity_id=entity_id,
                    entity_type=entity_type,
                    entity_definition_id=entity_definition_id,
                    field_name="__entity_deleted__",  # Special marker for entity deletion
                    timestamp=datetime.utcnow(),
                    payload=NodeEventPayload(
                        node_id=entity_id,
                        node_type=entity_type,
                        node_properties={"deleted": True, "reason": "orphaned"},
                        operation="DELETE",
                    ),
                )
                event_batch.node_events.append(delete_event)

        # Log and dispatch delete events
        total_events = len(event_batch.get_all_events())
        if total_events > 0:
            sync_context.logger.info(
                f"📊 Generated {total_events} DELETE graph events for orphaned entities"
            )
            await self._dispatch_graph_events(event_batch, sync_context)

    def _populate_base_entity_fields_from_flags(self, entity: BaseEntity) -> None:
        """Populate BaseEntity fields from flagged fields."""
        if not entity.entity_id:
            flagged_value = self._get_flagged_field_value(entity, ContextDFieldFlag.IS_ENTITY_ID)
            if flagged_value:
                entity.entity_id = str(flagged_value)

        if not entity.name:
            flagged_value = self._get_flagged_field_value(entity, ContextDFieldFlag.IS_NAME)
            if flagged_value:
                entity.name = str(flagged_value)

        if not entity.created_at:
            flagged_value = self._get_flagged_field_value(entity, ContextDFieldFlag.IS_CREATED_AT)
            if flagged_value is not None:
                entity.created_at = flagged_value

        if not entity.updated_at:
            flagged_value = self._get_flagged_field_value(entity, ContextDFieldFlag.IS_UPDATED_AT)
            if flagged_value is not None:
                entity.updated_at = flagged_value

    async def _enrich_early_metadata(
        self,
        entities: List[BaseEntity],
        sync_context: SyncContext,
    ) -> None:
        """Set early metadata fields from sync_context."""
        from contextd.platform.entities._base import ContextDSystemMetadata

        for entity in entities:
            if entity.contextd_system_metadata is None:
                entity.contextd_system_metadata = ContextDSystemMetadata()

            entity.contextd_system_metadata.source_name = sync_context.source_instance._short_name
            entity.contextd_system_metadata.entity_type = entity.__class__.__name__
            entity.contextd_system_metadata.sync_id = sync_context.sync.id
            entity.contextd_system_metadata.sync_job_id = sync_context.sync_job.id

        # Validate
        for entity in entities:
            if entity.contextd_system_metadata is None:
                raise SyncFailureError(
                    f"PROGRAMMING ERROR: contextd_system_metadata not initialized "
                    f"for entity {entity.entity_id}"
                )

    # -------------------------------------------------------------------------
    # LLM Enrichment Helpers (NEW)
    # -------------------------------------------------------------------------

    def _detect_llm_enabled_entities(
        self, entities: List[BaseEntity], sync_context: SyncContext
    ) -> List[BaseEntity]:
        """Detect entities with LLM extraction enabled.

        Uses the EntityMetadata system with _entity_metadata class attribute.
        Checks both entity-level enable_llm_enrichment and field-level LLM configs.

        Args:
            entities: Entities to check
            sync_context: Sync context for logging

        Returns:
            List of entities that need LLM enrichment
        """
        entities_with_llm = []
        entity_types_checked = set()

        for entity in entities:
            entity_type = entity.__class__.__name__

            # Check the EntityMetadata system
            entity_metadata = getattr(entity.__class__, "_entity_metadata", None)

            if not entity_metadata:
                continue

            # Check entity-level enable_llm_enrichment flag
            llm_enabled = getattr(entity_metadata, "enable_llm_enrichment", False)

            if llm_enabled:
                entities_with_llm.append(entity)
                if entity_type not in entity_types_checked:
                    sync_context.logger.debug(
                        f"[LLM Detection] {entity_type} has enable_llm_enrichment=True"
                    )
                    entity_types_checked.add(entity_type)
                continue

            # Check field-level LLM configs
            fields = getattr(entity_metadata, "fields", {})
            for field_name, field_meta in fields.items():
                llm_config = getattr(field_meta, "llm", None)
                if llm_config and getattr(llm_config, "enabled", False):
                    entities_with_llm.append(entity)
                    if entity_type not in entity_types_checked:
                        sync_context.logger.debug(
                            f"[LLM Detection] {entity_type}.{field_name} has LLM config enabled"
                        )
                        entity_types_checked.add(entity_type)
                    break

        return entities_with_llm

    async def _llm_enrichment_phase(
        self,
        entities: List[BaseEntity],
        sync_context: SyncContext,
    ) -> List[BaseEntity]:
        """Enrich entities using LLM to extract structured data from content fields.

        Args:
            entities: Entities that have llm_extraction_config
            sync_context: Sync context

        Returns:
            Enriched entities with _llm_extracted_entities and _llm_extracted_relationships
        """
        try:
            from contextd.platform.llm.gateway import (
                LLMConfigurationError,
                get_llm_gateway,
            )

            gateway = get_llm_gateway()
            try:
                provider = gateway.create_provider(role="extraction", ctx=sync_context)
            except LLMConfigurationError as e:
                sync_context.logger.warning(
                    "[LLM Enrichment] %s. Skipping LLM enrichment.",
                    e,
                )
                return entities

            # Create enrichment service
            enrichment_service = LLMEnrichmentService(
                provider=provider,
                sync_context=sync_context
            )

            # Process entities with concurrency limit
            enriched_entities = []
            semaphore = asyncio.Semaphore(5)  # Max 5 concurrent LLM calls

            async def enrich_one(entity: BaseEntity):
                async with semaphore:
                    try:
                        enriched = await enrichment_service.enrich_entity(entity)
                        return enriched
                    except Exception as e:
                        sync_context.logger.error(
                            f"[LLM Enrichment] Failed to enrich {entity.entity_id}: {e}"
                        )
                        return entity  # Return original entity on failure

            enriched_entities = await asyncio.gather(*[enrich_one(e) for e in entities])
            return enriched_entities

        except Exception as e:
            sync_context.logger.error(
                f"[LLM Enrichment] Failed to initialize enrichment service: {e}"
            )
            return entities  # Return originals on failure
