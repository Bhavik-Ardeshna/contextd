"""Tests for source connection response helpers."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
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

from contextd.core import source_connection_response_helpers  # noqa: E402
from contextd.core.shared_models import SourceConnectionStatus, SyncJobStatus  # noqa: E402
from contextd.core.source_connection_service_helpers import source_connection_helpers  # noqa: E402
from contextd.schemas.source_connection import AuthenticationMethod  # noqa: E402


class LoggerStub:
    def warning(self, *_args, **_kwargs) -> None:
        pass


def _ctx():
    return SimpleNamespace(
        organization=SimpleNamespace(id=uuid4()),
        logger=LoggerStub(),
    )


def test_compute_status_from_data_maps_auth_and_job_state() -> None:
    assert (
        source_connection_helpers.compute_status_from_data(is_authenticated=False)
        == SourceConnectionStatus.PENDING_AUTH
    )
    assert (
        source_connection_helpers.compute_status_from_data(
            is_authenticated=True,
            is_active=False,
        )
        == SourceConnectionStatus.INACTIVE
    )
    assert (
        source_connection_helpers.compute_status_from_data(
            is_authenticated=True,
            last_job_status=SyncJobStatus.RUNNING,
        )
        == SourceConnectionStatus.SYNCING
    )
    assert (
        source_connection_helpers.compute_status_from_data(
            is_authenticated=True,
            last_job_status=SyncJobStatus.FAILED,
        )
        == SourceConnectionStatus.ERROR
    )


def test_sync_job_to_source_connection_job_maps_metrics_and_duration() -> None:
    source_connection_id = uuid4()
    started_at = datetime.now(timezone.utc)
    completed_at = started_at + timedelta(seconds=42)

    job = SimpleNamespace(
        id=uuid4(),
        status=SyncJobStatus.COMPLETED,
        started_at=started_at,
        completed_at=completed_at,
        entities_inserted=3,
        entities_updated=4,
        entities_deleted=5,
        entities_failed=6,
        error=None,
    )

    result = source_connection_helpers.sync_job_to_source_connection_job(job, source_connection_id)

    assert result.source_connection_id == source_connection_id
    assert result.duration_seconds == 42
    assert result.entities_inserted == 3
    assert result.entities_updated == 4
    assert result.entities_deleted == 5
    assert result.entities_failed == 6


@pytest.mark.asyncio
async def test_build_source_connection_response_uses_fallback_auth_and_source_flags(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    source_connection = SimpleNamespace(
        id=uuid4(),
        name="GitHub",
        description=None,
        short_name="github",
        readable_collection_id="engineering",
        status=SourceConnectionStatus.ACTIVE,
        created_at=now,
        modified_at=now,
        is_authenticated=True,
        connection_id=None,
        sync_id=None,
        config_fields={"repository": "contextd"},
    )

    async def fake_get_by_short_name(_db, short_name):
        assert short_name == "github"
        return SimpleNamespace(federated_search=True)

    monkeypatch.setattr(
        source_connection_response_helpers.crud.source,
        "get_by_short_name",
        fake_get_by_short_name,
    )

    result = await source_connection_helpers.build_source_connection_response(
        object(),
        source_connection,
        _ctx(),
    )

    assert result.id == source_connection.id
    assert result.auth.method == AuthenticationMethod.DIRECT
    assert result.auth.authenticated is True
    assert result.auth.authenticated_at == now
    assert result.config == {"repository": "contextd"}
    assert result.federated_search is True
