"""Shared test fixtures."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database.base import Base
from app.database.database import engine, get_db
from app.main import app
from app.services import weather_service as weather_module
from app.services.cache_service import _MEMORY_CACHE
from app.services.cached_weather_service import _LAST_GOOD


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure a clean in-memory cache for every test."""
    _MEMORY_CACHE.clear()
    _LAST_GOOD.clear()
    yield
    _MEMORY_CACHE.clear()
    _LAST_GOOD.clear()


@pytest.fixture(autouse=True)
def _sqlite_url(monkeypatch):
    """Force SQLite + Open-Meteo for tests regardless of local .env."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test_weathergpt.db")
    # Use Open-Meteo (free, no key) instead of whatever .env has.
    # Patch the cached settings object directly since lru_cache is already populated.
    import app.config
    monkeypatch.setattr(app.config.settings, "weather_api_base_url", "https://api.open-meteo.com/v1")
    monkeypatch.setattr(app.config.settings, "weather_api_key", None)


@pytest_asyncio.fixture
async def client():
    """Async test client with tables created per test."""
    from app.database import database as db_module

    async def _override_get_db():
        async with db_module.AsyncSessionLocal() as session:
            yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def provider_current_payload():
    """Minimal Open-Meteo current-weather payload."""
    return {
        "current": {
            "time": "2026-09-10T12:00",
            "temperature_2m": 32.4,
            "relative_humidity_2m": 71,
            "apparent_temperature": 36.1,
            "is_day": 1,
            "precipitation": 0.0,
            "weather_code": 2,
            "cloud_cover": 50,
            "pressure_msl": 1005.2,
            "visibility": 12000.0,
            "wind_speed_10m": 12.5,
            "wind_direction_10m": 180,
        },
        "hourly": {
            "time": ["2026-09-10T12:00", "2026-09-10T13:00"],
            "uv_index": [7.0, 6.5],
        },
    }


@pytest.fixture
def provider_forecast_payload():
    """Minimal Open-Meteo forecast payload."""
    return {
        "daily": {
            "time": ["2026-09-10", "2026-09-11"],
            "weather_code": [2, 61],
            "temperature_2m_max": [35.0, 33.0],
            "temperature_2m_min": [27.0, 26.0],
            "sunrise": ["2026-09-10T06:00", "2026-09-11T06:00"],
            "sunset": ["2026-09-10T18:30", "2026-09-11T18:30"],
            "uv_index_max": [8.0, 6.0],
            "precipitation_sum": [0.0, 4.2],
            "precipitation_probability_max": [20, 75],
            "wind_speed_10m_max": [18.0, 22.0],
        },
        "hourly": {
            "time": [
                "2026-09-10T12:00",
                "2026-09-10T13:00",
                "2026-09-10T18:00",
                "2026-09-11T12:00",
            ],
            "temperature_2m": [32.0, 33.0, 30.0, 31.0],
            "apparent_temperature": [35.0, 36.0, 33.0, 34.0],
            "precipitation_probability": [10, 15, 70, 75],
            "precipitation": [0.0, 0.0, 1.2, 3.0],
            "weather_code": [2, 2, 61, 61],
            "relative_humidity_2m": [65, 66, 80, 82],
            "visibility": [11000.0, 10500.0, 8000.0, 7000.0],
            "wind_speed_10m": [12.0, 13.0, 20.0, 24.0],
            "uv_index": [7.0, 6.5, 2.0, 6.0],
        },
    }


def _mock_provider(monkeypatch, current_payload, forecast_payload):
    """Patch WeatherService._request to return canned payloads."""

    async def fake_request(self, url, params):
        if "geocoding" in url or "/search" in url:
            return {
                "results": [
                    {
                        "name": "Kanpur",
                        "latitude": 26.4499,
                        "longitude": 80.3319,
                        "country": "India",
                        "admin1": "Uttar Pradesh",
                    }
                ]
            }
        if params.get("daily"):
            return forecast_payload
        return current_payload

    monkeypatch.setattr(
        weather_module.WeatherService, "_request", fake_request
    )
