"""Cache service (in-memory).

Process-local TTL cache. Values are stored as JSON with a monotonic-clock
expiry so the cache works identically in tests and production. There is no
external cache dependency; caching lives only here, never inside route handlers.
"""

import json
import time
from typing import Any, Optional

from app.utils.logging import get_logger

logger = get_logger(__name__)

_MEMORY_CACHE: dict[str, tuple[float, str]] = {}


class CacheService:
    """TTL cache backed by in-memory storage."""

    async def get(self, key: str) -> Optional[Any]:
        """Get a cached JSON value or None on miss/expiry."""
        entry = _MEMORY_CACHE.get(key)
        if entry is None:
            return None
        expires_at, raw = entry
        if expires_at < time.monotonic():
            _MEMORY_CACHE.pop(key, None)
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Set a cached JSON value with TTL (stored in-process)."""
        payload = json.dumps(value, default=str)
        _MEMORY_CACHE[key] = (time.monotonic() + ttl_seconds, payload)

    async def delete_pattern(self, pattern: str) -> None:
        """Best-effort invalidation by prefix pattern."""
        for key in [k for k in list(_MEMORY_CACHE) if k.startswith(pattern)]:
            _MEMORY_CACHE.pop(key, None)

    async def clear_memory(self) -> None:
        """Clear the in-memory cache (used by tests)."""
        _MEMORY_CACHE.clear()


cache_service = CacheService()
