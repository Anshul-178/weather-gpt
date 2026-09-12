"""Pydantic schemas for climate, agriculture, aviation, and city insights."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.weather import GeoLocation


# --------------------------------------------------------------------- #
# Historical / climate trends
# --------------------------------------------------------------------- #


class HistoricalDailyPoint(BaseModel):
    """One day of historical (archive) weather observations."""

    date: str
    temperature_max: Optional[float] = None
    temperature_min: Optional[float] = None
    temperature_mean: Optional[float] = None
    precipitation_sum: Optional[float] = None
    wind_speed_max: Optional[float] = None


class HistoricalPeriodStats(BaseModel):
    """Aggregate statistics for the requested historical window."""

    period_days: int
    temp_mean: Optional[float] = None
    temp_max: Optional[float] = None
    temp_min: Optional[float] = None
    total_precipitation: Optional[float] = None
    wet_days: int = 0  # days with >= 1 mm precipitation
    hottest_day: Optional[HistoricalDailyPoint] = None
    wettest_day: Optional[HistoricalDailyPoint] = None


class HistoricalWeatherResponse(BaseModel):
    """GET /weather/historical response."""

    location: GeoLocation
    start_date: str
    end_date: str
    daily: list[HistoricalDailyPoint] = []
    stats: HistoricalPeriodStats


class ClimateTrendPoint(BaseModel):
    """One month of aggregated climate data."""

    month: str  # e.g. "2025-01"
    avg_temp_max: Optional[float] = None
    avg_temp_min: Optional[float] = None
    avg_temp_mean: Optional[float] = None
    total_precipitation: Optional[float] = None
    wet_days: int = 0


class ClimateTrendResponse(BaseModel):
    """GET /weather/climate response — monthly aggregates over N years."""

    location: GeoLocation
    years: int
    monthly: list[ClimateTrendPoint] = []
    # Simple linear warming trend in °C per decade (None if insufficient data).
    warming_trend_c_per_decade: Optional[float] = None
    # Long-term annual precipitation average (mm).
    annual_precipitation_mm: Optional[float] = None
    # Same calendar month from previous years, for "is this month unusual?".
    current_month_anomaly_c: Optional[float] = None


# --------------------------------------------------------------------- #
# Crop advisories (agriculture decision support)
# --------------------------------------------------------------------- #


class CropAdvisoryRequest(BaseModel):
    """POST /weather/crop-advisory request body."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    location_name: Optional[str] = Field(None, max_length=120)
    crop: Optional[str] = Field(
        None, max_length=40, description="Optional crop key (rice, wheat, cotton, …)"
    )


class CropAdvisory(BaseModel):
    """One actionable advisory bullet."""

    category: str  # irrigation | pest_disease | field_work | sowing | general
    severity: str  # info | caution | warning
    message: str


class CropAdvisoryResponse(BaseModel):
    """POST /weather/crop-advisory response."""

    location: str
    latitude: float
    longitude: float
    crop: Optional[str] = None
    advisories: list[CropAdvisory] = []
    # 0-100 suitability for field operations (spraying, harvesting, ploughing)
    field_work_score: Optional[int] = None
    # Growing-degree-day style heat accumulation over the forecast window
    irrigation_needed: Optional[bool] = None
    generated_at: datetime = Field(default_factory=datetime.now)


# --------------------------------------------------------------------- #
# Aviation briefing
# --------------------------------------------------------------------- #


class AviationCondition(BaseModel):
    """A single aviation-relevant observation/rule result."""

    parameter: str  # visibility | wind | ceiling | precipitation | storm | temp
    status: str  # ok | caution | hazard
    value: Optional[str] = None
    note: Optional[str] = None


class AviationBriefingRequest(BaseModel):
    """POST /weather/aviation request body."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    location_name: Optional[str] = Field(None, max_length=120)
    hours_ahead: int = Field(12, ge=1, le=24)


class AviationBriefingResponse(BaseModel):
    """POST /weather/aviation response."""

    location: str
    # ok | caution | hazard — worst of the individual conditions
    flight_category: str
    summary: str
    conditions: list[AviationCondition] = []
    # VFR-style window: hour ranges where conditions are acceptable
    best_windows: list[str] = []
    generated_at: datetime = Field(default_factory=datetime.now)


# --------------------------------------------------------------------- #
# Smart-city multi-location overview
# --------------------------------------------------------------------- #


class CityWeatherSnapshot(BaseModel):
    """Current weather snapshot for one city."""

    name: str
    latitude: float
    longitude: float
    temperature: Optional[float] = None
    feels_like: Optional[float] = None
    humidity: Optional[float] = None
    wind_speed: Optional[float] = None
    precipitation: Optional[float] = None
    condition: Optional[str] = None
    weather_code: Optional[int] = None
    aqi: Optional[int] = None


class CityOverviewResponse(BaseModel):
    """GET /weather/city-overview response — monitor many cities at once."""

    cities: list[CityWeatherSnapshot] = []
    generated_at: datetime = Field(default_factory=datetime.now)
