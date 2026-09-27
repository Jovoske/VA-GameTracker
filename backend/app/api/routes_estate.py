"""Estate config — map center, and the box the map keeps on a phone for no signal."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import estate_area
from app.api.deps import get_current_admin, get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.models import User

router = APIRouter(tags=["estate"])
DB = Annotated[Session, Depends(get_db)]


def _box_out(db: Session) -> dict:
    saved = estate_area.saved_box(db)
    box = saved or estate_area.suggested_box(db)
    ew, ns = estate_area.side_m(box)
    return {
        "box": {k: box[k] for k in ("south", "west", "north", "east")},
        # False: drawn round the stands, cameras and bedding, as nobody has set one.
        "box_set": saved is not None,
        "box_set_at": saved.get("set_at") if saved else None,
        "box_km": [round(ew / 1000, 1), round(ns / 1000, 1)],
    }


@router.get("/estate")
def estate(_: Annotated[User, Depends(get_current_user)], db: DB) -> dict:
    """The estate's name, centre and time zone, and `box`: the ground the map saves
    on a phone for use with no signal (south, west, north, east). An admin's box when
    one is set (`box_set`), else one round everything placed, with a margin."""
    return {
        "name": settings.estate_name,
        "lat": settings.estate_lat,
        "lng": settings.estate_lon,
        "timezone": settings.estate_timezone,
        **_box_out(db),
    }


class BoxBody(BaseModel):
    south: float
    west: float
    north: float
    east: float


@router.put("/estate/box")
def set_box(body: BoxBody, user: Annotated[User, Depends(get_current_admin)], db: DB) -> dict:
    """Set the estate's box (admins): what everyone's "Download the estate" saves.
    Refused in words past 15 km across, where it stops being one estate on a phone."""
    try:
        estate_area.save_box(db, body.model_dump(), by=user.email)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _box_out(db)


@router.delete("/estate/box")
def clear_box(_: Annotated[User, Depends(get_current_admin)], db: DB) -> dict:
    """Back to the box drawn round everything placed (admins)."""
    estate_area.clear_box(db)
    return _box_out(db)
