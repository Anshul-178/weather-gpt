"""Location service.

Combines geocoding search (via the weather provider) with saved-location
persistence for authenticated users.
"""

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.location import Location
from app.schemas.location import GeocodeResult, GeocodeResponse, LocationCreate
from app.services.cached_weather_service import cached_weather_service
from app.utils.logging import get_logger

logger = get_logger(__name__)


class LocationService:
    """Geocoding + saved locations."""

    async def search(self, query: str) -> GeocodeResponse:
        """Search places by name (cached geocoding)."""
        from app.utils.validation import validate_place_name

        cleaned = validate_place_name(query)
        results = await cached_weather_service.geocode(cleaned)
        return GeocodeResponse(
            results=[
                GeocodeResult(
                    name=item.name,
                    latitude=item.latitude,
                    longitude=item.longitude,
                    country=item.country,
                    admin1=item.admin1,
                )
                for item in results
            ]
        )

    async def resolve(
        self,
        latitude: Optional[float],
        longitude: Optional[float],
        name: Optional[str] = None,
    ) -> tuple[float, float, str]:
        """Resolve a request into (lat, lon, display_name).

        Priority: explicit coordinates > geocode name > default (Kanpur).
        """
        if latitude is not None and longitude is not None:
            display = name or f"{latitude:.2f}, {longitude:.2f}"
            return latitude, longitude, display
        if name:
            results = await cached_weather_service.geocode(name)
            if results:
                first = results[0]
                return first.latitude, first.longitude, self.display_name(first)
        # Sensible default location (product's home city) when nothing provided.
        return 26.4499, 80.3319, "Kanpur"

    def display_name(self, geo) -> str:
        """Format a geocode result for display."""
        parts = [geo.name]
        if geo.admin1 and geo.admin1 != geo.name:
            parts.append(geo.admin1)
        if geo.country:
            parts.append(geo.country)
        return ", ".join(parts)

    async def list_saved(self, user_id: int, db: AsyncSession) -> list[Location]:
        """List saved locations for a user."""
        result = await db.execute(
            select(Location).where(Location.user_id == user_id).order_by(Location.id)
        )
        return list(result.scalars().all())

    async def save(
        self, user_id: int, data: LocationCreate, db: AsyncSession
    ) -> Location:
        """Save a location for a user."""
        location = Location(
            user_id=user_id, name=data.name.strip(), latitude=data.latitude,
            longitude=data.longitude,
        )
        db.add(location)
        await db.commit()
        await db.refresh(location)
        return location

    async def delete(self, user_id: int, location_id: int, db: AsyncSession) -> None:
        """Delete a saved location owned by the user (404 if not found)."""
        result = await db.execute(
            delete(Location).where(
                Location.id == location_id, Location.user_id == user_id
            )
        )
        if result.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Location not found"
            )
        await db.commit()


location_service = LocationService()
