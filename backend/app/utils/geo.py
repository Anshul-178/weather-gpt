"""Geographic helpers."""


def round_coord(value: float, decimals: int = 2) -> float:
    """Round a coordinate for cache-key stability (technical.md §21)."""
    return round(value, decimals)


def cache_key_current(latitude: float, longitude: float) -> str:
    """Cache key for current weather."""
    return f"weather:current:{round_coord(latitude)}:{round_coord(longitude)}"


def cache_key_forecast(latitude: float, longitude: float, days: int, model: str | None = None) -> str:
    """Cache key for forecast weather (model-specific when a model is set)."""
    suffix = f":{model}" if model else ""
    return f"weather:forecast:{round_coord(latitude)}:{round_coord(longitude)}:{days}{suffix}"


def cache_key_geocode(name: str) -> str:
    """Cache key for geocoding lookups."""
    return f"geocode:{name.strip().lower()}"
