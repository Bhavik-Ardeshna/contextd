"""Characterization tests for the graph two-phase commit service."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.platform.entities._normalized import NormalizedEntity, PersonRef, PersonRole
from contextd.platform.sync.graph.commit_service import CommitResult, GraphCommitService
from contextd.platform.sync.graph.event_generator import GraphEventGenerator


def _iso_timestamp() -> str:
    return datetime.now(UTC).isoformat()


class _FakeNeo4jTransaction:
    def __init__(self) -> None:
        self.run = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type:
            await self.rollback()
        return False


class _FakeNeo4jSession:
    def __init__(self, tx: _FakeNeo4jTransaction) -> None:
        self.begin_transaction = AsyncMock(return_value=tx)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeNeo4jDriver:
    def __init__(self) -> None:
        self.tx = _FakeNeo4jTransaction()
        self.session_obj = _FakeNeo4jSession(self.tx)
        self.session_databases: list[str | None] = []
        self.ensured_databases: list[tuple[UUID, str | None]] = []

    def session(self, database: str | None = None):
        self.session_databases.append(database)
        return self.session_obj

    async def ensure_context_database(
        self,
        organization_id: UUID,
        readable_collection_id: str | None,
    ) -> str:
        self.ensured_databases.append((organization_id, readable_collection_id))
        return readable_collection_id or "neo4j"


@pytest.fixture
def neo4j_driver() -> _FakeNeo4jDriver:
    """Create a fake Neo4j driver that matches the production async context API."""
    return _FakeNeo4jDriver()


@pytest.fixture
def commit_service(neo4j_driver: _FakeNeo4jDriver) -> GraphCommitService:
    """Create a graph commit service with the fake Neo4j driver."""
    return GraphCommitService(neo4j_driver=neo4j_driver)


@pytest.fixture
def sample_sync_id() -> UUID:
    """Generate a sample sync ID."""
    return uuid4()


@pytest.fixture
def sample_organization_id() -> UUID:
    """Generate a sample organization ID."""
    return uuid4()


@pytest.fixture
def sample_node_events() -> list[dict]:
    """Create sample deduplicated node event rows."""
    return [
        {
            "id": uuid4(),
            "node_id": "person_john_doe",
            "entity_id": "entity_001",
            "entity_type": "GmailMessage",
            "event_type": "NODE_CREATE",
            "event_data": {
                "event_type": "NODE_CREATE",
                "timestamp": _iso_timestamp(),
                "payload": {
                    "node_id": "person_john_doe",
                    "node_type": "PersonNode",
                    "node_properties": {"name": "John Doe"},
                    "operation": "CREATE",
                },
            },
            "organization_id": uuid4(),
        },
        {
            "id": uuid4(),
            "node_id": "task_123",
            "entity_id": "entity_002",
            "entity_type": "AsanaTask",
            "event_type": "NODE_CREATE",
            "event_data": {
                "event_type": "NODE_CREATE",
                "timestamp": _iso_timestamp(),
                "payload": {
                    "node_id": "task_123",
                    "node_type": "TaskNode",
                    "node_properties": {"name": "Complete project"},
                    "operation": "CREATE",
                },
            },
            "organization_id": uuid4(),
        },
    ]


@pytest.fixture
def sample_edge_events() -> list[dict]:
    """Create sample deduplicated edge event rows."""
    return [
        {
            "id": uuid4(),
            "entity_id": "entity_002",
            "entity_type": "AsanaTask",
            "event_type": "EDGE_CREATE",
            "event_data": {
                "event_type": "EDGE_CREATE",
                "timestamp": _iso_timestamp(),
                "payload": {
                    "from_node": {"node_id": "task_123", "node_type": "TaskNode"},
                    "to_node": {"node_id": "person_john_doe", "node_type": "PersonNode"},
                    "edge_type": "ASSIGNED_TO",
                    "edge_properties": {},
                    "operation": "CREATE",
                },
            },
            "organization_id": uuid4(),
        },
    ]


def _mock_db_context(mock_db: AsyncMock):
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=mock_db)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def test_commit_result_success_and_failure_defaults(sample_sync_id: UUID) -> None:
    """Commit results expose counts and errors without requiring DB state."""
    success = CommitResult(success=True, nodes_committed=10, edges_committed=5)
    failure = CommitResult(success=False, error="Neo4j connection failed")

    assert success.success is True
    assert success.nodes_committed == 10
    assert success.edges_committed == 5
    assert success.error is None
    assert failure.success is False
    assert failure.error == "Neo4j connection failed"
    assert failure.nodes_committed == 0
    assert str(sample_sync_id)


def test_service_initialization_and_edge_ids(commit_service: GraphCommitService) -> None:
    """The service keeps the driver and generates deterministic edge IDs."""
    edge_id_1 = commit_service._generate_edge_id("node_a", "node_b", "RELATES_TO")
    edge_id_2 = commit_service._generate_edge_id("node_a", "node_b", "RELATES_TO")
    edge_id_3 = commit_service._generate_edge_id("node_a", "node_c", "RELATES_TO")

    assert commit_service.driver is not None
    assert edge_id_1 == edge_id_2
    assert edge_id_1 != edge_id_3
    assert edge_id_1.startswith("edge_")


@pytest.mark.asyncio
async def test_graph_event_generator_emits_people_from_normalized_entity() -> None:
    """Normalized people must become PersonNode graph events and traversal edges."""
    normalized = NormalizedEntity(
        entity_id="msg_123",
        entity_type="GmailMessageEntity",
        source_type="gmail",
        name="Roadmap update",
        people=[
            PersonRef(
                id="gmail-alice",
                name="Alice Example",
                email="Alice@Example.com",
                role=PersonRole.AUTHOR,
            )
        ],
        properties={"semantic_canonical_node_id": "canonical_msg_123"},
    )

    events = await GraphEventGenerator().generate_events_from_normalized(
        normalized=normalized,
        entity_definition_id=uuid4(),
        sync_context=SimpleNamespace(),
    )

    person_nodes = [
        event
        for event in events
        if event.event_type == "NODE_CREATE" and event.entity_type == "PersonNode"
    ]
    people_edges = [event for event in events if event.field_name == "people"]

    assert len(person_nodes) == 1
    assert person_nodes[0].payload.node_id == "person_alice@example.com"

    assert len(people_edges) == 3
    forward_edge = next(event for event in people_edges if event.event_type == "EDGE_CREATE")
    assert forward_edge.payload.from_node.node_id == "canonical_msg_123"
    assert forward_edge.payload.to_node.node_id == "person_alice@example.com"
    assert forward_edge.payload.edge_type == "AUTHORED_BY"


@pytest.mark.asyncio
async def test_get_deduplicated_nodes(
    commit_service: GraphCommitService,
    sample_sync_id: UUID,
    sample_node_events: list[dict],
) -> None:
    """Deduplicated node query returns only pending node rows selected by SQL."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [SimpleNamespace(**event) for event in sample_node_events]
    mock_db.execute.return_value = mock_result

    with patch(
        "contextd.platform.sync.graph.commit_service.get_db_context",
        return_value=_mock_db_context(mock_db),
    ):
        nodes = await commit_service._get_deduplicated_nodes(sample_sync_id)

    assert [node["node_id"] for node in nodes] == ["person_john_doe", "task_123"]
    query = str(mock_db.execute.await_args.args[0])
    assert "commit_status = 'pending'" in query
    assert "DISTINCT ON (node_id)" in query


@pytest.mark.asyncio
async def test_get_deduplicated_edges(
    commit_service: GraphCommitService,
    sample_sync_id: UUID,
    sample_edge_events: list[dict],
) -> None:
    """Deduplicated edge query keys by source, target, and edge type."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [SimpleNamespace(**event) for event in sample_edge_events]
    mock_db.execute.return_value = mock_result

    with patch(
        "contextd.platform.sync.graph.commit_service.get_db_context",
        return_value=_mock_db_context(mock_db),
    ):
        edges = await commit_service._get_deduplicated_edges(sample_sync_id)

    assert len(edges) == 1
    assert edges[0]["event_type"] == "EDGE_CREATE"
    query = str(mock_db.execute.await_args.args[0])
    assert "event_data->'payload'->'from_node'->>'node_id'" in query
    assert "commit_status = 'pending'" in query


@pytest.mark.asyncio
async def test_execute_neo4j_transaction_success(
    commit_service: GraphCommitService,
    neo4j_driver: _FakeNeo4jDriver,
    sample_node_events: list[dict],
    sample_edge_events: list[dict],
    sample_organization_id: UUID,
) -> None:
    """Neo4j transaction writes nodes before edges and commits once."""
    nodes_created, edges_created = await commit_service._execute_neo4j_transaction(
        nodes=sample_node_events,
        edges=sample_edge_events,
        organization_id=sample_organization_id,
    )

    assert nodes_created == 2
    assert edges_created == 1
    assert neo4j_driver.tx.run.await_count == 3
    first_node_params = neo4j_driver.tx.run.await_args_list[0].args[1]
    assert first_node_params["fulltext_properties"] == {"ft_name": "John Doe"}
    neo4j_driver.tx.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_neo4j_transaction_rolls_back_on_error(
    commit_service: GraphCommitService,
    neo4j_driver: _FakeNeo4jDriver,
    sample_node_events: list[dict],
    sample_organization_id: UUID,
) -> None:
    """A failed Neo4j write exits the transaction with rollback semantics."""
    neo4j_driver.tx.run.side_effect = RuntimeError("Neo4j error")

    with pytest.raises(RuntimeError, match="Neo4j error"):
        await commit_service._execute_neo4j_transaction(
            nodes=sample_node_events,
            edges=[],
            organization_id=sample_organization_id,
        )

    neo4j_driver.tx.rollback.assert_awaited_once()
    neo4j_driver.tx.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_commit_sync_events_marks_committed_and_skipped_statuses(
    commit_service: GraphCommitService,
    sample_sync_id: UUID,
    sample_organization_id: UUID,
    sample_node_events: list[dict],
    sample_edge_events: list[dict],
) -> None:
    """Commit success records written events as committed and deduped events as skipped."""
    with (
        patch.object(
            commit_service, "_get_deduplicated_nodes", AsyncMock(return_value=sample_node_events)
        ),
        patch.object(
            commit_service, "_get_deduplicated_edges", AsyncMock(return_value=sample_edge_events)
        ),
        patch.object(
            commit_service, "_execute_neo4j_transaction", AsyncMock(side_effect=[(2, 0), (0, 1)])
        ),
        patch.object(
            commit_service, "_mark_committed", AsyncMock(return_value=3)
        ) as mark_committed,
        patch.object(
            commit_service, "_mark_skipped", AsyncMock(return_value=(1, 2))
        ) as mark_skipped,
        patch.object(
            commit_service, "_mark_metadata_skipped", AsyncMock(return_value=4)
        ) as mark_metadata_skipped,
    ):
        result = await commit_service.commit_sync_events(
            sync_id=sample_sync_id,
            organization_id=sample_organization_id,
        )

    committed_ids = sample_node_events[0:2] + sample_edge_events
    expected_ids = [event["id"] for event in committed_ids]
    mark_committed.assert_awaited_once_with(sample_sync_id, expected_ids)
    mark_skipped.assert_awaited_once_with(sample_sync_id, expected_ids)
    mark_metadata_skipped.assert_awaited_once_with(sample_sync_id)
    assert result.success is True
    assert result.nodes_committed == 2
    assert result.edges_committed == 1
    assert result.nodes_skipped == 1
    assert result.edges_skipped == 2
    assert result.metadata_skipped == 4


@pytest.mark.asyncio
async def test_commit_sync_events_metadata_only_is_successful(
    commit_service: GraphCommitService,
    sample_sync_id: UUID,
    sample_organization_id: UUID,
) -> None:
    """Metadata-only graph events are skipped because they have no Neo4j mutation."""
    with (
        patch.object(commit_service, "_get_deduplicated_nodes", AsyncMock(return_value=[])),
        patch.object(commit_service, "_get_deduplicated_edges", AsyncMock(return_value=[])),
        patch.object(commit_service, "_mark_committed", AsyncMock()) as mark_committed,
        patch.object(
            commit_service, "_mark_metadata_skipped", AsyncMock(return_value=2)
        ) as mark_metadata_skipped,
    ):
        result = await commit_service.commit_sync_events(sample_sync_id, sample_organization_id)

    assert result.success is True
    assert result.nodes_committed == 0
    assert result.edges_committed == 0
    assert result.metadata_skipped == 2
    mark_committed.assert_not_awaited()
    mark_metadata_skipped.assert_awaited_once_with(sample_sync_id)


@pytest.mark.asyncio
async def test_commit_sync_events_failure_marks_pending_failed(
    commit_service: GraphCommitService,
    sample_sync_id: UUID,
    sample_organization_id: UUID,
    sample_node_events: list[dict],
) -> None:
    """Neo4j failures leave the sync retryable by marking pending events failed."""
    with (
        patch.object(
            commit_service, "_get_deduplicated_nodes", AsyncMock(return_value=sample_node_events)
        ),
        patch.object(commit_service, "_get_deduplicated_edges", AsyncMock(return_value=[])),
        patch.object(
            commit_service,
            "_execute_neo4j_transaction",
            AsyncMock(side_effect=RuntimeError("Neo4j connection failed")),
        ),
        patch.object(commit_service, "_mark_failed", AsyncMock(return_value=2)) as mark_failed,
    ):
        result = await commit_service.commit_sync_events(sample_sync_id, sample_organization_id)

    assert result.success is False
    assert "Neo4j connection failed" in result.error
    mark_failed.assert_awaited_once_with(sample_sync_id, "Neo4j connection failed")


@pytest.mark.asyncio
async def test_mark_committed_targets_selected_event_ids(
    commit_service: GraphCommitService,
    sample_sync_id: UUID,
) -> None:
    """Only events selected by deduplication should be marked committed."""
    event_id = uuid4()
    mock_db = AsyncMock()
    mock_db.execute.return_value = SimpleNamespace(rowcount=1)

    with patch(
        "contextd.platform.sync.graph.commit_service.get_db_context",
        return_value=_mock_db_context(mock_db),
    ):
        count = await commit_service._mark_committed(sample_sync_id, [event_id])

    assert count == 1
    query = str(mock_db.execute.await_args.args[0])
    params = mock_db.execute.await_args.args[1]
    assert "commit_status = 'committed'" in query
    assert "id IN" in query
    assert params["event_ids"] == (event_id,)
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_skipped_targets_remaining_pending_node_and_edge_events(
    commit_service: GraphCommitService,
    sample_sync_id: UUID,
) -> None:
    """Superseded pending events are marked skipped after a successful commit."""
    event_id = uuid4()
    mock_db = AsyncMock()
    mock_db.execute.side_effect = [SimpleNamespace(rowcount=1), SimpleNamespace(rowcount=2)]

    with patch(
        "contextd.platform.sync.graph.commit_service.get_db_context",
        return_value=_mock_db_context(mock_db),
    ):
        nodes_skipped, edges_skipped = await commit_service._mark_skipped(
            sample_sync_id,
            [event_id],
        )

    assert (nodes_skipped, edges_skipped) == (1, 2)
    assert mock_db.execute.await_count == 2
    assert mock_db.execute.await_args_list[0].args[1]["event_type"] == "NODE%"
    assert mock_db.execute.await_args_list[1].args[1]["event_type"] == "EDGE%"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_metadata_skipped_targets_pending_metadata_events(
    commit_service: GraphCommitService,
    sample_sync_id: UUID,
) -> None:
    """Metadata graph events are recorded in Postgres but skipped for Neo4j writes."""
    mock_db = AsyncMock()
    mock_db.execute.return_value = SimpleNamespace(rowcount=3)

    with patch(
        "contextd.platform.sync.graph.commit_service.get_db_context",
        return_value=_mock_db_context(mock_db),
    ):
        count = await commit_service._mark_metadata_skipped(sample_sync_id)

    assert count == 3
    query = str(mock_db.execute.await_args.args[0])
    assert "event_type = 'METADATA_UPDATE'" in query
    assert "commit_status = 'skipped'" in query
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_failed_and_retry_failed_sync(
    commit_service: GraphCommitService,
    sample_sync_id: UUID,
    sample_organization_id: UUID,
) -> None:
    """Failed events can be reset to pending and retried through the normal commit path."""
    mock_db = AsyncMock()
    mock_db.execute.return_value = SimpleNamespace(rowcount=3)

    with patch(
        "contextd.platform.sync.graph.commit_service.get_db_context",
        return_value=_mock_db_context(mock_db),
    ):
        failed_count = await commit_service._mark_failed(sample_sync_id, "Test error")

    assert failed_count == 3
    mock_db.commit.assert_awaited_once()

    retry_db = AsyncMock()
    retry_db.execute.return_value = SimpleNamespace(rowcount=2)
    expected = CommitResult(success=True, nodes_committed=1)

    with (
        patch(
            "contextd.platform.sync.graph.commit_service.get_db_context",
            return_value=_mock_db_context(retry_db),
        ),
        patch.object(
            commit_service, "commit_sync_events", AsyncMock(return_value=expected)
        ) as commit_sync_events,
    ):
        result = await commit_service.retry_failed_sync(sample_sync_id, sample_organization_id)

    assert result == expected
    commit_sync_events.assert_awaited_once_with(sample_sync_id, sample_organization_id)
    retry_db.commit.assert_awaited_once()
