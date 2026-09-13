"""Air Quality Index (AQI) service.

Fetches and normalizes air quality data from Open-Meteo's Air Pollution API.
Cached to avoid repeated provider calls for the same coordinates (free-tier
rate-limit mitigation).
"""

import asyncio
import time
from datetime import datetime
from typing import Optional

import httpx

from app.config import settings
from app.schemas.aqi import AQICurrent, AQIResponse, get_aqi_category
from app.services.cache_service import cache_service
from app.utils.geo import cache_key_aqi
from app.utils.logging import get_logger

logger = get_logger(__name__)

_AQI_LAST_GOOD: dict[str, tuple[float, dict]] = {}
_AQI_LAST_GOOD_TTL_SECONDS = 3600


class AQIServiceError(Exception):
    """AQI service failed."""


class AQIService:
    """Fetches air quality data from Open-Meteo Air Pollution API."""

    async def get_current_aqi(
        self, latitude: float, longitude: float, location_name: str = "Unknown"
    ) -> AQIResponse:
        """Return normalized current AQI for coordinates."""
        key = cache_key_aqi(latitude, longitude)
        cached = await self._get_cached(key)
        if cached is not None:
            return AQIResponse.model_validate(cached)

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "european_aqi,pm2_5,pm10,o3,no2,so2,co",
        }
        try:
            payload = await self._request(
                f"{settings.air_quality_api_base_url}/air-quality", params
            )
        except AQIServiceError:
            stale = self._recall_last_good(key)
            if stale is not None:
                logger.warning("Serving last-good AQI for %s", key)
                return AQIResponse.model_validate(stale)
            raise

        current = payload.get("current") or {}

        aqi_value = current.get("european_aqi")
        normalized = AQICurrent(
            aqi=aqi_value,
            pm2_5=current.get("pm2_5"),
            pm10=current.get("pm10"),
            o3=current.get("o3"),
            no2=current.get("no2"),
            so2=current.get("so2"),
            co=current.get("co"),
            epa_aqi=get_aqi_category(aqi_value),
        )

        observed_at = datetime.now()
        if current.get("time"):
            try:
                observed_at = datetime.fromisoformat(current["time"].replace("Z", "+00:00"))
            except ValueError:
                pass

        response = AQIResponse(
            location_name=location_name,
            latitude=latitude,
            longitude=longitude,
            current=normalized,
            timestamp=observed_at,
        )
        await self._set_cached(key, response)
        self._remember_last_good(key, response)
        return response

    # ------------------------------------------------------------------ #
    # cache helpers
    # ------------------------------------------------------------------ #

    async def _get_cached(self, key: str) -> Optional[dict]:
        """Fetch a cached AQI payload; treat any cache failure as a miss."""
        try:
            return await cache_service.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AQI cache GET failed for %s: %s", key, exc)
            return None

    async def _set_cached(self, key: str, response: AQIResponse) -> None:
        """Store a payload in cache; failures are non-fatal."""
        try:
            await cache_service.set(
                key,
                response.model_dump(mode="json"),
                ttl_seconds=settings.cache_aqi_ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("AQI cache SET failed for %s: %s", key, exc)

    def _remember_last_good(self, key: str, value) -> None:
        """Store a serializable payload as the last-known-good response."""
        try:
            _AQI_LAST_GOOD[key] = (
                time.monotonic() + _AQI_LAST_GOOD_TTL_SECONDS,
                value.model_dump(mode="json"),
            )
        except Exception:  # noqa: BLE001 - never fail the happy path
            pass

    def _recall_last_good(self, key: str) -> dict | None:
        """Return the last-known-good payload for a key, if still fresh."""
        entry = _AQI_LAST_GOOD.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if expires_at < time.monotonic():
            _AQI_LAST_GOOD.pop(key, None)
            return None
        return payload

    # ------------------------------------------------------------------ ## provider request
# ------------------------------------------------------------------ #

    async def _request(self, url: str, params: dict) -> dict:
        """Perform a GET request with timeout and error mapping.

        HTTP 429 is retried once with backoff. On persistent provider errors
        the caller (get_current_aqi) falls back to cache / last-good payload.
        """
        # Provider API key (moves quota from the shared deployment IP to the account).
        if (
            settings.weather_api_key
            and "open-meteo.com" in url
            and "api.open-meteo.com" in settings.weather_api_base_url
        ):
            params = {**params, "apikey": settings.weather_api_key}
        max_attempts = 2
        async with httpx.AsyncClient(timeout=settings.weather_timeout_seconds) as client:
            for attempt in range(max_attempts):
                try:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    return response.json()
                except httpx.TimeoutException as exc:
                    logger.warning("AQI provider timeout: %s", exc)
                    raise AQIServiceError("The air quality service timed out.") from exc
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    if status_code == 429 and attempt < max_attempts - 1:
                        logger.warning(
                            "AQI provider HTTP %s (attempt %d/%d) — retrying",
                            status_code,
                            attempt + 1,
                            max_attempts,
                        )
                        await asyncio.sleep(0.75 * (attempt + 1))
                        continue
                    logger.warning("AQI provider HTTP %s", status_code)
                    raise AQIServiceError(
                        f"The air quality service returned an error (HTTP {status_code})."
                    ) from exc
                except httpx.HTTPError as exc:
                    logger.warning("AQI provider network error: %s", exc)
                    raise AQIServiceError("Could not reach the air quality service.") from exc
                except ValueError as exc:
                    logger.warning("AQI provider returned invalid JSON: %s", exc)
                    raise AQIServiceError("The air quality service returned invalid data.") from exc
        raise AQIServiceError("The air quality service returned an error.")  # pragma: no cover

aqi_service = AQIService()
