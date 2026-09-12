"""Pydantic schemas for the activity recommendation engine."""

from typing import Optional

from pydantic import BaseModel, Field


class ActivityScoreRequest(BaseModel):
    """POST /weather/activity-score request body."""

    activity: str = Field(..., min_length=1, max_length=50)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    day_offset: int = Field(0, ge=0, le=15)


class ActivityScoreFactor(BaseModel):
    """One explainable factor contributing to the score."""

    name: str
    score: float  # 0-100
    detail: str


class ActivityScoreResponse(BaseModel):
    """Explainable weather impact score for an activity."""

    activity: str
    score: int
    rating: str
    reasons: list[str] = []
    factors: list[ActivityScoreFactor] = []
    best_time: Optional[str] = None
