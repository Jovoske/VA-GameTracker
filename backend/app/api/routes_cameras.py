"""Camera routes — list (with location), images, sync/backfill/scan, review, map placement."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.functions import ST_X, ST_Y
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.db import get_db
from app.models import Camera, Image, SyncLog, User
from app.tasks.ai import scan_empty
from app.tasks.sync import spypoint_backfill, spypoint_sync

router = APIRouter(prefix="/cameras", tags=["cameras"])


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
            select(ST_Y(Camera.location), ST_X(Camera.location)).where(Camera.id == c.id)
        ).first()
        lat = float(coords[0]) if coords and coords[0] is not None else None
        lng = float(coords[1]) if coords and coords[1] is not None else None
        sightings = (count or 0) - (empty or 0)
        out.append({
            "id": str(c.id), "name": c.name, "battery_pct": c.battery_pct,
            "signal_pct": c.signal_pct, "model": c.model, "active": c.active,
            "last_sync_at": c.last_sync_at, "last_capture": last,
            "image_count": count or 0, "empty_count": empty or 0, "sightings": sightings,
            "lat": lat, "lng": lng,
        })
    return out


@router.post("/sync")
def trigger_sync(_: User = Depends(get_current_admin)) -> dict:
    task = spypoint_sync.delay()
    return {"status": "queued", "task_id": task.id}


@router.post("/backfill")
def trigger_backfill(
    months: int = Query(13, ge=1, le=24), _: User = Depends(get_current_admin)
) -> dict:
    task = spypoint_backfill.delay(months)
    return {"status": "queued", "task_id": task.id, "months": months}


@router.post("/scan")
def trigger_scan(_: User = Depends(get_current_admin)) -> dict:
    task = scan_empty.delay()
    return {"status": "queued", "task_id": task.id}


@router.get("/sync/status")
def sync_status(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    row = db.scalar(select(SyncLog).order_by(SyncLog.started_at.desc()).limit(1))
    if row is None:
        return {"status": "never"}
    return {
        "status": row.status, "images_downloaded": row.images_downloaded,
        "started_at": row.started_at, "finished_at": row.finished_at, "error": row.error,
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
    cam.location = f"SRID=4326;POINT({body.lng} {body.lat})"
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
    return [{
        "id": str(i.id),
        "captured_at": i.captured_at,
        "file_url": f"/api/images/{i.id}/file" if i.original_path else None,
        "is_empty_frame": i.is_empty_frame,
        "reviewed": i.reviewed,
        "animal_conf": i.animal_conf,
    } for i in rows]
