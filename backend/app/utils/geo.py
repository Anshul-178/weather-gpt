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


def cache_key_historical(latitude: float, longitude: float, days: int) -> str:
    """Cache key for historical daily observations.

    The archive API returns immutable past observations, so the cache key does
    not include the request date — it is keyed by coordinate window only.
    """
    return f"historical:{round_coord(latitude)}:{round_coord(longitude)}:{days}"


def cache_key_climate(latitude: float, longitude: float, years: int) -> str:
    """Cache key for climate trend aggregates."""
    return f"climate:{round_coord(latitude)}:{round_coord(longitude)}:{years}"
