"""Vector similarity helpers (import-safe: no app settings)."""

from __future__ import annotations


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [0, 1]-ish range (1 = same direction, 0 = orthogonal or empty)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
