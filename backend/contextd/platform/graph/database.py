"""Neo4j database naming helpers for ContextD graph isolation."""

from __future__ import annotations

import hashlib
import re
from typing import Optional
from uuid import UUID

from contextd.platform.graph.config import get_graph_config


_DB_SAFE_CHARS = re.compile(r"[^a-z0-9-]+")
_DB_DASHES = re.compile(r"-+")
_MAX_NEO4J_DATABASE_NAME = 63


def neo4j_collection_database_name(
    organization_id: UUID | str | None,
    readable_collection_id: Optional[str],
) -> str:
    """Return the deterministic Neo4j database name for a ContextD collection.

    Neo4j database names must begin with an ASCII letter and are safest when
    limited to lowercase alphanumerics plus dashes. We keep the readable slug
    visible for operators, then add a hash so renamed-looking collisions cannot
    cross tenant or collection boundaries.
    """
    if not organization_id or not readable_collection_id:
        return get_graph_config().neo4j_database

    org = str(organization_id).replace("-", "").lower()
    org_part = org[:8] or "tenant"
    raw_slug = readable_collection_id.strip().lower()
    slug = _DB_SAFE_CHARS.sub("-", raw_slug)
    slug = _DB_DASHES.sub("-", slug).strip("-") or "collection"
    digest = hashlib.sha1(f"{organization_id}:{readable_collection_id}".encode()).hexdigest()[:10]

    suffix = f"-{digest}"
    prefix = f"ctxd-{org_part}-"
    available_slug = _MAX_NEO4J_DATABASE_NAME - len(prefix) - len(suffix)
    if available_slug < 8:
        available_slug = 8
    slug = slug[:available_slug].strip("-") or "collection"
    return f"{prefix}{slug}{suffix}"[:_MAX_NEO4J_DATABASE_NAME].strip("-")


def quote_neo4j_identifier(identifier: str) -> str:
    """Safely quote a Neo4j identifier such as a database or index name."""
    return f"`{identifier.replace('`', '``')}`"
