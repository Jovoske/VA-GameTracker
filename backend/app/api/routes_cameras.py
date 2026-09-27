"""Camera routes — list (with location), images, sync/backfill/scan, review, map placement."""
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import jobs
from app.ai.checking import photo_states
from app.api.deps import get_current_admin, get_current_user
from app.api.routes_map import seen_mark
from app.api.visibility import VISIBLE_ANIMAL
from app.core.db import get_db
from app.health import camera_health
from app.ingestion.logins import camera_logins
from app.models import Camera, CameraView, Detection, Image, Species, User
from app.notes import note_counts

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


@router.get("")
def list_cameras(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    rows = db.scalars(
        select(Camera).where(Camera.estate_id == user.estate_id).order_by(Camera.name)
    ).all()
    now = datetime.now(UTC)
    login_states = camera_logins(db, rows, now)
    out = []
    for c in rows:
        last = db.scalar(
            select(Image.captured_at)
            .where(Image.camera_id == c.id)
            .order_by(Image.captured_at.desc())
            .limit(1)
        )
        count = db.scalar(select(func.count(Image.id)).where(Image.camera_id == c.id))
        empty = db.scalar(
            select(func.count(Image.id)).where(
                Image.camera_id == c.id, Image.is_empty_frame.is_(True)
            )
        )
        coords = db.execute(
            select(Camera.lat, Camera.lon).where(Camera.id == c.id)
        ).first()
        lat = float(coords[0]) if coords and coords[0] is not None else None
        lng = float(coords[1]) if coords and coords[1] is not None else None
        sightings = (count or 0) - (empty or 0)
        out.append({
            "id": str(c.id), "name": c.name, "battery_pct": c.battery_pct,
            "provider_name": c.provider_name or c.name,
            "name_is_custom": c.name_is_custom,
            "can_rename": user.role in {"admin", "member"},
            "battery_level": c.battery_level,
            "signal_pct": c.signal_pct, "model": c.model, "active": c.active,
            "last_sync_at": c.last_sync_at, "last_capture": last,
            "last_report_at": c.last_report_at,
            "photo_count": c.photo_count, "photo_limit": c.photo_limit,
            "plan_name": c.plan_name, "cycle_end": c.cycle_end,
            "sd_used_mb": c.sd_used_mb, "sd_total_mb": c.sd_total_mb,
            "image_count": count or 0, "empty_count": empty or 0, "sightings": sightings,
            "lat": lat, "lng": lng,
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
    camera.name = camera.provider_name if body.name is None else body.name
    camera.name_is_custom = body.name is not None
    db.commit()
    return {
        "id": str(camera.id), "name": camera.name,
        "provider_name": camera.provider_name,
        "name_is_custom": camera.name_is_custom, "can_rename": True,
    }


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
    lat: float
    lng: float


@router.put("/{camera_id}/location")
def set_location(
    camera_id: uuid.UUID,
    body: LocationBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    cam = db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(404, "Camera not found.")
    cam.lat = body.lat
    cam.lon = body.lng
    db.commit()
    return {"id": str(cam.id), "lat": body.lat, "lng": body.lng}


@router.get("/{camera_id}/images")
def camera_images(
    camera_id: uuid.UUID,
    limit: int = Query(40, ge=1, le=300),
    include_empty: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = select(Image).where(Image.camera_id == camera_id)
    # Photos of nothing but hidden species never show; empties only on request.
    q = q.where(or_(Image.is_empty_frame.is_(True), VISIBLE_ANIMAL) if include_empty else VISIBLE_ANIMAL)
    rows = db.scalars(q.order_by(Image.captured_at.desc()).limit(limit)).all()
    ids = [i.id for i in rows]
    det_map: dict = {}
    if ids:
        drows = db.execute(
            select(
                Detection.image_id, Species.common_name,
                Detection.group_type, Detection.group_size, Detection.sex,
            )
            .join(Species, Detection.species_id == Species.id)
            .where(Detection.image_id.in_(ids))
        ).all()
        det_map = {
            r.image_id: {
                "species": r.common_name, "group_type": r.group_type,
                "group_size": r.group_size, "sex": r.sex,
            }
            for r in drows
        }
    counts = note_counts(db, ids)
    states = photo_states(db, ids)
    return [{
        "id": str(i.id),
        "captured_at": i.captured_at,
        "file_url": f"/api/images/{i.id}/file" if i.original_path else None,
        "species": det_map.get(i.id, {}).get("species"),
        "group_type": det_map.get(i.id, {}).get("group_type"),
        "group_size": det_map.get(i.id, {}).get("group_size"),
        "sex": det_map.get(i.id, {}).get("sex"),
        "is_empty_frame": i.is_empty_frame,
        "reviewed": i.reviewed,
        "animal_conf": i.animal_conf,
        "notes_count": counts.get(i.id, 0),
        # "waiting" / "failed" while the AI has not finished with it (checking.photo_states).
        "checking": states.get(i.id),
    } for i in rows]
