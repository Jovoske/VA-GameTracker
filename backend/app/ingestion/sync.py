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
from app.core.security import decrypt_secret, encrypt_secret
from app.enrichment.enrich import enrich_image
from app.ingestion.spypoint import SpypointCamera, SpypointClient, SpypointPhoto
from app.models import Camera, Estate, Image, SpypointAccount, SyncLog

log = get_logger(__name__)


def _media_path(estate_id, camera_id, captured_at: datetime, photo_id: str) -> str:
    folder = os.path.join(
        settings.media_root, str(estate_id), str(camera_id), captured_at.strftime("%Y-%m-%d")
    )
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{photo_id}.jpg")


def upsert_camera(db: Session, estate_id, cam: SpypointCamera, account_id=None) -> Camera:
    # Match within the account. Cameras ingested before multi-account support have a
    # NULL account_id, so fall back to a global match once and adopt them.
    row = db.scalar(
        select(Camera).where(
            Camera.spypoint_id == cam.spypoint_id, Camera.spypoint_account_id == account_id
        )
    )
    if row is None and account_id is not None:
        row = db.scalar(
            select(Camera).where(
                Camera.spypoint_id == cam.spypoint_id, Camera.spypoint_account_id.is_(None)
            )
        )
        if row is not None:
            row.spypoint_account_id = account_id
    if row is None:
        row = Camera(
            estate_id=estate_id,
            spypoint_id=cam.spypoint_id,
            name=cam.name,
            spypoint_account_id=account_id,
        )
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
        row.lat = cam.lat
        row.lon = cam.lng
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
    camera = upsert_camera(db, estate_id, cam, account_id)
    photos = client.list_photos(cam.spypoint_id, limit=limit)
    downloaded = sum(_ingest_photo(db, client, estate_id, camera, p) for p in photos)
    db.flush()
    return {"camera": cam.name, "photos_seen": len(photos), "downloaded": downloaded}


def backfill_camera(
    db: Session, client: SpypointClient, estate_id, cam: SpypointCamera, *,
    months: int = 13, page_size: int = 100, account_id=None,
) -> dict:
    """Page backward through a camera's full history via the dateEnd cursor."""
    camera = upsert_camera(db, estate_id, cam, account_id)
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


def resolve_accounts(db: Session, estate) -> list[SpypointAccount]:
    """Every active account for the estate.

    If the table is empty but env credentials are configured, adopt them here too —
    so an operator who upgrades and restarts the worker before running the seed
    still syncs, rather than silently doing nothing.
    """
    accounts = list(
        db.scalars(
            select(SpypointAccount)
            .where(SpypointAccount.estate_id == estate.id, SpypointAccount.active.is_(True))
            .order_by(SpypointAccount.created_at)
        ).all()
    )
    if accounts:
        return accounts
    if settings.spypoint_username and settings.spypoint_password:
        row = SpypointAccount(
            estate_id=estate.id,
            label="Main account",
            username=settings.spypoint_username,
            password_enc=encrypt_secret(settings.spypoint_password),
            active=True,
        )
        db.add(row)
        db.flush()
        log.info("spypoint.account_adopted_from_env", username=row.username)
        return [row]
    return []


def _run_one_account(
    db: Session, *, label: str, per_camera, estate, account: SpypointAccount
) -> tuple[int, list[dict]]:
    password = decrypt_secret(account.password_enc)
    if not password:
        account.last_error = "stored password unreadable — re-enter it for this account"
        log.error("spypoint.password_unreadable", account=account.username)
        return 0, [{"account": account.username, "error": account.last_error}]

    client = SpypointClient(account.username, password)
    total = 0
    results: list[dict] = []
    try:
        client.login()
        cameras = client.list_cameras()
        log.info(f"{label}.cameras_found", account=account.username, count=len(cameras))
        for cam in cameras:
            try:
                res = per_camera(db, client, estate.id, cam, account.id)
                res["account"] = account.username
                results.append(res)
                total += res.get("downloaded", res.get("new", 0))
            except Exception as e:
                log.error(
                    f"{label}.camera_failed",
                    account=account.username, camera=cam.name, error=str(e),
                )
                results.append({"account": account.username, "camera": cam.name, "error": str(e)})
        account.last_sync_at = datetime.now(timezone.utc)
        account.last_error = None
    except Exception as e:
        # One bad account must not stop the others — a wrong password on a second
        # login should never cost you the sync on the first.
        account.last_error = str(e)
        log.error(f"{label}.account_failed", account=account.username, error=str(e))
        results.append({"account": account.username, "error": str(e)})
    finally:
        client.close()
    return total, results


def _run(db: Session, *, label: str, per_camera) -> dict:
    estate = db.scalar(select(Estate).order_by(Estate.created_at))
    if estate is None:
        return {"status": "error", "reason": "no estate seeded"}

    accounts = resolve_accounts(db, estate)
    if not accounts:
        return {"status": "skipped", "reason": "no active SPYPOINT account configured"}

    sync_row = SyncLog(status="running", started_at=datetime.now(timezone.utc))
    db.add(sync_row)
    db.flush()

    total = 0
    results: list[dict] = []
    errors = 0
    for account in accounts:
        got, res = _run_one_account(
            db, label=label, per_camera=per_camera, estate=estate, account=account
        )
        total += got
        results.extend(res)
        errors += sum(1 for r in res if "error" in r)

    sync_row.status = "ok" if errors == 0 else ("partial" if total else "error")
    sync_row.images_downloaded = total
    sync_row.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "status": sync_row.status,
        "total": total,
        "accounts": len(accounts),
        "cameras": results,
    }


def sync_all(db: Session, *, limit: int = 100) -> dict:
    return _run(
        db,
        label="spypoint",
        per_camera=lambda d, c, e, cam, acc: sync_camera(d, c, e, cam, limit=limit, account_id=acc),
    )


def backfill_all(db: Session, *, months: int = 13) -> dict:
    return _run(
        db,
        label="backfill",
        per_camera=lambda d, c, e, cam, acc: backfill_camera(
            d, c, e, cam, months=months, account_id=acc
        ),
    )
