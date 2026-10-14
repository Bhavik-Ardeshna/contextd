"""Tests for the ContextD sync/search live path contract."""

from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")


class _Logger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str, *args, **kwargs) -> None:
        self.messages.append(str(message))

    def debug(self, message: str, *args, **kwargs) -> None:
        self.messages.append(str(message))

    def warning(self, message: str, *args, **kwargs) -> None:
        self.messages.append(str(message))


def test_default_sync_config_has_only_live_persistence_handlers() -> None:
    """Default sync persists records and lets IndexHandler own the search index."""
    from contextd.platform.sync.config import SyncExecutionConfig

    config = SyncExecutionConfig.default()

    assert config.enable_raw_data_handler is True
    assert config.enable_postgres_handler is True
    assert not hasattr(config, "enable_" + "vector_handlers")


def test_arf_capture_config_disables_metadata_writes() -> None:
    """ARF capture mode keeps raw capture without postgres metadata writes."""
    from contextd.platform.sync.config import SyncExecutionConfig

    config = SyncExecutionConfig.arf_capture_only()

    assert config.enable_raw_data_handler is True
    assert config.enable_postgres_handler is False
    assert config.skip_hash_comparison is True
    assert config.skip_cursor_load is True
    assert config.skip_cursor_updates is True


def test_sync_factory_uses_default_live_persistence_config() -> None:
    """The factory default has no hidden destination-write setting."""
    from contextd.platform.sync import factory as sync_factory

    config = sync_factory.SyncFactory._default_execution_config()
    removed_setting = "ENABLE_" + "CHUNK_VECTOR_DESTINATION_WRITES"

    assert config == sync_factory.SyncExecutionConfig.default()
    assert not hasattr(sync_factory.settings, removed_setting)


def test_dispatcher_builder_ignores_destination_context_for_live_sync() -> None:
    """The live sync path persists only through ARF and postgres handlers."""
    from contextd.platform.contexts.destinations import DestinationsContext
    from contextd.platform.sync.actions.entity.builder import EntityDispatcherBuilder
    from contextd.platform.sync.config import SyncExecutionConfig

    fake_destination = SimpleNamespace()
    logger = _Logger()

    dispatcher = EntityDispatcherBuilder.build(
        destinations=DestinationsContext(destinations=[fake_destination]),
        execution_config=SyncExecutionConfig.default(),
        logger=logger,
    )

    assert not hasattr(dispatcher, "_destination_handlers")
    assert dispatcher._arf_handler is not None
    assert dispatcher._postgres_handler is not None
    assert any("Ignoring configured destinations" in msg for msg in logger.messages)


def test_dispatcher_builder_supports_arf_only_capture() -> None:
    """ARF capture mode does not register the postgres handler."""
    from contextd.platform.contexts.destinations import DestinationsContext
    from contextd.platform.sync.actions.entity.builder import EntityDispatcherBuilder
    from contextd.platform.sync.config import SyncExecutionConfig

    dispatcher = EntityDispatcherBuilder.build(
        destinations=DestinationsContext(destinations=[]),
        execution_config=SyncExecutionConfig.arf_capture_only(),
        logger=_Logger(),
    )

    assert dispatcher._arf_handler is not None
    assert dispatcher._postgres_handler is None


@pytest.mark.asyncio
async def test_destination_context_builds_no_live_write_destinations(monkeypatch) -> None:
    """Live sync context avoids constructing destination clients."""
    from contextd.platform.builders.destinations import DestinationsContextBuilder
    from contextd.platform.sync.config import SyncExecutionConfig

    async def fake_entity_map(db):
        return {object: uuid4()}

    monkeypatch.setattr(
        DestinationsContextBuilder,
        "_get_entity_definition_map",
        fake_entity_map,
    )

    context = await DestinationsContextBuilder.build(
        db=None,
        sync=SimpleNamespace(destination_connection_ids=[uuid4()]),
        collection=SimpleNamespace(),
        infra=SimpleNamespace(ctx=SimpleNamespace(), logger=_Logger()),
        execution_config=SyncExecutionConfig.default(),
    )

    assert context.destinations == []
    assert object in context.entity_map


@pytest.mark.asyncio
async def test_cleanup_context_builds_no_destination_adapters() -> None:
    """Cleanup no longer constructs destination clients in the live path."""
    from contextd.platform.builders.destinations import DestinationsContextBuilder

    context = await DestinationsContextBuilder.build_for_cleanup(
        db=None,
        collection=SimpleNamespace(),
        logger=_Logger(),
    )

    assert context == []


@pytest.mark.asyncio
async def test_default_search_destination_is_neo4j_fulltext(monkeypatch) -> None:
    """The default live search destination follows the Docker runtime."""
    from contextd.platform.destinations.neo4j_fulltext import Neo4jFulltextDestination
    from contextd.search import factory as search_factory_module
    from contextd.search.factory import SearchFactory

    collection_id = uuid4()
    organization_id = uuid4()
    monkeypatch.setattr(search_factory_module.settings, "SEARCH_INDEX_BACKEND", "neo4j-fulltext")

    destination = await SearchFactory()._get_destination_for_collection(
        db=None,
        collection=SimpleNamespace(id=collection_id, readable_id="demo", vector_size=1536),
        ctx=SimpleNamespace(organization=SimpleNamespace(id=organization_id), logger=_Logger()),
    )

    assert isinstance(destination, Neo4jFulltextDestination)
    assert destination.collection_id == collection_id
    assert destination.organization_id == organization_id
    assert destination._requires_client_embedding is False
    assert destination._supports_user_filters is False


def test_sync_execution_config_has_no_removed_destination_write_controls() -> None:
    """Removed execution controls are not part of the live sync contract."""
    from contextd.platform.sync.config import SyncExecutionConfig

    config = SyncExecutionConfig.default()
    removed_service = "ve" + "spa"

    assert not hasattr(config, "skip_" + removed_service)
    assert not hasattr(SyncExecutionConfig, removed_service + "_only")


def test_source_tree_has_no_removed_destination_write_path_references() -> None:
    """The removed destination-write path should not linger in source files."""
    source_root = Path(__file__).resolve().parents[3] / "contextd"
    patterns = [
        re.compile(r"ENABLE_" + "CHUNK_VECTOR_DESTINATION_WRITES"),
        re.compile(r"\benable_" + r"vector_handlers\b"),
        re.compile(r"\bCHUNKS_AND_" + r"EMBEDDINGS\b"),
        re.compile(r"\bDestination" + r"Handler\b"),
        re.compile(r"\bProcessing" + r"Requirement\b"),
    ]

    offenders: list[str] = []
    for path in source_root.rglob("*.py"):
        text = path.read_text()
        for pattern in patterns:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(source_root)}: {pattern.pattern}")

    assert offenders == []
