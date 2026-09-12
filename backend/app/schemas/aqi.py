"""Pydantic schemas for air quality data."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AQICurrent(BaseModel):
    """Normalized current AQI observation."""

    aqi: Optional[int] = None
    pm2_5: Optional[float] = None
    pm10: Optional[float] = None
    o3: Optional[float] = None  # Ozone
    no2: Optional[float] = None  # Nitrogen Dioxide
    so2: Optional[float] = None  # Sulfur Dioxide
    co: Optional[float] = None  # Carbon Monoxide
    epa_aqi: Optional[str] = None  # EPA AQI category
    dominant_pollutant: Optional[str] = None


class AQIResponse(BaseModel):
    """GET /weather/aqi response."""

    location_name: str
    latitude: float
    longitude: float
    current: AQICurrent
    timestamp: datetime = Field(default_factory=datetime.now)


def get_aqi_category(aqi: int) -> str:
    """Map AQI value to EPA category."""
    if aqi is None:
        return "Unknown"
    if aqi <= 50:
        return "Good"
    elif aqi <= 100:
        return "Moderate"
    elif aqi <= 150:
        return "Unhealthy for Sensitive Groups"
    elif aqi <= 200:
        return "Unhealthy"
    elif aqi <= 300:
        return "Very Unhealthy"
    else:
        return "Hazardous"


def get_aqi_color(aqi: int) -> str:
    """Get color code for AQI value."""
    if aqi is None:
        return "#808080"  # Gray
    if aqi <= 50:
        return "#00E400"  # Green
    elif aqi <= 100:
        return "#FFFF00"  # Yellow
    elif aqi <= 150:
        return "#FF7E00"  # Orange
    elif aqi <= 200:
        return "#FF0000"  # Red
    elif aqi <= 300:
        return "#8F3F97"  # Purple
    else:
        return "#7E0023"  # Maroon
