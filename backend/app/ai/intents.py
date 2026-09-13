"""Lightweight rule-based intent detection (technical.md §15).

Deterministic handling keeps trivial questions cheap and fast; the LLM is
reserved for interpretation and recommendations.
"""

import re
from enum import Enum
from typing import Optional


class Intent(str, Enum):
    """Supported weather intents."""

    CURRENT_WEATHER = "CURRENT_WEATHER"
    FORECAST = "FORECAST"
    RAIN = "RAIN"
    TEMPERATURE = "TEMPERATURE"
    WIND = "WIND"
    HUMIDITY = "HUMIDITY"
    UV = "UV"
    AIR_QUALITY = "AIR_QUALITY"
    WEATHER_COMPARISON = "WEATHER_COMPARISON"
    ACTIVITY_RECOMMENDATION = "ACTIVITY_RECOMMENDATION"
    TRAVEL = "TRAVEL"
    ALERT = "ALERT"
    GENERAL_WEATHER_KNOWLEDGE = "GENERAL_WEATHER_KNOWLEDGE"


# Ordered keyword rules: first match wins.
_PATTERNS: list[tuple[Intent, str]] = [
    (Intent.WEATHER_COMPARISON, r"\b(compare|vs\.?|versus|difference between|better weather)\b"),
    (Intent.ACTIVITY_RECOMMENDATION, r"\b(carry|umbrella|wear|jacket|should i (go|play|run|ride|cycle|hike|walk|travel|drive|leave)|good (day|time) for|best time|cricket|football|cycling|running|hiking|picnic|photography|outdoor)\b"),
    (Intent.ALERT, r"\b(alert|warn(ing)?|severe|storm coming|extreme)\b"),
    (Intent.TRAVEL, r"\b(travel|commute|drive|driving|road trip|flight|pack(ing)?)\b"),
    (Intent.RAIN, r"\b(rain|raining|drizzle|shower|umbrella|precipitation)\b"),
    (Intent.UV, r"\b(uv|sunburn|sunscreen)\b"),
    (Intent.AIR_QUALITY, r"\b(air quality|aqi|pollution|pollen)\b"),
    (Intent.WIND, r"\b(wind|windy|gust|breeze)\b"),
    (Intent.HUMIDITY, r"\b(humidity|humid|muggy)\b"),
    (Intent.TEMPERATURE, r"\b(temperature|hot|cold|warm|cool|degrees|°c|°f)\b"),
    (Intent.FORECAST, r"\b(tomorrow|forecast|week|next \d+ days|weekend|later (today|tonight)|this evening)\b"),
    (Intent.CURRENT_WEATHER, r"\b(now|currently|right now|today|current weather|weather (like|in|at))\b"),
]

# Words that indicate a relative date/time qualifier.
_PERIOD_PATTERN = re.compile(
    r"\b(morning|afternoon|evening|night|tonight|now|later|today|tomorrow|"
    r"day after tomorrow|weekend|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday)\b",
    re.IGNORECASE,
)


def detect_intent(message: str) -> Intent:
    """Detect the dominant intent of a user message."""
    text = message.lower()
    for intent, pattern in _PATTERNS:
        if re.search(pattern, text):
            return intent
    return Intent.GENERAL_WEATHER_KNOWLEDGE


def detect_period(message: str) -> Optional[str]:
    """Extract a time-of-day/day qualifier from a message, if any."""
    match = _PERIOD_PATTERN.search(message)
    return match.group(0).lower() if match else None


def is_follow_up(message: str) -> bool:
    """Heuristic: short messages that reference prior context."""
    text = message.lower().strip()
    if len(text.split()) > 6:
        return False
    return bool(
        re.match(
            r"^(what about|and|how about|what if|is it|will it|should i)\b",
            text,
        )
    ) or bool(re.search(r"\b(evening|morning|afternoon|night|there|then|that)\b", text))


def detect_activity(message: str) -> Optional[str]:
    """Extract the activity named in a recommendation question."""
    text = message.lower()
    activities = (
        "cycling", "running", "hiking", "cricket", "football", "picnic",
        "photography", "driving", "walking", "travel", "commute", "outdoor",
    )
    for activity in activities:
        if re.search(rf"\b{re.escape(activity)}\b", text):
            return activity
    if re.search(r"\b(what should i wear|what to wear|jacket|clothes)\b", text):
        return "walking"
    if re.search(r"\b(carry|take) an? umbrella\b", text):
        return "walking"
    return None
