"""SPYPOINT sync orchestration: pull → download → enrich → log.

Two entry points share the same per-photo ingest logic:
- sync_all:     incremental (recent photos), runs every 15 min via beat.
- backfill_all: pages backward through the full history to seed pattern data.
"""
from __future__ import annotations

import hashlib
import os
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.enrichment.enrich import enrich_image
from app.ingestion.spypoint import SpypointCamera, SpypointClient, SpypointPhoto
from app.models import Camera, CameraAccount, Estate, Image, SyncLog

log = get_logger(__name__)


def _accounts(db: Session) -> list[dict]:
    """Every SPYPOINT login to sync: the primary .env account + active guest accounts."""
    out: list[dict] = []
    if settings.spypoint_username and settings.spypoint_password:
        out.append({"id": None, "username": settings.spypoint_username,
                    "password": settings.spypoint_password})
    from app.core.crypto import decrypt

    for a in db.scalars(select(CameraAccount).where(CameraAccount.active.is_(True))).all():
        try:
            out.append({"id": a.id, "username": a.username, "password": decrypt(a.password_enc)})
        except Exception as e:
            log.error("sync.account_decrypt_failed", account=a.username, error=str(e))
    return out


def _media_path(estate_id, camera_id, captured_at: datetime, photo_id: str) -> str:
    folder = os.path.join(
        settings.media_root, str(estate_id), str(camera_id), captured_at.strftime("%Y-%m-%d")
    )
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{photo_id}.jpg")


def upsert_camera(db: Session, estate_id, cam: SpypointCamera, account_id=None) -> Camera:
    row = db.scalar(select(Camera).where(Camera.spypoint_id == cam.spypoint_id))
    if row is None:
        row = Camera(estate_id=estate_id, spypoint_id=cam.spypoint_id, name=cam.name)
        db.add(row)
    if account_id is not None:
        row.account_id = account_id
    if cam.name:
        row.name = cam.name
    if cam.battery_pct is not None:
        row.battery_pct = cam.battery_pct
    if cam.signal_pct is not None:
        row.signal_pct = cam.signal_pct
    if cam.model:
        row.model = cam.model
    if cam.lat is not None and cam.lng is not None:
        row.lat = cam.lat
        row.lon = cam.lng
    if cam.last_report_at is not None:
        row.last_report_at = cam.last_report_at
    row.battery_level = cam.battery_level
    if cam.sd_used_mb is not None:
        row.sd_used_mb = cam.sd_used_mb
    if cam.sd_total_mb is not None:
        row.sd_total_mb = cam.sd_total_mb
    if cam.photo_count is not None:
        row.photo_count = cam.photo_count
    if cam.photo_limit is not None:
        row.photo_limit = cam.photo_limit
    if cam.plan_name:
        row.plan_name = cam.plan_name
    if cam.cycle_end is not None:
        row.cycle_end = cam.cycle_end
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
    db: Session, client: SpypointClient, estate_id, cam: SpypointCamera, *,
    limit: int = 100, account_id=None,
) -> dict:
    camera = upsert_camera(db, estate_id, cam, account_id=account_id)
    photos = client.list_photos(cam.spypoint_id, limit=limit)
    downloaded = sum(_ingest_photo(db, client, estate_id, camera, p) for p in photos)
    db.flush()
    return {"camera": cam.name, "photos_seen": len(photos), "downloaded": downloaded}


def backfill_camera(
    db: Session, client: SpypointClient, estate_id, cam: SpypointCamera, *,
    months: int = 13, page_size: int = 100, account_id=None,
) -> dict:
    """Page backward through a camera's full history via the dateEnd cursor."""
    camera = upsert_camera(db, estate_id, cam, account_id=account_id)
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
    """Sync every connected SPYPOINT account (.env primary + guests') into one estate."""
    accounts = _accounts(db)
    if not accounts:
        return {"status": "skipped", "reason": "No SPYPOINT accounts configured"}
    estate = db.scalar(select(Estate).order_by(Estate.created_at))
    if estate is None:
        return {"status": "error", "reason": "no estate seeded"}

    sync_row = SyncLog(status="running", started_at=datetime.now(timezone.utc))
    db.add(sync_row)
    db.flush()

    total = 0
    ok_accounts = 0
    errors: list[str] = []
    results: list[dict] = []
    for acct in accounts:
        client = SpypointClient(acct["username"], acct["password"])
        try:
            client.login()
            cameras = client.list_cameras()
            log.info(f"{label}.cameras_found", account=acct["username"], count=len(cameras))
            for cam in cameras:
                try:
                    res = per_camera(db, client, estate.id, cam, acct["id"])
                    results.append(res)
                    total += res.get("downloaded", res.get("new", 0))
                except Exception as e:
                    log.error(f"{label}.camera_failed", camera=cam.name, error=str(e))
                    results.append({"camera": cam.name, "error": str(e)})
            if acct["id"] is not None:
                row = db.get(CameraAccount, acct["id"])
                if row is not None:
                    row.last_sync_at = datetime.now(timezone.utc)
            ok_accounts += 1
        except Exception as e:
            errors.append(f"{acct['username']}: {e}")
            log.error(f"{label}.account_failed", account=acct["username"], error=str(e))
        finally:
            client.close()

    sync_row.status = "ok" if ok_accounts > 0 else "error"
    sync_row.error = "; ".join(errors) if errors else None
    sync_row.images_downloaded = total
    sync_row.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": sync_row.status, "total": total, "accounts_ok": ok_accounts,
            "accounts_failed": len(errors), "cameras": results}


def sync_all(db: Session, *, limit: int = 100) -> dict:
    return _run(
        db,
        label="spypoint",
        per_camera=lambda d, c, e, cam, acct: sync_camera(d, c, e, cam, limit=limit, account_id=acct),
    )


def backfill_all(db: Session, *, months: int = 13) -> dict:
    return _run(
        db,
        label="backfill",
        per_camera=lambda d, c, e, cam, acct: backfill_camera(d, c, e, cam, months=months, account_id=acct),
    )


def backfill_account(db: Session, account_id: str, *, months: int = 2) -> dict:
    """Initial import for ONE newly-connected guest account (SPYPOINT keeps ~1 month)."""
    from app.core.crypto import decrypt

    acct = db.get(CameraAccount, uuidlib.UUID(account_id))
    if acct is None:
        return {"status": "gone"}
    estate = db.scalar(select(Estate).order_by(Estate.created_at))
    client = SpypointClient(acct.username, decrypt(acct.password_enc))
    results = []
    try:
        client.login()
        for cam in client.list_cameras():
            results.append(backfill_camera(db, client, estate.id, cam, months=months, account_id=acct.id))
        acct.last_sync_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        client.close()
    log.info("backfill_account.done", account=acct.username, cameras=len(results))
    return {"status": "ok", "cameras": results}
