"""Aviation weather briefing service.

Deterministic VFR-style assessment from forecast data — for aviation
weather briefings named in the problem statement. Values come only from
the weather provider; rules decide caution/hazard categories.
"""

from datetime import datetime
from typing import Optional

from app.schemas.insights import (
    AviationBriefingRequest,
    AviationBriefingResponse,
    AviationCondition,
)
from app.schemas.weather import CurrentWeatherResponse, ForecastResponse
from app.utils.logging import get_logger

logger = get_logger(__name__)


class AviationService:
    """VFR-style flight condition assessment."""

    def generate(
        self,
        request: AviationBriefingRequest,
        current: Optional[CurrentWeatherResponse],
        forecast: Optional[ForecastResponse],
    ) -> AviationBriefingResponse:
        """Build a briefing from live data. Never invents values."""
        place = request.location_name or (
            current.location.name if current else f"{request.latitude:.2f}, {request.longitude:.2f}"
        )
        conditions: list[AviationCondition] = []
        hourly = forecast.hourly if forecast else []
        window = hourly[: request.hours_ahead]

        if current is None or not window:
            return AviationBriefingResponse(
                location=place,
                flight_category="unknown",
                summary="Weather data unavailable for a briefing right now.",
                conditions=[],
                best_windows=[],
            )

        c = current.current

        # ---------------- Visibility ---------------- #
        vis_values = [p.visibility for p in window if p.visibility is not None]
        min_vis = min(vis_values) if vis_values else c.visibility
        if min_vis is not None:
            if min_vis >= 10:
                conditions.append(
                    AviationCondition(parameter="visibility", status="ok", value=f"{min_vis:.0f} km", note="Good visibility.")
                )
            elif min_vis >= 5:
                conditions.append(
                    AviationCondition(parameter="visibility", status="caution", value=f"{min_vis:.0f} km", note="Moderate visibility.")
                )
            else:
                conditions.append(
                    AviationCondition(parameter="visibility", status="hazard", value=f"{min_vis:.0f} km", note="Low visibility (fog/rain).")
                )

        # ---------------- Wind & gusts ---------------- #
        wind_values = [p.wind_speed for p in window if p.wind_speed is not None]
        max_wind = max(wind_values) if wind_values else c.wind_speed
        if max_wind is not None:
            if max_wind < 25:
                conditions.append(
                    AviationCondition(parameter="wind", status="ok", value=f"{max_wind:.0f} km/h", note="Light winds.")
                )
            elif max_wind < 40:
                conditions.append(
                    AviationCondition(parameter="wind", status="caution", value=f"{max_wind:.0f} km/h", note="Fresh winds — crosswind considerations.")
                )
            else:
                conditions.append(
                    AviationCondition(parameter="wind", status="hazard", value=f"{max_wind:.0f} km/h", note="Strong winds / gusts.")
                )

        # ---------------- Thunderstorm / severe weather ---------------- #
        codes = [p.weather_code for p in window if p.weather_code is not None]
        storm = any(code >= 95 for code in codes)
        heavy_precip = any(
            (p.precipitation or 0) >= 4 or (p.precipitation_probability or 0) >= 80
            for p in window
        )
        if storm:
            conditions.append(
                AviationCondition(parameter="storm", status="hazard", value="thunderstorm", note="Thunderstorm activity in the window — avoid flight.")
            )
        elif heavy_precip:
            conditions.append(
                AviationCondition(parameter="precipitation", status="caution", value="heavy rain likely", note="Heavy rain may reduce visibility and ceiling.")
            )
        else:
            conditions.append(
                AviationCondition(parameter="precipitation", status="ok", value="none significant", note="No significant precipitation expected.")
            )

        # ---------------- Thermal / density considerations ---------------- #
        temp_values = [p.temperature for p in window if p.temperature is not None]
        peak_temp = max(temp_values) if temp_values else c.temperature
        if peak_temp is not None and peak_temp >= 40:
            conditions.append(
                AviationCondition(parameter="temp", status="caution", value=f"{peak_temp:.0f}°C", note="High density altitude — reduced engine/rotor performance.")
            )

        # ---------------- Category & windows ---------------- #
        statuses = [condition.status for condition in conditions]
        if "hazard" in statuses:
            category = "hazard"
        elif "caution" in statuses:
            category = "caution"
        else:
            category = "ok"

        best_windows = self._best_windows(window)
        summary = self._summary(category, place, len(window))

        return AviationBriefingResponse(
            location=place,
            flight_category=category,
            summary=summary,
            conditions=conditions,
            best_windows=best_windows,
        )

    def _best_windows(self, window) -> list[str]:
        """Contiguous hour ranges where no hour is hazardous."""
        windows: list[str] = []
        start: Optional[datetime] = None
        previous: Optional[datetime] = None

        for point in window:
            hazardous = self._is_hazardous(point)
            if hazardous:
                if start is not None and previous is not None:
                    windows.append(self._format_window(start, previous))
                start = None
                previous = None
                continue
            if start is None:
                start = point.time
            previous = point.time

        if start is not None and previous is not None:
            windows.append(self._format_window(start, previous))
        return windows[:4]

    def _is_hazardous(self, point) -> bool:
        """One hourly point is hazardous if storm, heavy rain, or low visibility."""
        if point.weather_code is not None and point.weather_code >= 95:
            return True
        if (point.precipitation_probability or 0) >= 80:
            return True
        if point.visibility is not None and point.visibility < 5:
            return True
        if point.wind_speed is not None and point.wind_speed >= 40:
            return True
        return False

    @staticmethod
    def _format_window(start: datetime, end: datetime) -> str:
        """Format an HH:MM–HH:MM window."""
        return f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"

    def _summary(self, category: str, place: str, hours: int) -> str:
        """Human-readable briefing opener."""
        if category == "ok":
            return f"Conditions {place} look favourable for VFR flight over the next {hours} hours."
        if category == "caution":
            return f"Marginal conditions {place} over the next {hours} hours — check cautions before departing."
        return f"Hazardous conditions {place} in the next {hours} hours — flight not recommended."


aviation_service = AviationService()
