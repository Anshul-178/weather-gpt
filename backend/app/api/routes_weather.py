"""Weather API routes.

Thin route handlers: validation and delegation to services only.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.activity import ActivityScoreRequest, ActivityScoreResponse
from app.schemas.chat import ComparisonRequest, ComparisonResponse
from app.schemas.location import GeocodeResponse
from app.schemas.weather import CurrentWeatherResponse, ForecastResponse
from app.services.activity_engine import compute_activity_score
from app.services.cached_weather_service import cached_weather_service
from app.services.comparison_service import comparison_service
from app.services.location_service import location_service

from app.services.weather_service import (
    WeatherProviderError,
    WeatherValidationError,
)
from app.utils.validation import ValidationError as AppValidationError
from app.utils.validation import validate_days, validate_latitude, validate_longitude

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get(
    "/current",
    response_model=CurrentWeatherResponse,
    responses={503: {"description": "Weather provider unavailable"}},
)
async def get_current_weather(
    latitude: float = Query(..., ge=-90, le=90, description="Latitude"),
    longitude: float = Query(..., ge=-180, le=180, description="Longitude"),
    location_name: Optional[str] = Query(None, max_length=120),
) -> CurrentWeatherResponse:
    """Return normalized current weather for coordinates."""
    try:
        validate_latitude(latitude)
        validate_longitude(longitude)
        geo = None
        if location_name:
            geo = await location_service.resolve(latitude, longitude, location_name)
            from app.schemas.weather import GeoLocation

            geo = GeoLocation(name=geo[2], latitude=geo[0], longitude=geo[1])
        return await cached_weather_service.get_current(latitude, longitude, geo)
    except (WeatherProviderError, WeatherValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except AppValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get(
    "/forecast",
    response_model=ForecastResponse,
    responses={503: {"description": "Weather provider unavailable"}},
)
async def get_forecast(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    days: int = Query(7, ge=1, le=16),
    model: Optional[str] = Query(
        None,
        max_length=60,
        description="Forecast model id (see /weather/models); OpenWeather serves its own global model",
    ),
) -> ForecastResponse:
    """Return normalized daily + hourly forecast for coordinates."""
    try:
        validate_days(days)
        return await cached_weather_service.get_forecast(latitude, longitude, days, model=model)
    except (WeatherProviderError, WeatherValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except AppValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get(
    "/search",
    response_model=GeocodeResponse,
    responses={503: {"description": "Geocoding provider unavailable"}},
)
async def search_locations(
    query: str = Query(..., min_length=1, max_length=120),
) -> GeocodeResponse:
    """Search places by name (geocoding)."""
    try:
        return await location_service.search(query)
    except WeatherProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except AppValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post(
    "/activity-score",
    response_model=ActivityScoreResponse,
    responses={503: {"description": "Weather provider unavailable"}},
)
async def get_activity_score(body: ActivityScoreRequest) -> ActivityScoreResponse:
    """Explainable weather impact score for an activity."""
    try:
        current = await cached_weather_service.get_current(body.latitude, body.longitude)
        forecast = await cached_weather_service.get_forecast(
            body.latitude, body.longitude, days=min(body.day_offset + 1, 16)
        )
        return compute_activity_score(
            body.activity, current, forecast, day_offset=body.day_offset
        )
    except (WeatherProviderError, WeatherValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.post(
    "/compare",
    response_model=ComparisonResponse,
    responses={503: {"description": "Weather provider unavailable"}},
)
async def compare_weather(body: ComparisonRequest) -> ComparisonResponse:
    """Compare weather between two locations for a given day offset."""
    try:
        return await comparison_service.compare_locations(
            body.latitude_a,
            body.longitude_a,
            body.latitude_b,
            body.longitude_b,
            name_a=body.name_a,
            name_b=body.name_b,
            day_offset=body.day_offset,
        )
    except WeatherProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.get("/best-time")
async def get_best_time(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    activity: str = Query("walking", max_length=50),
    day_offset: int = Query(0, ge=0, le=15),
) -> dict:
    """Recommend the best time window for an activity."""
    try:
        current = await cached_weather_service.get_current(latitude, longitude)
        forecast = await cached_weather_service.get_forecast(
            latitude, longitude, days=min(day_offset + 1, 16)
        )
        result = compute_activity_score(
            activity, current, forecast, day_offset=day_offset
        )
        return {
            "activity": result.activity,
            "best_time": result.best_time,
            "score": result.score,
            "rating": result.rating,
        }
    except (WeatherProviderError, WeatherValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


