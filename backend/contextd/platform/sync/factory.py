"""Module for sync factory that creates orchestrator instances.

This factory uses SyncContextBuilder and EntityDispatcherBuilder to construct
all components needed for a sync run.
"""

import time
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api.context import ApiContext
from contextd.core.config import settings
from contextd.core.logging import logger
from contextd.platform.builders import SyncContextBuilder
from contextd.platform.sync.actions import EntityActionResolver, EntityDispatcherBuilder
from contextd.platform.sync.config import SyncExecutionConfig
from contextd.platform.sync.entity_pipeline import EntityPipeline
from contextd.platform.sync.graph import GraphEventGenerator
from contextd.platform.sync.graph.entity_resolution import EntityResolutionService
from contextd.platform.sync.handlers.index_handler import create_index_handler
from contextd.platform.sync.orchestrator import SyncOrchestrator
from contextd.platform.sync.state.comparator import StateComparator
from contextd.platform.sync.stream import AsyncSourceStream
from contextd.platform.sync.worker_pool import AsyncWorkerPool


class SyncFactory:
    """Factory for sync orchestrator.

    Uses SyncContextBuilder to create contexts and EntityDispatcherBuilder
    to create the action dispatcher with handlers.
    """

    @staticmethod
    def _default_execution_config() -> SyncExecutionConfig:
        """Build the default live sync config."""
        return SyncExecutionConfig.default()

    @staticmethod
    def _source_requires_complete_graph_snapshot(
        *,
        short_name: str,
        config_fields: dict | None,
    ) -> bool:
        """Return True when graph commits need a full relational snapshot.

        Relational connectors emit graph edges across tables. Cursor-only delta runs
        should upsert changed graph events without pruning the live graph; explicit
        full snapshot runs can also reconcile deletions. This helper is only for
        opt-in sources that truly need a complete snapshot every time.
        """
        if not bool(getattr(settings, "USE_GRAPH_EVENTS", False)):
            return False

        if short_name not in {"clickhouse", "postgresql", "snowflake"}:
            return False

        config_fields = config_fields or {}
        if config_fields.get("contextd_graph_enabled") is False:
            return False
        return str(config_fields.get("graph_snapshot_mode", "")).lower() in {
            "complete",
            "complete_always",
            "full",
        }

    @classmethod
    async def create_orchestrator(
        cls,
        db: AsyncSession,
        sync: schemas.Sync,
        sync_job: schemas.SyncJob,
        collection: schemas.Collection,
        connection: schemas.Connection,
        ctx: ApiContext,
        access_token: Optional[str] = None,
        max_workers: int = None,
        force_full_sync: bool = False,
        execution_config: Optional[SyncExecutionConfig] = None,
    ) -> SyncOrchestrator:
        """Create a dedicated orchestrator instance for a sync run.

        This method creates all necessary components for a sync run, including the
        context and a dedicated orchestrator instance for concurrent execution.

        Args:
            db: Database session
            sync: The sync configuration
            sync_job: The sync job
            collection: The collection to sync to
            connection: The connection
            ctx: The API context
            access_token: Optional token to use instead of stored credentials
            max_workers: Maximum number of concurrent workers (default: from settings)
            force_full_sync: If True, forces a full sync with orphaned entity deletion
            execution_config: Optional execution config for controlling sync behavior

        Returns:
            A dedicated SyncOrchestrator instance
        """
        execution_config = execution_config or cls._default_execution_config()

        if not force_full_sync:
            try:
                source_connection = await crud.source_connection.get_by_sync_id(
                    db=db,
                    sync_id=sync.id,
                    ctx=ctx,
                )
                if source_connection and cls._source_requires_complete_graph_snapshot(
                    short_name=connection.short_name,
                    config_fields=source_connection.config_fields,
                ):
                    force_full_sync = True
                    logger.info(
                        "ContextD graph snapshot mode: forcing a complete relational "
                        "snapshot for %s sync %s before graph commit.",
                        connection.short_name,
                        sync.id,
                    )
            except Exception as exc:
                logger.warning(
                    "Could not determine graph snapshot mode for sync %s; "
                    "continuing with requested sync mode: %s",
                    sync.id,
                    exc,
                )

        # Use configured value if max_workers not specified
        if max_workers is None:
            max_workers = settings.SYNC_MAX_WORKERS
            logger.debug(f"Using configured max_workers: {max_workers}")

        # Track initialization timing
        init_start = time.time()
        logger.info("Creating sync context via context builders...")

        # Step 0: Load database schema definitions if PostgreSQL source
        if connection.short_name == "postgresql":
            try:
                from contextd.platform.configs.database.definitions.postgres import (
                    POSTGRES_SCHEMA_DEFINITIONS,
                )
                from contextd.platform.configs.database.loader import DatabaseSchemaLoader

                # Load schema definitions into registry
                DatabaseSchemaLoader.load_schema_definitions(
                    "postgres", POSTGRES_SCHEMA_DEFINITIONS
                )

                # Validate schemas
                validation_results = DatabaseSchemaLoader.validate_all_schemas("postgres")
                if validation_results:
                    logger.warning(
                        f"Schema validation warnings: {validation_results}. "
                        "Continuing with sync..."
                    )
                else:
                    logger.info(
                        f"Loaded {len(POSTGRES_SCHEMA_DEFINITIONS)} PostgreSQL schema definitions"
                    )
            except ImportError as e:
                logger.debug(f"Could not load PostgreSQL schema definitions: {e}")
            except Exception as e:
                logger.warning(f"Error loading PostgreSQL schema definitions: {e}")

        # ClickHouse uses dynamic introspection only (no pre-loaded schema definitions)
        if connection.short_name == "clickhouse":
            logger.debug("ClickHouse source: schema will be introspected at sync time")

        # Step 1: Build sync context using SyncContextBuilder
        sync_context = await SyncContextBuilder.build(
            db=db,
            sync=sync,
            sync_job=sync_job,
            collection=collection,
            connection=connection,
            ctx=ctx,
            access_token=access_token,
            force_full_sync=force_full_sync,
            execution_config=execution_config,
        )

        logger.debug(f"Sync context created in {time.time() - init_start:.2f}s")

        # Step 2: Build dispatcher using EntityDispatcherBuilder
        logger.debug("Initializing pipeline components...")

        dispatcher = EntityDispatcherBuilder.build(
            destinations=sync_context.destinations,
            execution_config=execution_config,
            logger=sync_context.logger,
        )

        # Step 3: Build pipeline
        action_resolver = EntityActionResolver(entity_map=sync_context.entity_map)

        # Phase 2: Graph event generation components
        # Set USE_GRAPH_EVENTS=true in environment to enable
        use_graph_events = settings.USE_GRAPH_EVENTS if hasattr(settings, 'USE_GRAPH_EVENTS') else False
        state_comparator = StateComparator() if use_graph_events else None

        # Initialize entity resolution service for cross-connector entity merging
        resolution_service = None
        if use_graph_events:
            try:
                from contextd.platform.graph.factory import get_graph_driver
                graph_driver = await get_graph_driver()
                readable_collection_id = getattr(
                    getattr(sync_context, "collection", None),
                    "readable_id",
                    None,
                )
                if readable_collection_id:
                    target_database = await graph_driver.ensure_context_database(
                        sync.organization_id,
                        readable_collection_id,
                    )
                    graph_driver = graph_driver.for_database(target_database)
                resolution_service = EntityResolutionService(
                    graph_driver=graph_driver,
                    organization_id=sync.organization_id,
                    fuzzy_threshold=0.8,
                )
                logger.info("✅ Entity resolution service initialized for cross-connector merging")
            except Exception as e:
                logger.warning(f"Failed to initialize entity resolution service: {e}")
                logger.warning("Falling back to deterministic ID generation (no cross-connector merging)")

        event_generator = GraphEventGenerator(resolution_service=resolution_service) if use_graph_events else None

        if use_graph_events:
            logger.info("📊 Graph event generation enabled for this sync")

        # Entity-level indexing is the current live search path:
        # Neo4j fulltext indexes over graph-backed entities.
        use_entity_indexing = bool(getattr(settings, "USE_ENTITY_INDEXING", True)) or use_graph_events
        index_handler = None

        if use_entity_indexing:
            try:
                from contextd.platform.configs.index import get_index_config
                index_config = get_index_config()

                if index_config.enabled:
                    index_handler = create_index_handler(index_config)
                    logger.info(
                        f"🔍 Entity-level indexing enabled for this sync "
                        f"(fulltext={index_config.fulltext_enabled})"
                    )
                else:
                    logger.debug("Entity indexing is disabled in config")
                    use_entity_indexing = False
            except Exception as e:
                logger.warning(f"Failed to initialize index handler: {e}")
                logger.warning("Entity-level indexing will be skipped for this sync")
                use_entity_indexing = False

        entity_pipeline = EntityPipeline(
            entity_tracker=sync_context.entity_tracker,
            action_resolver=action_resolver,
            action_dispatcher=dispatcher,
            state_comparator=state_comparator,
            event_generator=event_generator,
            use_graph_events=use_graph_events,
            index_handler=index_handler,
            use_entity_indexing=use_entity_indexing,
        )

        # Step 4: Create worker pool
        worker_pool = AsyncWorkerPool(max_workers=max_workers, logger=sync_context.logger)

        # Step 5: Create stream
        queue_size = getattr(settings, "SYNC_QUEUE_SIZE", 10000)
        stream = AsyncSourceStream(
            source_generator=sync_context.source_instance.generate_entities(),
            queue_size=queue_size,
            logger=sync_context.logger,
        )

        # Step 6: Create orchestrator
        orchestrator = SyncOrchestrator(
            entity_pipeline=entity_pipeline,
            worker_pool=worker_pool,
            stream=stream,
            sync_context=sync_context,
        )

        logger.info(f"Total orchestrator initialization took {time.time() - init_start:.2f}s")

        return orchestrator
