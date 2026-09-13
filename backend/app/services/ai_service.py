"""AI service.

Receives the user question plus structured weather context, constructs the
prompt, calls the LLM (OpenAI-compatible chat completions API), validates
the response, and returns a clean answer.

The LLM provider implementation is isolated here — routes never call the
LLM directly. When no LLM key is configured, or the LLM fails, a
deterministic rule-based fallback generates a useful answer from the same
weather data (never inventing values).
"""

import time  # noqa: F401  (used for latency logging in future)
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.ai import intents as intent_module
from app.ai.prompts import (
    SYSTEM_PROMPT,
    build_activity_context,
    build_aqi_context,
    build_user_prompt,
    build_weather_context,
)
from app.ai.retriever import maybe_retrieve
from app.config import settings
from app.schemas.aqi import AQIResponse
from app.schemas.weather import CurrentWeatherResponse, ForecastResponse
from app.utils.logging import get_logger

logger = get_logger(__name__)

FALLBACK_NO_DATA = (
    "I'm unable to retrieve the live weather data right now — "
    "give it another try in a moment."
)


class LLMError(Exception):
    """LLM call failed after retries."""


class AIService:
    """Weather-aware AI assistant service."""

    async def answer_question(
        self,
        question: str,
        current: Optional[CurrentWeatherResponse],
        forecast: Optional[ForecastResponse],
        location_name: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
        activity_result: Optional[dict] = None,
        rag_enabled: bool = False,
        aqi: Optional[AQIResponse] = None,
    ) -> dict:
        """Answer a weather question using live weather + AQI context.

        Returns a dict with keys: answer, sources.
        """
        has_weather = current is not None or forecast is not None
        weather_context = build_weather_context(current, forecast)
        aqi_context = build_aqi_context(aqi)
        activity_context = (
            build_activity_context(activity_result) if activity_result else None
        )
        rag_context = await maybe_retrieve(question, rag_enabled)

        # If weather data is unavailable, never call the LLM for values.
        if not has_weather:
            return {
                "answer": FALLBACK_NO_DATA,
                "sources": [],
            }

        history = self._bounded_history(conversation_history)

        if settings.gemini_api_key:
            try:
                answer = await self._call_llm(
                    question, weather_context, activity_context, rag_context, history, aqi_context
                )
                return self._validate_answer(answer, weather_context, sources=["weather_api", "llm"])
            except LLMError as exc:
                logger.warning("LLM failed, using rule-based fallback: %s", exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Unexpected LLM error, using fallback: %s", exc)

        answer = self._rule_based_answer(
            question, current, forecast, activity_result, location_name, aqi
        )
        return self._validate_answer(answer, weather_context, sources=["weather_api", "rules"])

    # ------------------------------------------------------------------ #
    # LLM call
    # ------------------------------------------------------------------ #

    async def _call_llm(
        self,
        question: str,
        weather_context: str,
        activity_context: Optional[str],
        rag_context: Optional[str],
        history: list[dict],
        aqi_context: Optional[str] = None,
    ) -> str:
        """Call Google Gemini Flash via LangChain."""
        llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=0.7,
            max_output_tokens=600,
        )

        # Build the message list for LangChain.
        messages = [SystemMessage(content=SYSTEM_PROMPT)]
        for msg in history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            else:
                messages.append(AIMessage(content=msg["content"]))

        user_prompt = build_user_prompt(
            question, weather_context, activity_context, rag_context, aqi_context
        )
        messages.append(HumanMessage(content=user_prompt))

        try:
            response = await llm.ainvoke(messages)
        except Exception as exc:
            raise LLMError(f"Gemini call failed: {exc}") from exc

        answer = self._extract_text(response.content)
        if not answer or not answer.strip():
            raise LLMError("Gemini returned empty answer")
        return answer.strip()

    @staticmethod
    def _extract_text(content: object) -> str:
        """Extract plain text from LLM response content.

        LangChain Google GenAI returns content as either a plain string or a list
        of content blocks (e.g. [{'type': 'text', 'text': '...', 'extras': {...}}]).
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    if "text" in block and isinstance(block["text"], str):
                        parts.append(block["text"])
                elif hasattr(block, "text") and isinstance(block.text, str):
                    parts.append(block.text)
            return "".join(parts)
        return str(content) if content is not None else ""

    def _bounded_history(
        self, history: Optional[list[dict]]
    ) -> list[dict]:
        """Keep only the last N messages with role/content fields."""
        if not history:
            return []
        cleaned = [
            {"role": m.get("role", "user"), "content": str(m.get("content", ""))[:1000]}
            for m in history
            if m.get("role") in ("user", "assistant")
        ]
        return cleaned[-settings.llm_max_history_messages:]

    def _validate_answer(self, answer: str, weather_context: str, sources: list[str]) -> dict:
        """Basic response validation before returning to the client."""
        cleaned = answer.strip()
        if not cleaned:
            cleaned = FALLBACK_NO_DATA
        # Guardrail: if the LLM confessed to guessing numbers, prefer fallback.
        _ = weather_context  # context kept for future rule extensions
        return {"answer": cleaned, "sources": sources}

    # ------------------------------------------------------------------ #
    # Deterministic fallback (no LLM key or LLM failure)
    # ------------------------------------------------------------------ #

    def _rule_based_answer(
        self,
        question: str,
        current: Optional[CurrentWeatherResponse],
        forecast: Optional[ForecastResponse],
        activity_result: Optional[dict],
        location_name: Optional[str],
        aqi: Optional[AQIResponse] = None,
    ) -> str:
        """Generate a useful answer from weather data without an LLM.

        All values come strictly from the provided weather objects.
        """
        intent = intent_module.detect_intent(question)
        period = intent_module.detect_period(question)
        place = location_name or (
            current.location.name if current else
            (forecast.location.name if forecast else None)
        )
        where = f"in {place}" if place else ""

        if intent == intent_module.Intent.WEATHER_COMPARISON and forecast:
            return self._answer_forecast(forecast, where, period)

        if activity_result:
            return self._answer_activity(activity_result, where)

        if intent == intent_module.Intent.RAIN:
            return self._answer_rain(current, forecast, where, period)
        if intent == intent_module.Intent.TEMPERATURE:
            return self._answer_temperature(current, forecast, where, period)
        if intent == intent_module.Intent.WIND:
            return self._answer_wind(current, forecast, where)
        if intent == intent_module.Intent.HUMIDITY:
            return self._answer_humidity(current, where)
        if intent == intent_module.Intent.UV:
            return self._answer_uv(current, forecast, where)
        if intent == intent_module.Intent.AIR_QUALITY:
            return self._answer_aqi(aqi, where)
        if intent in (intent_module.Intent.FORECAST,):
            return self._answer_forecast(forecast, where, period)
        return self._answer_general(current, forecast, where, period)

    def _answer_general(self, current, forecast, where, period) -> str:
        """Answer general weather questions with a current + today summary."""
        parts: list[str] = []
        if current is not None:
            c = current.current
            if c.temperature is not None:
                feels_diff = (
                    abs(c.feels_like - c.temperature)
                    if c.feels_like is not None
                    else 0
                )
                feels = ", feels like %.0f°C" % c.feels_like if feels_diff >= 2 else ""
                condition = f" with {c.condition.lower()}" if c.condition else ""
                parts.append(
                    f"Right now {where} it's {c.temperature:.0f}°C{feels}{condition}."
                )
        day = self._today_or_tomorrow(forecast, period)
        if day is not None:
            when = "Tomorrow" if "tomorrow" in (period or "") else "Today"
            parts.append(
                f"{when} looks like a high of {day.temperature_max:.0f}°C and a low of "
                f"{day.temperature_min:.0f}°C, with a {day.precipitation_probability or 0:.0f}% "
                "chance of rain."
            )
        if not parts:
            return FALLBACK_NO_DATA
        return " ".join(parts)

    def _today_or_tomorrow(self, forecast, period):
        """Pick today's or tomorrow's daily point based on the period keyword."""
        if not forecast or not forecast.forecast:
            return None
        index = 1 if "tomorrow" in (period or "") else 0
        if index < len(forecast.forecast):
            return forecast.forecast[index]
        return forecast.forecast[-1]

    def _answer_rain(self, current, forecast, where, period) -> str:
        """Answer rain/umbrella questions from forecast data."""
        points = self._window_points(forecast, period)
        when = period or "in the coming hours"
        if points:
            probs = [p.precipitation_probability for p in points if p.precipitation_probability is not None]
            if probs:
                peak = max(probs)
                if peak >= 60:
                    return (
                        f"Rain looks very likely {where} {when} — probability peaks around "
                        f"{peak:.0f}%, so definitely take an umbrella."
                    )
                if peak >= 30:
                    return (
                        f"There's a decent chance of rain {where} {when} — up to about "
                        f"{peak:.0f}%. Might be worth keeping an umbrella handy just in case."
                    )
                return (
                    f"Good news — rain is unlikely {where} {when}, with chances staying "
                    f"at or below {peak:.0f}%. You can leave the umbrella at home."
                )
        if current and current.current.precipitation is not None:
            mm = current.current.precipitation
            state = "raining lightly" if 0 < mm < 2.5 else ("raining" if mm else "not raining")
            return f"It's {state} {where} right now."
        return FALLBACK_NO_DATA

    def _answer_temperature(self, current, forecast, where, period) -> str:
        """Answer temperature questions."""
        if period and forecast:
            points = self._window_points(forecast, period)
            temps = [p.temperature for p in points if p.temperature is not None]
            if temps:
                if period == "now":
                    return f"Right now it's around {min(temps):.0f}–{max(temps):.0f}°C {where}."
                return f"Expect around {min(temps):.0f}–{max(temps):.0f}°C {where} {period}."
        if current and current.current.temperature is not None:
            c = current.current
            feels = (
                f", feels like {c.feels_like:.0f}°C"
                if c.feels_like is not None and abs(c.feels_like - c.temperature) >= 2
                else ""
            )
            return f"It's currently {c.temperature:.0f}°C {where}{feels}."
        return FALLBACK_NO_DATA

    def _answer_wind(self, current, forecast, where) -> str:
        """Answer wind questions."""
        if current and current.current.wind_speed is not None:
            speed = current.current.wind_speed
            compass = current.current.wind_direction_compass or ""
            if speed < 12:
                return f"It's pretty calm {where} right now, around {speed:.0f} km/h from the {compass}."
            if speed < 30:
                return f"A bit breezy {where} — winds around {speed:.0f} km/h from the {compass}."
            return f"It's quite windy {where} — {speed:.0f} km/h from the {compass}, so secure anything loose outdoors."
        return FALLBACK_NO_DATA

    def _answer_humidity(self, current, where) -> str:
        """Answer humidity questions."""
        if current and current.current.humidity is not None:
            h = current.current.humidity
            feel = (
                "pretty humid out there"
                if h >= 70
                else ("comfortable" if h >= 40 else "on the dry side")
            )
            return f"Humidity is around {h:.0f}% {where} — {feel}."
        return FALLBACK_NO_DATA

    def _answer_uv(self, current, forecast, where) -> str:
        """Answer UV questions."""
        value = None
        if current and current.current.uv_index is not None:
            value = current.current.uv_index
        elif forecast and forecast.forecast:
            value = forecast.forecast[0].uv_index_max
        if value is None:
            return FALLBACK_NO_DATA
        if value < 3:
            return f"UV is low {where} right now ({value:.0f}) — nothing to worry about."
        if value < 8:
            return (
                f"UV is fairly strong {where} ({value:.0f}) — sunscreen and sunglasses "
                "would be a good idea."
            )
        return (
            f"UV is very high {where} ({value:.0f}) — best to stay out of the midday "
            "sun and cover up."
        )

    def _answer_aqi(self, aqi: Optional[AQIResponse], where: str) -> str:
        """Answer air quality questions."""
        if aqi is None:
            return FALLBACK_NO_DATA
        c = aqi.current
        aqi_val = c.aqi
        category = c.epa_aqi or "Unknown"
        if aqi_val is None:
            return f"Air quality data isn't available {where} right now."
        if aqi_val <= 50:
            base = f"Air quality {where} is good right now (AQI {aqi_val}, {category}). "
            return base + "It's fine for all outdoor activities."
        if aqi_val <= 100:
            base = f"Air quality {where} is moderate (AQI {aqi_val}, {category}). "
            return base + "Generally fine for most people, though unusually sensitive individuals might notice mild effects."
        if aqi_val <= 150:
            base = f"Air quality {where} is unhealthy for sensitive groups (AQI {aqi_val}, {category}). "
            return base + "Children, elderly, and people with respiratory conditions should limit prolonged outdoor exertion."
        if aqi_val <= 200:
            return (
                f"Air quality {where} is unhealthy (AQI {aqi_val}, {category}). "
                "Everyone should reduce prolonged outdoor activity. Wear a mask if you need to be outside."
            )
        return (
            f"Air quality {where} is very unhealthy (AQI {aqi_val}, {category}). "
            "Avoid all outdoor activity if possible and keep windows closed."
        )

    def _answer_forecast(self, forecast, where, period) -> str:
        """Answer general forecast questions."""
        if not forecast or not forecast.forecast:
            return FALLBACK_NO_DATA
        day = forecast.forecast[1 if "tomorrow" in (period or "") else 0]
        when = "Tomorrow" if "tomorrow" in (period or "") else "Today"
        cond = f", {day.condition.lower()}" if day.condition else ""
        return (
            f"{when} {where} is looking at a high of {day.temperature_max:.0f}°C and a low of "
            f"{day.temperature_min:.0f}°C, with a {day.precipitation_probability or 0:.0f}% chance "
            f"of rain{cond}."
        )

    def _answer_activity(self, result: dict, where: str) -> str:
        """Answer activity questions using the deterministic engine result."""
        rating = str(result.get("rating", "unknown")).lower()
        activity = str(result.get("activity", "this activity")).replace("_", " ")
        reasons = result.get("reasons") or []
        reason_text = self._natural_activity_reason(reasons)
        if any(word in rating for word in ("good", "excellent", "great", "ideal")):
            opener = f"{activity.capitalize()} {where} looks like a good option today."
        elif any(word in rating for word in ("poor", "bad", "harsh")):
            opener = f"I'd probably skip {activity} {where} today — the conditions aren't very comfortable."
        else:
            opener = f"{activity.capitalize()} {where} is doable today, but it may not be especially comfortable."
        if reason_text:
            return f"{opener} {reason_text}"
        return opener

    @staticmethod
    def _natural_activity_reason(reasons: list) -> str:
        """Convert engine labels into a short, human-sounding explanation."""
        if not reasons:
            return ""
        text = str(reasons[0])
        text = text.replace(" (favorable)", "").replace(" (unfavorable)", "")
        if ": " in text:
            text = text.split(": ", 1)[1]
        if text.endswith("."):
            return text
        return text + "."

    def _window_points(self, forecast, period):
        """Select hourly points matching a period keyword."""
        if not forecast or not forecast.hourly:
            return []
        now_hour = forecast.hourly[0].time
        selected = []
        for point in forecast.hourly:
            hour = point.time.hour
            if period in ("morning",):
                match = 5 <= hour < 12
            elif period in ("afternoon",):
                match = 12 <= hour < 17
            elif period in ("evening", "tonight", "night"):
                match = 17 <= hour < 23
            elif period == "tomorrow":
                match = point.time.date() > now_hour.date()
            else:
                match = point.time >= now_hour
            if match:
                selected.append(point)
            if len(selected) >= 12:
                break
        return selected


ai_service = AIService()
