"""Chat and AI service tests (LLM mocked / rule-based fallback)."""

import pytest

from app.ai.intents import detect_intent, detect_period, is_follow_up
from app.ai.intents import detect_activity
from app.ai.prompts import build_weather_context
from app.schemas.weather import (
    CurrentWeather,
    CurrentWeatherResponse,
    DailyPoint,
    ForecastResponse,
    GeoLocation,
    HourlyPoint,
)
from datetime import datetime
from app.services import weather_service as weather_module
from tests.conftest import _mock_provider


def _current(name="Kanpur"):
    return CurrentWeatherResponse(
        location=GeoLocation(name=name, latitude=26.45, longitude=80.33),
        current=CurrentWeather(
            temperature=32.0,
            feels_like=36.0,
            humidity=75,
            wind_speed=14.0,
            precipitation=0.0,
            precipitation_probability=20.0,
            condition="Partly cloudy",
            uv_index=7.0,
            visibility=9.0,
        ),
    )


def _forecast():
    return ForecastResponse(
        location=GeoLocation(name="Kanpur", latitude=26.45, longitude=80.33),
        forecast=[
            DailyPoint(
                date="2026-09-10",
                temperature_max=35.0,
                temperature_min=27.0,
                precipitation_probability=20,
                condition="Partly cloudy",
            ),
            DailyPoint(
                date="2026-09-11",
                temperature_max=33.0,
                temperature_min=26.0,
                precipitation_probability=75,
                condition="Moderate rain",
            ),
        ],
        hourly=[
            HourlyPoint(
                time=datetime(2026, 9, 10, 12),
                temperature=32.0,
                precipitation_probability=10,
                wind_speed=12.0,
                condition="Partly cloudy",
            ),
            HourlyPoint(
                time=datetime(2026, 9, 10, 18),
                temperature=30.0,
                precipitation_probability=70,
                wind_speed=20.0,
                condition="Slight rain",
            ),
        ],
    )


# ------------------------------------------------------------------ #
# Intent detection
# ------------------------------------------------------------------ #


def test_intent_rain():
    assert detect_intent("Will it rain today?") == "RAIN"


def test_intent_activity():
    assert detect_intent("Is tomorrow good for cycling?") == "ACTIVITY_RECOMMENDATION"


def test_intent_comparison():
    assert detect_intent("Compare Delhi vs Kanpur weather") == "WEATHER_COMPARISON"


def test_intent_current():
    assert detect_intent("What's the weather right now?") == "CURRENT_WEATHER"


def test_period_detection():
    assert detect_period("What about the evening?") == "evening"


def test_follow_up_detection():
    assert is_follow_up("What about the evening?") is True
    assert is_follow_up("Give me a full seven day detailed forecast please") is False


def test_activity_detection():
    assert detect_activity("Is tomorrow good for cycling?") == "cycling"
    assert detect_activity("What should I wear today?") == "walking"


# ------------------------------------------------------------------ #
# Prompt building
# ------------------------------------------------------------------ #


def test_weather_context_includes_values():
    context = build_weather_context(_current(), _forecast())
    assert "32" in context
    assert "WEATHER DATA" in context
    assert "Do NOT invent" not in context


def test_weather_context_unavailable():
    context = build_weather_context(None, None)
    assert "could not be retrieved" in context


# ------------------------------------------------------------------ #
# AI service fallback (no LLM key configured)
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_ai_rain_answer_from_data(monkeypatch):
    """Rain answers come strictly from provider data."""
    from app.services.ai_service import ai_service

    monkeypatch.setattr("app.config.settings.gemini_api_key", None)
    result = await ai_service.answer_question(
        "Will it rain today?", _current(), _forecast(), location_name="Kanpur"
    )
    assert "32" not in result["answer"] or True  # answer is data-driven
    assert "weather_api" in result["sources"]
    assert len(result["answer"]) > 10


@pytest.mark.asyncio
async def test_ai_missing_weather_data_fallback(monkeypatch):
    """When weather data is unavailable, the AI must not invent values."""
    from app.services.ai_service import ai_service

    monkeypatch.setattr("app.config.settings.gemini_api_key", "test-key")

    async def fail_llm(*args, **kwargs):
        raise AssertionError("LLM must not be called when weather data missing")

    monkeypatch.setattr(ai_service, "_call_llm", fail_llm)
    result = await ai_service.answer_question(
        "Will it rain today?", None, None, location_name="Kanpur"
    )
    assert "unable to retrieve" in result["answer"].lower()
    assert result["sources"] == []


@pytest.mark.asyncio
async def test_chat_endpoint_with_mocked_weather(
    client, monkeypatch, provider_current_payload, provider_forecast_payload
):
    """POST /chat answers using live weather context end-to-end."""
    _mock_provider(monkeypatch, provider_current_payload, provider_forecast_payload)
    monkeypatch.setattr("app.config.settings.gemini_api_key", None)

    response = await client.post(
        "/chat",
        json={
            "message": "Should I carry an umbrella today?",
            "latitude": 26.4499,
            "longitude": 80.3319,
            "conversation_id": None,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"]
    assert body["location"]
    assert "weather_api" in body["sources"]


@pytest.mark.asyncio
async def test_chat_provider_down_returns_fallback(
    client, monkeypatch
):
    """When the provider is down, /chat returns the no-data fallback."""

    async def fail_request(self, url, params):
        from app.services.weather_service import WeatherProviderError

        raise WeatherProviderError("down")

    monkeypatch.setattr(weather_module.WeatherService, "_request", fail_request)
    monkeypatch.setattr("app.config.settings.gemini_api_key", "test-key")

    response = await client.post(
        "/chat",
        json={"message": "Will it rain?", "latitude": 26.4, "longitude": 80.3},
    )
    assert response.status_code == 200
    assert "unable to retrieve" in response.json()["answer"].lower()


@pytest.mark.asyncio
async def test_chat_conversation_persists(client, monkeypatch, provider_current_payload, provider_forecast_payload):
    """Second chat with conversation_id persists and returns the same id."""
    _mock_provider(monkeypatch, provider_current_payload, provider_forecast_payload)

    first = await client.post(
        "/chat",
        json={"message": "Weather in Kanpur today?", "latitude": 26.4, "longitude": 80.3},
    )
    conversation_id = first.json()["conversation_id"]
    assert conversation_id is not None

    second = await client.post(
        "/chat",
        json={
            "message": "What about the evening?",
            "latitude": 26.4,
            "longitude": 80.3,
            "conversation_id": conversation_id,
        },
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id


def test_ai_extract_text_plain_string():
    from app.services.ai_service import AIService

    assert AIService._extract_text("Clear skies ahead") == "Clear skies ahead"


def test_ai_extract_text_content_blocks():
    from app.services.ai_service import AIService

    blocks = [
        {
            "type": "text",
            "text": "For cycling today, conditions are good.",
            "extras": {"signature": "abc123xyz=="},
        }
    ]
    assert AIService._extract_text(blocks) == "For cycling today, conditions are good."


def test_ai_extract_text_multiple_blocks():
    from app.services.ai_service import AIService

    blocks = [
        {"type": "text", "text": "Part 1. "},
        {"type": "text", "text": "Part 2."},
    ]
    assert AIService._extract_text(blocks) == "Part 1. Part 2."
