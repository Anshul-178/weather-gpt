"""Weather service and endpoint tests."""

import asyncio

import httpx
import pytest

from app.services import weather_service as weather_module
from app.services.cached_weather_service import cached_weather_service
from app.services.weather_service import (
    WeatherProviderError,
    WeatherRateLimitError,
    WeatherService,
)
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
async def test_concurrent_cache_misses_share_one_provider_request(
    monkeypatch, provider_current_payload
):
    """Concurrent requests for one location must be coalesced."""
    calls = {"count": 0}

    async def fake_request(self, url, params):
        calls["count"] += 1
        await asyncio.sleep(0)
        return provider_current_payload

    monkeypatch.setattr(weather_module.WeatherService, "_request", fake_request)
    results = await asyncio.gather(
        cached_weather_service.get_current(26.4499, 80.3319),
        cached_weather_service.get_current(26.4499, 80.3319),
    )

    assert calls["count"] == 1
    assert results[0].current.temperature == results[1].current.temperature == 32.4


@pytest.mark.asyncio
async def test_provider_429_serves_last_good_weather(
    monkeypatch, provider_current_payload
):
    """An upstream 429 returns cached last-good weather instead of an error."""
    from app.services import cached_weather_service as cached_module
    from app.services.cache_service import cache_service

    monkeypatch.setattr(cached_module, "_PROVIDER_RATE_LIMITED_UNTIL", 0.0)
    _mock_provider(monkeypatch, provider_current_payload, {})
    first = await cached_weather_service.get_current(26.4499, 80.3319)
    await cache_service.clear_memory()

    async def rate_limited(*args, **kwargs):
        raise WeatherRateLimitError("provider rate limited")

    monkeypatch.setattr(weather_module.weather_service, "get_current", rate_limited)
    second = await cached_weather_service.get_current(26.4499, 80.3319)

    assert second.current.temperature == first.current.temperature == 32.4


@pytest.mark.asyncio
async def test_weather_provider_maps_429_to_rate_limit_error(monkeypatch):
    """HTTP 429 is classified separately so the cache can start cooldown."""

    class _Response:
        status_code = 429

        def raise_for_status(self):
            request = httpx.Request("GET", "https://api.open-meteo.com/v1/forecast")
            raise httpx.HTTPStatusError("rate limited", request=request, response=self)

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, *args, **kwargs):
            return _Response()

    class _FakeHTTPX:
        AsyncClient = _Client
        TimeoutException = httpx.TimeoutException
        HTTPStatusError = httpx.HTTPStatusError
        HTTPError = httpx.HTTPError

    monkeypatch.setattr(weather_module, "httpx", _FakeHTTPX)
    with pytest.raises(WeatherRateLimitError):
        await WeatherService()._request("https://api.open-meteo.com/v1/forecast", {})


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
