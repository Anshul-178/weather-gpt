"""Pydantic schemas for saved locations and geocoding."""

from typing import Optional

from pydantic import BaseModel, Field


class LocationCreate(BaseModel):
    """POST /locations request body."""

    name: str = Field(..., min_length=1, max_length=120)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class LocationResponse(BaseModel):
    """A saved location record."""

    id: int
    name: str
    latitude: float
    longitude: float

    model_config = {"from_attributes": True}


class GeocodeResult(BaseModel):
    """One geocoding search result."""

    name: str
    latitude: float
    longitude: float
    country: Optional[str] = None
    admin1: Optional[str] = None


class GeocodeResponse(BaseModel):
    """GET /locations/search response."""

    results: list[GeocodeResult] = []
