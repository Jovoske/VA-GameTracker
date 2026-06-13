"""Activity analytics + a data-grounded tonight suggestion (no faked ML)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import Integer, cast, extract, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.enrichment.astro import moon_phase, solar
from app.models import Camera, Detection, Image, Species, User

router = APIRouter(prefix="/analytics", tags=["analytics"])

_ANIMAL = Image.is_empty_frame.isnot(True)
_TZ = settings.estate_timezone


def _local_hour():
    return cast(extract("hour", func.timezone(_TZ, Image.captured_at)), Integer)


def _best_window(by_hour: dict[int, int]) -> dict:
    total = sum(by_hour.values()) or 1
    best_start, best_sum = 0, -1
    for start in range(24):
        block = sum(by_hour.get((start + d) % 24, 0) for d in range(3))
        if block > best_sum:
            best_start, best_sum = start, block
    return {
        "start_hour": best_start,
        "end_hour": (best_start + 3) % 24,
        "share_pct": round(best_sum / total * 100),
    }


@router.get("/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    sightings = db.scalar(select(func.count(Image.id)).where(_ANIMAL)) or 0
    empties = db.scalar(select(func.count(Image.id)).where(Image.is_empty_frame.is_(True))) or 0
    oldest = db.scalar(select(func.min(Image.captured_at)))
    newest = db.scalar(select(func.max(Image.captured_at)))
    nights = db.scalar(
        select(func.count(func.distinct(func.date(func.timezone(_TZ, Image.captured_at)))))
    ) or 0

    h = _local_hour().label("h")
    hour_rows = db.execute(select(h, func.count()).where(_ANIMAL).group_by(h)).all()
    by_hour = {int(hr): int(c) for hr, c in hour_rows}
    hours = [{"hour": i, "count": by_hour.get(i, 0)} for i in range(24)]

    cam_rows = db.execute(
        select(Camera.name, func.count(Image.id))
        .join(Image, Image.camera_id == Camera.id)
        .where(_ANIMAL)
        .group_by(Camera.name)
        .order_by(func.count(Image.id).desc())
    ).all()
    by_camera = [{"name": n, "sightings": int(c)} for n, c in cam_rows]

    sp_rows = db.execute(
        select(Species.common_name, func.count(Detection.id))
        .join(Detection, Detection.species_id == Species.id)
        .group_by(Species.common_name)
        .order_by(func.count(Detection.id).desc())
    ).all()
    by_species = [{"species": n, "count": int(c)} for n, c in sp_rows]

    now = datetime.now(timezone.utc)
    phase, illum = moon_phase(now)
    s = solar(settings.estate_lat, settings.estate_lon, now.date())

    return {
        "totals": {
            "sightings": sightings, "empty": empties, "nights": nights,
            "cameras": len(by_camera), "oldest": oldest, "newest": newest,
        },
        "by_hour": hours,
        "by_camera": by_camera,
        "by_species": by_species,
        "best_window": _best_window(by_hour),
        "tonight": {
            "moon_phase": phase,
            "moon_illum": illum,
            "sunset": s.get("sunset"),
            "darkness_minutes": s.get("darkness_minutes"),
            "most_active_camera": by_camera[0]["name"] if by_camera else None,
        },
    }
