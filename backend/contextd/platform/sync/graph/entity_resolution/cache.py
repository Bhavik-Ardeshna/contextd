"""Resolution cache for sync duration.

Provides in-memory caching of entity resolution results
to avoid repeated graph queries during a sync.

NOTE: This cache is for caching Neo4j query results during entity resolution.
It prevents repeated graph lookups for the same person/entity within a single sync.
This is a performance optimization, NOT a deduplication mechanism.

Deduplication is handled at the database level by GraphCommitService using
SQL DISTINCT ON queries in the Two-Phase Commit architecture.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional

from .types import ResolutionResult


@dataclass
class ResolutionCache:
    """In-memory cache for entity resolution query results.

    Lives for the duration of a single sync to avoid:
    1. Repeated Neo4j queries for same entity
    2. Generating different IDs for same entity within sync

    Thread-safe for async operations (uses dict which is thread-safe for basic ops).

    NOTE: This cache is for query result caching, not deduplication.
    Graph deduplication is handled by GraphCommitService using PostgreSQL
    DISTINCT ON queries at commit time.

    Usage:
        cache = ResolutionCache()

        # Check cache
        result = cache.get("person:email:john@example.com")

        # Store result
        cache.set("person:email:john@example.com", result)

        # Get stats
        print(cache.stats)
    """

    _cache: Dict[str, ResolutionResult] = field(default_factory=dict)
    _stats: Dict[str, int] = field(default_factory=lambda: {
        "hits": 0,
        "misses": 0,
        "stores": 0,
    })
    created_at: datetime = field(default_factory=datetime.utcnow)

    def get(self, key: str) -> Optional[ResolutionResult]:
        """Get cached resolution result.

        Args:
            key: Cache key (e.g., "person:email:john@example.com")

        Returns:
            Cached ResolutionResult or None if not found
        """
        result = self._cache.get(key)
        if result is not None:
            self._stats["hits"] += 1
        else:
            self._stats["misses"] += 1
        return result

    def set(self, key: str, result: ResolutionResult) -> None:
        """Cache a resolution result.

        Args:
            key: Cache key
            result: Resolution result to cache
        """
        self._cache[key] = result
        self._stats["stores"] += 1

    def get_or_compute(
        self,
        key: str,
        factory: Callable[[], ResolutionResult],
    ) -> ResolutionResult:
        """Get from cache or compute and store.

        Synchronous version for simple factories.

        Args:
            key: Cache key
            factory: Callable that returns ResolutionResult if not cached

        Returns:
            Cached or newly computed ResolutionResult
        """
        result = self.get(key)
        if result is None:
            result = factory()
            self.set(key, result)
        return result

    def contains(self, key: str) -> bool:
        """Check if key exists in cache without affecting stats.

        Args:
            key: Cache key

        Returns:
            True if key exists
        """
        return key in self._cache

    def clear(self) -> None:
        """Clear the cache and reset stats."""
        self._cache.clear()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "stores": 0,
        }
        self.created_at = datetime.utcnow()

    def remove(self, key: str) -> bool:
        """Remove a specific key from cache.

        Args:
            key: Cache key to remove

        Returns:
            True if key was removed, False if not found
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    @property
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)

    @property
    def stats(self) -> Dict[str, float]:
        """Get cache statistics.

        Returns:
            Dict with hits, misses, stores, size, and hit_rate
        """
        total_lookups = self._stats["hits"] + self._stats["misses"]
        hit_rate = (
            self._stats["hits"] / total_lookups
            if total_lookups > 0
            else 0.0
        )

        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "stores": self._stats["stores"],
            "size": len(self._cache),
            "hit_rate": hit_rate,
            "age_seconds": (datetime.utcnow() - self.created_at).total_seconds(),
        }

    def get_all_keys(self) -> list[str]:
        """Get all cache keys.

        Returns:
            List of all cached keys
        """
        return list(self._cache.keys())

    def get_keys_by_prefix(self, prefix: str) -> list[str]:
        """Get all keys matching a prefix.

        Args:
            prefix: Key prefix to match (e.g., "person:")

        Returns:
            List of matching keys
        """
        return [k for k in self._cache.keys() if k.startswith(prefix)]
