"""Camera routes — list (with location), images, sync/backfill/scan, review, map placement."""
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import geo, jobs
from app.api.deps import get_current_admin, get_current_user
from app.api.routes_map import seen_mark
from app.api.routes_photos import _items, after_cursor
from app.api.visibility import VISIBLE_ANIMAL
from app.core.db import get_db
from app.health import camera_health
from app.ingestion.logins import camera_logins
from app.models import Camera, CameraView, Image, User

router = APIRouter(prefix="/cameras", tags=["cameras"])


# ── background jobs ───────────────────────────────────────────
# The Docker build queued these to Celery; the native build has no broker. The buttons
# start `pipeline.py` as a process of its own (app.jobs.spawn), under the same lock
# as the scheduled runs, so the AI models never load into the web server and a press
# can never overlap the 15-min sync.
FETCH_REQUEST = "fetch_request"  # app_settings: when the Check button last asked
# How long a requested check reads as "running" before its process has taken the lock.
REQUEST_GRACE = timedelta(minutes=2)


def _pipeline_busy() -> bool:
    return jobs.holder("pipeline") is not None


# What a job that holds the photo fetch up is doing, in words, by its lock's owner.
BUSY_WITH = {
    "reid": "looking for repeat visitors",
    "plan": "writing tonight’s plan",
    "score": "checking last night’s plan against the cameras",
    "scan": "checking photos for animals",
}


def _busy_words() -> str:
    """Why a one-off can't start now, in words: what holds the lock."""
    holder = jobs.holder("pipeline")
    what = "fetching photos" if holder is None or holder.owner in jobs.FETCH_MODES else (
        BUSY_WITH.get(holder.owner, "busy with another job"))
    return f"The server is {what}. Try again in a few minutes."


def _lock_started() -> datetime | None:
    """When the run holding the pipeline lock began, or None when nothing holds it."""
    return jobs.busy_since("pipeline")


def _start(db: Session, mode: str, *args: str) -> None:
    """Start a pipeline job, or say in words that it could not be started."""
    if not jobs.spawn(mode, *args):
        raise HTTPException(503, "Could not start it on the server. Try again in a minute.")


# How long a camera's photos take to reach the app: the middle one of its last
# UPLOAD_SAMPLE that say when they were received (FTP and email), with at least
# UPLOAD_MIN_PHOTOS of them. A clock an hour slow shows as photos an hour late, which
# the import can't tell from a slow upload; one ahead is put right there (audit H-17).
UPLOAD_SAMPLE = 50
UPLOAD_MIN_PHOTOS = 5


def _upload_delays(db: Session, camera_ids: list) -> dict:
    """Minutes from capture to receipt, per camera, the median of its recent photos."""
    if not camera_ids:
        return {}
    lag = func.extract("epoch", Image.received_at - Image.captured_at) / 60
    recent = (
        select(Image.camera_id, lag.label("lag"), func.row_number().over(
            partition_by=Image.camera_id, order_by=Image.received_at.desc()).label("n"))
        # A photo filed at its receipt time (no camera time to go on) says nothing.
        .where(Image.camera_id.in_(camera_ids), Image.received_at.is_not(None),
               Image.received_at != Image.captured_at)
        .subquery()
    )
    rows = db.execute(
        select(recent.c.camera_id, func.percentile_cont(0.5).within_group(recent.c.lag),
               func.count())
        .where(recent.c.n <= UPLOAD_SAMPLE)
        .group_by(recent.c.camera_id)
    ).all()
    return {cam: round(median) for cam, median, n in rows if n >= UPLOAD_MIN_PHOTOS}


@router.get("")
def list_cameras(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    """The estate's cameras, each with its photo counts as the strip shows them.

    The strip lists `animal_count` + `unchecked_count` photos: the checked ones with
    an animal in them (not only a hidden animal, with a picture), and the ones the AI
    has not checked yet (or couldn't), which are often grass, so they are counted
    apart. `empty_count` is the "nothing in it" ones "Show empty photos" brings up.
    They used to be every frame minus the empty ones, so hidden rabbits and frames
    not checked yet counted as animals, and it took four queries a camera; now it is
    one for them all.
    """
    rows = db.scalars(
        select(Camera).where(Camera.estate_id == user.estate_id).order_by(Camera.name)
    ).all()
    now = datetime.now(UTC)
    login_states = camera_logins(db, rows, now)
    has_file = Image.original_path.isnot(None)
    counts = {r.camera_id: r for r in db.execute(
        select(
            Image.camera_id,
            func.max(Image.captured_at).label("last"),
            func.count(Image.id).label("count"),
            func.count(Image.id).filter(
                has_file, Image.is_empty_frame.is_(False), VISIBLE_ANIMAL).label("animals"),
            func.count(Image.id).filter(
                has_file, Image.is_empty_frame.is_(None), VISIBLE_ANIMAL).label("unchecked"),
            func.count(Image.id).filter(has_file, Image.is_empty_frame.is_(True)).label("empty"),
        )
        .where(Image.camera_id.in_([c.id for c in rows]))
        .group_by(Image.camera_id)
    ).all()}
    delays = _upload_delays(db, [c.id for c in rows])
    out = []
    for c in rows:
        n = counts.get(c.id)
        last, count = (n.last, n.count) if n else (None, 0)
        animals, unchecked, empty = (n.animals, n.unchecked, n.empty) if n else (0, 0, 0)
        lat = float(c.lat) if c.lat is not None else None
        lng = float(c.lon) if c.lon is not None else None
        out.append({
            "id": str(c.id), "name": c.name, "battery_pct": c.battery_pct,
            "provider_name": c.provider_name or c.name,
            "name_is_custom": c.name_is_custom,
            "can_rename": user.role in {"admin", "member"},
            "battery_level": c.battery_level,
            "signal_pct": c.signal_pct, "model": c.model, "active": c.active,
            "retired_at": c.retired_at,
            "last_sync_at": c.last_sync_at, "last_capture": last,
            "last_report_at": c.last_report_at,
            "photo_count": c.photo_count, "photo_limit": c.photo_limit,
            "plan_name": c.plan_name, "cycle_end": c.cycle_end,
            "sd_used_mb": c.sd_used_mb, "sd_total_mb": c.sd_total_mb,
            "image_count": count, "empty_count": empty, "animal_count": animals,
            "unchecked_count": unchecked,
            "sightings": animals,
            "lat": lat, "lng": lng,
            # Minutes its photos take to arrive (FTP and email cameras), or None.
            "upload_delay_min": delays.get(c.id),
            "health": camera_health(c, now, login_states.get(c.id)),
        })
    return out


class CameraNameBody(BaseModel):
    # Explicit null restores the latest provider name; omission is not a reset.
    name: str | None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value):
            raise ValueError("Camera name has hidden characters in it. Retype it.")
        value = value.strip()
        if not 1 <= len(value) <= 100:
            raise ValueError("Camera name must be 1 to 100 characters.")
        return value


@router.patch("/{camera_id}/name")
def rename_camera(
    camera_id: uuid.UUID,
    body: CameraNameBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.role not in {"admin", "member"}:
        raise HTTPException(403, "Only estate admins and members can rename cameras.")
    camera = db.scalar(select(Camera).where(
        Camera.id == camera_id, Camera.estate_id == user.estate_id,
    ).with_for_update().execution_options(populate_existing=True))
    if camera is None:
        raise HTTPException(404, "Camera not found.")
    # Local imports have no vendor label, so retain their initial name as default.
    if not camera.provider_name:
        camera.provider_name = camera.name
    name = camera.provider_name if body.name is None else body.name
    # Two cameras with one name merge into one row wherever sightings are counted by
    # camera, and nobody can tell which "Feeder" a photo came from (audit I-26).
    taken = db.scalar(select(Camera.id).where(
        Camera.estate_id == user.estate_id, Camera.id != camera.id,
        func.lower(Camera.name) == name.lower(),
    ).limit(1))
    if taken is not None:
        # Going back to the vendor's name too: two SPYPOINTs called "SPYPOINT" are the
        # same trap as two cameras a hunter called "Feeder".
        raise HTTPException(409, (
            f"Another camera is already called {name}. Pick another name."
            if body.name is not None else
            f"Another camera is already called {name}, so this one keeps its own name."
        ))
    camera.name = name
    camera.name_is_custom = body.name is not None
    db.commit()
    return {
        "id": str(camera.id), "name": camera.name,
        "provider_name": camera.provider_name,
        "name_is_custom": camera.name_is_custom, "can_rename": True,
    }


class RetireBody(BaseModel):
    retired: bool


@router.patch("/{camera_id}/retired")
def retire_camera(
    camera_id: uuid.UUID,
    body: RetireBody,
    user: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Retire a camera that was taken down, or bring it back. Admins only.

    Retired, it is left out of tonight's plan, the alerts, Insights and the track
    record, instead of topping Tonight for weeks on what it saw before it went in a
    drawer (audit K-01). Its photos stay in Photos, and its login keeps fetching.
    """
    camera = db.scalar(select(Camera).where(
        Camera.id == camera_id, Camera.estate_id == user.estate_id,
    ))
    if camera is None:
        raise HTTPException(404, "Camera not found.")
    if body.retired and camera.retired_at is None:
        camera.retired_at = datetime.now(UTC)
    elif not body.retired and camera.retired_at is not None:
        camera.retired_at = None
        db.commit()
        # Back in the plan: its nights are counted again from where they stood.
        from app.forecasting.exposure import recompute_camera_nights

        recompute_camera_nights(db, camera_id=camera.id)
    db.commit()
    return {"id": str(camera.id), "name": camera.name, "retired_at": camera.retired_at}


@router.post("/{camera_id}/seen")
def mark_seen(
    camera_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """You opened this camera: its photos so far are no longer new to you.

    Any signed-in role, viewers included: it records what this person has looked
    at, not anything about the camera. What it records is the newest arrival or
    check stamp among the camera's photos, not the time now, so a photo a running
    sync is still storing, or one the detector hasn't passed yet, counts as new
    once it shows (routes_map.seen_mark).
    """
    camera = db.scalar(select(Camera.id).where(
        Camera.id == camera_id, Camera.estate_id == user.estate_id,
    ))
    if camera is None:
        raise HTTPException(404, "Camera not found.")
    stmt = pg_insert(CameraView).values(
        user_id=user.id, camera_id=camera_id, seen_at=seen_mark(camera_id),
    )
    seen_at = db.scalar(
        stmt.on_conflict_do_update(
            index_elements=[CameraView.user_id, CameraView.camera_id],
            set_={"seen_at": stmt.excluded.seen_at},
        ).returning(CameraView.seen_at)
    )
    db.commit()
    return {"camera_id": str(camera_id), "seen_at": seen_at}


@router.post("/sync")
def trigger_sync(
    _: Annotated[User, Depends(get_current_admin)], db: Annotated[Session, Depends(get_db)],
) -> dict:
    # `since` is what the Check button waits for: a fetch summary started after it
    # is this check's result; an older one is somebody else's.
    holder = jobs.holder("pipeline")
    if holder is not None and holder.owner in jobs.FETCH_MODES:
        return {"status": "busy", "since": holder.started,
                "note": "Already checking. New photos will show shortly."}
    if jobs.holder("fetchqueue") is not None:
        asked = jobs.read_note(db, FETCH_REQUEST).get("at")
        return {"status": "queued", "since": asked,
                "note": "Already asked. New photos come in as soon as the server is free."}
    since = datetime.now(UTC)
    if holder is None:
        _start(db, "sync")
        jobs.note(db, FETCH_REQUEST, at=since)
        return {"status": "started", "since": since}
    # Something else holds the fetch up (Look for repeats, tonight's plan): the fetch
    # waits for it and runs the moment it ends. It used to say "Already checking"
    # although no fetch had been asked for, and none came.
    _start(db, "sync", "queued")
    jobs.note(db, FETCH_REQUEST, at=since)
    what = BUSY_WITH.get(holder.owner, "busy with another job")
    return {"status": "queued", "since": since,
            "note": f"The server is {what}. New photos come in when it finishes."}


@router.post("/backfill")
def trigger_backfill(
    _: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    months: Annotated[int, Query(ge=1, le=24)] = 13,
) -> dict:
    if _pipeline_busy():
        return {"status": "busy", "note": _busy_words()}
    _start(db, "backfill", str(months))
    jobs.note(db, FETCH_REQUEST, at=datetime.now(UTC))
    return {"status": "started", "months": months}


@router.post("/scan")
def trigger_scan(
    _: Annotated[User, Depends(get_current_admin)], db: Annotated[Session, Depends(get_db)],
) -> dict:
    if _pipeline_busy():
        return {"status": "busy", "note": _busy_words()}
    _start(db, "scan")
    return {"status": "started"}


@router.get("/sync/status")
def sync_status(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Where the latest photo fetch is: running, identifying (photos in, the detector
    looking at them) or its result, with the logins that need attention in words."""
    from app.ingestion.fetch import latest_run

    row = latest_run(db)
    asked = jobs.read_note(db, FETCH_REQUEST).get("at")
    asked = datetime.fromisoformat(asked) if asked else None
    if not _pipeline_busy() and asked is not None and (
        # Queued behind another job, which has just ended: it takes the lock next.
        jobs.holder("fetchqueue") is not None
        or datetime.now(UTC) - asked < REQUEST_GRACE
    ) and (row is None or row.started_at is None or row.started_at < asked):
        # Asked for, and its process is still starting: not yet anyone's result.
        return {"status": "running", "started_at": asked}
    if _pipeline_busy():
        started = _lock_started()
        details = (row.details or {}) if row is not None else {}
        if (
            row is not None and started is not None
            and details.get("stage") == "identifying"
            and row.started_at >= started - timedelta(seconds=5)
        ):
            return {
                "status": "identifying", "result": row.status,
                "images_downloaded": row.images_downloaded, "started_at": row.started_at,
                "problems": details.get("problems", []),
            }
        return {"status": "running", "started_at": started}
    if row is None:
        return {"status": "never"}
    details = row.details or {}
    return {
        "status": row.status, "images_downloaded": row.images_downloaded,
        "started_at": row.started_at, "finished_at": row.finished_at, "error": row.error,
        "problems": details.get("problems", []),
        "details": details,
    }


class LocationBody(BaseModel):
    # Finite and on the planet: one camera at latitude 1000 took the map down for
    # everyone (audit B-08).
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)


def _location_out(cam: Camera) -> dict:
    return {
        "id": str(cam.id), "lat": cam.lat, "lng": cam.lon,
        "location_is_custom": cam.location_is_custom,
        "provider_location": cam.provider_lat is not None and cam.provider_lon is not None,
    }


def _camera_for_update(db: Session, user: User, camera_id: uuid.UUID) -> Camera:
    cam = db.scalar(select(Camera).where(
        Camera.id == camera_id, Camera.estate_id == user.estate_id,
    ).with_for_update().execution_options(populate_existing=True))
    if cam is None:
        raise HTTPException(404, "Camera not found.")
    return cam


@router.put("/{camera_id}/location")
def set_location(
    camera_id: uuid.UUID,
    body: LocationBody,
    user: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Place the camera by hand, admins only as on the map. It stays there: the
    provider's GPS no longer moves it at the next sync (audit B-09, E-16), until
    someone asks for the camera's own position again (DELETE)."""
    if not geo.plausible_position(body.lat, body.lng):
        raise HTTPException(422, "That spot is off the map. Move the map and try again.")
    cam = _camera_for_update(db, user, camera_id)
    cam.lat, cam.lon = body.lat, body.lng
    cam.location_is_custom = True
    db.commit()
    return _location_out(cam)


@router.delete("/{camera_id}/location")
def use_provider_location(
    camera_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Back to the position the camera itself last reported (SPYPOINT's GPS), and
    follow it from now on, as for a camera nobody placed."""
    cam = _camera_for_update(db, user, camera_id)
    if cam.provider_lat is None or cam.provider_lon is None:
        raise HTTPException(
            409, "This camera hasn’t reported a position of its own. Place it by hand."
        )
    cam.lat, cam.lon = cam.provider_lat, cam.provider_lon
    cam.location_is_custom = False
    db.commit()
    return _location_out(cam)


@router.get("/{camera_id}/images")
def camera_images(
    camera_id: uuid.UUID,
    limit: int = Query(40, ge=1, le=300),
    include_empty: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    before: Annotated[datetime | None, Query(description="the last photo's time")] = None,
    before_id: Annotated[uuid.UUID | None, Query(description="the last photo's id")] = None,
) -> list[dict]:
    """The camera's photos, newest first; empties too with `include_empty`. Older ones
    a page at a time with the last photo's time and id (`before`, `before_id`).

    `label` is the photo's name as Photos and Animals write it: its surest sighting
    of a species that isn't hidden (routes_photos._items). This page used to build
    its own ("Boar ♂", "Red Deer herd (3)") from whichever sighting came last.
    """
    # A photo with no picture yet (still to download) has nothing to show.
    q = select(Image).where(Image.camera_id == camera_id, Image.original_path.isnot(None))
    # Photos of nothing but hidden species never show; empties only on request.
    q = q.where(or_(Image.is_empty_frame.is_(True), VISIBLE_ANIMAL) if include_empty else VISIBLE_ANIMAL)
    q = after_cursor(q, before, before_id)
    rows = db.scalars(q.order_by(Image.captured_at.desc(), Image.id.desc()).limit(limit)).all()
    cam_name = db.scalar(select(Camera.name).where(Camera.id == camera_id))
    items = _items(db, [
        SimpleNamespace(id=i.id, captured_at=i.captured_at, camera_id=camera_id, name=cam_name)
        for i in rows
    ])
    out = []
    for i, it in zip(rows, items, strict=True):
        named = it["species_id"] is not None
        out.append({
            "id": str(i.id),
            "captured_at": i.captured_at,
            "file_url": f"/api/images/{i.id}/file" if i.original_path else None,
            # None while nobody has named it ("checking" says why, when the AI hasn't).
            "label": it["label"] if named else None,
            "species": it["label"] if named else None,  # what an older app reads
            "species_id": it["species_id"],
            "group_size": it["group_size"],
            "fixed_by": it["fixed_by"],
            "is_empty_frame": i.is_empty_frame,
            "reviewed": i.reviewed,
            "animal_conf": i.animal_conf,
            "notes_count": it["notes_count"],
            # "waiting" / "failed" while the AI has not finished with it (checking.photo_states).
            "checking": it["checking"],
        })
    return out
