"""Activity analytics + a data-grounded tonight suggestion (no faked ML)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import Integer, cast, extract, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.visibility import VISIBLE_ANIMAL, VISIBLE_SIGHTING
from app.core.config import settings
from app.core.db import get_db
from app.enrichment.astro import moon_phase, solar
from app.forecasting.exposure import night_expr
from app.models import Camera, Detection, Image, Species, User

router = APIRouter(prefix="/analytics", tags=["analytics"])

# Animal frames, minus photos of nothing but hidden species (see visibility.py).
_ANIMAL = VISIBLE_ANIMAL
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
    """The photo counts behind Tonight's fold, from cameras nobody retired (the plan
    leaves those out, so its numbers do too)."""
    kept = Camera.retired_at.is_(None)
    frames = select(Image.id).join(Camera, Camera.id == Image.camera_id).where(kept)
    empties = db.scalar(
        select(func.count()).select_from(
            frames.where(Image.is_empty_frame.is_(True)).subquery())
    ) or 0
    oldest, newest, nights = db.execute(
        # Nights by the app's night key: a visit either side of midnight is one night.
        select(func.min(Image.captured_at), func.max(Image.captured_at),
               func.count(func.distinct(night_expr())))
        .join(Camera, Camera.id == Image.camera_id).where(kept)
    ).one()

    # One pass over the animal photos, grouped by camera and local hour, then summed
    # here. The visibility test is the expensive part (an EXISTS per photo), and the
    # total, the hours and the cameras used to run it three times over (audit G-19).
    # By camera id: two cameras that share a name are still two rows.
    h = _local_hour().label("h")
    rows = db.execute(
        select(Camera.id, Camera.name, h, func.count(Image.id))
        .select_from(Image)
        .join(Camera, Camera.id == Image.camera_id)
        .where(_ANIMAL, kept)
        .group_by(Camera.id, Camera.name, h)
    ).all()
    sightings = 0
    by_hour: dict[int, int] = {}
    per_camera: dict = {}
    for cam_id, name, hr, c in rows:
        sightings += int(c)
        by_hour[int(hr)] = by_hour.get(int(hr), 0) + int(c)
        entry = per_camera.setdefault(cam_id, {"id": str(cam_id), "name": name, "sightings": 0})
        entry["sightings"] += int(c)
    hours = [{"hour": i, "count": by_hour.get(i, 0)} for i in range(24)]
    by_camera = sorted(per_camera.values(), key=lambda e: (-e["sightings"], e["name"]))

    # A photo marked "nothing in it" keeps its sighting row (so keeping it again
    # brings it back); it is not counted while it is marked.
    sp_rows = db.execute(
        select(Species.common_name, func.count(Detection.id))
        .join(Detection, Detection.species_id == Species.id)
        .join(Image, Image.id == Detection.image_id)
        .join(Camera, Camera.id == Image.camera_id)
        .where(VISIBLE_SIGHTING, kept)
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
