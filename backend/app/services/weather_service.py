"""Weather service.

Isolates the weather provider (OpenWeather) behind this module.
No provider-specific logic should spread into routes or other services.
Provider data is the source of truth; it is normalized into the internal
weather schemas defined in app.schemas.weather.

Historical/climate data is served by the Open-Meteo Archive API via
historical_service.py — the only place Open-Meteo is still used.
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

# WMO weather codes → human-readable conditions. OpenWeather condition ids
# are mapped onto these codes (see _OWM_ID_TO_WMO) so the rest of the app
# (alerts, aviation, activity engine, Flutter icons) keeps one code space.
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

# OpenWeather condition id → WMO weather code (groups: 2xx thunderstorm,
# 3xx drizzle, 5xx rain, 6xx snow, 7xx atmosphere, 800 clear, 80x clouds).
_OWM_ID_TO_WMO: dict[int, int] = {
    200: 95, 201: 95, 202: 95, 210: 95, 211: 95, 212: 95, 221: 95,
    230: 96, 231: 96, 232: 96,
    300: 51, 301: 51, 302: 81, 310: 51, 311: 81, 312: 82, 313: 81,
    314: 82, 321: 81,
    500: 61, 501: 63, 502: 65, 503: 65, 504: 65, 511: 66,
    520: 80, 521: 81, 522: 82, 531: 81,
    600: 71, 601: 73, 602: 75, 611: 66, 612: 66, 613: 66, 615: 66,
    616: 66, 620: 85, 621: 86, 622: 86,
    701: 45, 711: 45, 721: 45, 731: 45, 741: 45, 751: 45, 761: 45,
    762: 45, 771: 45, 781: 45,
    800: 0, 801: 1, 802: 2, 803: 2, 804: 3,
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


def _wmo_from_owm_id(owm_id: Optional[Any]) -> Optional[int]:
    """Map an OpenWeather condition id onto the internal WMO code space."""
    if owm_id is None:
        return None
    try:
        owm_id = int(owm_id)
    except (TypeError, ValueError):
        return None
    if owm_id in _OWM_ID_TO_WMO:
        return _OWM_ID_TO_WMO[owm_id]
    # Unknown id: fall back to its hundred-group so new provider ids still
    # map to a sensible family (2xx thunder, 3xx drizzle, 5xx rain, …).
    group = (owm_id // 100) * 100
    group_fallback = {
        200: 95, 300: 51, 500: 61, 600: 71, 700: 45, 800: 0,
    }.get(group)
    if group_fallback is not None:
        return group_fallback
    if 800 < owm_id < 900:
        return 2
    return None


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
        self._require_api_key()
        payload = await self._request(
            f"{self._provider_base_url()}/weather",
            {"lat": latitude, "lon": longitude, "units": "metric"},
        )
        response = self._normalize_current(payload, latitude, longitude, location)
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

        OpenWeather's free forecast endpoint provides 5-day/3-hour data; the
        `days` parameter is clamped to what the provider returns.
        """
        days = max(1, min(days, 5))
        self._require_api_key()
        payload = await self._request(
            f"{self._provider_base_url()}/forecast",
            {"lat": latitude, "lon": longitude, "units": "metric"},
        )
        loc = self._location_from_payload(payload, latitude, longitude, location)
        response = self._normalize_forecast(payload, loc, days)
        self._validate_response(response)
        return response

    async def geocode(self, name: str, count: int = 5) -> list[GeoLocation]:
        """Search for places by name using the Open-Meteo geocoding API.

        Open-Meteo is key-free and quota-free. Response shape:
        {"results": [{"name", "latitude", "longitude", "country",
        "country_code", "admin1", ...}], "generationtime_ms": ...}
        with no "results" key when nothing matches.
        """
        params = {"name": name, "count": max(1, min(count, 10)), "language": "en", "format": "json"}
        payload = await self._request(f"{settings.geocoding_api_base_url}/search", params)
        locations: list[GeoLocation] = []
        results = payload.get("results") if isinstance(payload, dict) else None
        for item in results if isinstance(results, list) else []:
            try:
                locations.append(
                    GeoLocation(
                        name=item.get("name") or name,
                        latitude=float(item["latitude"]),
                        longitude=float(item["longitude"]),
                        country=item.get("country") or item.get("country_code"),
                        admin1=item.get("admin1"),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return locations

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _api_key() -> str:
        """Return the configured OpenWeather API key (may be empty)."""
        return settings.weather_api_key or ""

    def _require_api_key(self) -> None:
        """Fail fast when the OpenWeather key is missing."""
        if not settings.weather_api_key:
            raise WeatherProviderError(
                "OpenWeather is selected but WEATHER_API_KEY is not configured."
            )

    def _provider_base_url(self) -> str:
        """Return the configured provider base URL without a trailing slash."""
        return settings.weather_api_base_url.rstrip("/")

    def _location_from_payload(
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

    def _normalize_current(
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
        snow = payload.get("snow") or {}
        timestamp = datetime.fromtimestamp(
            float(payload.get("dt", datetime.now(tz=timezone.utc).timestamp())),
            tz=timezone.utc,
        )
        sunrise = (payload.get("sys") or {}).get("sunrise")
        sunset = (payload.get("sys") or {}).get("sunset")
        is_day = None
        if sunrise is not None and sunset is not None:
            is_day = sunrise <= payload.get("dt", 0) <= sunset

        # Precipitation: prefer recent-hour rain, then snow, then 3h windows.
        precipitation = rain.get("1h", rain.get("3h"))
        if precipitation is None:
            precipitation = snow.get("1h", snow.get("3h"))

        normalized = CurrentWeather(
            temperature=current.get("temp"),
            feels_like=current.get("feels_like"),
            humidity=current.get("humidity"),
            wind_speed=self._metres_per_second_to_kmh(wind.get("speed")),
            wind_direction=wind.get("deg"),
            wind_direction_compass=wind_direction_to_compass(wind.get("deg")),
            pressure=current.get("pressure"),
            precipitation=precipitation,
            cloud_cover=clouds.get("all"),
            visibility=self._metres_to_km(payload.get("visibility")),
            condition=weather.get("description") or weather.get("main"),
            weather_code=_wmo_from_owm_id(weather.get("id")),
            is_day=is_day,
        )
        return CurrentWeatherResponse(
            location=self._location_from_payload(payload, latitude, longitude, location),
            current=normalized,
            timestamp=timestamp,
        )

    def _normalize_forecast(
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
                    weather_code=_wmo_from_owm_id(representative_weather.get("id")),
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
                        weather_code=_wmo_from_owm_id(item_weather.get("id")),
                        visibility=self._metres_to_km(item.get("visibility")),
                    )
                )

        return ForecastResponse(location=loc, forecast=daily_points, hourly=hourly_points)

    @staticmethod
    def _metres_per_second_to_kmh(value: Any) -> Optional[float]:
        """Convert OpenWeather wind speed from m/s to km/h."""
        if value is None:
            return None
        return round(float(value) * 3.6, 1)

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

    async def _request(self, url: str, params: dict[str, Any]) -> Any:
        """Perform a GET request with timeout and error mapping.

        Transient provider failures (HTTP 5xx) are retried with a short
        backoff. HTTP 429 is surfaced immediately so the cache layer can enter
        a cooldown and serve the last known good weather instead of creating
        more rate-limited requests. Returns the parsed JSON body, which for
        the OpenWeather geocoding endpoint is a JSON array.
        """
        if "openweathermap.org" in url:
            if not settings.weather_api_key:
                raise WeatherProviderError(
                    "OpenWeather is selected but WEATHER_API_KEY is not configured."
                )
            params = {**params, "appid": settings.weather_api_key}
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
