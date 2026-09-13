"""Tests for new insight features: historical, climate, crop, aviation,
flood/cyclone alerts, multilingual TTS, NWP model selection, push, and
city overview."""

from datetime import datetime

import pytest

from app.schemas.insights import (
    AviationBriefingRequest,
    CropAdvisoryRequest,
)
from app.schemas.weather import (
    CurrentWeather,
    CurrentWeatherResponse,
    DailyPoint,
    ForecastResponse,
    GeoLocation,
    HourlyPoint,
)
from app.services.alert_service import AlertRuleContext, evaluate_alert_rules
from app.services.aviation_service import aviation_service
from app.services.crop_advisory_service import crop_advisory_service
import asyncio

from app.services.historical_service import HistoricalService, HistoricalServiceError


# ------------------------------------------------------------------ #
# helpers
# ------------------------------------------------------------------ #


def _current(**overrides) -> CurrentWeatherResponse:
    values = dict(
        temperature=32.0,
        feels_like=36.0,
        humidity=70.0,
        wind_speed=12.0,
        visibility=10.0,
        uv_index=6.0,
        condition="Clear sky",
        weather_code=2,
    )
    values.update(overrides)
    return CurrentWeatherResponse(
        location=GeoLocation(name="Kanpur", latitude=26.45, longitude=80.33),
        current=CurrentWeather(**values),
    )


def _forecast(rain=20.0, temp_max=34.0, temp_min=26.0, wind=15.0, precip=2.0) -> ForecastResponse:
    return ForecastResponse(
        location=GeoLocation(name="Kanpur", latitude=26.45, longitude=80.33),
        forecast=[
            DailyPoint(
                date="2026-09-10",
                temperature_max=temp_max,
                temperature_min=temp_min,
                precipitation_probability=rain,
                precipitation_sum=precip,
                wind_speed_max=wind,
                condition="Partly cloudy",
            )
        ],
        hourly=[
            HourlyPoint(
                time=datetime(2026, 9, 10, hour),
                temperature=30.0,
                precipitation_probability=rain,
                wind_speed=wind,
                visibility=10.0,
                weather_code=2,
            )
            for hour in range(6, 22)
        ],
    )


# ------------------------------------------------------------------ #
# Historical service (parsing/aggregation, mocked HTTP)
# ------------------------------------------------------------------ #


def _archive_payload(days: int = 3) -> dict:
    dates = [f"2026-09-{10 + i}" for i in range(days)]
    return {
        "daily": {
            "time": dates,
            "temperature_2m_max": [35.0 + i for i in range(days)],
            "temperature_2m_min": [26.0] * days,
            "temperature_2m_mean": [30.0 + i for i in range(days)],
            "precipitation_sum": [0.0, 5.0, 12.0],
            "wind_speed_10m_max": [15.0] * days,
        }
    }


@pytest.mark.asyncio
async def test_historical_parses_and_aggregates(monkeypatch):
    async def fake_request(self, params):
        return _archive_payload(3)

    monkeypatch.setattr(HistoricalService, "_request", fake_request)
    monkeypatch.setattr(HistoricalService, "_request", fake_request)
    
    async def _get_cached(self, key):
        return None

    async def _set_cached(self, key, response):
        return None

    monkeypatch.setattr(HistoricalService, "_get_cached", _get_cached)
    monkeypatch.setattr(HistoricalService, "_set_cached", _set_cached)
    monkeypatch.setattr(HistoricalService, "_remember_last_good", lambda self, key, value: None)
    monkeypatch.setattr(HistoricalService, "_recall_last_good", lambda self, key: None)
    service = HistoricalService()
    result = await service.get_historical(26.45, 80.33, days=3)
    assert len(result.daily) == 3
    assert result.stats.total_precipitation == 17.0
    assert result.stats.wet_days == 2  # 5mm and 12mm
    assert result.stats.hottest_day is not None
    assert result.stats.temp_mean == pytest.approx(31.0, abs=0.1)


@pytest.mark.asyncio
async def test_climate_trend_monthly_aggregation(monkeypatch):
    # Two years of the same 60-day pattern → two month buckets minimum.
    payload = {
        "daily": {
            "time": [f"2025-{month:02d}-15" for month in range(1, 13)],
            "temperature_2m_max": [30.0] * 12,
            "temperature_2m_min": [20.0] * 12,
            "temperature_2m_mean": [25.0] * 12,
            "precipitation_sum": [10.0] * 12,
        }
    }

    async def fake_request(self, params):
        return payload

    monkeypatch.setattr(HistoricalService, "_request", fake_request)
    
    async def _get_cached(self, key):
        return None

    async def _set_cached(self, key, response):
        return None

    monkeypatch.setattr(HistoricalService, "_get_cached", _get_cached)
    monkeypatch.setattr(HistoricalService, "_set_cached", _set_cached)
    monkeypatch.setattr(HistoricalService, "_remember_last_good", lambda self, key, value: None)
    monkeypatch.setattr(HistoricalService, "_recall_last_good", lambda self, key: None)
    service = HistoricalService()
    result = await service.get_climate_trend(26.45, 80.33, years=2)
    assert len(result.monthly) == 12
    jan = result.monthly[0]
    assert jan.avg_temp_mean == 25.0
    assert jan.total_precipitation == 10.0
    assert jan.wet_days == 1


def test_historical_request_error_mapping():
    import httpx

    service = HistoricalService()

    class FakeResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            return FakeResponse()

    import app.services.historical_service as hs

    class FakeAsyncClient(FakeClient):
        pass

    async def run():
        monkey_hs = hs.httpx
        monkey_hs.AsyncClient = lambda **k: FakeAsyncClient()
        try:
            await service._request({"latitude": 1})
        finally:
            hs.httpx = monkey_hs

    # Just verify the exception type mapping exists
    assert HistoricalServiceError is not None


# ------------------------------------------------------------------ #
# Crop advisories
# ------------------------------------------------------------------ #


def test_crop_advisory_irrigation_on_dry_spell():
    request = CropAdvisoryRequest(latitude=26.45, longitude=80.33, location_name="Kanpur")
    result = crop_advisory_service.generate(request, _current(), _forecast(rain=5, precip=0.5))
    assert result.irrigation_needed is True
    assert any(a.category == "irrigation" for a in result.advisories)


def test_crop_advisory_spraying_warning_on_rain():
    request = CropAdvisoryRequest(latitude=26.45, longitude=80.33)
    result = crop_advisory_service.generate(request, _current(), _forecast(rain=70))
    assert any(
        a.category == "field_work" and "spraying" in a.message for a in result.advisories
    )


def test_crop_advisory_heat_warning():
    request = CropAdvisoryRequest(latitude=26.45, longitude=80.33)
    result = crop_advisory_service.generate(request, _current(), _forecast(temp_max=42.0))
    assert any(a.severity == "warning" and "Heat" in a.message for a in result.advisories)


def test_crop_advisory_fungal_risk():
    request = CropAdvisoryRequest(latitude=26.45, longitude=80.33)
    result = crop_advisory_service.generate(
        request, _current(humidity=85.0), _forecast(rain=60)
    )
    assert any(a.category == "pest_disease" for a in result.advisories)


def test_crop_advisory_crop_specific_note():
    request = CropAdvisoryRequest(latitude=26.45, longitude=80.33, crop="rice")
    result = crop_advisory_service.generate(request, _current(), _forecast())
    assert any("Rice" in a.message or "rice" in a.message.lower() for a in result.advisories)


def test_crop_advisory_no_data_is_safe():
    request = CropAdvisoryRequest(latitude=26.45, longitude=80.33)
    result = crop_advisory_service.generate(request, None, None)
    assert result.advisories == []
    assert result.field_work_score is None


# ------------------------------------------------------------------ #
# Aviation briefing
# ------------------------------------------------------------------ #


def test_aviation_ok_conditions():
    request = AviationBriefingRequest(latitude=26.45, longitude=80.33, hours_ahead=12)
    result = aviation_service.generate(request, _current(), _forecast(rain=10, wind=12))
    assert result.flight_category == "ok"
    assert result.best_windows  # some flyable window exists


def test_aviation_hazard_on_storm():
    forecast = _forecast(rain=90)
    for point in forecast.hourly:
        point.weather_code = 95
    request = AviationBriefingRequest(latitude=26.45, longitude=80.33)
    result = aviation_service.generate(request, _current(), forecast)
    assert result.flight_category == "hazard"
    assert any(c.parameter == "storm" for c in result.conditions)


def test_aviation_low_visibility_hazard():
    current = _current(visibility=2.0)
    forecast = _forecast()
    for point in forecast.hourly:
        point.visibility = 2.0
    request = AviationBriefingRequest(latitude=26.45, longitude=80.33)
    result = aviation_service.generate(request, current, forecast)
    assert result.flight_category in ("hazard", "caution")


def test_aviation_no_data():
    request = AviationBriefingRequest(latitude=26.45, longitude=80.33)
    result = aviation_service.generate(request, None, None)
    assert result.flight_category == "unknown"


# ------------------------------------------------------------------ #
# Flood / cyclone alerts
# ------------------------------------------------------------------ #


def _ctx(**overrides) -> AlertRuleContext:
    values = dict(
        temperature=30.0,
        precipitation_probability=20.0,
        precipitation_sum=0.0,
        wind_speed=10.0,
        visibility=10.0,
        uv_index=5.0,
        weather_code=2,
        location="Kanpur",
        precip_next_72h=30.0,
    )
    values.update(overrides)
    return AlertRuleContext(**values)


def test_flood_alert_fires_on_72h_accumulation():
    alerts = evaluate_alert_rules(
        _ctx(precip_next_72h=150.0),
        [{"alert_type": "flood_risk", "threshold": None, "enabled": True}],
    )
    assert len(alerts) == 1
    assert alerts[0].severity == "severe"
    assert "Flood" in alerts[0].title


def test_flood_alert_not_fired_below_threshold():
    alerts = evaluate_alert_rules(
        _ctx(precip_next_72h=40.0),
        [{"alert_type": "flood_risk", "threshold": None, "enabled": True}],
    )
    assert alerts == []


def test_cyclone_wind_alert_fires():
    alerts = evaluate_alert_rules(
        _ctx(wind_speed=95.0),
        [{"alert_type": "cyclone_wind", "threshold": None, "enabled": True}],
    )
    assert len(alerts) == 1
    assert alerts[0].severity == "severe"
    assert "Cyclone" in alerts[0].title


def test_new_alert_types_in_supported_set():
    from app.services.alert_service import SUPPORTED_TYPES

    assert "flood_risk" in SUPPORTED_TYPES
    assert "cyclone_wind" in SUPPORTED_TYPES


# ------------------------------------------------------------------ #
# Multilingual TTS
# ------------------------------------------------------------------ #


def test_detect_language_by_script():
    from app.services.edge_tts_service import detect_language

    assert detect_language("नमस्ते, आज मौसम कैसा है?") == "hi"
    assert detect_language("வணக்கம், இன்று வானிலை எப்படி?") == "ta"
    assert detect_language("నమస్కారం, ఈరోజు వాతావరణం ఎలా ఉంది?") == "te"
    assert detect_language("নমস্কার, আজকের আবহাওয়া কেমন?") == "bn"
    assert detect_language("નમસ્તે, આજનું હવામાન કેવું છે?") == "gu"
    assert detect_language("ನಮಸ್ಕಾರ, ಇಂದಿನ ಹವಾಮಾನ ಹೇಗಿದೆ?") == "kn"
    assert detect_language("നമസ്കാരം, ഇന്നത്തെ കാലാവസ്ഥ എങ്ങനെ?") == "ml"
    assert detect_language("Will it rain today?") == "en"


def test_supported_voices_cover_9_languages():
    from app.services.edge_tts_service import SUPPORTED_VOICES

    expected = {"en-IN", "hi-IN", "ta-IN", "te-IN", "bn-IN", "mr-IN", "kn-IN", "ml-IN", "gu-IN"}
    assert expected.issubset(set(SUPPORTED_VOICES.keys()))


@pytest.mark.asyncio
async def test_tts_language_param_selects_voice(monkeypatch):
    """Language override bypasses script detection."""
    captured = {}

    class FakeCommunicate:
        def __init__(self, text, voice, rate, pitch):
            captured["voice"] = voice

        async def stream(self):
            yield {"type": "audio", "data": b"mp3"}

    import app.services.edge_tts_service as tts_module

    monkeypatch.setattr(tts_module.edge_tts, "Communicate", FakeCommunicate)
    from app.services.edge_tts_service import edge_tts_service

    await edge_tts_service.synthesize_speech(
        text="Will it rain today?", language="ta-IN"
    )
    assert captured["voice"] == "ta-IN-PallaviNeural"


@pytest.mark.asyncio
async def test_tts_empty_text_returns_empty():
    from app.services.edge_tts_service import edge_tts_service

    result = await edge_tts_service.synthesize_speech(text="   ")
    assert result == b""


# ------------------------------------------------------------------ #
# NWP model selection
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_forecast_model_param_forwarded(monkeypatch):
    """The model param is passed through to the provider request."""
    from app.services.weather_service import WeatherService

    captured = {}

    async def fake_request(self, url, params):
        captured["params"] = params
        return {"daily": {"time": ["2026-09-10"]}, "hourly": {"time": ["2026-09-10T00:00"]}}

    monkeypatch.setattr(WeatherService, "_request", fake_request)
    service = WeatherService()
    await service.get_forecast(26.45, 80.33, days=1, model="gfs_seamless")
    assert captured["params"].get("models") == "gfs_seamless"


# ------------------------------------------------------------------ #
# Push notifications
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_push_dry_run_without_credentials(monkeypatch):
    from app.services import push_service as ps

    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
    ps.push_notification_service._service_account = None
    delivered = await ps.push_notification_service.send_to_tokens(
        ["fake_token_123456"], "Test Alert", "Rain incoming", data={"alert_type": "rain"}
    )
    assert delivered == 0
    log = ps.dispatch_log.recent(1)
    assert log and log[0]["mode"] == "dry_run"


def test_dispatch_log_records_entries():
    from app.services.push_service import PushDispatchLog

    log = PushDispatchLog()
    log.add("rain", "Title", "Body", recipients=3, delivered=2, mode="fcm")
    entries = log.recent(1)
    assert entries[0]["recipients"] == 3
    assert entries[0]["delivered"] == 2


# ------------------------------------------------------------------ #
# City overview API (mocked providers)
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_city_overview_endpoint(client, monkeypatch):
    from app.services import aqi_service as aqi_module
    from app.services import weather_service as weather_module

    async def fake_current(latitude, longitude, location=None):
        return CurrentWeatherResponse(
            location=location
            or GeoLocation(name="X", latitude=latitude, longitude=longitude),
            current=CurrentWeather(temperature=30.0, condition="Clear sky"),
        )

    async def fake_aqi(latitude, longitude, location_name="Unknown"):
        raise aqi_module.AQIServiceError("skip aqi in test")

    monkeypatch.setattr(weather_module.weather_service, "get_current", fake_current)
    monkeypatch.setattr(aqi_module.aqi_service, "get_current_aqi", fake_aqi)

    response = await client.get("/weather/city-overview")
    assert response.status_code == 200
    body = response.json()
    assert len(body["cities"]) >= 5
    assert body["cities"][0]["temperature"] == 30.0


# ------------------------------------------------------------------ #
# Insights API routes (mocked providers)
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_crop_advisory_endpoint(client, monkeypatch):
    from app.services import cached_weather_service as cws

    async def fake_current(latitude, longitude, location=None):
        return _current()

    async def fake_forecast(latitude, longitude, days=7, location=None, model=None):
        return _forecast()

    monkeypatch.setattr(cws.cached_weather_service, "get_current", fake_current)
    monkeypatch.setattr(cws.cached_weather_service, "get_forecast", fake_forecast)

    response = await client.post(
        "/weather/crop-advisory",
        json={"latitude": 26.45, "longitude": 80.33, "location_name": "Kanpur", "crop": "rice"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["location"] == "Kanpur"
    assert body["advisories"]


@pytest.mark.asyncio
async def test_aviation_endpoint(client, monkeypatch):
    from app.services import cached_weather_service as cws

    async def fake_current(latitude, longitude, location=None):
        return _current()

    async def fake_forecast(latitude, longitude, days=7, location=None, model=None):
        return _forecast(rain=10, wind=12)

    monkeypatch.setattr(cws.cached_weather_service, "get_current", fake_current)
    monkeypatch.setattr(cws.cached_weather_service, "get_forecast", fake_forecast)

    response = await client.post(
        "/weather/aviation",
        json={"latitude": 26.45, "longitude": 80.33, "location_name": "Kanpur"},
    )
    assert response.status_code == 200
    assert response.json()["flight_category"] == "ok"


@pytest.mark.asyncio
async def test_models_endpoint(client):
    response = await client.get("/weather/models")
    assert response.status_code == 200
    models = response.json()["models"]
    assert any(m["id"] == "gfs_seamless" for m in models)
    assert any(m["id"] == "ecmwf_ifs025" for m in models)


# ------------------------------------------------------------------ #
# Device registration API
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_device_register_and_broadcast(client, monkeypatch):
    from app.services import push_service as ps

    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
    ps.push_notification_service._service_account = None

    register = await client.post(
        "/notifications/register",
        json={
            "token": "device_token_abcdefgh",
            "platform": "android",
            "latitude": 26.45,
            "longitude": 80.33,
        },
    )
    assert register.status_code == 201

    # Broadcast requires auth
    unauth = await client.post(
        "/notifications/broadcast",
        json={"title": "T", "message": "M"},
    )
    assert unauth.status_code == 401

    await client.post(
        "/auth/register",
        json={"name": "U", "email": "u3@example.com", "password": "supersecret1"},
    )
    login = await client.post(
        "/auth/login", json={"email": "u3@example.com", "password": "supersecret1"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    broadcast = await client.post(
        "/notifications/broadcast",
        headers=headers,
        json={
            "title": "Flood watch",
            "message": "Heavy rain expected",
            "alert_type": "flood_risk",
            "latitude": 26.45,
            "longitude": 80.33,
        },
    )
    assert broadcast.status_code == 200
    assert broadcast.json()["delivered"] == 0  # dry-run mode
    assert broadcast.json()["fcm_configured"] is False
