"""The cameras as the map shows them: each one's latest photo, what is new to you,
and what came past it last night.

WeHunt puts every trail camera on the map as its latest photo with a count of the
new ones. Here that is one call for the whole map rather than one per camera, and it
follows the app's rules for what counts: hidden species and photos marked "nothing
in it" never show or count, and last night is counted in visits, so a burst of three
frames of one boar is one visit, not three.

The map is stricter than the Photos feed in one way: a frame the detector hasn't
checked yet is not a camera's map photo, not "new" and not a visit. Most frames turn
out empty, and a badge that jumps to 30 on a windy afternoon, then drops back when
the detector catches up, promised animals that were never there.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

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
# New also means recent: taken no more than this before the newest photo you had
# seen. A camera out of signal can deliver a few days late, and those photos are
# news; a history import (a new account's two months, an admin backfill) is not.
NEW_GRACE = timedelta(days=3)
# Past this the badge says "99+". Nobody reads the difference between 140 and 180.
NEW_CAP = 99
# Nights run 18:00 to 06:00 local time.
NIGHT_START, NIGHT_END = time(18), time(6)
WATCHED = ("CONFIRMED", "PRESUMED_UP")

# An animal photo the detector has checked and kept (or a hunter marked as not
# empty), with something in it that is not a hidden species.
CHECKED_ANIMAL = and_(Image.is_empty_frame.is_(False), VISIBLE_ANIMAL)


def seen_mark(camera_id):
    """What opening a camera records: the arrival stamp of its newest photo.

    Not the clock at the moment of opening. A photo's arrival stamp is when the
    transaction that stored it began, and a sync can run for a minute before its
    photos appear, so a photo you could not have seen yet may carry a stamp from
    before you looked. The camera's newest arrival you can see is what you could
    have seen; one camera's photos are stored by one sync at a time, so anything
    still on its way is stamped above it. A camera with nothing yet marks the start
    of the never-opened window, which every later photo is past.
    """
    newest = select(func.max(Image.created_at)).where(Image.camera_id == camera_id)
    return func.coalesce(newest.scalar_subquery(), func.now() - NEW_WINDOW)


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
    rule). Only frames inside the night window count, only checked animal photos,
    and never a hidden species. A kept photo nobody has named yet (the species pass
    hasn't reached it, or couldn't name it) is an "Animal", the same word its tile
    and the camera's map photo use, so the sheet never shows last night's photo
    under a line saying nothing came.
    """
    if not camera_ids:
        return {}
    start, end = night_window(night)
    # The photo's sightings of species that are not hidden; a photo without one
    # joins to nothing and is an unnamed animal.
    named = (
        select(Detection.image_id, Detection.species_id, Species.common_name)
        .join(Species, Species.id == Detection.species_id)
        .where(Species.hidden.is_(False))
        .subquery()
    )
    frames = (
        select(
            Image.camera_id,
            named.c.species_id,
            named.c.common_name,
            Image.captured_at,
            func.lag(Image.captured_at)
            .over(partition_by=(Image.camera_id, named.c.species_id), order_by=Image.captured_at)
            .label("prev_at"),
        )
        .select_from(Image)
        .outerjoin(named, named.c.image_id == Image.id)
        .where(
            Image.camera_id.in_(camera_ids),
            Image.captured_at >= start,
            Image.captured_at < end,
            CHECKED_ANIMAL,
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
            # The Photos tiles' word for it: "Wild boar", not the stored "Wild Boar";
            # an unnamed animal is "Animal".
            "label": class_label(r.species_id, r.common_name, None, None),
            "visits": int(r.visits or 0),
        })
    return out


def night_frames(db: Session, camera_ids: list, night: date) -> dict:
    """{camera_id: (frames, unchecked)} inside the night window.

    Every frame the camera sent, empty ones included (they are the proof it was
    awake), and how many are still waiting for the detector: a photo that neither
    it nor a hunter has called empty or kept, the ones CHECKED_ANIMAL can't judge.
    """
    if not camera_ids:
        return {}
    start, end = night_window(night)
    unchecked = and_(Image.is_empty_frame.is_(None), Image.original_path.isnot(None))
    rows = db.execute(
        select(Image.camera_id, func.count(Image.id), func.count(Image.id).filter(unchecked))
        .where(Image.camera_id.in_(camera_ids), Image.captured_at >= start, Image.captured_at < end)
        .group_by(Image.camera_id)
    ).all()
    return {r[0]: (int(r[1]), int(r[2])) for r in rows}


def night_status(state: str | None, frames: int, unchecked: int) -> str | None:
    """How far to trust last night's list, as one word the sheet turns into a sentence.

    checking    some of the night's frames haven't been through the detector yet
    incomplete  it sent frames but ran out of photo credits, so not all of them
    watched     it was working, so an empty list is a quiet night
    blind       it sent nothing and may not have been working
    None        no record either way

    The frames themselves win over camera_nights, which is rebuilt only hourly: at
    06:30 last night's row can be missing or still say UNPROCESSED.
    """
    if unchecked:
        return "checking"
    if frames:
        # Checked frames prove the camera was awake. Only a camera that ran out of
        # credits partway (the one way exposure says UNKNOWN with frames) sent less
        # than it saw.
        return "incomplete" if state == "UNKNOWN" else "watched"
    if state is None:
        return None
    return "watched" if state in WATCHED else "blind"


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

    `latest` is the newest checked animal photo, or null. `new_count` is how many
    such photos arrived after the newest one you had when you last opened the camera
    (POST /cameras/{id}/seen), or in the last 24 hours if you never have; only
    photos taken since a few days before that count, and it stops at 99. `last_night`
    is the most recent finished night, in visits; `last_night_status` says how far
    to trust it (see night_status), so an empty list is not read as a quiet night
    when the camera was down or its photos are still being checked.
    """
    night = last_completed_night()
    since = func.coalesce(CameraView.seen_at, func.now() - NEW_WINDOW)
    arrivals = (
        select(Image.id)
        .where(
            Image.camera_id == Camera.id,
            Image.created_at > since,
            Image.captured_at > since - NEW_GRACE,
            Image.original_path.isnot(None),
            CHECKED_ANIMAL,
        )
        # Counting stops past the cap: the badge says "99+" either way, and someone
        # who hasn't looked for a month doesn't cost a scan of the month.
        .limit(NEW_CAP + 1)
        .correlate(Camera, CameraView)
        .subquery()
    )
    fresh = select(func.count()).select_from(arrivals).scalar_subquery()
    # Newest first by the (camera_id, captured_at) index: one row per camera.
    latest = (
        select(Image.id)
        .where(Image.camera_id == Camera.id, Image.original_path.isnot(None), CHECKED_ANIMAL)
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

    ids = [r.Camera.id for r in rows]
    photos = latest_photos(db, [r.latest_id for r in rows if r.latest_id])
    visits = last_night_visits(db, ids, night)
    sent = night_frames(db, ids, night)
    now = datetime.now(UTC)
    can_rename = user.role in {"admin", "member"}
    out = []
    for r in rows:
        c = r.Camera
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
            "last_night_status": night_status(r.exposure_state, *sent.get(c.id, (0, 0))),
        })
    return out
