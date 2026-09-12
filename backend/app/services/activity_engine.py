"""Activity recommendation engine (technical.md §17, prompt §17-18).

Deterministic, configurable scoring: each factor contributes a 0-100
sub-score; the weighted mean maps to a rating band. Thresholds live in
ACTIVITY_THRESHOLDS / SCORE_BANDS, not scattered through the codebase.
"""

from datetime import datetime
from typing import Optional

from app.schemas.activity import ActivityScoreFactor, ActivityScoreResponse
from app.schemas.weather import CurrentWeatherResponse, ForecastResponse

# --------------------------------------------------------------------- #
# Configurable scoring configuration
# --------------------------------------------------------------------- #

SCORE_BANDS: list[tuple[int, str]] = [
    (80, "Excellent"),
    (60, "Good"),
    (40, "Moderate"),
    (20, "Poor"),
    (0, "Very Poor"),
]

# Per-factor ideal-range scoring. Each factor maps observed values to a
# 0-100 sub-score via piecewise-linear functions.
FACTOR_CONFIGS: dict[str, dict] = {
    "temperature": {
        "weight": 0.20,
        "ideal_min": 15.0,
        "ideal_max": 28.0,
        "hard_min": 0.0,
        "hard_max": 42.0,
        "unit": "°C",
        "label": "Temperature",
    },
    "feels_like": {
        "weight": 0.10,
        "ideal_min": 15.0,
        "ideal_max": 30.0,
        "hard_min": -2.0,
        "hard_max": 45.0,
        "unit": "°C",
        "label": "Feels-like temperature",
    },
    "precipitation_probability": {
        "weight": 0.25,
        "good_below": 20.0,
        "bad_above": 70.0,
        "unit": "%",
        "label": "Rain probability",
    },
    "precipitation": {
        "weight": 0.10,
        "good_below": 0.2,
        "bad_above": 4.0,
        "unit": "mm",
        "label": "Rainfall",
    },
    "wind_speed": {
        "weight": 0.15,
        "good_below": 15.0,
        "bad_above": 40.0,
        "unit": "km/h",
        "label": "Wind",
    },
    "humidity": {
        "weight": 0.08,
        "good_below": 60.0,
        "bad_above": 85.0,
        "unit": "%",
        "label": "Humidity",
    },
    "visibility": {
        "weight": 0.07,
        "good_above": 8.0,
        "bad_below": 2.0,
        "unit": "km",
        "label": "Visibility",
    },
    "uv_index": {
        "weight": 0.05,
        "good_below": 6.0,
        "bad_above": 10.0,
        "unit": "",
        "label": "UV index",
    },
}

# Activity-specific multipliers applied to the final score.
ACTIVITY_WEIGHTS: dict[str, dict[str, float]] = {
    "default": {},
    "cycling": {"wind_speed": 1.6},
    "running": {"temperature": 1.2, "humidity": 1.2},
    "hiking": {"wind_speed": 1.3, "visibility": 1.5},
    "photography": {"visibility": 1.8, "cloud_cover": 1.2},
    "driving": {"visibility": 1.8, "precipitation": 1.3},
    "cricket": {"precipitation_probability": 1.4, "wind_speed": 1.1},
    "picnic": {"precipitation_probability": 1.3, "temperature": 1.1},
}


def rating_for_score(score: float) -> str:
    """Map a 0-100 score to its rating band."""
    for threshold, label in SCORE_BANDS:
        if score >= threshold:
            return label
    return SCORE_BANDS[-1][1]


def score_factor(name: str, value: Optional[float]) -> Optional[float]:
    """Score a single factor 0-100 using its piecewise-linear config."""
    if value is None:
        return None
    cfg = FACTOR_CONFIGS[name]
    if "ideal_min" in cfg:  # ideal-range factors (temperature-like)
        lo, hi = cfg["ideal_min"], cfg["ideal_max"]
        hard_lo, hard_hi = cfg["hard_min"], cfg["hard_max"]
        if lo <= value <= hi:
            return 100.0
        if value < lo:
            span = max(lo - hard_lo, 1e-6)
            return max(0.0, 100.0 * (1.0 - (lo - value) / span))
        span = max(hard_hi - hi, 1e-6)
        return max(0.0, 100.0 * (1.0 - (value - hi) / span))
    if "good_below" in cfg:  # lower is better
        good, bad = cfg["good_below"], cfg["bad_above"]
        if value <= good:
            return 100.0
        if value >= bad:
            return 0.0
        return 100.0 * (1.0 - (value - good) / (bad - good))
    if "good_above" in cfg:  # higher is better
        good, bad = cfg["good_above"], cfg["bad_below"]
        if value >= good:
            return 100.0
        if value <= bad:
            return 0.0
        return 100.0 * ((value - bad) / (good - bad))
    return None


def compute_activity_score(
    activity: str,
    current: Optional[CurrentWeatherResponse],
    forecast: Optional[ForecastResponse],
    day_offset: int = 0,
) -> ActivityScoreResponse:
    """Compute an explainable activity score from weather data."""
    snapshot = _weather_snapshot(forecast, day_offset, current)
    multipliers = ACTIVITY_WEIGHTS.get(activity.lower(), ACTIVITY_WEIGHTS["default"])

    factors: list[ActivityScoreFactor] = []
    weighted_sum = 0.0
    weight_total = 0.0
    for key, cfg in FACTOR_CONFIGS.items():
        value = snapshot.get(key)
        sub = score_factor(key, value)
        if sub is None:
            continue
        weight = cfg["weight"] * float(multipliers.get(key, 1.0))
        weighted_sum += sub * weight
        weight_total += weight
        factors.append(
            ActivityScoreFactor(
                name=cfg["label"],
                score=round(sub, 0),
                detail=_describe(key, value),
            )
        )

    if weight_total == 0:
        return ActivityScoreResponse(
            activity=activity,
            score=0,
            rating="Unknown",
            reasons=["Weather data unavailable — score could not be computed."],
            factors=[],
        )

    score = weighted_sum / weight_total
    rating = rating_for_score(score)
    reasons = _build_reasons(factors, score)
    best_time = _best_time(forecast, day_offset, activity)

    return ActivityScoreResponse(
        activity=activity,
        score=int(round(score)),
        rating=rating,
        reasons=reasons,
        factors=factors,
        best_time=best_time,
    )


# --------------------------------------------------------------------- #
# internals
# --------------------------------------------------------------------- #


def _weather_snapshot(
    forecast: Optional[ForecastResponse], day_offset: int, current: Optional[CurrentWeatherResponse]
) -> dict:
    """Collect factor values from hourly/daily/current data for a given day."""
    snapshot: dict = {}
    if current:
        snapshot.update(
            {
                "temperature": current.current.temperature,
                "feels_like": current.current.feels_like,
                "precipitation_probability": current.current.precipitation_probability,
                "precipitation": current.current.precipitation,
                "wind_speed": current.current.wind_speed,
                "humidity": current.current.humidity,
                "visibility": current.current.visibility,
                "uv_index": current.current.uv_index,
            }
        )
    if forecast:
        target_date = None
        if forecast.forecast and 0 <= day_offset < len(forecast.forecast):
            target_date = forecast.forecast[day_offset].date
        hourly = [
            p
            for p in forecast.hourly
            if target_date is None or p.time.strftime("%Y-%m-%d") == target_date
        ]
        if hourly:
            def _avg(key: str) -> Optional[float]:
                values = [getattr(p, key) for p in hourly if getattr(p, key) is not None]
                return sum(values) / len(values) if values else None

            def _max(key: str) -> Optional[float]:
                values = [getattr(p, key) for p in hourly if getattr(p, key) is not None]
                return max(values) if values else None

            snapshot["wind_speed"] = _max("wind_speed") or snapshot.get("wind_speed")
            snapshot["humidity"] = _avg("humidity") or snapshot.get("humidity")
            snapshot["visibility"] = _avg("visibility") or snapshot.get("visibility")
            snapshot["uv_index"] = _max("uv_index") or snapshot.get("uv_index")
            snapshot["precipitation_probability"] = _max(
                "precipitation_probability"
            ) or snapshot.get("precipitation_probability")
            snapshot["precipitation"] = _max("precipitation") or snapshot.get("precipitation")
            snapshot["temperature"] = _avg("temperature") or snapshot.get("temperature")
            snapshot["feels_like"] = _avg("feels_like") or snapshot.get("feels_like")
        elif forecast.forecast and 0 <= day_offset < len(forecast.forecast):
            day = forecast.forecast[day_offset]
            snapshot["temperature"] = (
                (day.temperature_max + day.temperature_min) / 2
                if day.temperature_max is not None and day.temperature_min is not None
                else snapshot.get("temperature")
            )
            snapshot["precipitation_probability"] = (
                day.precipitation_probability or snapshot.get("precipitation_probability")
            )
            snapshot["precipitation"] = day.precipitation_sum or snapshot.get("precipitation")
            snapshot["wind_speed"] = day.wind_speed_max or snapshot.get("wind_speed")
            snapshot["uv_index"] = day.uv_index_max or snapshot.get("uv_index")
    return snapshot


def _describe(key: str, value: Optional[float]) -> str:
    """Human-readable description of a factor value."""
    if value is None:
        return "data unavailable"
    cfg = FACTOR_CONFIGS[key]
    unit = cfg["unit"]
    return f"{value:.0f}{(' ' + unit) if unit else ''} — " + _band_label(key, value)


def _band_label(key: str, value: float) -> str:
    """Band label for a factor value."""
    cfg = FACTOR_CONFIGS[key]
    if "ideal_min" in cfg:
        if cfg["ideal_min"] <= value <= cfg["ideal_max"]:
            return "comfortable range"
        return "outside comfortable range"
    if "good_below" in cfg:
        if value <= cfg["good_below"]:
            return "low"
        if value >= cfg["bad_above"]:
            return "high"
        return "moderate"
    if "good_above" in cfg:
        if value >= cfg["good_above"]:
            return "good"
        if value <= cfg["bad_below"]:
            return "poor"
        return "moderate"
    return ""


def _build_reasons(factors: list[ActivityScoreFactor], score: float) -> list[str]:
    """Explain the score: strongest positives and negatives."""
    if not factors:
        return []
    ordered = sorted(factors, key=lambda f: -f.score)
    reasons: list[str] = []
    best = ordered[0]
    if best.score >= 60:
        reasons.append(f"{best.name}: {best.detail} (favorable)")
    worst = ordered[-1]
    if worst.score < 60:
        reasons.append(f"{worst.name}: {worst.detail} (unfavorable)")
    reasons.append(f"Overall conditions rated {rating_for_score(score)}.")
    return reasons


def _best_time(
    forecast: Optional[ForecastResponse], day_offset: int, activity: str
) -> Optional[str]:
    """Recommend the best 2-hour window for the activity on the target day."""
    if not forecast or not forecast.hourly:
        return None
    target_date = (
        forecast.forecast[day_offset].date
        if forecast.forecast and 0 <= day_offset < len(forecast.forecast)
        else None
    )
    candidates = [
        p
        for p in forecast.hourly
        if target_date is None or p.time.strftime("%Y-%m-%d") == target_date
    ]
    best_score = None
    best_window: Optional[str] = None
    for i in range(max(1, len(candidates) - 1)):
        window = candidates[i : i + 2]
        temps = [p.temperature for p in window if p.temperature is not None]
        probs = [
            p.precipitation_probability for p in window if p.precipitation_probability is not None
        ]
        winds = [p.wind_speed for p in window if p.wind_speed is not None]
        if not temps and not probs:
            continue
        temp_penalty = max(temps) - 22 if temps else 0
        rain_penalty = max(probs) if probs else 0
        wind_penalty = (max(winds) - 15) if winds else 0
        window_score = -(temp_penalty + rain_penalty + max(wind_penalty, 0))
        if best_score is None or window_score > best_score:
            best_score = window_score
            start = window[0].time.strftime("%H:%M")
            end = window[-1].time.strftime("%H:%M")
            best_window = f"{start}–{end}"
    return best_window
