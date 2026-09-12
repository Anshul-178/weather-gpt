"""Alert engine (technical.md §18, prompt §20).

Deterministic rule-based alerting: thresholds are configured constants, and
alerts trigger ONLY when observed/forecast values meet them. The LLM may
generate human-readable explanations after a rule fires — it never decides
whether an alert triggers.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.config import settings
from app.schemas.alert import AlertCheckResponse, TriggeredAlert
from app.schemas.weather import CurrentWeatherResponse, ForecastResponse
from app.utils.logging import get_logger

logger = get_logger(__name__)

# --------------------------------------------------------------------- #
# Configurable alert thresholds (defaults; user thresholds override)
# --------------------------------------------------------------------- #

DEFAULT_THRESHOLDS: dict[str, float] = {
    "rain": 60.0,               # precipitation probability %
    "heavy_rain": 80.0,         # precipitation probability %
    "extreme_heat": 40.0,       # temperature °C
    "strong_wind": 40.0,        # wind speed km/h
    "poor_visibility": 1.0,     # visibility km
    "high_uv": 9.0,             # UV index
    "cold": 2.0,                # temperature °C
    "thunderstorm": 1.0,        # weather code >= 95 triggers
    "severe_weather": 1.0,      # any severe code (95+)
    "flood_risk": 100.0,        # 3-day accumulated precipitation mm
    "cyclone_wind": 90.0,       # sustained wind km/h
}

SEVERITY_BY_TYPE: dict[str, str] = {
    "rain": "info",
    "heavy_rain": "warning",
    "thunderstorm": "severe",
    "severe_weather": "severe",
    "extreme_heat": "warning",
    "strong_wind": "warning",
    "poor_visibility": "warning",
    "high_uv": "info",
    "cold": "info",
    "flood_risk": "severe",
    "cyclone_wind": "severe",
}

TITLES_BY_TYPE: dict[str, str] = {
    "rain": "🌧️ Rain Alert",
    "heavy_rain": "🌧️ Heavy Rain Alert",
    "thunderstorm": "⛈️ Storm Alert",
    "severe_weather": "⛈️ Severe Weather Alert",
    "extreme_heat": "🌡️ Heat Alert",
    "strong_wind": "💨 Strong Wind Alert",
    "poor_visibility": "🌫️ Poor Visibility Alert",
    "high_uv": "☀️ High UV Alert",
    "cold": "🥶 Cold Alert",
    "flood_risk": "🌊 Flood Risk Alert",
    "cyclone_wind": "🌀 Cyclone Wind Alert",
}

SUPPORTED_TYPES = set(DEFAULT_THRESHOLDS.keys())


@dataclass
class AlertRuleContext:
    """Weather values available to alert rules."""

    temperature: Optional[float]
    precipitation_probability: Optional[float]
    precipitation_sum: Optional[float]
    wind_speed: Optional[float]
    visibility: Optional[float]
    uv_index: Optional[float]
    weather_code: Optional[int]
    location: str
    precip_next_72h: Optional[float] = None  # mm accumulated over ~3 days


def evaluate_alert_rules(
    ctx: AlertRuleContext,
    rules: list[dict],
) -> list[TriggeredAlert]:
    """Evaluate user rules deterministically against weather context.

    Each rule: {alert_type, threshold (optional user override), enabled}.
    """
    triggered: list[TriggeredAlert] = []
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        alert_type = rule.get("alert_type", "")
        if alert_type not in SUPPORTED_TYPES:
            continue
        threshold = rule.get("threshold")
        if threshold is None:
            threshold = DEFAULT_THRESHOLDS.get(alert_type)
        if threshold is None:
            continue

        alert = _check_rule(alert_type, threshold, ctx)
        if alert is not None:
            triggered.append(alert)
    return triggered


def _check_rule(alert_type: str, threshold: float, ctx: AlertRuleContext) -> Optional[TriggeredAlert]:
    """Check one rule; return a TriggeredAlert when the threshold is met."""
    observed: Optional[float] = None
    fired = False

    if alert_type in ("rain", "heavy_rain"):
        observed = ctx.precipitation_probability
        fired = observed is not None and observed >= threshold
    elif alert_type == "extreme_heat":
        observed = ctx.temperature
        fired = observed is not None and observed >= threshold
    elif alert_type == "cold":
        observed = ctx.temperature
        fired = observed is not None and observed <= threshold
    elif alert_type == "strong_wind":
        observed = ctx.wind_speed
        fired = observed is not None and observed >= threshold
    elif alert_type == "poor_visibility":
        observed = ctx.visibility
        fired = observed is not None and observed <= threshold
    elif alert_type == "high_uv":
        observed = ctx.uv_index
        fired = observed is not None and observed >= threshold
    elif alert_type in ("thunderstorm", "severe_weather"):
        observed = float(ctx.weather_code) if ctx.weather_code is not None else None
        fired = ctx.weather_code is not None and ctx.weather_code >= 95
    elif alert_type == "flood_risk":
        observed = ctx.precip_next_72h
        fired = observed is not None and observed >= threshold
    elif alert_type == "cyclone_wind":
        observed = ctx.wind_speed
        fired = observed is not None and observed >= threshold

    if not fired:
        return None

    explanation = _explain(alert_type, observed, threshold, ctx)
    return TriggeredAlert(
        alert_type=alert_type,
        severity=SEVERITY_BY_TYPE.get(alert_type, "info"),
        title=TITLES_BY_TYPE.get(alert_type, "⚠️ Weather Alert"),
        message=explanation,
        observed_value=observed,
        threshold=threshold,
        location=ctx.location,
    )


def _explain(
    alert_type: str, observed: Optional[float], threshold: float, ctx: AlertRuleContext
) -> str:
    """Human-readable explanation generated AFTER the rule fires."""
    place = f"in {ctx.location}" if ctx.location else ""
    if alert_type in ("rain", "heavy_rain"):
        return (
            f"Rain probability {place} is {observed:.0f}%, "
            f"at or above your {threshold:.0f}% threshold. Carry an umbrella."
        )
    if alert_type == "extreme_heat":
        return (
            f"Temperature {place} is {observed:.0f}°C, at or above your "
            f"{threshold:.0f}°C threshold. Stay hydrated and avoid peak sun."
        )
    if alert_type == "cold":
        return (
            f"Temperature {place} is {observed:.0f}°C, at or below your "
            f"{threshold:.0f}°C threshold. Dress warmly."
        )
    if alert_type == "strong_wind":
        return (
            f"Wind {place} is {observed:.0f} km/h, at or above your "
            f"{threshold:.0f} km/h threshold. Take care outdoors."
        )
    if alert_type == "poor_visibility":
        return (
            f"Visibility {place} is {observed:.1f} km, at or below your "
            f"{threshold:.1f} km threshold. Drive carefully."
        )
    if alert_type == "high_uv":
        return (
            f"UV index {place} is {observed:.0f}, at or above your "
            f"{threshold:.0f} threshold. Use sun protection."
        )
    if alert_type in ("thunderstorm", "severe_weather"):
        return (
            f"Severe weather (thunderstorm) detected {place}. "
            "Seek shelter and avoid open areas."
        )
    if alert_type == "flood_risk":
        return (
            f"Heavy rainfall of {observed:.0f} mm expected over the next 3 days {place}. "
            "Flood risk — move livestock and valuables to higher ground, avoid low-lying routes."
        )
    if alert_type == "cyclone_wind":
        return (
            f"Destructive winds of {observed:.0f} km/h {place} — cyclonic-strength conditions. "
            "Stay indoors away from windows and follow official evacuation advisories."
        )
    return "Weather alert threshold met."


def build_rules_context(current: CurrentWeatherResponse, forecast: Optional[ForecastResponse]) -> AlertRuleContext:
    """Build the rule context from live weather data."""
    rain_prob = current.current.precipitation_probability
    if rain_prob is None and forecast and forecast.hourly:
        upcoming = [p.precipitation_probability for p in forecast.hourly[:12]
                    if p.precipitation_probability is not None]
        rain_prob = max(upcoming) if upcoming else None

    # Accumulate ~72h of precipitation for flood-risk assessment.
    precip_next_72h: Optional[float] = None
    if forecast:
        values = [
            d.precipitation_sum for d in forecast.forecast[:3]
            if d.precipitation_sum is not None
        ]
        if values:
            precip_next_72h = round(sum(values), 1)

    return AlertRuleContext(
        temperature=current.current.temperature,
        precipitation_probability=rain_prob,
        precipitation_sum=current.current.precipitation,
        wind_speed=current.current.wind_speed,
        visibility=current.current.visibility,
        uv_index=current.current.uv_index,
        weather_code=current.current.weather_code,
        location=current.location.name,
        precip_next_72h=precip_next_72h,
    )


class AlertService:
    """CRUD + evaluation for alert preferences."""

    async def check_for_preferences(
        self, preferences: list, current: CurrentWeatherResponse, forecast: Optional[ForecastResponse]
    ) -> AlertCheckResponse:
        """Evaluate saved preferences against live weather."""
        ctx = build_rules_context(current, forecast)
        rules = [
            {
                "alert_type": pref.alert_type,
                "threshold": pref.threshold,
                "enabled": pref.enabled,
            }
            for pref in preferences
        ]
        triggered = evaluate_alert_rules(ctx, rules)
        return AlertCheckResponse(location=ctx.location, alerts=triggered, checked_at=datetime.now())


alert_service = AlertService()
