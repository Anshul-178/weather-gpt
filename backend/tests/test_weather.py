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
async def test_openweathermap_current_normalization(monkeypatch):
    """OpenWeather current data is normalized into the existing API schema."""
    payload = {
        "coord": {"lon": 80.3319, "lat": 26.4499},
        "weather": [{"id": 800, "main": "Clear", "description": "clear sky"}],
        "main": {
            "temp": 32.4,
            "feels_like": 36.1,
            "pressure": 1005,
            "humidity": 71,
        },
        "visibility": 12000,
        "wind": {"speed": 3.472222, "deg": 180},
        "clouds": {"all": 5},
        "sys": {"country": "IN", "sunrise": 1, "sunset": 9999999999},
        "dt": 1700000000,
        "name": "Kanpur",
    }

    monkeypatch.setattr(
        weather_module.settings,
        "weather_api_base_url",
        "https://api.openweathermap.org/data/2.5",
    )

    async def fake_request(self, url, params):
        assert url.endswith("/weather")
        assert params["units"] == "metric"
        return payload

    monkeypatch.setattr(weather_module.WeatherService, "_request", fake_request)
    result = await WeatherService().get_current(26.4499, 80.3319)

    assert result.location.name == "Kanpur"
    assert result.current.temperature == 32.4
    assert result.current.wind_speed == pytest.approx(12.5, abs=0.01)
    assert result.current.visibility == 12.0
    assert result.current.condition == "clear sky"


@pytest.mark.asyncio
async def test_openweathermap_forecast_normalization(monkeypatch):
    """OpenWeather 3-hour points are grouped into daily forecast points."""
    payload = {
        "city": {
            "name": "Kanpur",
            "coord": {"lon": 80.3319, "lat": 26.4499},
            "country": "IN",
        },
        "list": [
            {
                "dt_txt": "2026-09-14 09:00:00",
                "main": {"temp": 30.0, "feels_like": 31.0, "humidity": 60},
                "weather": [{"id": 800, "main": "Clear", "description": "clear sky"}],
                "wind": {"speed": 2.0},
                "pop": 0.1,
                "visibility": 10000,
            },
            {
                "dt_txt": "2026-09-14 12:00:00",
                "main": {"temp": 34.0, "feels_like": 36.0, "humidity": 55},
                "weather": [{"id": 801, "main": "Clouds", "description": "few clouds"}],
                "wind": {"speed": 3.0},
                "pop": 0.4,
                "rain": {"3h": 1.2},
                "visibility": 9000,
            },
            {
                "dt_txt": "2026-09-15 12:00:00",
                "main": {"temp": 33.0, "feels_like": 35.0, "humidity": 65},
                "weather": [{"id": 500, "main": "Rain", "description": "light rain"}],
                "wind": {"speed": 4.0},
                "pop": 0.7,
                "visibility": 8000,
            },
        ],
    }

    monkeypatch.setattr(
        weather_module.settings,
        "weather_api_base_url",
        "https://api.openweathermap.org/data/2.5",
    )

    async def fake_request(self, url, params):
        assert url.endswith("/forecast")
        return payload

    monkeypatch.setattr(weather_module.WeatherService, "_request", fake_request)
    result = await WeatherService().get_forecast(26.4499, 80.3319, days=2)

    assert len(result.forecast) == 2
    assert result.forecast[0].temperature_max == 34.0
    assert result.forecast[0].precipitation_probability == 40.0
    assert len(result.hourly) == 3


@pytest.mark.asyncio
async def test_openweathermap_requires_api_key(monkeypatch):
    """OpenWeather configuration fails clearly when no key is configured."""
    monkeypatch.setattr(
        weather_module.settings,
        "weather_api_base_url",
        "https://api.openweathermap.org/data/2.5",
    )
    monkeypatch.setattr(weather_module.settings, "weather_api_key", None)

    with pytest.raises(WeatherProviderError, match="WEATHER_API_KEY"):
        await WeatherService().get_current(26.4499, 80.3319)


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
