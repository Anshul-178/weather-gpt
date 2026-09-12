"""Unit conversion and validation tests."""

import pytest

from app.utils.units import (
    celsius_to_fahrenheit,
    fahrenheit_to_celsius,
    kelvin_to_celsius,
    metres_to_km,
    mph_to_kmh,
    wind_direction_to_compass,
)
from app.utils.validation import (
    validate_days,
    validate_latitude,
    validate_longitude,
    validate_place_name,
    validate_query,
    ValidationError,
)


def test_ms_to_kmh():
    from app.utils.units import ms_to_kmh, kmh_to_ms

    assert ms_to_kmh(10) == 36.0
    assert kmh_to_ms(36) == 10.0


def test_temperature_conversions():
    assert fahrenheit_to_celsius(212) == 100.0
    assert kelvin_to_celsius(373.15) == 100.0
    assert celsius_to_fahrenheit(100) == 212.0


def test_distance_and_speed():
    assert metres_to_km(12000) == 12.0
    assert mph_to_kmh(100) == 160.9


def test_none_safe_conversions():
    assert metres_to_km(None) is None
    assert mph_to_kmh(None) is None


def test_wind_compass():
    assert wind_direction_to_compass(0) == "N"
    assert wind_direction_to_compass(180) == "S"
    assert wind_direction_to_compass(90) == "E"
    assert wind_direction_to_compass(270) == "W"
    assert wind_direction_to_compass(None) is None


def test_coordinate_validation():
    assert validate_latitude(26.45) == 26.45
    with pytest.raises(ValidationError):
        validate_latitude(91)
    with pytest.raises(ValidationError):
        validate_longitude(-181)


def test_days_validation():
    assert validate_days(7) == 7
    with pytest.raises(ValidationError):
        validate_days(0)
    with pytest.raises(ValidationError):
        validate_days(17)


def test_message_validation():
    assert validate_query("  hello  ") == "hello"
    with pytest.raises(ValidationError):
        validate_query("   ")
    with pytest.raises(ValidationError):
        validate_query("x" * 1001)


def test_place_validation():
    with pytest.raises(ValidationError):
        validate_place_name("")


@pytest.mark.asyncio
async def test_health(client):
    """Basic sanity: health endpoint works through the app."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
