"""SPYPOINT sync orchestration: pull → download → enrich → log.

Two entry points share the same per-photo ingest logic:
- sync_all:     incremental (recent photos), runs every 15 min via beat.
- backfill_all: pages backward through the full history to seed pattern data.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.enrichment.enrich import enrich_image
from app.ingestion.spypoint import SpypointCamera, SpypointClient, SpypointPhoto
from app.models import Camera, Estate, Image, SyncLog

log = get_logger(__name__)


def _media_path(estate_id, camera_id, captured_at: datetime, photo_id: str) -> str:
    folder = os.path.join(
        settings.media_root, str(estate_id), str(camera_id), captured_at.strftime("%Y-%m-%d")
    )
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{photo_id}.jpg")


def upsert_camera(db: Session, estate_id, cam: SpypointCamera) -> Camera:
    row = db.scalar(select(Camera).where(Camera.spypoint_id == cam.spypoint_id))
    if row is None:
        row = Camera(estate_id=estate_id, spypoint_id=cam.spypoint_id, name=cam.name)
        db.add(row)
    if cam.name:
        row.name = cam.name
    if cam.battery_pct is not None:
        row.battery_pct = cam.battery_pct
    if cam.signal_pct is not None:
        row.signal_pct = cam.signal_pct
    if cam.model:
        row.model = cam.model
    if cam.lat is not None and cam.lng is not None:
        row.location = f"SRID=4326;POINT({cam.lng} {cam.lat})"
    row.last_sync_at = datetime.now(timezone.utc)
    db.flush()
    return row


def _ingest_photo(
    db: Session, client: SpypointClient, estate_id, camera: Camera, photo: SpypointPhoto
) -> bool:
    """Download + store + enrich one photo. Returns True if newly ingested."""
    if not photo.spypoint_id:
        return False
    if db.scalar(select(Image.id).where(Image.spypoint_photo_id == photo.spypoint_id)):
        return False  # dedupe — already have it

    data = None
    if photo.url:
        try:
            data = client.download(photo.url)
        except Exception as e:
            log.warning("spypoint.download_failed", photo=photo.spypoint_id, error=str(e))
    path = None
    if data:
        path = _media_path(estate_id, camera.id, photo.captured_at, photo.spypoint_id)
        with open(path, "wb") as f:
            f.write(data)

    image = Image(
        camera_id=camera.id,
        spypoint_photo_id=photo.spypoint_id,
        captured_at=photo.captured_at,
        original_path=path,
        cdn_url=photo.url,
        file_hash=hashlib.sha256(data).hexdigest() if data else None,
    )
    db.add(image)
    db.flush()
    try:
        enrich_image(db, image)
    except Exception as e:
        log.warning("enrich.failed", image=str(image.id), error=str(e))
    return True


def sync_camera(
    db: Session, client: SpypointClient, estate_id, cam: SpypointCamera, *, limit: int = 100
) -> dict:
    camera = upsert_camera(db, estate_id, cam)
    photos = client.list_photos(cam.spypoint_id, limit=limit)
    downloaded = sum(_ingest_photo(db, client, estate_id, camera, p) for p in photos)
    db.flush()
    return {"camera": cam.name, "photos_seen": len(photos), "downloaded": downloaded}


def backfill_camera(
    db: Session, client: SpypointClient, estate_id, cam: SpypointCamera, *,
    months: int = 13, page_size: int = 100,
) -> dict:
    """Page backward through a camera's full history via the dateEnd cursor."""
    camera = upsert_camera(db, estate_id, cam)
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 31)
    date_end: str | None = None
    seen_oldest: datetime | None = None
    total_new = 0
    pages = 0

    while True:
        photos = client.list_photos(cam.spypoint_id, limit=page_size, date_end=date_end)
        if not photos:
            break
        pages += 1
        for photo in photos:
            if photo.captured_at >= cutoff:
                total_new += _ingest_photo(db, client, estate_id, camera, photo)
        db.commit()  # commit each page → resumable if interrupted

        oldest = min((p.captured_at for p in photos), default=None)
        log.info("backfill.page", camera=cam.name, page=pages, oldest=str(oldest), new=total_new)
        if oldest is None or oldest < cutoff or oldest == seen_oldest:
            break  # reached cutoff, ran out, or no progress
        seen_oldest = oldest
        date_end = oldest.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    return {"camera": cam.name, "pages": pages, "new": total_new}


def _run(db: Session, *, label: str, per_camera) -> dict:
    if not settings.spypoint_username or not settings.spypoint_password:
        return {"status": "skipped", "reason": "SPYPOINT credentials not set"}
    estate = db.scalar(select(Estate).order_by(Estate.created_at))
    if estate is None:
        return {"status": "error", "reason": "no estate seeded"}

    sync_row = SyncLog(status="running", started_at=datetime.now(timezone.utc))
    db.add(sync_row)
    db.flush()

    client = SpypointClient(settings.spypoint_username, settings.spypoint_password)
    total = 0
    results: list[dict] = []
    try:
        client.login()
        cameras = client.list_cameras()
        log.info(f"{label}.cameras_found", count=len(cameras))
        if cameras:  # one-time structure sample to verify metadata field mapping
            sample = cameras[0].raw
            log.info(
                f"{label}.camera_sample",
                keys=list(sample.keys()),
                status_keys=list((sample.get("status") or {}).keys()),
            )
        for cam in cameras:
            try:
                res = per_camera(db, client, estate.id, cam)
                results.append(res)
                total += res.get("downloaded", res.get("new", 0))
            except Exception as e:
                log.error(f"{label}.camera_failed", camera=cam.name, error=str(e))
                results.append({"camera": cam.name, "error": str(e)})
        sync_row.status = "ok"
    except Exception as e:
        sync_row.status = "error"
        sync_row.error = str(e)
        log.error(f"{label}.failed", error=str(e))
    finally:
        sync_row.images_downloaded = total
        sync_row.finished_at = datetime.now(timezone.utc)
        client.close()
        db.commit()
    return {"status": sync_row.status, "total": total, "cameras": results}


def sync_all(db: Session, *, limit: int = 100) -> dict:
    return _run(
        db,
        label="spypoint",
        per_camera=lambda d, c, e, cam: sync_camera(d, c, e, cam, limit=limit),
    )


def backfill_all(db: Session, *, months: int = 13) -> dict:
    return _run(
        db,
        label="backfill",
        per_camera=lambda d, c, e, cam: backfill_camera(d, c, e, cam, months=months),
    )
