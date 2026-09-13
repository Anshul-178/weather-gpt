"""Cached weather service.

Adds cache-aside behavior on top of WeatherService (technical.md §7, §21).
Cache failures must never break weather retrieval: on any cache error we
fetch directly from the provider.
"""

import time

from app.schemas.weather import (
    CurrentWeatherResponse,
    ForecastResponse,
    GeoLocation,
)
from app.services.cache_service import cache_service
from app.services.weather_service import WeatherProviderError
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


class CachedWeatherService:
    """Weather retrieval with Redis/in-memory caching."""

    async def get_current(
        self, latitude: float, longitude: float, location: GeoLocation | None = None
    ) -> CurrentWeatherResponse:
        """Return current weather, served from cache when fresh."""
        key = cache_key_current(latitude, longitude)
        cached = await self._get_cached(key)
        if cached is not None:
            return CurrentWeatherResponse.model_validate(cached)

        try:
            result = await weather_service.get_current(latitude, longitude, location)
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
        cached = await self._get_cached(key)
        if cached is not None:
            return ForecastResponse.model_validate(cached)

        try:
            result = await weather_service.get_forecast(
                latitude, longitude, days, location, model=model
            )
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
