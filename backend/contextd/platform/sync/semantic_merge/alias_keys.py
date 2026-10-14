"""Normalize alias keys for lookup (email, name, composite)."""

from __future__ import annotations

import re

from .normalize_identity import normalize_email, normalize_name


def email_alias_key(email: str | None) -> str | None:
    """Return stable alias key for email or None."""
    if not email:
        return None
    n = normalize_email(email)
    return f"email:{n}" if n else None


def name_alias_key(name: str | None) -> str | None:
    """Return stable alias key for display name or None."""
    if not name:
        return None
    n = normalize_name(name)
    return f"name:{n}" if n else None


def extraction_text_for_embedding(
    *,
    name: str,
    description: str | None = None,
    entity_type: str | None = None,
    extra: str | None = None,
) -> str:
    """Single string used for embedding and similarity."""
    parts = [name or ""]
    if entity_type:
        parts.append(entity_type)
    if description:
        parts.append(description)
    if extra:
        parts.append(extra)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()
