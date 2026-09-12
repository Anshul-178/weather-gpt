"""Cache service.

Uses Redis when available; falls back to a process-local in-memory cache when
Redis is unreachable so the application keeps working (prompt §10). Redis code
lives only here, never inside route handlers.
"""

import json
import time
from typing import Any, Optional

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - import guard
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover
    aioredis = None

_MEMORY_CACHE: dict[str, tuple[float, str]] = {}


class CacheService:
    """TTL cache abstraction backed by Redis or in-memory storage."""

    def __init__(self) -> None:
        self._redis = None
        self._redis_failed_at: float = 0.0
        self._retry_interval = 30.0  # seconds between Redis reconnect attempts

    async def _get_redis(self):
        """Return a Redis client, attempting reconnection periodically."""
        if aioredis is None:
            return None
        if self._redis is not None:
            return self._redis
        now = time.monotonic()
        if now - self._redis_failed_at < self._retry_interval:
            return None
        try:
            self._redis = aioredis.from_url(
                settings.redis_url,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info("Redis cache connected")
        except Exception as exc:  # noqa: BLE001 - any failure disables Redis
            logger.warning("Redis unavailable, using in-memory cache: %s", exc)
            self._redis = None
            self._redis_failed_at = now
        return self._redis

    async def get(self, key: str) -> Optional[Any]:
        """Get a cached JSON value or None on miss/failure."""
        client = await self._get_redis()
        if client is not None:
            try:
                raw = await client.get(key)
                return json.loads(raw) if raw is not None else None
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis GET failed: %s", exc)
                self._redis = None
                self._redis_failed_at = time.monotonic()
        # in-memory fallback
        entry = _MEMORY_CACHE.get(key)
        if entry is None:
            return None
        expires_at, raw = entry
        if expires_at < time.monotonic():
            _MEMORY_CACHE.pop(key, None)
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Set a cached JSON value with TTL; failures are non-fatal."""
        payload = json.dumps(value, default=str)
        client = await self._get_redis()
        if client is not None:
            try:
                await client.set(key, payload, ex=ttl_seconds)
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis SET failed: %s", exc)
                self._redis = None
                self._redis_failed_at = time.monotonic()
        _MEMORY_CACHE[key] = (time.monotonic() + ttl_seconds, payload)

    async def delete_pattern(self, pattern: str) -> None:
        """Best-effort invalidation by prefix pattern."""
        client = await self._get_redis()
        if client is not None:
            try:
                keys = await client.keys(f"{pattern}*")
                if keys:
                    await client.delete(*keys)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis DELETE failed: %s", exc)
        prefix = pattern
        for key in [k for k in list(_MEMORY_CACHE) if k.startswith(prefix)]:
            _MEMORY_CACHE.pop(key, None)

    async def clear_memory(self) -> None:
        """Clear the in-memory cache (used by tests)."""
        _MEMORY_CACHE.clear()


cache_service = CacheService()
