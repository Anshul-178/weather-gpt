"""WeatherGPT system prompts.

The system prompt enforces the core guardrails (technical.md §11, prompt §12):
the weather service data is the source of truth and the LLM never invents
weather values.
"""

from app.schemas.aqi import AQIResponse
from app.schemas.weather import CurrentWeatherResponse, ForecastResponse

SYSTEM_PROMPT = """You are WeatherGPT — a friendly, weather-savvy companion.
People chat with you the way they'd ask a friend who happens to know the
weather, so talk like a real person, not like a report.

How you sound:
- Warm, casual, confident. Use contractions (it's, you'll, don't). Vary your
  sentence rhythm so it doesn't read like a template.
- Lead with the answer, then add one short practical takeaway. No preamble
  like "Certainly!" and never refer to yourself as an AI or assistant.
- Keep it brief: a couple of natural sentences is usually perfect. Go longer
  only when the question genuinely needs detail (e.g. planning a trip).
- Write flowing prose, not bullet lists or headings, unless the user asks
  for a structured breakdown.
- A little personality is welcome ("pack a jacket, it'll be breezy tonight")
  but keep emojis to at most one, usually none.
- When recommending an activity, weave the key factors (rain chance, wind,
  heat, humidity, UV) naturally into your reasoning.

Rules you must never break:
1. The WEATHER DATA and AIR QUALITY sections are your ONLY sources for
   weather and air quality facts. Never invent or estimate values that
   are not there.
2. If something isn't in the data, say you can't check it right now — don't
   guess, and don't give specific numbers.
3. Distinguish observed weather from forecasts from your own interpretation
   in the natural flow of the sentence ("right now it's...", "later today
   you can expect...", "I'd say...").
4. Forecasts aren't guarantees — use "likely", "looks like", "chance of"
   where uncertainty exists.
5. Temperatures are in Celsius, as provided in the data.
6. Mention the place and time when it helps ("in Kanpur this evening...").
7. Language matching: Always respond in the language used by the user. If the
   user asks in Hindi (Devanagari or Romanized/Hinglish), answer in clean, natural
   Hindi or Hinglish accordingly. If the user asks in English, answer in English.
"""


def build_weather_context(
    current: CurrentWeatherResponse | None,
    forecast: ForecastResponse | None,
    hourly_window_hours: int = 12,
) -> str:
    """Render structured weather data as compact text for the LLM.

    Includes current observation, daily summaries, and a near-term hourly
    window so time-of-day questions can be answered.
    """
    if current is None and forecast is None:
        return "WEATHER DATA:\n- Weather data could not be retrieved. Do NOT invent values."

    lines: list[str] = ["WEATHER DATA (source of truth):"]
    lines.append(f"- Retrieved at: {current.timestamp.isoformat() if current else 'n/a'}")

    if current is not None:
        c = current.current
        lines.append(
            f"- Location: {current.location.name} "
            f"(lat {current.location.latitude}, lon {current.location.longitude})"
        )
        lines.append(
            "CURRENT OBSERVATION: "
            f"temperature={_fmt(c.temperature)}°C, feels_like={_fmt(c.feels_like)}°C, "
            f"humidity={_fmt(c.humidity)}%, wind={_fmt(c.wind_speed)} km/h "
            f"({c.wind_direction_compass or 'n/a'}), pressure={_fmt(c.pressure)} hPa, "
            f"precipitation={_fmt(c.precipitation)} mm, cloud_cover={_fmt(c.cloud_cover)}%, "
            f"visibility={_fmt(c.visibility)} km, uv_index={_fmt(c.uv_index)}, "
            f"condition={c.condition or 'unknown'}"
        )

    if forecast is not None:
        if forecast.forecast:
            lines.append("DAILY FORECAST:")
            for day in forecast.forecast[:7]:
                lines.append(
                    f"  {day.date}: max={_fmt(day.temperature_max)}°C, "
                    f"min={_fmt(day.temperature_min)}°C, "
                    f"rain_prob={_fmt(day.precipitation_probability)}%, "
                    f"rain_sum={_fmt(day.precipitation_sum)} mm, "
                    f"wind_max={_fmt(day.wind_speed_max)} km/h, "
                    f"uv_max={_fmt(day.uv_index_max)}, condition={day.condition or 'unknown'}"
                )
        if forecast.hourly:
            first = forecast.hourly[0].time
            window = forecast.hourly[:hourly_window_hours]
            lines.append(f"HOURLY FORECAST (next {len(window)}h from {first}):")
            for point in window:
                lines.append(
                    f"  {point.time.strftime('%Y-%m-%d %H:%M')}: "
                    f"temp={_fmt(point.temperature)}°C, "
                    f"rain_prob={_fmt(point.precipitation_probability)}%, "
                    f"wind={_fmt(point.wind_speed)} km/h, "
                    f"condition={point.condition or 'unknown'}"
                )

    lines.append(
        "Reminder: use ONLY the values above for weather facts. "
        "Anything not present here is unknown — say so instead of guessing."
    )
    return "\n".join(lines)


def build_activity_context(score_result: dict) -> str:
    """Render an activity-engine result as text for the LLM."""
    factors = ", ".join(
        f"{f['name']}: {f['score']}/100 ({f['detail']})" for f in score_result.get("factors", [])
    )
    reasons = "; ".join(score_result.get("reasons", []))
    return (
        f"ACTIVITY ENGINE RESULT (deterministic, source of truth): "
        f"activity={score_result.get('activity')}, score={score_result.get('score')}/100, "
        f"rating={score_result.get('rating')}. Factors: {factors}. Summary: {reasons}"
    )


def build_aqi_context(aqi: AQIResponse | None) -> str:
    """Render AQI data as compact text for the LLM."""
    if aqi is None:
        return ""
    c = aqi.current
    parts = [
        f"AIR QUALITY (source of truth):",
        f"- AQI: {_fmt(c.aqi)} ({c.epa_aqi or 'n/a'})",
        f"- PM2.5: {_fmt(c.pm2_5)} μg/m³, PM10: {_fmt(c.pm10)} μg/m³",
        f"- O3: {_fmt(c.o3)} μg/m³, NO2: {_fmt(c.no2)} μg/m³, SO2: {_fmt(c.so2)} μg/m³, CO: {_fmt(c.co)} μg/m³",
    ]
    if c.dominant_pollutant:
        parts.append(f"- Dominant pollutant: {c.dominant_pollutant}")
    return "\n".join(parts)


def build_user_prompt(
    question: str,
    weather_context: str,
    activity_context: str | None = None,
    rag_context: str | None = None,
    aqi_context: str | None = None,
) -> str:
    """Combine all context sections with the user's question."""
    parts = [weather_context]
    if aqi_context:
        parts.append(aqi_context)
    if activity_context:
        parts.append(activity_context)
    if rag_context:
        parts.append(f"REFERENCE INFORMATION (may be helpful):\n{rag_context}")
    parts.append(f"USER QUESTION: {question}")
    return "\n\n".join(parts)


def _fmt(value) -> str:
    """Format a numeric value or return 'n/a'."""
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)
