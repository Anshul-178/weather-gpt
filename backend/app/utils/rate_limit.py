"""Simple in-memory rate limiting (technical.md §34).

Per-process sliding window limiter. Adequate for a single instance; use a
Redis-based limiter for multi-instance deployments.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

_HITS: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    """Best-effort client IP (behind a proxy, set X-Forwarded-For at Nginx)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


async def enforce_rate_limit(request: Request, *, chat: bool = False) -> None:
    """Enforce per-IP sliding window limits; raise 429 when exceeded."""
    identity = _client_ip(request)
    if chat:
        max_requests = settings.chat_rate_limit_requests
        window = settings.chat_rate_limit_window_seconds
        bucket = f"chat:{identity}"
    else:
        max_requests = settings.rate_limit_requests
        window = settings.rate_limit_window_seconds
        bucket = f"api:{identity}"

    now = time.monotonic()
    hits = _HITS[bucket]
    while hits and hits[0] <= now - window:
        hits.popleft()
    if len(hits) >= max_requests:
        logger.warning("Rate limit exceeded for %s", identity)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
        )
    hits.append(now)
