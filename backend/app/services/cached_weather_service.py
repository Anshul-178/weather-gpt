"""Cached weather service.

Adds cache-aside behavior on top of WeatherService (technical.md §7, §21).
Cache failures must never break weather retrieval: on any cache error we
fetch directly from the provider.
"""

import asyncio
import time

from app.config import settings
from app.schemas.weather import (
    CurrentWeatherResponse,
    ForecastResponse,
    GeoLocation,
)
from app.services.cache_service import cache_service
from app.services.weather_service import WeatherProviderError, WeatherRateLimitError
from app.services.weather_service import weather_service
from app.utils.geo import cache_key_current, cache_key_forecast, cache_key_geocode
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Last-good payload store: key -> (expires_at_monotonic, payload).
# Serves stale weather (up to ~1h old) when the live provider is unreachable
# or rate-limited, so the AI chat keeps answering instead of always returning
# the same fallback message.
_LAST_GOOD: dict[str, tuple[float, dict]] = {}
_LAST_GOOD_TTL_SECONDS = 3600

# Upper bound for a provider-requested cooldown so a pathological Retry-After
# header cannot pin weather fetches for hours.
_MAX_COOLDOWN_SECONDS = 300

# Avoid a thundering herd when several clients request the same location after
# its cache entry expires. A provider 429 is then one failed request, not one
# failed request per waiting client.
_IN_FLIGHT_LOCKS: dict[str, asyncio.Lock] = {}

# Do not immediately retry the provider after it has explicitly rate-limited
# us. This is process-local, like the in-memory cache.
_PROVIDER_RATE_LIMITED_UNTIL = 0.0


class CachedWeatherService:
    """Weather retrieval with in-memory caching."""

    async def get_current(
        self, latitude: float, longitude: float, location: GeoLocation | None = None
    ) -> CurrentWeatherResponse:
        """Return current weather, served from cache when fresh."""
        key = cache_key_current(latitude, longitude)
        async with self._lock_for(key):
            cached = await self._get_cached(key)
            if cached is not None:
                return CurrentWeatherResponse.model_validate(cached)

            try:
                self._raise_if_provider_cooldown()
                result = await weather_service.get_current(latitude, longitude, location)
            except WeatherRateLimitError as exc:
                # Only restart the cooldown on a *fresh* upstream 429. Raising
                # from the cooldown itself is a re-check, not new evidence, and
                # must not extend the window (otherwise a steady stream of
                # requests would keep the cooldown alive forever).
                if not exc.from_cooldown:
                    self._start_provider_cooldown(exc.retry_after_seconds)
                stale = self._recall_last_good(key)
                if stale is not None and settings.serve_stale_on_provider_rate_limit:
                    logger.warning("Serving last-good CURRENT weather for %s", key)
                    return CurrentWeatherResponse.model_validate(stale)
                raise
            except WeatherProviderError:
                stale = self._recall_last_good(key)
                if stale is not None:
                    logger.warning("Serving last-good CURRENT weather for %s", key)
                    return CurrentWeatherResponse.model_validate(stale)
                raise
            await self._set_cached(
                key, result, settings_ttl="cache_current_ttl_seconds"
            )
            self._remember_last_good(key, result)
            return result

    async def get_forecast(
        self,
        latitude: float,
        longitude: float,
        days: int = 7,
        location: GeoLocation | None = None,
        model: str | None = None,
    ) -> ForecastResponse:
        """Return forecast, served from cache when fresh."""
        days = max(1, min(days, 16))
        key = cache_key_forecast(latitude, longitude, days, model)
        async with self._lock_for(key):
            cached = await self._get_cached(key)
            if cached is not None:
                return ForecastResponse.model_validate(cached)

            try:
                self._raise_if_provider_cooldown()
                result = await weather_service.get_forecast(
                    latitude, longitude, days, location, model=model
                )
            except WeatherRateLimitError as exc:
                # See get_current: never extend an active cooldown locally.
                if not exc.from_cooldown:
                    self._start_provider_cooldown(exc.retry_after_seconds)
                stale = self._recall_last_good(key)
                if stale is not None and settings.serve_stale_on_provider_rate_limit:
                    logger.warning("Serving last-good FORECAST weather for %s", key)
                    return ForecastResponse.model_validate(stale)
                raise
            except WeatherProviderError:
                stale = self._recall_last_good(key)
                if stale is not None:
                    logger.warning("Serving last-good FORECAST weather for %s", key)
                    return ForecastResponse.model_validate(stale)
                raise
            await self._set_cached(
                key, result, settings_ttl="cache_forecast_ttl_seconds"
            )
            self._remember_last_good(key, result)
            return result

    async def geocode(self, name: str) -> list[GeoLocation]:
        """Geocode a place name with long-TTL caching."""
        key = cache_key_geocode(name)
        cached = await self._get_cached(key)
        if cached is not None:
            return [GeoLocation.model_validate(item) for item in cached]

        results = await weather_service.geocode(name)
        if results:
            await cache_service.set(
                key,
                [item.model_dump(mode="json") for item in results],
                ttl_seconds=_ttl("cache_geocode_ttl_seconds"),
            )
        return results

    async def invalidate(self, latitude: float, longitude: float) -> None:
        """Invalidate cached weather for coordinates (best effort)."""
        await cache_service.delete_pattern(
            f"weather:{_round(latitude)}:{_round(longitude)}"
        )

    # ------------------------------------------------------------------ #

    def _remember_last_good(self, key: str, value) -> None:
        """Store a serializable payload as the last-known-good response."""
        try:
            _LAST_GOOD[key] = (
                time.monotonic() + _LAST_GOOD_TTL_SECONDS,
                value.model_dump(mode="json"),
            )
        except Exception:  # noqa: BLE001 - never fail the happy path
            pass

    def _recall_last_good(self, key: str) -> dict | None:
        """Return the last-known-good payload for a key, if still fresh."""
        entry = _LAST_GOOD.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if expires_at < time.monotonic():
            _LAST_GOOD.pop(key, None)
            return None
        return payload

    async def _get_cached(self, key: str):
        """Fetch a cached payload; treat any cache failure as a miss."""
        try:
            return await cache_service.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache GET failed for %s: %s", key, exc)
            return None

    def _lock_for(self, key: str) -> asyncio.Lock:
        """Return the per-cache-key lock used for request coalescing."""
        return _IN_FLIGHT_LOCKS.setdefault(key, asyncio.Lock())

    def _raise_if_provider_cooldown(self) -> None:
        """Avoid another provider request while a rate-limit cooldown is active."""
        if _PROVIDER_RATE_LIMITED_UNTIL <= time.monotonic():
            return
        raise WeatherRateLimitError(
            "The weather provider is temporarily rate-limited. Please try again shortly.",
            from_cooldown=True,
        )

    def _start_provider_cooldown(self, retry_after_seconds: float | None = None) -> None:
        """Start (or cap) the cooldown after a fresh upstream 429 response.

        Honors the provider's Retry-After when the caller provides it. When a
        cooldown is already running, this never extends it beyond what the
        provider asked for — re-raising during cooldown must not push the
        recovery time further out.
        """
        global _PROVIDER_RATE_LIMITED_UNTIL
        requested = float(retry_after_seconds) if retry_after_seconds else None
        duration = max(1, int(settings.weather_rate_limit_cooldown_seconds))
        if requested is not None:
            duration = max(duration, int(min(requested, _MAX_COOLDOWN_SECONDS)))
        until = time.monotonic() + duration
        # Never lengthen an active cooldown when re-entering from local
        # re-checks; only a fresh upstream 429 reaches here with from_cooldown
        # False, and even then an already-running window stands unless the
        # provider explicitly asks to wait longer.
        if _PROVIDER_RATE_LIMITED_UNTIL > time.monotonic() and requested is None:
            return
        _PROVIDER_RATE_LIMITED_UNTIL = max(
            _PROVIDER_RATE_LIMITED_UNTIL if _PROVIDER_RATE_LIMITED_UNTIL > time.monotonic() else 0.0,
            until,
        )

    async def _set_cached(self, key: str, value, settings_ttl: str) -> None:
        """Store a payload in cache; failures are non-fatal."""
        try:
            await cache_service.set(
                key, value.model_dump(mode="json"), ttl_seconds=_ttl(settings_ttl)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache SET failed for %s: %s", key, exc)


def _ttl(name: str) -> int:
    """Read a TTL setting by attribute name."""
    from app.config import settings as app_settings

    return int(getattr(app_settings, name))


def _round(value: float) -> float:
    """Round coordinate consistent with cache keys."""
    return round(value, 2)


cached_weather_service = CachedWeatherService()
