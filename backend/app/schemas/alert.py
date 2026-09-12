"""Pydantic schemas for alerts."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AlertPreferenceCreate(BaseModel):
    """POST /alerts request body."""

    alert_type: str = Field(..., max_length=50)
    threshold: Optional[float] = None
    enabled: bool = True
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    location_name: Optional[str] = Field(None, max_length=120)


class AlertPreferenceUpdate(BaseModel):
    """PATCH /alerts/{id} request body."""

    threshold: Optional[float] = None
    enabled: Optional[bool] = None


class AlertPreferenceResponse(BaseModel):
    """An alert preference record."""

    id: int
    alert_type: str
    threshold: Optional[float] = None
    enabled: bool
    latitude: float
    longitude: float
    location_name: Optional[str] = None

    model_config = {"from_attributes": True}


class TriggeredAlert(BaseModel):
    """A deterministically-triggered weather alert."""

    alert_type: str
    severity: str  # info | warning | severe
    title: str
    message: str
    observed_value: Optional[float] = None
    threshold: Optional[float] = None
    location: Optional[str] = None


class AlertCheckResponse(BaseModel):
    """POST /alerts/check response."""

    location: str
    alerts: list[TriggeredAlert] = []
    checked_at: datetime = Field(default_factory=datetime.now)
