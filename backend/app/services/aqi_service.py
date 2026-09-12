"""Air Quality Index (AQI) service.

Fetches and normalizes air quality data from Open-Meteo's Air Pollution API.
"""

from datetime import datetime
from typing import Optional

import httpx

from app.config import settings
from app.schemas.aqi import AQICurrent, AQIResponse, get_aqi_category
from app.utils.logging import get_logger

logger = get_logger(__name__)


class AQIServiceError(Exception):
    """AQI service failed."""


class AQIService:
    """Fetches air quality data from Open-Meteo Air Pollution API."""

    async def get_current_aqi(
        self, latitude: float, longitude: float, location_name: str = "Unknown"
    ) -> AQIResponse:
        """Return normalized current AQI for coordinates."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "european_aqi,pm2_5,pm10,o3,no2,so2,co",
        }
        payload = await self._request(
            f"{settings.air_quality_api_base_url}/air-quality", params
        )
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

        return AQIResponse(
            location_name=location_name,
            latitude=latitude,
            longitude=longitude,
            current=normalized,
            timestamp=observed_at,
        )

    async def _request(self, url: str, params: dict) -> dict:
        """Perform a GET request with timeout and error mapping."""
        try:
            async with httpx.AsyncClient(timeout=settings.weather_timeout_seconds) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            logger.warning("AQI provider timeout: %s", exc)
            raise AQIServiceError("The air quality service timed out.") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning("AQI provider HTTP %s", exc.response.status_code)
            raise AQIServiceError(
                f"The air quality service returned an error (HTTP {exc.response.status_code})."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("AQI provider network error: %s", exc)
            raise AQIServiceError("Could not reach the air quality service.") from exc
        except ValueError as exc:
            logger.warning("AQI provider returned invalid JSON: %s", exc)
            raise AQIServiceError("The air quality service returned invalid data.") from exc


aqi_service = AQIService()
