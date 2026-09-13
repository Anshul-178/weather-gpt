"""Historical weather & climate trend service.

Uses the Open-Meteo Archive API (free, no key) to fetch past observations.
Feature 7 of the problem statement: climate trend and historical weather
analysis for researchers and planners.

Cached to avoid repeated archive API calls for the same coordinate window
(free-tier rate-limit mitigation).
"""

import asyncio
import time
from datetime import date, timedelta
from typing import Awaitable, Callable, Optional as _Optional
from unittest.mock import AsyncMock
from typing import Any, Optional

import httpx

from app.config import settings
from app.schemas.insights import (
    ClimateTrendPoint,
    ClimateTrendResponse,
    HistoricalDailyPoint,
    HistoricalPeriodStats,
    HistoricalWeatherResponse,
)
from app.schemas.weather import GeoLocation
from app.services.cache_service import cache_service
from app.utils.geo import (
    cache_key_climate,
    cache_key_historical,
    round_coord,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

ARCHIVE_BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

_HISTORICAL_LAST_GOOD: dict[str, tuple[float, dict]] = {}
_HISTORICAL_LAST_GOOD_TTL_SECONDS = 3600


class HistoricalServiceError(Exception):
    """Historical weather service failed."""


class HistoricalService:
    """Fetches and aggregates historical weather from the archive API."""

    async def get_historical(
        self,
        latitude: float,
        longitude: float,
        days: int = 30,
        location: Optional[GeoLocation] = None,
    ) -> HistoricalWeatherResponse:
        """Return daily historical observations for the past `days` days."""
        days = max(1, min(days, 365))
        key = cache_key_historical(latitude, longitude, days)
        cached = await self._get_cached(key)
        if cached is not None:
            return HistoricalWeatherResponse.model_validate(cached)

        end = date.today() - timedelta(days=1)  # archive has ~5-day lag
        start = end - timedelta(days=days - 1)

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
            "precipitation_sum,wind_speed_10m_max",
            "timezone": "auto",
        }
        try:
            payload = await self._request(params)
        except HistoricalServiceError:
            stale = self._recall_last_good(key)
            if stale is not None:
                logger.warning("Serving last-good HISTORICAL weather for %s", key)
                return HistoricalWeatherResponse.model_validate(stale)
            raise

        loc = location or GeoLocation(
            name=f"{latitude:.2f}, {longitude:.2f}", latitude=latitude, longitude=longitude
        )

        daily_payload = payload.get("daily") or {}
        points = self._parse_daily(daily_payload)
        stats = self._compute_stats(points, days)
        response = HistoricalWeatherResponse(
            location=loc,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            daily=points,
            stats=stats,
        )
        await self._set_cached(key, response)
        self._remember_last_good(key, response)
        return response

    async def get_climate_trend(
        self,
        latitude: float,
        longitude: float,
        years: int = 5,
        location: Optional[GeoLocation] = None,
    ) -> ClimateTrendResponse:
        """Return monthly climate aggregates over the past N years."""
        years = max(2, min(years, 20))
        key = cache_key_climate(latitude, longitude, years)
        cached = await self._get_cached(key)
        if cached is not None:
            return ClimateTrendResponse.model_validate(cached)

        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=years * 365)

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
            "precipitation_sum",
            "timezone": "auto",
        }
        try:
            payload = await self._request(params)
        except HistoricalServiceError:
            stale = self._recall_last_good(key)
            if stale is not None:
                logger.warning("Serving last-good CLIMATE TREND for %s", key)
                return ClimateTrendResponse.model_validate(stale)
            raise

        loc = location or GeoLocation(
            name=f"{latitude:.2f}, {longitude:.2f}", latitude=latitude, longitude=longitude
        )

        points = self._parse_daily(payload.get("daily") or {})
        monthly = self._aggregate_monthly(points)

        warming = self._warming_trend_c_per_decade(monthly)
        annual_precip = self._annual_precipitation(monthly, years)
        anomaly = self._current_month_anomaly(monthly)

        response = ClimateTrendResponse(
            location=loc,
            years=years,
            monthly=monthly,
            warming_trend_c_per_decade=warming,
            annual_precipitation_mm=annual_precip,
            current_month_anomaly_c=anomaly,
        )
        await self._set_cached(key, response)
        self._remember_last_good(key, response)
        return response

    # ------------------------------------------------------------------ #
    # cache helpers
    # ------------------------------------------------------------------ #

    async def _get_cached(self, key: str) -> Optional[dict]:
        """Fetch a cached payload; treat any cache failure as a miss."""
        try:
            return await cache_service.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Historical cache GET failed for %s: %s", key, exc)
            return None

    async def _set_cached(
        self, key: str, response: HistoricalWeatherResponse | ClimateTrendResponse
    ) -> None:
        """Store a payload in cache; failures are non-fatal."""
        try:
            if isinstance(response, HistoricalWeatherResponse):
                ttl = settings.cache_historical_ttl_seconds
            else:
                ttl = settings.cache_climate_ttl_seconds
            await cache_service.set(
                key,
                response.model_dump(mode="json"),
                ttl_seconds=ttl,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Historical cache SET failed for %s: %s", key, exc)

    def _remember_last_good(self, key: str, value) -> None:
        """Store a serializable payload as the last-known-good response."""
        try:
            _HISTORICAL_LAST_GOOD[key] = (
                time.monotonic() + _HISTORICAL_LAST_GOOD_TTL_SECONDS,
                value.model_dump(mode="json"),
            )
        except Exception:  # noqa: BLE001 - never fail the happy path
            pass

    def _recall_last_good(self, key: str) -> dict | None:
        """Return the last-known-good payload for a key, if still fresh."""
        entry = _HISTORICAL_LAST_GOOD.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if expires_at < time.monotonic():
            _HISTORICAL_LAST_GOOD.pop(key, None)
            return None
        return payload

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _parse_daily(self, daily: dict[str, Any]) -> list[HistoricalDailyPoint]:
        """Convert archive daily arrays into typed points."""
        dates = daily.get("time") or []
        points: list[HistoricalDailyPoint] = []
        for index, date_str in enumerate(dates):
            points.append(
                HistoricalDailyPoint(
                    date=str(date_str),
                    temperature_max=self._f(daily.get("temperature_2m_max"), index),
                    temperature_min=self._f(daily.get("temperature_2m_min"), index),
                    temperature_mean=self._f(daily.get("temperature_2m_mean"), index),
                    precipitation_sum=self._f(daily.get("precipitation_sum"), index),
                    wind_speed_max=self._f(daily.get("wind_speed_10m_max"), index),
                )
            )
        return points

    def _compute_stats(
        self, points: list[HistoricalDailyPoint], period_days: int
    ) -> HistoricalPeriodStats:
        """Aggregate the period statistics shown in the UI."""
        temps = [p.temperature_mean for p in points if p.temperature_mean is not None]
        maxima = [p.temperature_max for p in points if p.temperature_max is not None]
        minima = [p.temperature_min for p in points if p.temperature_min is not None]
        precip = [p.precipitation_sum for p in points if p.precipitation_sum is not None]

        hottest = max(
            (p for p in points if p.temperature_max is not None),
            key=lambda p: p.temperature_max,  # type: ignore[arg-type,return-value]
            default=None,
        )
        wettest = max(
            (p for p in points if p.precipitation_sum is not None),
            key=lambda p: p.precipitation_sum,  # type: ignore[arg-type,return-value]
            default=None,
        )
        return HistoricalPeriodStats(
            period_days=period_days,
            temp_mean=round(sum(temps) / len(temps), 1) if temps else None,
            temp_max=max(maxima) if maxima else None,
            temp_min=min(minima) if minima else None,
            total_precipitation=round(sum(precip), 1) if precip else None,
            wet_days=sum(1 for p in precip if p >= 1.0),
            hottest_day=hottest,
            wettest_day=wettest,
        )

    def _aggregate_monthly(
        self, points: list[HistoricalDailyPoint]
    ) -> list[ClimateTrendPoint]:
        """Group daily points into monthly aggregates."""
        buckets: dict[str, dict] = {}
        for point in points:
            month_key = point.date[:7]
            bucket = buckets.setdefault(
                month_key,
                {"tmax": [], "tmin": [], "tmean": [], "precip": 0.0, "wet": 0},
            )
            if point.temperature_max is not None:
                bucket["tmax"].append(point.temperature_max)
            if point.temperature_min is not None:
                bucket["tmin"].append(point.temperature_min)
            if point.temperature_mean is not None:
                bucket["tmean"].append(point.temperature_mean)
            if point.precipitation_sum is not None:
                bucket["precip"] += point.precipitation_sum
                if point.precipitation_sum >= 1.0:
                    bucket["wet"] += 1

        monthly: list[ClimateTrendPoint] = []
        for month_key in sorted(buckets):
            bucket = buckets[month_key]
            monthly.append(
                ClimateTrendPoint(
                    month=month_key,
                    avg_temp_max=round(sum(bucket["tmax"]) / len(bucket["tmax"]), 1)
                    if bucket["tmax"]
                    else None,
                    avg_temp_min=round(sum(bucket["tmin"]) / len(bucket["tmin"]), 1)
                    if bucket["tmin"]
                    else None,
                    avg_temp_mean=round(sum(bucket["tmean"]) / len(bucket["tmean"]), 1)
                    if bucket["tmean"]
                    else None,
                    total_precipitation=round(bucket["precip"], 1),
                    wet_days=bucket["wet"],
                )
            )
        return monthly

    def _warming_trend_c_per_decade(
        self, monthly: list[ClimateTrendPoint]
    ) -> Optional[float]:
        """Linear regression slope of monthly mean temps, scaled to °C/decade."""
        samples = [
            (index, point.avg_temp_mean)
            for index, point in enumerate(monthly)
            if point.avg_temp_mean is not None
        ]
        if len(samples) < 12:
            return None
        n = len(samples)
        mean_x = sum(x for x, _ in samples) / n
        mean_y = sum(y for _, y in samples) / n
        cov = sum((x - mean_x) * (y - mean_y) for x, y in samples)
        var = sum((x - mean_x) ** 2 for x, _ in samples)
        if var == 0:
            return None
        slope_per_month = cov / var
        return round(slope_per_month * 120, 2)  # 12 months × 10 years

    def _annual_precipitation(
        self, monthly: list[ClimateTrendPoint], years: int
    ) -> Optional[float]:
        """Average total annual precipitation across the window."""
        totals = [point.total_precipitation for point in monthly if point.total_precipitation is not None]
        if not totals:
            return None
        return round(sum(totals) / max(years, 1), 1)

    def _current_month_anomaly(
        self, monthly: list[ClimateTrendPoint]
    ) -> Optional[float]:
        """This calendar month vs the same months in previous years."""
        if not monthly:
            return None
        latest = monthly[-1]
        if latest.avg_temp_mean is None:
            return None
        same_month = [
            point.avg_temp_mean
            for point in monthly[:-1]
            if point.month.endswith(latest.month[5:8]) and point.avg_temp_mean is not None
        ]
        if not same_month:
            return None
        baseline = sum(same_month) / len(same_month)
        return round(latest.avg_temp_mean - baseline, 1)

    @staticmethod
    def _f(values: Any, index: int) -> Optional[float]:
        """Safe float extraction from provider arrays."""
        if isinstance(values, list) and 0 <= index < len(values):
            value = values[index]
            if isinstance(value, (int, float)):
                return float(value)
        return None

    async def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        """Perform the archive GET request with timeout and error mapping.

        HTTP 429 is retried once with backoff. On persistent provider errors
        the caller falls back to cache / last-good payload.
        """
        # Provider API key (moves quota from the shared deployment IP to the account).
        if settings.weather_api_key and "open-meteo.com" in ARCHIVE_BASE_URL:
            params = {**params, "apikey": settings.weather_api_key}
        try:
            async with httpx.AsyncClient(timeout=settings.weather_timeout_seconds) as client:
                response = await client.get(ARCHIVE_BASE_URL, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            logger.warning("Archive API timeout: %s", exc)
            raise HistoricalServiceError("The climate data service timed out.") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning("Archive API HTTP %s", exc.response.status_code)
            raise HistoricalServiceError(
                f"The climate data service returned an error (HTTP {exc.response.status_code})."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("Archive API network error: %s", exc)
            raise HistoricalServiceError("Could not reach the climate data service.") from exc
        except ValueError as exc:
            logger.warning("Archive API returned invalid JSON: %s", exc)
            raise HistoricalServiceError("The climate data service returned invalid data.") from exc


historical_service = HistoricalService()
