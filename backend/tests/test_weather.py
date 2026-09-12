"""Weather service and endpoint tests."""

import httpx
import pytest

from app.services import weather_service as weather_module
from app.services.cached_weather_service import cached_weather_service
from app.services.weather_service import WeatherService, WeatherProviderError
from tests.conftest import _mock_provider


@pytest.mark.asyncio
async def test_current_normalization(monkeypatch, provider_current_payload):
    """Provider payload is normalized into internal schema correctly."""
    _mock_provider(monkeypatch, provider_current_payload, {})
    service = WeatherService()
    result = await service.get_current(26.4499, 80.3319)

    assert result.current.temperature == 32.4
    assert result.current.feels_like == 36.1
    assert result.current.humidity == 71
    assert result.current.wind_speed == 12.5  # km/h preserved
    assert result.current.wind_direction_compass == "S"
    assert result.current.visibility == 12.0  # metres → km
    assert result.current.condition == "Partly cloudy"
    assert result.current.weather_code == 2
    assert result.current.is_day is True


@pytest.mark.asyncio
async def test_current_endpoint_success(client, monkeypatch, provider_current_payload):
    """GET /weather/current returns normalized data."""
    _mock_provider(monkeypatch, provider_current_payload, {})

    response = await client.get(
        "/weather/current?latitude=26.4499&longitude=80.3319"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["current"]["temperature"] == 32.4
    assert body["location"]["latitude"] == 26.4499


@pytest.mark.asyncio
async def test_current_endpoint_cached_second_call(
    client, monkeypatch, provider_current_payload
):
    """Second call is served from cache (provider called once)."""
    calls = {"count": 0}

    async def fake_request(self, url, params):
        calls["count"] += 1
        return provider_current_payload

    monkeypatch.setattr(weather_module.WeatherService, "_request", fake_request)

    await client.get("/weather/current?latitude=26.4499&longitude=80.3319")
    await client.get("/weather/current?latitude=26.4499&longitude=80.3319")
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_forecast_endpoint_success(client, monkeypatch, provider_forecast_payload):
    """GET /weather/forecast returns daily and hourly arrays."""
    _mock_provider(monkeypatch, {}, provider_forecast_payload)

    response = await client.get(
        "/weather/forecast?latitude=26.4499&longitude=80.3319&days=2"
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["forecast"]) == 2
    assert body["forecast"][1]["precipitation_probability"] == 75
    assert len(body["hourly"]) >= 3


@pytest.mark.asyncio
async def test_provider_timeout_maps_to_503(client, monkeypatch):
    """Provider timeout becomes a clean 503, never fabricated data."""

    class _FailingAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, *args, **kwargs):
            raise httpx.TimeoutException("timeout")

    class _FakeHTTPX:
        AsyncClient = _FailingAsyncClient
        TimeoutException = httpx.TimeoutException

    # Patch only the weather module's httpx reference, not the test client's.
    monkeypatch.setattr(weather_module, "httpx", _FakeHTTPX)
    response = await client.get("/weather/current?latitude=26.4499&longitude=80.3319")
    assert response.status_code == 503
    assert "error" in response.json()


@pytest.mark.asyncio
async def test_provider_http_error_maps_to_503(client, monkeypatch):
    """Provider HTTP error becomes a clean 503."""

    async def error_request(self, url, params):
        raise WeatherProviderError("Provider exploded")

    monkeypatch.setattr(weather_module.WeatherService, "_request", error_request)
    response = await client.get("/weather/current?latitude=26.4499&longitude=80.3319")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_invalid_coordinates_rejected(client):
    """Out-of-range coordinates are rejected with 400."""
    response = await client.get("/weather/current?latitude=999&longitude=80.3319")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_days_out_of_range_rejected(client):
    """Forecast days outside provider bounds are rejected."""
    response = await client.get(
        "/weather/forecast?latitude=26.4499&longitude=80.3319&days=99"
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_geocode_success(client, monkeypatch):
    """Location search returns geocoding results."""

    async def fake_request(self, url, params):
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

    monkeypatch.setattr(weather_module.WeatherService, "_request", fake_request)
    response = await client.get("/weather/search?query=Kanpur")
    assert response.status_code == 200
    results = response.json()["results"]
    assert results and results[0]["name"] == "Kanpur"
