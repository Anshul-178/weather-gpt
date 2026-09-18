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
    """OpenWeather payload is normalized into internal schema correctly."""
    _mock_provider(monkeypatch, provider_current_payload, {})
    service = WeatherService()
    result = await service.get_current(26.4499, 80.3319)

    assert result.location.name == "Kanpur"
    assert result.current.temperature == 32.4
    assert result.current.feels_like == 36.1
    assert result.current.humidity == 71
    assert result.current.wind_speed == pytest.approx(12.5, abs=0.01)  # m/s → km/h
    assert result.current.wind_direction_compass == "S"
    assert result.current.visibility == 12.0  # metres → km
    assert result.current.condition == "scattered clouds"
    assert result.current.weather_code == 2  # OpenWeather 802 → WMO 2
    assert result.current.is_day is True


@pytest.mark.asyncio
async def test_openweathermap_requires_api_key(monkeypatch):
    """Missing OpenWeather key fails clearly instead of calling the provider."""
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
        headers = {}  # httpx responses always carry headers

        def raise_for_status(self):
            request = httpx.Request(
                "GET", "https://api.openweathermap.org/data/2.5/weather"
            )
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
    with pytest.raises(WeatherRateLimitError) as exc_info:
        await WeatherService()._request(
            "https://api.openweathermap.org/data/2.5/weather", {}
        )
    assert exc_info.value.retry_after_seconds is None
    assert exc_info.value.from_cooldown is False


@pytest.mark.asyncio
async def test_weather_provider_follows_redirects(monkeypatch):
    """Provider redirects are followed instead of being returned as 503s."""

    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class _Client:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

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
    result = await WeatherService()._request(
        "https://api.openweathermap.org/data/2.5/weather", {}
    )

    assert result == {"ok": True}
    assert captured["follow_redirects"] is True


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
        assert "/direct" in url
        assert params["q"] == "Kanpur"
        return [
            {
                "name": "Kanpur",
                "lat": 26.4499,
                "lon": 80.3319,
                "country": "IN",
                "state": "Uttar Pradesh",
            }
        ]

    monkeypatch.setattr(weather_module.WeatherService, "_request", fake_request)
    response = await client.get("/weather/search?query=Kanpur")
    assert response.status_code == 200
    results = response.json()["results"]
    assert results and results[0]["name"] == "Kanpur"


# ------------------------------------------------------------------ #
# Provider 429 cooldown regression tests
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_cooldown_does_not_extend_under_traffic(monkeypatch):
    """Requests DURING a cooldown must not extend it (self-extension bug)."""
    import time as time_module

    from app.services import cached_weather_service as cached_module

    monkeypatch.setattr(cached_module, "_PROVIDER_RATE_LIMITED_UNTIL", 0.0)

    calls = {"n": 0}

    async def rate_limited(*args, **kwargs):
        calls["n"] += 1
        raise WeatherRateLimitError("provider rate limited")

    monkeypatch.setattr(weather_module.weather_service, "get_current", rate_limited)

    # First call hits the provider and starts the cooldown.
    with pytest.raises(WeatherRateLimitError):
        await cached_weather_service.get_current(26.4499, 80.3319)
    assert calls["n"] == 1
    first_until = cached_module._PROVIDER_RATE_LIMITED_UNTIL
    assert first_until > time_module.monotonic()  # cooldown is active

    # Steady traffic during the cooldown: provider is not consulted again
    # and the deadline must stay put. (Old code restarted the 60s window on
    # every request, so it never expired.)
    for _ in range(5):
        with pytest.raises(WeatherRateLimitError):
            await cached_weather_service.get_current(26.4499, 80.3319)
    assert calls["n"] == 1
    assert cached_module._PROVIDER_RATE_LIMITED_UNTIL == first_until


@pytest.mark.asyncio
async def test_cooldown_recovers_and_retries_provider(monkeypatch):
    """After the cooldown expires the provider is consulted again."""
    import time as time_module

    from app.services import cached_weather_service as cached_module

    monkeypatch.setattr(cached_module, "_PROVIDER_RATE_LIMITED_UNTIL", 0.0)

    calls = {"n": 0}

    async def rate_limited(*args, **kwargs):
        calls["n"] += 1
        raise WeatherRateLimitError("provider rate limited")

    monkeypatch.setattr(weather_module.weather_service, "get_current", rate_limited)

    with pytest.raises(WeatherRateLimitError):
        await cached_weather_service.get_current(26.4499, 80.3319)
    assert calls["n"] == 1

    # Force the cooldown into the past (expired).
    monkeypatch.setattr(
        cached_module, "_PROVIDER_RATE_LIMITED_UNTIL", time_module.monotonic() - 1
    )
    with pytest.raises(WeatherRateLimitError):
        await cached_weather_service.get_current(26.4499, 80.3319)
    assert calls["n"] == 2  # provider consulted again after expiry


@pytest.mark.asyncio
async def test_cooldown_honors_provider_retry_after(monkeypatch):
    """Provider Retry-After extends the cooldown, capped at a sane maximum."""
    import time as time_module

    from app.services import cached_weather_service as cached_module

    monkeypatch.setattr(cached_module, "_PROVIDER_RATE_LIMITED_UNTIL", 0.0)

    async def rate_limited(*args, **kwargs):
        raise WeatherRateLimitError("provider rate limited", retry_after_seconds=120)

    monkeypatch.setattr(weather_module.weather_service, "get_current", rate_limited)
    with pytest.raises(WeatherRateLimitError):
        await cached_weather_service.get_current(26.4499, 80.3319)

    remaining = cached_module._PROVIDER_RATE_LIMITED_UNTIL - time_module.monotonic()
    # Default cooldown is 60s; provider asked 120s -> honored.
    assert 115 <= remaining <= 125

    # A pathological Retry-After is capped (_MAX_COOLDOWN_SECONDS = 300).
    monkeypatch.setattr(cached_module, "_PROVIDER_RATE_LIMITED_UNTIL", 0.0)

    async def rate_limited_huge(*args, **kwargs):
        raise WeatherRateLimitError(
            "provider rate limited", retry_after_seconds=100000
        )

    monkeypatch.setattr(
        weather_module.weather_service, "get_current", rate_limited_huge
    )
    with pytest.raises(WeatherRateLimitError):
        await cached_weather_service.get_current(26.4499, 80.3319)
    remaining = cached_module._PROVIDER_RATE_LIMITED_UNTIL - time_module.monotonic()
    assert remaining <= 301


@pytest.mark.asyncio
async def test_weather_service_parses_retry_after_header(monkeypatch):
    """HTTP 429 with Retry-After exposes retry_after_seconds on the error."""

    class _Response:
        status_code = 429
        headers = {"retry-after": "7"}

        def raise_for_status(self):
            request = httpx.Request(
                "GET", "https://api.openweathermap.org/data/2.5/weather"
            )
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
    with pytest.raises(WeatherRateLimitError) as exc_info:
        await WeatherService()._request(
            "https://api.openweathermap.org/data/2.5/weather", {}
        )
    assert exc_info.value.retry_after_seconds == 7.0
    assert exc_info.value.from_cooldown is False


@pytest.mark.asyncio
async def test_own_rate_limit_response_has_retry_after(client, monkeypatch):
    """The backend's own 429 carries a Retry-After header."""
    from app.config import settings
    from app.utils import rate_limit as rl_module

    rl_module._HITS.clear()

    # Exhaust the per-IP window (60 req/min default).
    for _ in range(settings.rate_limit_requests):
        response = await client.get("/health")
        assert response.status_code == 200

    response = await client.get("/health")
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1
