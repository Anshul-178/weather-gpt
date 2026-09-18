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
    """Force SQLite + OpenWeather for tests regardless of local .env."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test_weathergpt.db")
    # Use OpenWeather with a dummy key instead of whatever .env has.
    # Patch the cached settings object directly since lru_cache is already populated.
    import app.config
    monkeypatch.setattr(
        app.config.settings,
        "weather_api_base_url",
        "https://api.openweathermap.org/data/2.5",
    )
    monkeypatch.setattr(app.config.settings, "weather_api_key", "test-api-key")


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
    """Minimal OpenWeather current-weather payload."""
    return {
        "coord": {"lon": 80.3319, "lat": 26.4499},
        "weather": [{"id": 802, "main": "Clouds", "description": "scattered clouds"}],
        "main": {
            "temp": 32.4,
            "feels_like": 36.1,
            "pressure": 1005,
            "humidity": 71,
        },
        "visibility": 12000,
        "wind": {"speed": 3.472222, "deg": 180},
        "clouds": {"all": 50},
        "dt": 1700000000,
        "sys": {"country": "IN", "sunrise": 1, "sunset": 9999999999},
        "name": "Kanpur",
    }


@pytest.fixture
def provider_forecast_payload():
    """Minimal OpenWeather 5-day/3-hour forecast payload."""
    return {
        "city": {
            "name": "Kanpur",
            "coord": {"lon": 80.3319, "lat": 26.4499},
            "country": "IN",
        },
        "list": [
            {
                "dt_txt": "2026-09-10 09:00:00",
                "main": {"temp": 30.0, "feels_like": 33.0, "humidity": 60},
                "weather": [{"id": 802, "main": "Clouds", "description": "scattered clouds"}],
                "wind": {"speed": 3.5},
                "pop": 0.2,
                "visibility": 11000,
            },
            {
                "dt_txt": "2026-09-10 12:00:00",
                "main": {"temp": 35.0, "feels_like": 38.0, "humidity": 55},
                "weather": [{"id": 802, "main": "Clouds", "description": "scattered clouds"}],
                "wind": {"speed": 5.0},
                "pop": 0.2,
                "rain": {"3h": 0.0},
                "visibility": 10500,
            },
            {
                "dt_txt": "2026-09-10 18:00:00",
                "main": {"temp": 30.0, "feels_like": 32.0, "humidity": 75},
                "weather": [{"id": 500, "main": "Rain", "description": "light rain"}],
                "wind": {"speed": 6.0},
                "pop": 0.7,
                "rain": {"3h": 1.2},
                "visibility": 8000,
            },
            {
                "dt_txt": "2026-09-11 12:00:00",
                "main": {"temp": 33.0, "feels_like": 36.0, "humidity": 65},
                "weather": [{"id": 501, "main": "Rain", "description": "moderate rain"}],
                "wind": {"speed": 6.5},
                "pop": 0.75,
                "rain": {"3h": 3.0},
                "visibility": 7000,
            },
        ],
    }


def _mock_provider(monkeypatch, current_payload, forecast_payload):
    """Patch WeatherService._request to return canned payloads."""

    async def fake_request(self, url, params):
        if "geo/1.0" in url or "/direct" in url:
            return [
                {
                    "name": "Kanpur",
                    "lat": 26.4499,
                    "lon": 80.3319,
                    "country": "IN",
                    "state": "Uttar Pradesh",
                }
            ]
        if url.endswith("/forecast"):
            return forecast_payload
        return current_payload

    monkeypatch.setattr(
        weather_module.WeatherService, "_request", fake_request
    )
