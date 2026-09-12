"""Weather comparison service (technical.md §7.4, prompt §19).

Comparisons are calculated from actual weather data — never generated.
"""

from app.schemas.chat import ComparisonResponse
from app.schemas.weather import ForecastResponse
from app.services.cached_weather_service import cached_weather_service


class ComparisonService:
    """Compare weather between two locations (or days)."""

    async def compare_locations(
        self,
        lat_a: float,
        lon_a: float,
        lat_b: float,
        lon_b: float,
        name_a: str | None = None,
        name_b: str | None = None,
        day_offset: int = 0,
    ) -> ComparisonResponse:
        """Compare forecast conditions for two locations on a given day."""
        forecast_a, forecast_b = await self._fetch_both(lat_a, lon_a, lat_b, lon_b)
        label_a = name_a or forecast_a.location.name
        label_b = name_b or forecast_b.location.name

        day_a = self._day(forecast_a, day_offset)
        day_b = self._day(forecast_b, day_offset)
        if day_a is None or day_b is None:
            return ComparisonResponse(
                location_a=label_a,
                location_b=label_b,
                summary="Forecast data for comparison could not be retrieved.",
            )

        temp_diff = None
        if day_a.temperature_max is not None and day_b.temperature_max is not None:
            temp_diff = round(day_a.temperature_max - day_b.temperature_max, 1)

        summary = self._summarize(label_a, label_b, day_a, day_b, temp_diff)
        return ComparisonResponse(
            location_a=label_a,
            location_b=label_b,
            summary=summary,
            temperature_diff_c=temp_diff,
            precipitation_probability_a=day_a.precipitation_probability,
            precipitation_probability_b=day_b.precipitation_probability,
            wind_speed_a=day_a.wind_speed_max,
            wind_speed_b=day_b.wind_speed_max,
            condition_a=day_a.condition,
            condition_b=day_b.condition,
        )

    def _summarize(self, label_a, label_b, day_a, day_b, temp_diff) -> str:
        """Build a natural-language comparison summary from real values."""
        parts: list[str] = []
        if temp_diff is not None and abs(temp_diff) >= 1:
            warmer, cooler = (label_a, label_b) if temp_diff > 0 else (label_b, label_a)
            parts.append(
                f"{warmer} is expected to be about {abs(temp_diff):.0f}°C warmer than {cooler}"
            )
        else:
            parts.append(f"{label_a} and {label_b} have similar expected temperatures")
        prob_a = day_a.precipitation_probability
        prob_b = day_b.precipitation_probability
        if prob_a is not None and prob_b is not None and abs(prob_a - prob_b) >= 15:
            wetter = label_a if prob_a > prob_b else label_b
            parts.append(f"{wetter} has a higher chance of rain")
        cond_a = day_a.condition
        cond_b = day_b.condition
        if cond_a and cond_b and cond_a != cond_b:
            parts.append(f"{label_a}: {cond_a.lower()} vs {label_b}: {cond_b.lower()}")
        return ". ".join(parts) + "."

    async def _fetch_both(self, lat_a, lon_a, lat_b, lon_b):
        """Fetch both forecasts concurrently."""
        import asyncio

        results = await asyncio.gather(
            cached_weather_service.get_forecast(lat_a, lon_a, days=1 + 1),
            cached_weather_service.get_forecast(lat_b, lon_b, days=1 + 1),
            return_exceptions=True,
        )
        from app.services.weather_service import WeatherProviderError

        ok = []
        for r in results:
            if isinstance(r, WeatherProviderError):
                raise r
            if isinstance(r, BaseException):
                raise WeatherProviderError("Weather data unavailable for comparison.")
            ok.append(r)
        return ok[0], ok[1]

    def _day(self, forecast: ForecastResponse, day_offset: int):
        """Get the daily point for a day offset."""
        if forecast.forecast and 0 <= day_offset < len(forecast.forecast):
            return forecast.forecast[day_offset]
        return None


comparison_service = ComparisonService()
