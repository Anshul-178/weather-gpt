"""Insights API routes.

Historical weather, climate trends, crop advisories, aviation briefings,
multi-city overview, and NWP model listing — the researcher/agriculture/
aviation/smart-city features of the problem statement.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.schemas.insights import (
    AviationBriefingRequest,
    AviationBriefingResponse,
    CityOverviewResponse,
    CityWeatherSnapshot,
    ClimateTrendResponse,
    CropAdvisoryRequest,
    CropAdvisoryResponse,
    HistoricalWeatherResponse,
)
from app.schemas.weather import GeoLocation
from app.services.aqi_service import AQIServiceError, aqi_service
from app.services.aviation_service import aviation_service
from app.services.cached_weather_service import cached_weather_service
from app.services.crop_advisory_service import crop_advisory_service
from app.config import settings
from app.services.cache_service import cache_service
from app.services.historical_service import (
    HistoricalServiceError,
    historical_service,
)
from app.utils.geo import cache_key_historical, cache_key_climate

from app.services.weather_service import (
    WeatherProviderError,
    WeatherValidationError,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/weather", tags=["insights"])

# Monitoring cities used when no explicit list is provided.
DEFAULT_CITIES: list[dict[str, object]] = [
    {"name": "Delhi", "latitude": 28.6139, "longitude": 77.209},
    {"name": "Mumbai", "latitude": 19.076, "longitude": 72.8777},
    {"name": "Kolkata", "latitude": 22.5726, "longitude": 88.3639},
    {"name": "Chennai", "latitude": 13.0827, "longitude": 80.2707},
    {"name": "Bengaluru", "latitude": 12.9716, "longitude": 77.5946},
    {"name": "Hyderabad", "latitude": 17.385, "longitude": 78.4867},
    {"name": "Ahmedabad", "latitude": 23.0225, "longitude": 72.5714},
    {"name": "Jaipur", "latitude": 26.9124, "longitude": 75.7873},
    {"name": "Lucknow", "latitude": 26.8467, "longitude": 80.9462},
    {"name": "Kanpur", "latitude": 26.4499, "longitude": 80.3319},
]

# NWP models available through Open-Meteo (grid + documentation names).
NWP_MODELS: list[dict[str, str]] = [
    {"id": "best_match", "name": "Best match (auto)", "source": "Open-Meteo"},
    {"id": "gfs_seamless", "name": "GFS seamless (NOAA)", "source": "NOAA GFS / HRRR"},
    {"id": "ecmwf_ifs025", "name": "ECMWF IFS 0.25°", "source": "ECMWF"},
    {"id": "icon_seamless", "name": "ICON seamless (DWD)", "source": "DWD ICON"},
    {"id": "ukmo_seamless", "name": "UKMO Global (UK Met Office)", "source": "Met Office"},
    {"id": "gem_seamless", "name": "GEM (Canada)", "source": "CMC"},
    {"id": "jma_seamless", "name": "JMA (Japan)", "source": "JMA"},
]


@router.get("/historical")
async def get_historical(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    days: int = Query(30, ge=1, le=365),
    location_name: Optional[str] = Query(None, max_length=120),
):
    """Historical daily observations for the past N days (archive API)."""
    try:
        loc = GeoLocation(name=location_name, latitude=latitude, longitude=longitude) \
            if location_name else None
        return await historical_service.get_historical(latitude, longitude, days, loc)
    except HistoricalServiceError as exc:
        stale = await _serve_stale_historical(latitude, longitude, days)
        if stale is not None:
            logger.warning(
                "Serving stale historical weather for %.2f,%.2f (%d days)",
                latitude, longitude, days,
            )
            return stale
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.get("/climate")
async def get_climate_trends(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    years: int = Query(5, ge=2, le=20),
    location_name: Optional[str] = Query(None, max_length=120),
):
    """Monthly climate aggregates + warming trend over the past N years."""
    try:
        loc = GeoLocation(name=location_name, latitude=latitude, longitude=longitude) \
            if location_name else None
        return await historical_service.get_climate_trend(latitude, longitude, years, loc)
    except HistoricalServiceError as exc:
        stale = await _serve_stale_climate(latitude, longitude, years)
        if stale is not None:
            logger.warning(
                "Serving stale climate trend for %.2f,%.2f (%d years)",
                latitude, longitude, years,
            )
            return stale
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.post(
    "/crop-advisory",
    response_model=CropAdvisoryResponse,
    responses={503: {"description": "Weather provider unavailable"}},
)
async def get_crop_advisory(body: CropAdvisoryRequest) -> CropAdvisoryResponse:
    """Deterministic crop-weather advisories for the next 3 days."""
    try:
        current = await cached_weather_service.get_current(
            body.latitude, body.longitude
        )
        forecast = await cached_weather_service.get_forecast(
            body.latitude, body.longitude, days=4
        )
        return crop_advisory_service.generate(body, current, forecast)
    except (WeatherProviderError, WeatherValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.post(
    "/aviation",
    response_model=AviationBriefingResponse,
    responses={503: {"description": "Weather provider unavailable"}},
)
async def get_aviation_briefing(body: AviationBriefingRequest) -> AviationBriefingResponse:
    """VFR-style aviation weather briefing for the next N hours."""
    try:
        current = await cached_weather_service.get_current(
            body.latitude, body.longitude
        )
        forecast = await cached_weather_service.get_forecast(
            body.latitude, body.longitude, days=2
        )
        return aviation_service.generate(body, current, forecast)
    except (WeatherProviderError, WeatherValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.get("/city-overview", response_model=CityOverviewResponse)
async def get_city_overview(
    cities: Optional[str] = Query(
        None, description="Comma-separated 'Name:lat:lon' entries (max 20)"
    ),
) -> CityOverviewResponse:
    """Current conditions across many cities at once (smart-city monitoring)."""
    city_list = _parse_cities(cities) if cities else DEFAULT_CITIES
    snapshots = await _gather_cities(city_list)
    return CityOverviewResponse(cities=snapshots)


@router.get("/models")
async def list_nwp_models() -> dict:
    """NWP models selectable for forecasts via the `model` parameter."""
    return {"models": NWP_MODELS}


async def _serve_stale_historical(
    latitude: float, longitude: float, days: int
) -> HistoricalWeatherResponse | None:
    """Best-effort stale historical payload from cache."""
    if not settings.serve_stale_on_provider_rate_limit:
        return None
    try:
        payload = await cache_service.get(cache_key_historical(latitude, longitude, days))
        if payload is None:
            return None
        return HistoricalWeatherResponse.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Stale historical cache read failed: %s", exc)
        return None


async def _serve_stale_climate(
    latitude: float, longitude: float, years: int
) -> ClimateTrendResponse | None:
    """Best-effort stale climate payload from cache."""
    if not settings.serve_stale_on_provider_rate_limit:
        return None
    try:
        payload = await cache_service.get(cache_key_climate(latitude, longitude, years))
        if payload is None:
            return None
        return ClimateTrendResponse.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Stale climate cache read failed: %s", exc)
        return None


async def _gather_cities(city_list: list[dict[str, object]]) -> list[CityWeatherSnapshot]:
    """Fetch current weather (+AQI) for all cities concurrently."""
    async def fetch_one(city: dict[str, object]) -> CityWeatherSnapshot:
        name = str(city["name"])
        lat = float(city["latitude"])  # type: ignore[arg-type]
        lon = float(city["longitude"])  # type: ignore[arg-type]
        try:
            current = await cached_weather_service.get_current(
                lat, lon, GeoLocation(name=name, latitude=lat, longitude=lon)
            )
            snapshot = CityWeatherSnapshot(
                name=name,
                latitude=lat,
                longitude=lon,
                temperature=current.current.temperature,
                feels_like=current.current.feels_like,
                humidity=current.current.humidity,
                wind_speed=current.current.wind_speed,
                precipitation=current.current.precipitation,
                condition=current.current.condition,
                weather_code=current.current.weather_code,
            )
        except (WeatherProviderError, WeatherValidationError):
            return CityWeatherSnapshot(
                name=name, latitude=lat, longitude=lon, condition="unavailable"
            )
        try:
            aqi = await aqi_service.get_current_aqi(lat, lon, name)
            snapshot.aqi = aqi.current.aqi
        except AQIServiceError:
            snapshot.aqi = None
        return snapshot

    return list(await asyncio.gather(*(fetch_one(city) for city in city_list)))


def _parse_cities(raw: str) -> list[dict[str, object]]:
    """Parse 'Name:lat:lon,Name:lat:lon' into city dicts."""
    parsed: list[dict[str, object]] = []
    for chunk in raw.split(","):
        parts = chunk.strip().split(":")
        if len(parts) != 3:
            continue
        try:
            parsed.append(
                {
                    "name": parts[0].strip()[:60],
                    "latitude": float(parts[1]),
                    "longitude": float(parts[2]),
                }
            )
        except ValueError:
            continue
        if len(parsed) >= 20:
            break
    return parsed or DEFAULT_CITIES
