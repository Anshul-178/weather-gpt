"""Alert scheduler.

Background asyncio task that periodically evaluates alert rules for saved
preferences (technical.md §19). This is the hook point where triggered
alerts would be pushed via Firebase Cloud Messaging. Disabled by default;
enable with ALERT_SCHEDULER_ENABLED=true.
"""

import asyncio
from datetime import datetime

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def run_alert_scheduler() -> None:
    """Periodically check alert preferences until cancelled."""
    from app.database.database import AsyncSessionLocal
    from app.models.alert import AlertPreference
    from app.services.alert_service import alert_service
    from app.services.cached_weather_service import cached_weather_service
    from app.services.push_service import push_notification_service
    from app.services.weather_service import WeatherProviderError
    from sqlalchemy import select

    logger.info(
        "Alert scheduler started (interval %ss)", settings.alert_check_interval_seconds
    )
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(AlertPreference).where(
                        AlertPreference.enabled.is_(True)
                    )
                )
                preferences = list(result.scalars().all())

            by_coords: dict[tuple[float, float], list] = {}
            for pref in preferences:
                key = (round(pref.latitude, 2), round(pref.longitude, 2))
                by_coords.setdefault(key, []).append(pref)

            for (lat, lon), prefs in by_coords.items():
                try:
                    current = await cached_weather_service.get_current(lat, lon)
                    forecast = await cached_weather_service.get_forecast(lat, lon, days=1)
                    check = await alert_service.check_for_preferences(
                        prefs, current, forecast
                    )
                    if not check.alerts:
                        continue

                    # Dissemination: push triggered alerts to devices near
                    # these coordinates (FCM when configured, dry-run log
                    # otherwise). See services/push_service.py.
                    from app.database.database import AsyncSessionLocal as _Session

                    for alert in check.alerts:
                        logger.info(
                            "ALERT [%s] %s for %s: %s",
                            alert.severity,
                            alert.title,
                            alert.location,
                            alert.message,
                        )
                        try:
                            async with _Session() as push_db:
                                await push_notification_service.broadcast_alert(
                                    db=push_db,
                                    alert_type=alert.alert_type,
                                    title=alert.title,
                                    message=alert.message,
                                    latitude=lat,
                                    longitude=lon,
                                )
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "Push dispatch failed for %s: %s", alert.alert_type, exc
                            )
                except WeatherProviderError as exc:
                    logger.warning(
                        "Alert check skipped for %s,%s: %s", lat, lon, exc
                    )
        except asyncio.CancelledError:
            logger.info("Alert scheduler stopped")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Alert scheduler iteration failed: %s", exc)

        await asyncio.sleep(settings.alert_check_interval_seconds)


def start_alert_scheduler(app) -> None:
    """Start the scheduler task on app startup when enabled."""
    if not settings.alert_scheduler_enabled:
        logger.info("Alert scheduler disabled")
        return
    task = asyncio.create_task(run_alert_scheduler())
    app.state.alert_scheduler_task = task


def stop_alert_scheduler(app) -> None:
    """Cancel the scheduler task on shutdown."""
    task = getattr(app.state, "alert_scheduler_task", None)
    if task is not None:
        task.cancel()
