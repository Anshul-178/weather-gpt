"""Input validation helpers."""


class ValidationError(ValueError):
    """Raised when user input is invalid."""


def validate_latitude(latitude: float) -> float:
    """Latitude must be within [-90, 90]."""
    if not -90.0 <= latitude <= 90.0:
        raise ValidationError("latitude must be between -90 and 90")
    return latitude


def validate_longitude(longitude: float) -> float:
    """Longitude must be within [-180, 180]."""
    if not -180.0 <= longitude <= 180.0:
        raise ValidationError("longitude must be between -180 and 180")
    return longitude


def validate_days(days: int, minimum: int = 1, maximum: int = 16) -> int:
    """Forecast days must be within provider-supported bounds."""
    if not minimum <= days <= maximum:
        raise ValidationError(f"days must be between {minimum} and {maximum}")
    return days


def validate_query(message: str, max_length: int = 1000) -> str:
    """Chat message must be a non-empty, bounded string."""
    cleaned = message.strip()
    if not cleaned:
        raise ValidationError("message must not be empty")
    if len(cleaned) > max_length:
        raise ValidationError(f"message must be at most {max_length} characters")
    return cleaned


def validate_place_name(name: str, max_length: int = 120) -> str:
    """Place names must be non-empty and bounded."""
    cleaned = name.strip()
    if not cleaned:
        raise ValidationError("location name must not be empty")
    if len(cleaned) > max_length:
        raise ValidationError(f"location name must be at most {max_length} characters")
    return cleaned
