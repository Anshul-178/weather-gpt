"""Pydantic schemas for the AI chat API."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """POST /chat request body."""

    message: str = Field(..., min_length=1, max_length=1000)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    conversation_id: Optional[int] = None
    location_name: Optional[str] = Field(None, max_length=120)


class ChatResponse(BaseModel):
    """POST /chat response body."""

    answer: str
    location: Optional[str] = None
    intent: Optional[str] = None
    sources: list[str] = []
    conversation_id: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class TtsRequest(BaseModel):
    """POST /chat/tts request body."""

    text: str = Field(..., min_length=1, max_length=2000)
    voice: Optional[str] = None  # explicit Edge voice name, e.g. "ta-IN-PallaviNeural"
    language: Optional[str] = None  # BCP-47 code, e.g. "ta-IN", overrides script detection


class ComparisonRequest(BaseModel):
    """POST /weather/compare request body."""

    latitude_a: float = Field(..., ge=-90, le=90)
    longitude_a: float = Field(..., ge=-180, le=180)
    latitude_b: float = Field(..., ge=-90, le=90)
    longitude_b: float = Field(..., ge=-180, le=180)
    name_a: Optional[str] = None
    name_b: Optional[str] = None
    day_offset: int = Field(0, ge=0, le=15)


class ComparisonResponse(BaseModel):
    """Structured weather comparison between two locations."""

    location_a: str
    location_b: str
    summary: str
    temperature_diff_c: Optional[float] = None
    precipitation_probability_a: Optional[float] = None
    precipitation_probability_b: Optional[float] = None
    wind_speed_a: Optional[float] = None
    wind_speed_b: Optional[float] = None
    condition_a: Optional[str] = None
    condition_b: Optional[str] = None
