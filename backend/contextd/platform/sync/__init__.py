"""Sync module for ContextD.

Import from submodules (e.g. ``contextd.platform.sync.arf``) so lightweight
packages like ``semantic_merge`` do not pull ARF/storage at import time.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ArfService",
    "arf_service",
    "SyncManifest",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from contextd.platform.sync import arf

        return getattr(arf, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
