"""Push notification API routes.

Device registration, manual broadcast (demo/admin), and dispatch log.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.database import get_db
from app.models.device import DeviceToken
from app.models.user import User
from app.schemas.notifications import (
    BroadcastRequest,
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    DispatchLogResponse,
)
from app.services.auth_service import get_current_user, get_current_user_optional
from app.services.push_service import (
    dispatch_log,
    push_notification_service,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post(
    "/register",
    response_model=DeviceRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_device(
    body: DeviceRegisterRequest,
    user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> DeviceRegisterResponse:
    """Register (or refresh) a device push token for alert dissemination."""
    result = await db.execute(
        select(DeviceToken).where(DeviceToken.token == body.token)
    )
    device = result.scalars().first()
    if device is None:
        device = DeviceToken(
            token=body.token,
            platform=body.platform,
            latitude=body.latitude,
            longitude=body.longitude,
            user_id=user.id if user else None,
        )
        db.add(device)
    else:
        device.platform = body.platform or device.platform
        device.latitude = body.latitude if body.latitude is not None else device.latitude
        device.longitude = body.longitude if body.longitude is not None else device.longitude
        device.enabled = True
        if user is not None:
            device.user_id = user.id
    await db.commit()

    preview = body.token[:8] + "…" if len(body.token) > 8 else body.token
    return DeviceRegisterResponse(
        registered=True,
        token_preview=preview,
        message="Device registered for weather alert notifications.",
    )


@router.post("/unregister", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_device(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Disable notifications for a device token."""
    result = await db.execute(select(DeviceToken).where(DeviceToken.token == token))
    device = result.scalars().first()
    if device is not None:
        device.enabled = False
        await db.commit()


@router.get("/log", response_model=DispatchLogResponse)
async def get_dispatch_log(
    limit: int = 50,
    user: User = Depends(get_current_user),
) -> DispatchLogResponse:
    """Recent alert dispatch records (auth required)."""
    entries = dispatch_log.recent(limit=min(limit, 200))
    return DispatchLogResponse(
        fcm_configured=push_notification_service.is_configured,
        entries=entries,
    )


@router.post("/broadcast")
async def broadcast(
    body: BroadcastRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually disseminate an alert to matching devices (auth required).

    This is the dissemination entry point also used by the alert scheduler
    when rules fire automatically.
    """
    delivered = await push_notification_service.broadcast_alert(
        db=db,
        alert_type=body.alert_type,
        title=body.title,
        message=body.message,
        latitude=body.latitude,
        longitude=body.longitude,
    )
    return {
        "queued": True,
        "delivered": delivered,
        "fcm_configured": push_notification_service.is_configured,
    }


@router.get("/health")
async def notifications_health() -> dict:
    """Whether FCM credentials are configured on this deployment."""
    return {
        "fcm_configured": push_notification_service.is_configured,
    }
