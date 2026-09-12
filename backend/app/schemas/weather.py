"""Pydantic schemas for weather data (internal normalized format)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GeoLocation(BaseModel):
    """A named geographic location."""

    name: str
    latitude: float
    longitude: float
    country: Optional[str] = None
    admin1: Optional[str] = None


class CurrentWeather(BaseModel):
    """Normalized current weather observation."""

    temperature: Optional[float] = None
    feels_like: Optional[float] = None
    humidity: Optional[float] = None
    wind_speed: Optional[float] = None  # km/h
    wind_direction: Optional[float] = None  # degrees
    wind_direction_compass: Optional[str] = None
    pressure: Optional[float] = None  # hPa
    precipitation: Optional[float] = None  # mm
    precipitation_probability: Optional[float] = None  # %
    cloud_cover: Optional[float] = None  # %
    visibility: Optional[float] = None  # km
    uv_index: Optional[float] = None
    condition: Optional[str] = None
    weather_code: Optional[int] = None
    is_day: Optional[bool] = None


class HourlyPoint(BaseModel):
    """One hourly forecast point."""

    time: datetime
    temperature: Optional[float] = None
    feels_like: Optional[float] = None
    precipitation_probability: Optional[float] = None
    precipitation: Optional[float] = None
    wind_speed: Optional[float] = None
    humidity: Optional[float] = None
    uv_index: Optional[float] = None
    condition: Optional[str] = None
    weather_code: Optional[int] = None
    visibility: Optional[float] = None


class DailyPoint(BaseModel):
    """One daily forecast point."""

    date: str
    temperature_max: Optional[float] = None
    temperature_min: Optional[float] = None
    precipitation_sum: Optional[float] = None
    precipitation_probability: Optional[float] = None
    wind_speed_max: Optional[float] = None
    uv_index_max: Optional[float] = None
    condition: Optional[str] = None
    weather_code: Optional[int] = None
    sunrise: Optional[str] = None
    sunset: Optional[str] = None


class CurrentWeatherResponse(BaseModel):
    """GET /weather/current response."""

    location: GeoLocation
    current: CurrentWeather
    timestamp: datetime = Field(default_factory=datetime.now)


class ForecastResponse(BaseModel):
    """GET /weather/forecast response."""

    location: GeoLocation
    forecast: list[DailyPoint] = []
    hourly: list[HourlyPoint] = []
    timestamp: datetime = Field(default_factory=datetime.now)
