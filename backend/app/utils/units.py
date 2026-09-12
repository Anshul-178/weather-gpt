"""Unit conversion helpers.

Backend normalizes to: Celsius, km/h, km, hPa (per technical.md §8).
"""


def ms_to_kmh(value: float | None) -> float | None:
    """Convert metres/second to kilometres/hour."""
    return round(value * 3.6, 1) if value is not None else None


def kmh_to_ms(value: float | None) -> float | None:
    """Convert kilometres/hour to metres/second."""
    return round(value / 3.6, 3) if value is not None else None


def mph_to_kmh(value: float | None) -> float | None:
    """Convert miles/hour to kilometres/hour."""
    return round(value * 1.609344, 1) if value is not None else None


def metres_to_km(value: float | None) -> float | None:
    """Convert metres to kilometres."""
    return round(value / 1000.0, 1) if value is not None else None


def fahrenheit_to_celsius(value: float | None) -> float | None:
    """Convert Fahrenheit to Celsius."""
    return round((value - 32.0) * 5.0 / 9.0, 1) if value is not None else None


def kelvin_to_celsius(value: float | None) -> float | None:
    """Convert Kelvin to Celsius."""
    return round(value - 273.15, 1) if value is not None else None


def celsius_to_fahrenheit(value: float | None) -> float | None:
    """Convert Celsius to Fahrenheit."""
    return round(value * 9.0 / 5.0 + 32.0, 1) if value is not None else None


def wind_direction_to_compass(degrees: float | None) -> str | None:
    """Convert wind direction degrees to a compass label like 'NNE'."""
    if degrees is None:
        return None
    compass = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    index = int(((degrees % 360) + 11.25) // 22.5) % 16
    return compass[index]
