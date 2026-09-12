"""Pydantic schemas for push notifications."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DeviceRegisterRequest(BaseModel):
    """POST /notifications/register request body."""

    token: str = Field(..., min_length=10, max_length=4096)
    platform: Optional[str] = Field(None, max_length=20)  # android | ios | web
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)


class DeviceRegisterResponse(BaseModel):
    """POST /notifications/register response body."""

    registered: bool = True
    token_preview: str
    message: str


class DispatchLogEntry(BaseModel):
    """One alert dispatch record."""

    alert_type: str
    title: str
    message: str
    recipients: int
    delivered: int
    mode: str  # fcm | dry_run
    timestamp: datetime


class DispatchLogResponse(BaseModel):
    """GET /notifications/log response body."""

    fcm_configured: bool
    entries: list[DispatchLogEntry] = []


class BroadcastRequest(BaseModel):
    """POST /notifications/broadcast — manual alert dissemination (admin/demo)."""

    title: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=2000)
    alert_type: str = Field("general", max_length=50)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
