"""Alert API routes.

CRUD for alert preferences (auth required) plus a deterministic check
endpoint that evaluates rules against live weather data.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.database import get_db
from app.models.alert import AlertPreference
from app.models.user import User
from app.schemas.alert import (
    AlertCheckResponse,
    AlertPreferenceCreate,
    AlertPreferenceResponse,
    AlertPreferenceUpdate,
)
from app.services.alert_service import SUPPORTED_TYPES, alert_service
from app.services.auth_service import get_current_user, get_current_user_optional
from app.services.cached_weather_service import cached_weather_service
from app.services.weather_service import WeatherProviderError
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertPreferenceResponse])
async def list_alerts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AlertPreference]:
    """List the authenticated user's alert preferences."""
    result = await db.execute(
        select(AlertPreference)
        .where(AlertPreference.user_id == user.id)
        .order_by(AlertPreference.id)
    )
    return list(result.scalars().all())


@router.post(
    "",
    response_model=AlertPreferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_alert(
    body: AlertPreferenceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertPreference:
    """Create an alert preference."""
    if body.alert_type not in SUPPORTED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"alert_type must be one of: {', '.join(sorted(SUPPORTED_TYPES))}",
        )
    pref = AlertPreference(
        user_id=user.id,
        alert_type=body.alert_type,
        threshold=body.threshold,
        enabled=body.enabled,
        latitude=body.latitude,
        longitude=body.longitude,
        location_name=body.location_name,
    )
    db.add(pref)
    await db.commit()
    await db.refresh(pref)
    return pref


@router.patch("/{alert_id}", response_model=AlertPreferenceResponse)
async def update_alert(
    alert_id: int,
    body: AlertPreferenceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertPreference:
    """Update an alert preference (threshold/enabled)."""
    pref = await _get_owned(alert_id, user, db)
    if body.threshold is not None:
        pref.threshold = body.threshold
    if body.enabled is not None:
        pref.enabled = body.enabled
    await db.commit()
    await db.refresh(pref)
    return pref


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an alert preference."""
    pref = await _get_owned(alert_id, user, db)
    await db.delete(pref)
    await db.commit()


@router.post("/check", response_model=AlertCheckResponse)
async def check_alerts(
    latitude: float,
    longitude: float,
    location_name: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> AlertCheckResponse:
    """Evaluate alert rules against live weather for coordinates."""
    try:
        current = await cached_weather_service.get_current(latitude, longitude)
        forecast = await cached_weather_service.get_forecast(latitude, longitude, days=1)
    except WeatherProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    preferences: list[AlertPreference] = []
    if user is not None:
        result = await db.execute(
            select(AlertPreference).where(
                AlertPreference.user_id == user.id,
                AlertPreference.enabled.is_(True),
            )
        )
        preferences = list(result.scalars().all())
    return await alert_service.check_for_preferences(preferences, current, forecast)


async def _get_owned(
    alert_id: int, user: User, db: AsyncSession
) -> AlertPreference:
    """Fetch an alert preference owned by the user or raise 404."""
    result = await db.execute(
        select(AlertPreference).where(
            AlertPreference.id == alert_id, AlertPreference.user_id == user.id
        )
    )
    pref = result.scalars().first()
    if pref is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found"
        )
    return pref
