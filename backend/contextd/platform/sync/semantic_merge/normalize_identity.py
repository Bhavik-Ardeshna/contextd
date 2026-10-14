"""Lightweight name/email normalization for alias keys (no graph or settings imports)."""

from __future__ import annotations

import re


def normalize_name(name: str | None) -> str:
    """Normalize a name for comparison (lowercase, titles/suffixes, whitespace)."""
    if not name:
        return ""

    normalized = name.lower().strip()
    titles = r"^(mr\.?|mrs\.?|ms\.?|miss\.?|dr\.?|prof\.?|professor\.?)\s+"
    normalized = re.sub(titles, "", normalized, flags=re.IGNORECASE)
    suffixes = r"\s+(jr\.?|sr\.?|ii|iii|iv|phd|md|esq\.?)$"
    normalized = re.sub(suffixes, "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def normalize_email(email: str | None) -> str:
    """Normalize email for comparison (lowercase, stripped)."""
    if not email:
        return ""
    return email.lower().strip()
