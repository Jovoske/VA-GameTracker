"""Camera routes — list, latest images, and SPYPOINT sync trigger."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.db import get_db
from app.models import Camera, Image, SyncLog, User
from app.tasks.sync import spypoint_sync

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
        out.append({
            "id": str(c.id), "name": c.name, "battery_pct": c.battery_pct,
            "signal_pct": c.signal_pct, "model": c.model, "active": c.active,
            "last_sync_at": c.last_sync_at, "image_count": count or 0, "last_capture": last,
        })
    return out


@router.post("/sync")
def trigger_sync(_: User = Depends(get_current_admin)) -> dict:
    task = spypoint_sync.delay()
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


@router.get("/{camera_id}/images")
def camera_images(
    camera_id: uuid.UUID,
    limit: int = Query(30, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.scalars(
        select(Image)
        .where(Image.camera_id == camera_id)
        .order_by(Image.captured_at.desc())
        .limit(limit)
    ).all()
    return [{
        "id": str(i.id),
        "captured_at": i.captured_at,
        "file_url": f"/api/images/{i.id}/file" if i.original_path else None,
        "cdn_url": i.cdn_url,
    } for i in rows]
