"""Weather service.

Isolates the weather provider (Open-Meteo by default, OpenWeather supported)
behind this module.
No provider-specific logic should spread into routes or other services.
Provider data is the source of truth; it is normalized into the internal
weather schemas defined in app.schemas.weather.
"""

import asyncio
from datetime import datetime, timezone
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


class WeatherRateLimitError(WeatherProviderError):
    """The weather provider rejected the request because of rate limiting."""

    def __init__(
        self,
        message: str = "The weather provider is temporarily rate-limited.",
        retry_after_seconds: Optional[float] = None,
        from_cooldown: bool = False,
    ) -> None:
        super().__init__(message)
        # Honors the provider's Retry-After header when present (seconds), so
        # the cache layer can wait exactly as long as the provider asks.
        self.retry_after_seconds = retry_after_seconds
        # True when raised locally because a cooldown was already active (as
        # opposed to a fresh upstream 429). The cache layer must not restart
        # the cooldown for these, or steady traffic would extend it forever.
        self.from_cooldown = from_cooldown


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


def _parse_retry_after(value: Any) -> Optional[float]:
    """Parse a Retry-After header value (seconds or HTTP-date), or None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:  # HTTP-date form, e.g. "Wed, 21 Oct 2026 07:28:00 GMT"
        from email.utils import parsedate_to_datetime

        retry_at = parsedate_to_datetime(text)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except Exception:  # noqa: BLE001 - header is advisory; ignore bad values
        return None


class WeatherService:
    """Fetches and normalizes weather data from the configured provider."""

    async def get_current(
        self, latitude: float, longitude: float, location: Optional[GeoLocation] = None
    ) -> CurrentWeatherResponse:
        """Return normalized current weather for coordinates."""
        if self._uses_openweathermap():
            payload = await self._request(
                f"{self._provider_base_url()}/weather",
                {"lat": latitude, "lon": longitude, "units": "metric"},
            )
            response = self._normalize_openweathermap_current(
                payload, latitude, longitude, location
            )
            self._validate_response(response)
            return response

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
        # OpenWeather's free 5-day endpoint provides 3-hour forecast points;
        # Open-Meteo supports the existing 16-day route contract.
        max_days = 5 if self._uses_openweathermap() else 16
        days = max(1, min(days, max_days))
        if self._uses_openweathermap():
            payload = await self._request(
                f"{self._provider_base_url()}/forecast",
                {"lat": latitude, "lon": longitude, "units": "metric"},
            )
            loc = self._openweathermap_location(payload, latitude, longitude, location)
            response = self._normalize_openweathermap_forecast(payload, loc, days)
            self._validate_response(response)
            return response

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
        payload = await self._request(f"{settings.geocoding_api_base_url}/search", params)
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

    def _uses_openweathermap(self) -> bool:
        """Return whether the configured forecast provider is OpenWeather."""
        return "openweathermap.org" in settings.weather_api_base_url.lower()

    def _provider_base_url(self) -> str:
        """Return the configured provider base URL without a trailing slash."""
        return settings.weather_api_base_url.rstrip("/")

    def _openweathermap_location(
        self,
        payload: dict[str, Any],
        latitude: float,
        longitude: float,
        location: Optional[GeoLocation],
    ) -> GeoLocation:
        """Build a normalized location from OpenWeather metadata."""
        if location is not None:
            return location
        metadata = payload.get("city") or payload
        coordinates = metadata.get("coord") or {}
        city_name = metadata.get("name") or f"{latitude:.2f}, {longitude:.2f}"
        return GeoLocation(
            name=str(city_name),
            latitude=float(coordinates.get("lat", latitude)),
            longitude=float(coordinates.get("lon", longitude)),
            country=(metadata.get("sys") or {}).get("country")
            or metadata.get("country"),
        )

    def _normalize_openweathermap_current(
        self,
        payload: dict[str, Any],
        latitude: float,
        longitude: float,
        location: Optional[GeoLocation],
    ) -> CurrentWeatherResponse:
        """Normalize OpenWeather's current-weather response."""
        current = payload.get("main") or {}
        weather = (payload.get("weather") or [{}])[0]
        wind = payload.get("wind") or {}
        clouds = payload.get("clouds") or {}
        rain = payload.get("rain") or {}
        timestamp = datetime.fromtimestamp(
            float(payload.get("dt", datetime.now(tz=timezone.utc).timestamp())),
            tz=timezone.utc,
        )
        sunrise = (payload.get("sys") or {}).get("sunrise")
        sunset = (payload.get("sys") or {}).get("sunset")
        is_day = None
        if sunrise is not None and sunset is not None:
            is_day = sunrise <= payload.get("dt", 0) <= sunset

        normalized = CurrentWeather(
            temperature=current.get("temp"),
            feels_like=current.get("feels_like"),
            humidity=current.get("humidity"),
            wind_speed=self._metres_per_second_to_kmh(wind.get("speed")),
            wind_direction=wind.get("deg"),
            wind_direction_compass=wind_direction_to_compass(wind.get("deg")),
            pressure=current.get("pressure"),
            precipitation=rain.get("1h", rain.get("3h")),
            cloud_cover=clouds.get("all"),
            visibility=self._metres_to_km(payload.get("visibility")),
            condition=weather.get("description") or weather.get("main"),
            weather_code=weather.get("id"),
            is_day=is_day,
        )
        return CurrentWeatherResponse(
            location=self._openweathermap_location(
                payload, latitude, longitude, location
            ),
            current=normalized,
            timestamp=timestamp,
        )

    def _normalize_openweathermap_forecast(
        self, payload: dict[str, Any], loc: GeoLocation, days: int
    ) -> ForecastResponse:
        """Normalize OpenWeather's 3-hour forecast into daily/hourly points."""
        entries = payload.get("list") or []
        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            date_time = _parse_iso(entry.get("dt_txt"))
            if date_time is None:
                continue
            grouped.setdefault(date_time.date().isoformat(), []).append(entry)

        daily_points: list[DailyPoint] = []
        hourly_points: list[HourlyPoint] = []
        for date_str, day_entries in list(grouped.items())[:days]:
            representative = min(
                day_entries,
                key=lambda item: abs(
                    (_parse_iso(item.get("dt_txt")) or datetime.min).hour - 12
                ),
            )
            representative_weather = (representative.get("weather") or [{}])[0]
            temperatures = [
                item.get("main", {}).get("temp")
                for item in day_entries
                if item.get("main", {}).get("temp") is not None
            ]
            probabilities = [float(item.get("pop", 0)) * 100 for item in day_entries]
            wind_speeds = [
                self._metres_per_second_to_kmh(item.get("wind", {}).get("speed"))
                for item in day_entries
            ]
            wind_speeds = [value for value in wind_speeds if value is not None]
            precipitation = sum(
                self._forecast_precipitation(item) for item in day_entries
            )
            daily_points.append(
                DailyPoint(
                    date=date_str,
                    temperature_max=max(temperatures) if temperatures else None,
                    temperature_min=min(temperatures) if temperatures else None,
                    precipitation_sum=precipitation or None,
                    precipitation_probability=max(probabilities) if probabilities else None,
                    wind_speed_max=max(wind_speeds) if wind_speeds else None,
                    condition=representative_weather.get("description")
                    or representative_weather.get("main"),
                    weather_code=representative_weather.get("id"),
                )
            )

            for item in day_entries:
                parsed_time = _parse_iso(item.get("dt_txt"))
                if parsed_time is None:
                    continue
                main = item.get("main") or {}
                item_weather = (item.get("weather") or [{}])[0]
                hourly_points.append(
                    HourlyPoint(
                        time=parsed_time,
                        temperature=main.get("temp"),
                        feels_like=main.get("feels_like"),
                        precipitation_probability=float(item.get("pop", 0)) * 100,
                        precipitation=self._forecast_precipitation(item),
                        wind_speed=self._metres_per_second_to_kmh(
                            (item.get("wind") or {}).get("speed")
                        ),
                        humidity=main.get("humidity"),
                        condition=item_weather.get("description")
                        or item_weather.get("main"),
                        weather_code=item_weather.get("id"),
                        visibility=self._metres_to_km(item.get("visibility")),
                    )
                )

        return ForecastResponse(location=loc, forecast=daily_points, hourly=hourly_points)

    @staticmethod
    def _metres_per_second_to_kmh(value: Any) -> Optional[float]:
        """Convert OpenWeather wind speed from m/s to km/h."""
        if value is None:
            return None
        return float(value) * 3.6

    @staticmethod
    def _metres_to_km(value: Any) -> Optional[float]:
        """Convert metres to kilometres."""
        if value is None:
            return None
        return round(float(value) / 1000.0, 1)

    @staticmethod
    def _forecast_precipitation(entry: dict[str, Any]) -> float:
        """Read precipitation from an OpenWeather forecast interval."""
        rain = entry.get("rain") or {}
        snow = entry.get("snow") or {}
        return float(rain.get("3h", rain.get("1h", 0))) + float(
            snow.get("3h", snow.get("1h", 0))
        )

    async def _request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """Perform a GET request with timeout and error mapping.

        Transient provider failures (HTTP 5xx) are retried with a short
        backoff. HTTP 429 is surfaced immediately so the cache layer can enter
        a cooldown and serve the last known good weather instead of creating
        more rate-limited requests.
        """
        if "openweathermap.org" in url:
            if not settings.weather_api_key:
                raise WeatherProviderError(
                    "OpenWeather is selected but WEATHER_API_KEY is not configured."
                )
            params = {**params, "appid": settings.weather_api_key}
        # Provider API key (needed for paid-tier Open-Meteo access when set).
        elif (
            settings.weather_api_key
            and "api.open-meteo.com" in url
            and "api.open-meteo.com" in settings.weather_api_base_url
        ):
            params = {**params, "apikey": settings.weather_api_key}
        max_attempts = 3
        async with httpx.AsyncClient(
            timeout=settings.weather_timeout_seconds,
            # Some provider endpoints redirect (HTTP 303) to their canonical
            # HTTPS URL. Follow that redirect instead of surfacing it as a
            # backend 503.
            follow_redirects=True,
        ) as client:
            for attempt in range(max_attempts):
                try:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    return response.json()
                except httpx.TimeoutException as exc:
                    logger.warning("Weather provider timeout: %s", exc)
                    raise WeatherProviderError("The weather service timed out.") from exc
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    if status_code == 429:
                        retry_after = _parse_retry_after(
                            exc.response.headers.get("retry-after")
                        )
                        if retry_after is not None:
                            logger.warning(
                                "Weather provider HTTP 429 (rate limited; "
                                "retry after %.0fs)",
                                retry_after,
                            )
                        else:
                            logger.warning("Weather provider HTTP 429 (rate limited)")
                        raise WeatherRateLimitError(
                            "The weather provider is temporarily rate-limited.",
                            retry_after_seconds=retry_after,
                        ) from exc
                    if status_code >= 500 and attempt < max_attempts - 1:
                        logger.warning(
                            "Weather provider HTTP %s (attempt %d/%d) — retrying",
                            status_code,
                            attempt + 1,
                            max_attempts,
                        )
                        await asyncio.sleep(0.75 * (attempt + 1))
                        continue
                    logger.warning("Weather provider HTTP %s", status_code)
                    raise WeatherProviderError(
                        f"The weather service returned an error (HTTP {status_code})."
                    ) from exc
                except httpx.HTTPError as exc:
                    logger.warning("Weather provider network error: %s", exc)
                    raise WeatherProviderError("Could not reach the weather service.") from exc
                except ValueError as exc:
                    logger.warning("Weather provider returned invalid JSON: %s", exc)
                    raise WeatherProviderError("The weather service returned invalid data.") from exc
        raise WeatherProviderError("The weather service returned an error.")  # pragma: no cover

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
