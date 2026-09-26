"""The cameras as the map shows them: each one's latest photo, what is new to you,
and what came past it last night.

WeHunt puts every trail camera on the map as its latest photo with a count of the
new ones. Here that is one call for the whole map rather than one per camera, and it
follows the app's rules for what counts: hidden species and photos marked "nothing
in it" never show or count, and last night is counted in visits, so a burst of three
frames of one boar is one visit, not three.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_current_user
from app.api.routes_stands import tonight
from app.api.visibility import VISIBLE_ANIMAL
from app.core.config import settings
from app.core.db import get_db
from app.forecasting.exposure import VISIT_GAP
from app.forecasting.model import class_label
from app.health import camera_health
from app.models import Camera, CameraNight, CameraView, Detection, Image, Species, User

router = APIRouter(prefix="/map", tags=["map"])

# A camera you have never opened counts what arrived in the last day, not its whole
# history: a new hunter's first look at the map shouldn't read "99+" everywhere.
NEW_WINDOW = timedelta(hours=24)
# Past this the badge says "99+". Nobody reads the difference between 140 and 180.
NEW_CAP = 99
# Nights run 18:00 to 06:00 local time.
NIGHT_START, NIGHT_END = time(18), time(6)
WATCHED = ("CONFIRMED", "PRESUMED_UP")


def last_completed_night(now: datetime | None = None) -> date:
    """The evening date of the most recent night that has finished (06:00 has passed)."""
    return tonight(now) - timedelta(days=1)


def night_window(night: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.estate_timezone)
    return (
        datetime.combine(night, NIGHT_START, tzinfo=tz),
        datetime.combine(night + timedelta(days=1), NIGHT_END, tzinfo=tz),
    )


def last_night_visits(db: Session, camera_ids: list, night: date) -> dict:
    """{camera_id: [{species_id, label, visits}]}, busiest first.

    A visit is an arrival: frames of the same species at the same camera within
    VISIT_GAP of the previous one are the same visit (exposure.visits_by_night's
    rule). Only frames inside the night window count, only visible photos, and
    never a hidden species.
    """
    if not camera_ids:
        return {}
    start, end = night_window(night)
    # Aliased, so VISIBLE_ANIMAL's own subqueries on detections/species stay about
    # the photo as a whole and are not tied to this row's detection.
    det, sp = aliased(Detection), aliased(Species)
    frames = (
        select(
            Image.camera_id,
            det.species_id,
            sp.common_name,
            Image.captured_at,
            func.lag(Image.captured_at)
            .over(partition_by=(Image.camera_id, det.species_id), order_by=Image.captured_at)
            .label("prev_at"),
        )
        .select_from(det)
        .join(Image, Image.id == det.image_id)
        .outerjoin(sp, sp.id == det.species_id)
        .where(
            Image.camera_id.in_(camera_ids),
            Image.captured_at >= start,
            Image.captured_at < end,
            VISIBLE_ANIMAL,
            or_(det.species_id.is_(None), sp.hidden.is_(False)),
        )
        .subquery()
    )
    arrival = case(
        (or_(frames.c.prev_at.is_(None), frames.c.captured_at - frames.c.prev_at > VISIT_GAP), 1),
        else_=0,
    )
    visits = func.sum(arrival).label("visits")
    rows = db.execute(
        select(frames.c.camera_id, frames.c.species_id, frames.c.common_name, visits)
        .group_by(frames.c.camera_id, frames.c.species_id, frames.c.common_name)
        .order_by(visits.desc(), frames.c.common_name)
    ).all()
    out: dict = {}
    for r in rows:
        out.setdefault(r.camera_id, []).append({
            "species_id": r.species_id,
            "label": r.common_name or "Animal",
            "visits": int(r.visits or 0),
        })
    return out


def latest_photos(db: Session, image_ids: list) -> dict:
    """{image_id: {image_id, captured_at, species_id, label}} for the cameras' newest photos.

    The label is the photo's surest sighting of a species that is not hidden, the
    same choice the Photos feed makes for its tiles; a photo nobody has named yet
    is an "Animal".
    """
    if not image_ids:
        return {}
    rows = db.execute(
        select(Image.id, Image.captured_at, Detection.species_id, Species.common_name,
               Species.hidden, Detection.sex, Detection.group_type)
        .outerjoin(Detection, Detection.image_id == Image.id)
        .outerjoin(Species, Species.id == Detection.species_id)
        .where(Image.id.in_(image_ids))
        .order_by(Detection.species_conf.desc().nullslast())
    ).all()
    out: dict = {}
    for r in rows:
        named = r.species_id is not None and r.hidden is False
        if r.id in out and (out[r.id]["species_id"] or not named):
            continue  # the first named sighting per photo is the surest
        out[r.id] = {
            "image_id": str(r.id),
            "captured_at": r.captured_at,
            "species_id": r.species_id if named else None,
            "label": class_label(r.species_id, r.common_name, r.sex, r.group_type)
            if named else "Animal",
        }
    return out


@router.get("/cameras")
def map_cameras(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    """Every camera with what the map draws for it and what its sheet opens with.

    `latest` is the newest photo worth showing, or null. `new_count` is how many
    photos arrived since *you* last opened the camera (POST /cameras/{id}/seen), or
    in the last 24 hours if you never have, capped at 99. `last_night` is the most
    recent finished night, in visits; `last_night_watched` says whether the camera
    was demonstrably working that night (null when there is no record either way),
    so an empty list is not read as a quiet night when the camera was down.
    """
    night = last_completed_night()
    seen = func.coalesce(CameraView.seen_at, func.now() - NEW_WINDOW)
    fresh = (
        select(func.count(Image.id))
        .where(
            Image.camera_id == Camera.id,
            Image.created_at > seen,
            Image.original_path.isnot(None),
            VISIBLE_ANIMAL,
        )
        .scalar_subquery()
    )
    # Newest first by the (camera_id, captured_at) index: one row per camera.
    latest = (
        select(Image.id)
        .where(Image.camera_id == Camera.id, Image.original_path.isnot(None), VISIBLE_ANIMAL)
        .order_by(Image.captured_at.desc(), Image.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    mine = and_(CameraView.camera_id == Camera.id, CameraView.user_id == user.id)
    that_night = and_(CameraNight.camera_id == Camera.id, CameraNight.night == night)
    rows = db.execute(
        select(Camera, fresh.label("fresh"), latest.label("latest_id"), CameraNight.exposure_state)
        .outerjoin(CameraView, mine)
        .outerjoin(CameraNight, that_night)
        .where(Camera.estate_id == user.estate_id)
        .order_by(Camera.name)
    ).all()

    photos = latest_photos(db, [r.latest_id for r in rows if r.latest_id])
    visits = last_night_visits(db, [r.Camera.id for r in rows], night)
    now = datetime.now(UTC)
    can_rename = user.role in {"admin", "member"}
    out = []
    for r in rows:
        c = r.Camera
        state = r.exposure_state
        out.append({
            "id": str(c.id),
            "name": c.name,
            "lat": c.lat,
            "lon": c.lon,
            "battery_pct": c.battery_pct,
            "signal_pct": c.signal_pct,
            "last_report_at": c.last_report_at,
            "health": camera_health(c, now),
            "can_rename": can_rename,
            "latest": photos.get(r.latest_id),
            "new_count": min(int(r.fresh or 0), NEW_CAP),
            "last_night": visits.get(c.id, []),
            "last_night_watched": None if state is None else state in WATCHED,
        })
    return out
