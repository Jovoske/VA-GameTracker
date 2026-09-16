"""Camera routes — list (with location), images, sync/backfill/scan, review, map placement."""
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.health import camera_health
from app.models import Camera, Detection, Image, Species, SyncLog, User

router = APIRouter(prefix="/cameras", tags=["cameras"])


# ── native-build task runner ─────────────────────────────────
# The Docker build queued these to Celery; the native build has no broker, so they run
# as FastAPI background tasks in the api process. The same lock file the scheduled
# pipeline uses keeps a button press from overlapping the 15-min sync.
def _lock_path() -> Path:
    return Path(settings.models_root).parent / "pipeline.lock"


def _pipeline_busy() -> bool:
    p = _lock_path()
    return p.exists() and (time.time() - p.stat().st_mtime) < 3 * 3600


def _run_locked(work) -> None:
    lock = _lock_path()
    try:
        lock.write_text(f"api {int(time.time())}")
        from app.core.db import SessionLocal

        with SessionLocal() as db:
            work(db)
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _sync_work(db: Session) -> None:
    from app.ai.empty_filter import scan_unprocessed
    from app.ai.species import classify_unclassified
    from app.ingestion.sync import sync_all
    from app.ingestion.ubox_sync import sync_ubox_all

    results = {}
    error = None
    try:
        results["spypoint"] = sync_all(db)
        results["ubox"] = sync_ubox_all(db)
        scan_unprocessed(db)
        classify_unclassified(db)
        from app.forecasting.exposure import recompute_camera_nights

        recompute_camera_nights(db)
    except Exception as exc:
        db.rollback()
        error = f"Sync pipeline failed ({type(exc).__name__})"
    # Provider imports each keep a diagnostic log. This final summary gives the
    # Sync button a combined count after both providers and the AI pass finish.
    now = datetime.now(timezone.utc)
    db.add(SyncLog(
        status="error" if error or any(r.get("status") == "error" for r in results.values())
        else "ok",
        started_at=now, finished_at=now, error=error,
        images_downloaded=sum(r.get("total", 0) for r in results.values()),
        details={"provider": "pipeline", "results": results},
    ))
    db.commit()


@router.get("")
def list_cameras(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    rows = db.scalars(
        select(Camera).where(Camera.estate_id == user.estate_id).order_by(Camera.name)
    ).all()
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
            "health": camera_health(c),
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
            raise ValueError("Camera name cannot contain control characters")
        value = value.strip()
        if not 1 <= len(value) <= 100:
            raise ValueError("Camera name must contain between 1 and 100 characters")
        return value


@router.patch("/{camera_id}/name")
def rename_camera(
    camera_id: uuid.UUID,
    body: CameraNameBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.role not in {"admin", "member"}:
        raise HTTPException(403, "Only estate admins and members can rename cameras")
    camera = db.scalar(select(Camera).where(
        Camera.id == camera_id, Camera.estate_id == user.estate_id,
    ).with_for_update().execution_options(populate_existing=True))
    if camera is None:
        raise HTTPException(404, "Camera not found")
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


@router.post("/sync")
def trigger_sync(background: BackgroundTasks, _: User = Depends(get_current_admin)) -> dict:
    if _pipeline_busy():
        return {"status": "busy", "note": "A sync is already running — new photos will appear shortly."}
    background.add_task(_run_locked, _sync_work)
    return {"status": "started"}


@router.post("/backfill")
def trigger_backfill(
    background: BackgroundTasks,
    months: int = Query(13, ge=1, le=24),
    _: User = Depends(get_current_admin),
) -> dict:
    if _pipeline_busy():
        return {"status": "busy", "note": "The pipeline is already running — try again later."}

    def work(db: Session) -> None:
        from app.ingestion.sync import backfill_all

        backfill_all(db, months=months)
        _sync_work(db)

    background.add_task(_run_locked, work)
    return {"status": "started", "months": months}


@router.post("/scan")
def trigger_scan(background: BackgroundTasks, _: User = Depends(get_current_admin)) -> dict:
    if _pipeline_busy():
        return {"status": "busy", "note": "The pipeline is already running — try again later."}

    def work(db: Session) -> None:
        from app.ai.empty_filter import scan_unprocessed
        from app.ai.species import classify_unclassified

        scan_unprocessed(db)
        classify_unclassified(db)

    background.add_task(_run_locked, work)
    return {"status": "started"}


@router.get("/sync/status")
def sync_status(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if _pipeline_busy():
        return {"status": "running"}
    row = db.scalar(select(SyncLog).order_by(SyncLog.started_at.desc()).limit(1))
    if row is None:
        return {"status": "never"}
    return {
        "status": row.status, "images_downloaded": row.images_downloaded,
        "started_at": row.started_at, "finished_at": row.finished_at, "error": row.error,
        "details": row.details,
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
        raise HTTPException(404, "Camera not found")
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
    if not include_empty:
        q = q.where(Image.is_empty_frame.isnot(True))
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
    } for i in rows]
