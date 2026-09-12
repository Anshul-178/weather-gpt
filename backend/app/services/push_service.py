"""Push notification service (Firebase Cloud Messaging).

Closes the dissemination gap: triggered alerts are delivered to registered
devices. Uses the FCM HTTP v1 API via `google-auth` service-account tokens
when FIREBASE_SERVICE_ACCOUNT_JSON is configured; otherwise it logs the
notification (dry-run mode) so the pipeline is testable without credentials.

Devices register their FCM tokens via POST /notifications/register.
"""

import json
import time
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.logging import get_logger

logger = get_logger(__name__)

FCM_SEND_URL_TEMPLATE = (
    "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
)


class PushDispatchLog:
    """In-memory record of dispatch attempts (queryable via /notifications/log)."""

    def __init__(self) -> None:
        self._entries: list[dict] = []

    def add(
        self,
        alert_type: str,
        title: str,
        message: str,
        recipients: int,
        delivered: int,
        mode: str,
    ) -> None:
        """Append one dispatch record."""
        self._entries.append(
            {
                "alert_type": alert_type,
                "title": title,
                "message": message,
                "recipients": recipients,
                "delivered": delivered,
                "mode": mode,
                "timestamp": datetime.now().isoformat(),
            }
        )
        # Bound memory in long-running processes.
        if len(self._entries) > 500:
            self._entries = self._entries[-500:]

    def recent(self, limit: int = 50) -> list[dict]:
        """Return the most recent dispatch records."""
        return list(reversed(self._entries[-limit:]))


dispatch_log = PushDispatchLog()


class PushNotificationService:
    """Sends triggered weather alerts to registered devices via FCM."""

    def __init__(self) -> None:
        self._credentials = None
        self._credentials_exppiry: float = 0.0

    @property
    def is_configured(self) -> bool:
        """True when Firebase credentials are present in the environment."""
        return bool(self._load_service_account())

    def _load_service_account(self) -> Optional[dict]:
        """Load the service-account JSON from env/file path, caching the result."""
        import os

        cached = getattr(self, "_service_account", None)
        if cached is not None:
            return cached
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        if not raw:
            return None
        try:
            self._service_account = json.loads(raw)
        except (TypeError, ValueError):
            # Support a file path instead of inline JSON.
            try:
                with open(raw, "r", encoding="utf-8") as handle:
                    self._service_account = json.load(handle)
            except (OSError, ValueError):
                logger.warning("FIREBASE_SERVICE_ACCOUNT_JSON is set but invalid")
                self._service_account = None
        return self._service_account

    async def _access_token(self) -> Optional[str]:
        """Mint an OAuth2 access token for the FCM HTTP v1 API."""
        service_account = self._load_service_account()
        if service_account is None:
            return None
        now = time.time()
        if self._credentials is not None and now < self._credentials_exppiry - 60:
            return self._credentials
        try:
            from google.oauth2 import service_account as sa_credentials

            credentials = sa_credentials.Credentials.from_service_account_info(
                service_account,
                scopes=["https://www.googleapis.com/auth/firebase.messaging"],
            )
            import google.auth.transport.requests as ga_requests

            request = ga_requests.Request()
            credentials.refresh(request)
            self._credentials = credentials.token
            self._credentials_exppiry = now + 3600
            return self._credentials
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not mint FCM access token: %s", exc)
            return None

    async def send_to_tokens(
        self,
        tokens: list[str],
        title: str,
        body: str,
        data: Optional[dict[str, str]] = None,
    ) -> int:
        """Send one notification to many device tokens; return delivery count."""
        if not tokens:
            return 0
        token = await self._access_token()
        project_id = (self._load_service_account() or {}).get("project_id")
        if token is None or not project_id:
            logger.info(
                "FCM dry-run: %d device(s) would receive '%s'", len(tokens), title
            )
            dispatch_log.add(
                alert_type=(data or {}).get("alert_type", "unknown"),
                title=title,
                message=body,
                recipients=len(tokens),
                delivered=0,
                mode="dry_run",
            )
            return 0

        url = FCM_SEND_URL_TEMPLATE.format(project_id=project_id)
        delivered = 0
        async with httpx.AsyncClient(timeout=10.0) as client:
            for device_token in tokens:
                payload = {
                    "message": {
                        "token": device_token,
                        "notification": {"title": title, "body": body},
                        "data": data or {},
                        "android": {"priority": "HIGH"},
                    }
                }
                try:
                    response = await client.post(
                        url,
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json; UTF-8",
                        },
                    )
                    if response.status_code < 400:
                        delivered += 1
                    else:
                        logger.warning(
                            "FCM send failed (HTTP %s) for a device token",
                            response.status_code,
                        )
                except httpx.HTTPError as exc:
                    logger.warning("FCM send network error: %s", exc)

        dispatch_log.add(
            alert_type=(data or {}).get("alert_type", "unknown"),
            title=title,
            message=body,
            recipients=len(tokens),
            delivered=delivered,
            mode="fcm",
        )
        return delivered

    async def broadcast_alert(
        self,
        db: AsyncSession,
        alert_type: str,
        title: str,
        message: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> int:
        """Send an alert to devices registered near the alert's coordinates.

        Matching is coarse (same city, ~0.5°) so city-wide alerts reach
        everyone monitoring that city. Falls back to all devices when the
        alert has no coordinates (global broadcast).
        """
        from app.models.device import DeviceToken

        query = select(DeviceToken).where(DeviceToken.enabled.is_(True))
        if latitude is not None and longitude is not None:
            query = query.where(
                DeviceToken.latitude.is_(None)
                | (
                    (
                        DeviceToken.latitude.between(latitude - 0.5, latitude + 0.5)
                    )
                    & (
                        DeviceToken.longitude.between(longitude - 0.5, longitude + 0.5)
                    )
                )
            )
        result = await db.execute(query)
        devices = list(result.scalars().all())
        tokens = [device.token for device in devices]
        return await self.send_to_tokens(
            tokens,
            title,
            message,
            data={"alert_type": alert_type, "lat": str(latitude), "lon": str(longitude)},
        )


push_notification_service = PushNotificationService()
