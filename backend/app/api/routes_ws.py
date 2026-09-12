"""WebSocket real-time weather endpoint.

Streaming live weather to connected clients — covers the real-time data
ingestion/dissemination requirement (WebSocket transport). Clients connect
with /ws/weather?latitude=..&longitude=.. and receive a JSON snapshot every
`interval` seconds. Clients can send {"latitude": .., "longitude": ..} to
re-target the stream, or "ping" to keep the connection alive.
"""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


class WeatherStreamHub:
    """Tracks connected sockets per coordinate for future fan-in fan-out."""

    def __init__(self) -> None:
        self._connections: dict[tuple[float, float], int] = {}

    def connect(self, key: tuple[float, float]) -> None:
        """Register a connection for a coordinate key."""
        self._connections[key] = self._connections.get(key, 0) + 1

    def disconnect(self, key: tuple[float, float]) -> None:
        """Deregister a connection for a coordinate key."""
        count = self._connections.get(key, 0) - 1
        if count <= 0:
            self._connections.pop(key, None)
        else:
            self._connections[key] = count

    @property
    def connection_count(self) -> int:
        """Total live sockets."""
        return sum(self._connections.values())


hub = WeatherStreamHub()


@router.websocket("/ws/weather")
async def weather_socket(websocket: WebSocket) -> None:
    """Stream live weather snapshots over WebSocket."""
    await websocket.accept()
    latitude = _float_param(websocket.query_params.get("latitude"))
    longitude = _float_param(websocket.query_params.get("longitude"))
    interval = _float_param(websocket.query_params.get("interval")) or 60.0
    interval = max(15.0, min(interval, 600.0))

    if latitude is None or longitude is None:
        await websocket.send_json(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "latitude and longitude query params are required",
                }
            }
        )
        await websocket.close(code=4400)
        return

    key = (round(latitude, 2), round(longitude, 2))
    hub.connect(key)
    logger.info("WS connected: %s (interval %.0fs)", key, interval)
    try:
        while True:
            snapshot = await _snapshot(latitude, longitude)
            if snapshot is not None:
                await websocket.send_text(json.dumps(snapshot))
            # Drain client messages non-blocking so re-target/ping works.
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=interval)
                latitude, longitude = _handle_client_message(message, latitude, longitude)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
    except WebSocketDisconnect:
        logger.info("WS disconnected: %s", key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("WS error for %s: %s", key, exc)
    finally:
        hub.disconnect(key)


def _handle_client_message(
    message: str, latitude: float, longitude: float
) -> tuple[float, float]:
    """Apply a client re-target or ping message; return updated coordinates."""
    text = (message or "").strip()
    if text == "ping":
        return latitude, longitude
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            new_lat = _float_param(payload.get("latitude"))
            new_lon = _float_param(payload.get("longitude"))
            if new_lat is not None and new_lon is not None:
                return new_lat, new_lon
    except ValueError:
        pass
    return latitude, longitude


async def _snapshot(latitude: float, longitude: float) -> Optional[dict]:
    """Build one broadcast payload; None when the provider is unavailable."""
    from app.services.cached_weather_service import cached_weather_service
    from app.services.weather_service import WeatherProviderError

    try:
        current = await cached_weather_service.get_current(latitude, longitude)
    except WeatherProviderError:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("WS snapshot failed: %s", exc)
        return None

    return {
        "type": "weather_update",
        "latitude": latitude,
        "longitude": longitude,
        "location": current.location.model_dump(mode="json"),
        "current": current.current.model_dump(mode="json"),
        "timestamp": current.timestamp.isoformat(),
    }


def _float_param(value) -> Optional[float]:
    """Parse a float query param, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
