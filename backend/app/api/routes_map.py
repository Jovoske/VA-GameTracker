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
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes_stands import tonight
from app.core.config import settings
from app.core.db import get_db
from app.forecasting.activity import activity, replay, replay_nights
from app.forecasting.model import class_label
from app.forecasting.visits import CHECKED_ANIMAL, visit_rows
from app.health import camera_health
from app.models import Camera, CameraNight, CameraView, Detection, Image, Species, User

router = APIRouter(prefix="/map", tags=["map"])
CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]

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

    Visits come from visits.visit_rows, the rule the activity map and the replay
    count with, so the three agree: frames of the same species at the same camera
    within VISIT_GAP of the previous one are the same visit. Only frames inside the
    night window count, only checked animal photos, and never a hidden species. A
    kept photo nobody has named yet (the species pass hasn't reached it, or couldn't
    name it) is an "Animal", the same word its tile and the camera's map photo use,
    so the sheet never shows last night's photo under a line saying nothing came.
    """
    if not camera_ids:
        return {}
    start, end = night_window(night)
    v = visit_rows(start=start, end=end, camera_ids=camera_ids)
    visits = func.count().label("visits")
    rows = db.execute(
        select(v.c.camera_id, v.c.species_id, v.c.common_name, visits)
        .group_by(v.c.camera_id, v.c.species_id, v.c.common_name)
        .order_by(visits.desc(), v.c.common_name)
    ).all()
    out: dict = {}
    for r in rows:
        out.setdefault(r.camera_id, []).append({
            "species_id": r.species_id,
            # The Photos tiles' word for it: "Wild boar", not the stored "Wild Boar";
            # an unnamed animal is "Animal".
            "label": class_label(r.species_id, r.common_name, None, None),
            "visits": int(r.visits),
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
def map_cameras(user: CurrentUser, db: DB) -> list[dict]:
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


# ── activity and replay ─────────────────────────────────────────────────────

PERIODS = (1, 7, 30)


def _estate_cameras(db: Session, user: User) -> list[Camera]:
    return list(db.scalars(
        select(Camera).where(Camera.estate_id == user.estate_id).order_by(Camera.name)
    ).all())


@router.get("/activity")
def map_activity(
    user: CurrentUser,
    db: DB,
    species: Annotated[str, Query(max_length=64)] = "all",
    part: Literal["dusk", "night", "dawn", "all"] = "all",
    nights: int = 7,
) -> dict:
    """Where the game is: visits per watched night at each camera.

    `nights` is 1 (the last finished night), 7 or 30, counted back from last
    night. `part` is dusk 18-22, night 22-03, dawn 03-08 or all of 18-08, by local
    hour. `species` is a species id or "all". Per camera: visits, the nights it was
    watching (watched_nights) and how many of those had a visit (nights_with),
    per_night (null when it watched none), the busiest two hours (peak, '21–23'),
    the species behind the count, and `read`, the line the map leads with. Nights a
    camera wasn't working are left out, never counted as quiet. Any role.
    """
    if nights not in PERIODS:
        raise HTTPException(422, "nights is 1, 7 or 30.")
    label = None
    if species != "all":
        sp = db.get(Species, species)
        # A hidden species is out of the app altogether, filters included.
        if sp is None or sp.hidden:
            raise HTTPException(404, "No such species.")
        label = class_label(sp.id, sp.common_name, None, None)
    return activity(
        db, cameras=_estate_cameras(db, user), last_night=last_completed_night(),
        nights=nights, part=part, species=None if species == "all" else species,
        species_label=label,
    )


@router.get("/replay/nights")
def map_replay_nights(
    user: CurrentUser, db: DB, limit: Annotated[int, Query(ge=1, le=60)] = 14,
) -> list[dict]:
    """The last `limit` finished nights, newest first, each with its number of visits
    (18:00-08:00, every camera and species). Any role."""
    return replay_nights(
        db, cameras=_estate_cameras(db, user), last_night=last_completed_night(), limit=limit,
    )


@router.get("/replay")
def map_replay(user: CurrentUser, db: DB, night: date) -> dict:
    """One night, 18:00 to 08:00 local, as the map replays it.

    `visits` are in time order: when (`at`, `last_at`), where, what (`label`,
    `group_size`, the largest group in the visit) and the first frame's image_id for
    its thumbnail. `links` join consecutive visits of the same species at two
    different cameras within three hours, when the animals could have walked it: a
    guess at where they went, and the map says so. Any role.
    """
    return replay(db, cameras=_estate_cameras(db, user), night=night)
