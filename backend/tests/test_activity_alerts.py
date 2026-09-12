"""Activity engine and alert engine tests."""

from datetime import datetime

import pytest

from app.schemas.weather import (
    CurrentWeather,
    CurrentWeatherResponse,
    DailyPoint,
    ForecastResponse,
    GeoLocation,
    HourlyPoint,
)
from app.services.activity_engine import compute_activity_score, rating_for_score
from app.services.alert_service import (
    AlertRuleContext,
    evaluate_alert_rules,
)


def _weather(rain_prob=10.0, wind=10.0, temp=25.0, humidity=50.0, visibility=10.0, uv=4.0):
    hourly = [
        HourlyPoint(
            time=datetime(2026, 9, 10, hour),
            temperature=temp,
            precipitation_probability=rain_prob,
            wind_speed=wind,
            humidity=humidity,
            visibility=visibility,
            uv_index=uv,
        )
        for hour in range(6, 22)
    ]
    return CurrentWeatherResponse(
        location=GeoLocation(name="Kanpur", latitude=26.45, longitude=80.33),
        current=CurrentWeather(
            temperature=temp,
            feels_like=temp + 2,
            humidity=humidity,
            wind_speed=wind,
            precipitation_probability=rain_prob,
            visibility=visibility,
            uv_index=uv,
            condition="Clear sky",
        ),
    ), ForecastResponse(
        location=GeoLocation(name="Kanpur", latitude=26.45, longitude=80.33),
        forecast=[
            DailyPoint(date="2026-09-10", temperature_max=temp + 3, temperature_min=temp - 3,
                       precipitation_probability=rain_prob, condition="Clear sky")
        ],
        hourly=hourly,
    )


# ------------------------------------------------------------------ #
# Rating bands
# ------------------------------------------------------------------ #


def test_rating_bands():
    assert rating_for_score(95) == "Excellent"
    assert rating_for_score(70) == "Good"
    assert rating_for_score(50) == "Moderate"
    assert rating_for_score(30) == "Poor"
    assert rating_for_score(5) == "Very Poor"


# ------------------------------------------------------------------ #
# Activity scores
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_activity_score_excellent_conditions():
    current, forecast = _weather(rain_prob=5, wind=8, temp=24, humidity=45, visibility=12, uv=3)
    result = compute_activity_score("cycling", current, forecast)
    assert 80 <= result.score <= 100
    assert result.rating == "Excellent"
    assert result.factors
    assert result.best_time is not None


@pytest.mark.asyncio
async def test_activity_score_poor_conditions():
    current, forecast = _weather(rain_prob=90, wind=45, temp=41, humidity=90, visibility=1, uv=11)
    result = compute_activity_score("cycling", current, forecast)
    assert result.score <= 20
    assert result.rating in ("Poor", "Very Poor")
    assert any("unfavorable" in r for r in result.reasons)


@pytest.mark.asyncio
async def test_activity_score_is_explainable():
    current, forecast = _weather()
    result = compute_activity_score("running", current, forecast)
    for factor in result.factors:
        assert 0 <= factor.score <= 100
        assert factor.detail


def test_activity_score_missing_data():
    result = compute_activity_score("cycling", None, None)
    assert result.rating == "Unknown"


# ------------------------------------------------------------------ #
# Alert rules (deterministic)
# ------------------------------------------------------------------ #


def _ctx(rain=None, temp=None, wind=None, vis=None, uv=None, code=None):
    return AlertRuleContext(
        temperature=temp,
        precipitation_probability=rain,
        precipitation_sum=None,
        wind_speed=wind,
        visibility=vis,
        uv_index=uv,
        weather_code=code,
        location="Kanpur",
    )


def test_rain_alert_threshold_reached():
    alerts = evaluate_alert_rules(_ctx(rain=75), [{"alert_type": "rain", "threshold": None, "enabled": True}])
    assert len(alerts) == 1
    assert alerts[0].alert_type == "rain"


def test_rain_alert_threshold_not_reached():
    alerts = evaluate_alert_rules(_ctx(rain=40), [{"alert_type": "rain", "threshold": None, "enabled": True}])
    assert alerts == []


def test_rain_alert_boundary():
    """Boundary condition: exactly at threshold triggers."""
    alerts = evaluate_alert_rules(_ctx(rain=60), [{"alert_type": "rain", "threshold": None, "enabled": True}])
    assert len(alerts) == 1


def test_heat_alert_custom_threshold():
    alerts = evaluate_alert_rules(_ctx(temp=38), [{"alert_type": "extreme_heat", "threshold": 38.0, "enabled": True}])
    assert len(alerts) == 1


def test_thunderstorm_by_weather_code():
    alerts = evaluate_alert_rules(_ctx(code=95), [{"alert_type": "thunderstorm", "threshold": None, "enabled": True}])
    assert alerts and alerts[0].severity == "severe"


def test_disabled_alert_never_fires():
    alerts = evaluate_alert_rules(_ctx(rain=95), [{"alert_type": "rain", "threshold": None, "enabled": False}])
    assert alerts == []


def test_unknown_alert_type_ignored():
    alerts = evaluate_alert_rules(_ctx(rain=95), [{"alert_type": "zombie_apocalypse", "threshold": None, "enabled": True}])
    assert alerts == []


# ------------------------------------------------------------------ #
# Alert API (auth-protected CRUD)
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_alerts_require_auth(client):
    response = await client.get("/alerts")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_alert_crud_flow(client, monkeypatch):
    """Register → create → list → update → delete alert preferences."""

    async def fake_request(self, url, params):
        if "/search" in url:
            return {"results": []}
        return {}

    from app.services import weather_service as weather_module

    monkeypatch.setattr(weather_module.WeatherService, "_request", fake_request)

    register = await client.post(
        "/auth/register",
        json={"name": "Test User", "email": "test@example.com", "password": "supersecret1"},
    )
    assert register.status_code == 201

    login = await client.post(
        "/auth/login", json={"email": "test@example.com", "password": "supersecret1"}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/alerts",
        headers=headers,
        json={
            "alert_type": "rain",
            "threshold": 70,
            "enabled": True,
            "latitude": 26.45,
            "longitude": 80.33,
            "location_name": "Kanpur",
        },
    )
    assert create.status_code == 201
    alert_id = create.json()["id"]

    listed = await client.get("/alerts", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = await client.patch(
        f"/alerts/{alert_id}", headers=headers, json={"threshold": 90}
    )
    assert updated.status_code == 200
    assert updated.json()["threshold"] == 90

    deleted = await client.delete(f"/alerts/{alert_id}", headers=headers)
    assert deleted.status_code == 204

    listed_again = await client.get("/alerts", headers=headers)
    assert listed_again.json() == []


@pytest.mark.asyncio
async def test_invalid_alert_type_rejected(client):
    token = await _register_and_login(client)
    response = await client.post(
        "/alerts",
        headers=token,
        json={
            "alert_type": "not_a_type",
            "enabled": True,
            "latitude": 26.45,
            "longitude": 80.33,
        },
    )
    assert response.status_code == 400


async def _register_and_login(client) -> dict:
    """Helper returning auth headers for a fresh user."""
    await client.post(
        "/auth/register",
        json={"name": "Test User", "email": "test2@example.com", "password": "supersecret1"},
    )
    login = await client.post(
        "/auth/login", json={"email": "test2@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
