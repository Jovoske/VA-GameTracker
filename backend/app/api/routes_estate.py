"""Estate config — map center, etc."""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import settings
from app.models import User

router = APIRouter(tags=["estate"])


@router.get("/estate")
def estate(_: User = Depends(get_current_user)) -> dict:
    return {
        "name": settings.estate_name,
        "lat": settings.estate_lat,
        "lng": settings.estate_lon,
        "timezone": settings.estate_timezone,
    }
