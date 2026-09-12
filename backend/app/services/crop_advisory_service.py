"""Crop-weather advisory service (agriculture decision support).

Deterministic rules over forecast data — the same pattern as the alert
engine: rules decide, numbers come only from the weather provider.
Use case from the problem statement: farmers seeking crop-weather advisories.
"""

from typing import Optional

from app.schemas.insights import (
    CropAdvisory,
    CropAdvisoryRequest,
    CropAdvisoryResponse,
)
from app.schemas.weather import CurrentWeatherResponse, ForecastResponse
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Crop-specific notes by growth stage-independent rules. Keys are common
# Indian crops; unknown/None crops get the general advisory set.
CROP_NOTES: dict[str, list[str]] = {
    "rice": [
        "Rice nurseries need standing water — check that irrigation channels are not blocked before a dry spell.",
    ],
    "wheat": [
        "Wheat grain filling is heat-sensitive: temperatures above 35°C during the day can cut yields.",
    ],
    "cotton": [
        "Cotton picking is best done on dry, low-humidity days to keep fiber quality high.",
    ],
    "sugarcane": [
        "Sugarcane is water-hungry: a week without rain in high heat means irrigation is due.",
    ],
    "maize": [
        "Maize pollination suffers above 35°C — heat during flowering can reduce grain set.",
    ],
    "mustard": [
        "Mustard prefers cool, dry harvest weather; rain on standing crops risks shattering.",
    ],
    "groundnut": [
        "Groundnut pods mature best with alternating wet and dry spells; waterlogging damages pegs.",
    ],
    "onion": [
        "Onion curing needs low humidity; postpone harvest-drying if rain is likely.",
    ],
    "potato": [
        "Potato late blight risk rises sharply with cool nights (below 15°C) and high humidity.",
    ],
    "tomato": [
        "Tomato fruit set suffers above 35°C day or above 24°C night temperatures.",
    ],
}


class CropAdvisoryService:
    """Deterministic crop-weather advisory generation."""

    def generate(
        self,
        request: CropAdvisoryRequest,
        current: Optional[CurrentWeatherResponse],
        forecast: Optional[ForecastResponse],
    ) -> CropAdvisoryResponse:
        """Build advisories purely from weather data. Never invents values."""
        place = request.location_name or (
            current.location.name if current else f"{request.latitude:.2f}, {request.longitude:.2f}"
        )
        advisories: list[CropAdvisory] = []

        if current is None or forecast is None:
            return CropAdvisoryResponse(
                location=place,
                latitude=request.latitude,
                longitude=request.longitude,
                crop=request.crop,
                advisories=[],
                field_work_score=None,
                irrigation_needed=None,
            )

        c = current.current
        daily = forecast.forecast
        hourly = forecast.hourly

        rain_today = self._max_rain_probability(daily, 0)
        rain_next_3 = max((self._max_rain_probability(daily, i) for i in range(3)), default=0)
        precip_next_3 = sum(
            (daily[i].precipitation_sum or 0) for i in range(min(3, len(daily)))
        )
        temp_maxes = [d.temperature_max for d in daily[:3] if d.temperature_max is not None]
        temp_mins = [d.temperature_min for d in daily[:3] if d.temperature_min is not None]
        peak_temp = max(temp_maxes) if temp_maxes else None
        min_temp = min(temp_mins) if temp_mins else None
        max_wind = max(
            (d.wind_speed_max for d in daily[:3] if d.wind_speed_max is not None),
            default=None,
        )
        humidity = c.humidity

        # ---------------- Irrigation ---------------- #
        dry_spell = precip_next_3 < 5 and (peak_temp is None or peak_temp >= 30)
        irrigation_needed = bool(dry_spell or (humidity is not None and humidity < 35 and precip_next_3 < 5))
        if irrigation_needed:
            advisories.append(
                CropAdvisory(
                    category="irrigation",
                    severity="caution",
                    message=(
                        f"Little rain expected in the next 3 days ({precip_next_3:.0f} mm total)"
                        + (f" with peaks of {peak_temp:.0f}°C" if peak_temp is not None else "")
                        + " — plan irrigation within 48 hours."
                    ),
                )
            )
        elif precip_next_3 >= 20:
            advisories.append(
                CropAdvisory(
                    category="irrigation",
                    severity="info",
                    message=(
                        f"Good rainfall expected ({precip_next_3:.0f} mm over 3 days) — "
                        "you can postpone irrigation and check field drainage."
                    ),
                )
            )

        # ---------------- Spraying / field work ---------------- #
        field_work_score = self._field_work_score(rain_today, hourly, max_wind)
        if rain_today >= 40:
            advisories.append(
                CropAdvisory(
                    category="field_work",
                    severity="caution",
                    message=(
                        f"Rain probability today is {rain_today:.0f}% — postpone spraying "
                        "and fertilizer application; it will wash off."
                    ),
                )
            )
        if max_wind is not None and max_wind >= 20:
            advisories.append(
                CropAdvisory(
                    category="field_work",
                    severity="caution",
                    message=(
                        f"Winds up to {max_wind:.0f} km/h expected — avoid pesticide "
                        "spraying (drift risk) and support tall crops."
                    ),
                )
            )

        # ---------------- Heat / cold stress ---------------- #
        if peak_temp is not None and peak_temp >= 38:
            advisories.append(
                CropAdvisory(
                    category="general",
                    severity="warning",
                    message=(
                        f"Heat wave risk: temperatures up to {peak_temp:.0f}°C in the next 3 days — "
                        "irrigate in the evening, mulch young plants."
                    ),
                )
            )
        if min_temp is not None and min_temp <= 8:
            advisories.append(
                CropAdvisory(
                    category="general",
                    severity="warning",
                    message=(
                        f"Cold stress possible: nights down to {min_temp:.0f}°C — "
                        "light irrigation before a cold night can protect crops."
                    ),
                )
            )

        # ---------------- Disease / pest risk ---------------- #
        if humidity is not None and humidity >= 80 and rain_today >= 40:
            advisories.append(
                CropAdvisory(
                    category="pest_disease",
                    severity="warning",
                    message=(
                        f"High humidity ({humidity:.0f}%) with rain ({rain_today:.0f}%) — "
                        "fungal disease risk is high; consider preventive fungicide on susceptible crops."
                    ),
                )
            )

        # ---------------- Harvest window ---------------- #
        if daily:
            harvest_ok = all(
                (d.precipitation_probability or 0) < 40 for d in daily[:2]
            )
            if harvest_ok:
                advisories.append(
                    CropAdvisory(
                        category="sowing",
                        severity="info",
                        message="Next 2 days look dry — a good window for harvesting or threshing if crops are ready.",
                    )
                )

        # ---------------- Crop-specific notes ---------------- #
        crop_key = (request.crop or "").strip().lower()
        for note in CROP_NOTES.get(crop_key, []):
            advisories.append(CropAdvisory(category="general", severity="info", message=note))

        if not advisories:
            advisories.append(
                CropAdvisory(
                    category="general",
                    severity="info",
                    message="Conditions look stable — no urgent field actions indicated for the next 3 days.",
                )
            )

        return CropAdvisoryResponse(
            location=place,
            latitude=request.latitude,
            longitude=request.longitude,
            crop=request.crop,
            advisories=advisories,
            field_work_score=field_work_score,
            irrigation_needed=irrigation_needed,
        )

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _max_rain_probability(self, daily, day_index: int) -> float:
        """Max precipitation probability for one forecast day (0 if absent)."""
        if daily and day_index < len(daily):
            return daily[day_index].precipitation_probability or 0
        return 0

    def _field_work_score(self, rain_today: float, hourly, max_wind: Optional[float]) -> int:
        """0-100 suitability for spraying/harvesting/ploughing today."""
        score = 100
        score -= min(60, rain_today * 0.8)
        if max_wind is not None:
            score -= min(20, max_wind * 0.5)
        wet_hours = sum(
            1 for p in hourly[:12] if (p.precipitation_probability or 0) >= 50
        )
        score -= min(20, wet_hours * 2)
        return int(max(0, min(100, score)))


crop_advisory_service = CropAdvisoryService()
