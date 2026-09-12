"""Weather service.

Isolates the weather provider (Open-Meteo by default) behind this module.
No provider-specific logic should spread into routes or other services.
Provider data is the source of truth; it is normalized into the internal
weather schemas defined in app.schemas.weather.
"""

from datetime import datetime
from typing import Any, Optional

import httpx

from app.config import settings
from app.schemas.weather import (
    CurrentWeather,
    CurrentWeatherResponse,
    DailyPoint,
    ForecastResponse,
    GeoLocation,
    HourlyPoint,
)
from app.utils.logging import get_logger
from app.utils.units import wind_direction_to_compass

logger = get_logger(__name__)

# Open-Meteo WMO weather codes → human-readable conditions.
WMO_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherProviderError(Exception):
    """Weather provider failed (network, HTTP error, bad payload)."""


class WeatherValidationError(Exception):
    """Provider returned data that could not be normalized."""


def _condition_from_code(code: Optional[int]) -> Optional[str]:
    """Map a WMO weather code to a human-readable condition."""
    if code is None:
        return None
    return WMO_CODES.get(int(code), "Unknown")


def _at(values: Any, index: int) -> Any:
    """Safely get the element at `index` from a provider array."""
    if isinstance(values, list) and 0 <= index < len(values):
        return values[index]
    return None


def _parse_iso(value: Any) -> Optional[datetime]:
    """Parse an ISO datetime string, returning None on failure."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class WeatherService:
    """Fetches and normalizes weather data from the configured provider."""

    async def get_current(
        self, latitude: float, longitude: float, location: Optional[GeoLocation] = None
    ) -> CurrentWeatherResponse:
        """Return normalized current weather for coordinates."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "apparent_temperature",
                    "is_day",
                    "precipitation",
                    "weather_code",
                    "cloud_cover",
                    "pressure_msl",
                    "visibility",
                    "wind_speed_10m",
                    "wind_direction_10m",
                ]
            ),
            "hourly": "uv_index",
            "forecast_days": 1,
        }
        payload = await self._request(f"{settings.weather_api_base_url}/forecast", params)
        current = payload.get("current") or {}
        code = current.get("weather_code")

        normalized = CurrentWeather(
            temperature=current.get("temperature_2m"),
            feels_like=current.get("apparent_temperature"),
            humidity=current.get("relative_humidity_2m"),
            wind_speed=current.get("wind_speed_10m"),  # Open-Meteo default: km/h
            wind_direction=current.get("wind_direction_10m"),
            wind_direction_compass=wind_direction_to_compass(
                current.get("wind_direction_10m")
            ),
            pressure=current.get("pressure_msl"),
            precipitation=current.get("precipitation"),
            cloud_cover=current.get("cloud_cover"),
            visibility=self._visibility_km(current.get("visibility")),
            uv_index=self._current_uv(payload.get("hourly"), current.get("time")),
            condition=_condition_from_code(code),
            weather_code=code,
            is_day=bool(current["is_day"]) if current.get("is_day") is not None else None,
        )
        loc = location or GeoLocation(
            name=f"{latitude:.2f}, {longitude:.2f}", latitude=latitude, longitude=longitude
        )
        observed_at = _parse_iso(current.get("time")) or datetime.now()
        response = CurrentWeatherResponse(
            location=loc, current=normalized, timestamp=observed_at
        )
        self._validate_response(response)
        return response

    async def get_forecast(
        self,
        latitude: float,
        longitude: float,
        days: int = 7,
        location: Optional[GeoLocation] = None,
        model: Optional[str] = None,
    ) -> ForecastResponse:
        """Return normalized daily + hourly forecast for coordinates.

        `model` selects a specific NWP model (e.g. gfs_seamless, ecmwf_ifs025,
        icon_seamless) — see /weather/models for available options.
        """
        days = max(1, min(days, 16))
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": ",".join(
                [
                    "weather_code",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "sunrise",
                    "sunset",
                    "uv_index_max",
                    "precipitation_sum",
                    "precipitation_probability_max",
                    "wind_speed_10m_max",
                ]
            ),
            "hourly": ",".join(
                [
                    "temperature_2m",
                    "apparent_temperature",
                    "precipitation_probability",
                    "precipitation",
                    "weather_code",
                    "relative_humidity_2m",
                    "visibility",
                    "wind_speed_10m",
                    "uv_index",
                ]
            ),
            "forecast_days": days,
        }
        if model:
            params["models"] = model
        payload = await self._request(f"{settings.weather_api_base_url}/forecast", params)
        loc = location or GeoLocation(
            name=f"{latitude:.2f}, {longitude:.2f}", latitude=latitude, longitude=longitude
        )
        response = self._normalize_forecast(payload, loc, days)
        self._validate_response(response)
        return response

    async def geocode(self, name: str, count: int = 5) -> list[GeoLocation]:
        """Search for places by name using the provider geocoding API."""
        params = {"name": name, "count": count, "language": "en", "format": "json"}
        payload = await self._request(f"{settings.geocoding_base_url}/search", params)
        results = payload.get("results") or []
        locations: list[GeoLocation] = []
        for item in results:
            try:
                locations.append(
                    GeoLocation(
                        name=item.get("name") or name,
                        latitude=float(item["latitude"]),
                        longitude=float(item["longitude"]),
                        country=item.get("country"),
                        admin1=item.get("admin1"),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return locations

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    async def _request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """Perform a GET request with timeout and error mapping."""
        try:
            async with httpx.AsyncClient(
                timeout=settings.weather_timeout_seconds
            ) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            logger.warning("Weather provider timeout: %s", exc)
            raise WeatherProviderError("The weather service timed out.") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Weather provider HTTP %s", exc.response.status_code
            )
            raise WeatherProviderError(
                f"The weather service returned an error "
                f"(HTTP {exc.response.status_code})."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("Weather provider network error: %s", exc)
            raise WeatherProviderError("Could not reach the weather service.") from exc
        except ValueError as exc:
            logger.warning("Weather provider returned invalid JSON: %s", exc)
            raise WeatherProviderError("The weather service returned invalid data.") from exc

    def _normalize_forecast(
        self, payload: dict[str, Any], loc: GeoLocation, days: int
    ) -> ForecastResponse:
        """Convert provider payload into ForecastResponse."""
        daily = payload.get("daily") or {}
        hourly = payload.get("hourly") or {}

        daily_points: list[DailyPoint] = []
        for index, date_str in enumerate(daily.get("time") or []):
            if index >= days:
                break
            daily_points.append(
                DailyPoint(
                    date=str(date_str),
                    temperature_max=_at(daily.get("temperature_2m_max"), index),
                    temperature_min=_at(daily.get("temperature_2m_min"), index),
                    precipitation_sum=_at(daily.get("precipitation_sum"), index),
                    precipitation_probability=_at(
                        daily.get("precipitation_probability_max"), index
                    ),
                    wind_speed_max=_at(daily.get("wind_speed_10m_max"), index),
                    uv_index_max=_at(daily.get("uv_index_max"), index),
                    condition=_condition_from_code(_at(daily.get("weather_code"), index)),
                    weather_code=_at(daily.get("weather_code"), index),
                    sunrise=_at(daily.get("sunrise"), index),
                    sunset=_at(daily.get("sunset"), index),
                )
            )

        hourly_points: list[HourlyPoint] = []
        for index, time_str in enumerate(hourly.get("time") or []):
            parsed_time = _parse_iso(time_str)
            if parsed_time is None:
                continue
            code = _at(hourly.get("weather_code"), index)
            hourly_points.append(
                HourlyPoint(
                    time=parsed_time,
                    temperature=_at(hourly.get("temperature_2m"), index),
                    feels_like=_at(hourly.get("apparent_temperature"), index),
                    precipitation_probability=_at(
                        hourly.get("precipitation_probability"), index
                    ),
                    precipitation=_at(hourly.get("precipitation"), index),
                    wind_speed=_at(hourly.get("wind_speed_10m"), index),
                    humidity=_at(hourly.get("relative_humidity_2m"), index),
                    uv_index=_at(hourly.get("uv_index"), index),
                    visibility=self._visibility_km(_at(hourly.get("visibility"), index)),
                    condition=_condition_from_code(code),
                    weather_code=code,
                )
            )

        return ForecastResponse(location=loc, forecast=daily_points, hourly=hourly_points)

    def _current_uv(
        self, hourly: Optional[dict[str, Any]], current_time: Optional[str]
    ) -> Optional[float]:
        """Pick the closest hourly UV index value for the current time."""
        if not hourly or not hourly.get("time") or not current_time:
            return None
        target = _parse_iso(current_time)
        if target is None:
            return None
        best_value: Optional[float] = None
        best_delta: Optional[float] = None
        for time_str, value in zip(hourly.get("time") or [], hourly.get("uv_index") or []):
            hour_time = _parse_iso(time_str)
            if hour_time is None or value is None:
                continue
            delta = abs((hour_time - target).total_seconds())
            if best_delta is None or delta < best_delta:
                best_value = value
                best_delta = delta
        return best_value

    def _visibility_km(self, visibility_metres: Optional[float]) -> Optional[float]:
        """Convert provider visibility (metres) to kilometres."""
        if visibility_metres is None:
            return None
        return round(visibility_metres / 1000.0, 1)

    def _validate_response(self, response: Any) -> None:
        """Ensure normalized response contains usable data; raise otherwise."""
        if isinstance(response, CurrentWeatherResponse):
            if response.current.temperature is None and response.current.condition is None:
                raise WeatherValidationError(
                    "Weather response missing temperature and condition."
                )
        elif isinstance(response, ForecastResponse):
            if not response.forecast and not response.hourly:
                raise WeatherValidationError("Weather response missing forecast data.")


weather_service = WeatherService()
