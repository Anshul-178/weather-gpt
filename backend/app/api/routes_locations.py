"""Location API routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.database import get_db
from app.models.user import User
from app.schemas.location import LocationCreate, LocationResponse
from app.services.auth_service import get_current_user
from app.services.location_service import location_service
from app.services.weather_service import WeatherProviderError
from app.utils.validation import ValidationError as AppValidationError

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("/search")
async def search_locations(query: str):
    """Search places by name."""
    try:
        return await location_service.search(query)
    except WeatherProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except AppValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("", response_model=list[LocationResponse])
async def list_locations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List saved locations for the authenticated user."""
    return await location_service.list_saved(user.id, db)


@router.post(
    "",
    response_model=LocationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_location(
    body: LocationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save a location for the authenticated user."""
    return await location_service.save(user.id, body, db)


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_location(
    location_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a saved location."""
    await location_service.delete(user.id, location_id, db)
