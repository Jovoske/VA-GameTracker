"""SPYPOINT sync orchestration: pull → download → enrich → log."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.enrichment.enrich import enrich_image
from app.ingestion.spypoint import SpypointCamera, SpypointClient
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


def sync_camera(db: Session, client: SpypointClient, estate_id, cam: SpypointCamera, *, limit: int = 100) -> dict:
    camera = upsert_camera(db, estate_id, cam)
    photos = client.list_photos(cam.spypoint_id, limit=limit)
    downloaded = 0
    for photo in photos:
        if not photo.spypoint_id:
            continue
        if db.scalar(select(Image.id).where(Image.spypoint_photo_id == photo.spypoint_id)):
            continue  # dedupe — already synced

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
        downloaded += 1

    db.flush()
    return {"camera": cam.name, "photos_seen": len(photos), "downloaded": downloaded}


def sync_all(db: Session, *, limit: int = 100) -> dict:
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
        log.info("spypoint.cameras_found", count=len(cameras))
        if cameras:  # one-time structure sample to verify metadata field mapping
            sample = cameras[0].raw
            log.info(
                "spypoint.camera_sample",
                keys=list(sample.keys()),
                status_keys=list((sample.get("status") or {}).keys()),
            )
        for cam in cameras:
            try:
                res = sync_camera(db, client, estate.id, cam, limit=limit)
                results.append(res)
                total += res["downloaded"]
            except Exception as e:
                log.error("spypoint.camera_failed", camera=cam.name, error=str(e))
                results.append({"camera": cam.name, "error": str(e)})
        sync_row.status = "ok"
    except Exception as e:
        sync_row.status = "error"
        sync_row.error = str(e)
        log.error("spypoint.sync_failed", error=str(e))
    finally:
        sync_row.images_downloaded = total
        sync_row.finished_at = datetime.now(timezone.utc)
        client.close()
        db.commit()
    return {"status": sync_row.status, "downloaded": total, "cameras": results}
