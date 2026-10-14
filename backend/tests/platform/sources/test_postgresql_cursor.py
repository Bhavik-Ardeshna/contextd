"""PostgreSQL source cursor handling."""

from __future__ import annotations

import os
from datetime import datetime

import pytest

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")

from contextd.platform.sources.postgresql import PostgreSQLSource  # noqa: E402


class _Conn:
    async def fetchrow(self, *_args):
        return {"data_type": "timestamp with time zone", "udt_name": "timestamptz"}


@pytest.mark.asyncio
async def test_iso_cursor_value_is_deserialized_for_asyncpg() -> None:
    source = PostgreSQLSource()
    source.conn = _Conn()

    value = await source._deserialize_cursor_value(
        "public",
        "members",
        "updated_at",
        "2026-03-24T20:33:14.909534+00:00",
    )

    assert isinstance(value, datetime)
    assert value.isoformat() == "2026-03-24T20:33:14.909534+00:00"
