"""Mention parsing helpers for graph chat schema routing."""

from __future__ import annotations

import re
from typing import Any, List, Optional

CONNECTOR_MENTION_PATTERN = re.compile(r"@([A-Za-z0-9_-]+)", re.IGNORECASE)

QUERY_CONTROL_MENTIONS = {
    "search",
    "graph",
    "temporal",
    "core",
    "cohort",
    "decision",
}


def _first_non_control_mention(message: str) -> Optional[str]:
    for match in CONNECTOR_MENTION_PATTERN.finditer(message):
        mention = match.group(1).strip()
        if mention.lower() in QUERY_CONTROL_MENTIONS:
            continue
        return mention
    return None


def parse_collection_mention_from_message(message: str) -> Optional[str]:
    """Parse first @mention from message and return it as a collection identifier."""
    if not message or not message.strip():
        return None
    return _first_non_control_mention(message)


def parse_connector_filter_from_message(message: str) -> Optional[str]:
    """Parse first @mention from message and return it as a lowercase source type."""
    if not message or not message.strip():
        return None
    mention = _first_non_control_mention(message)
    return mention.lower() if mention else None


def get_source_types_in_collection_from_syncs(
    syncs: List[Any],
) -> List[str]:
    """Extract distinct source_type values from sync source connections."""
    source_types: List[str] = []
    seen: set[str] = set()
    for sync in syncs or []:
        source_connection = getattr(sync, "source_connection", None)
        if not source_connection:
            continue
        source = getattr(source_connection, "source", None)
        if not source:
            continue
        short_name = getattr(source, "short_name", None)
        if short_name and short_name not in seen:
            seen.add(short_name)
            source_types.append(short_name)
    return source_types
