"""Read Nordic Gamekeeper photos into GameSense's ordinary image/AI pipeline.

REST polling leaves the camera and its native app alone. Each camera commits
independently; a failed file remains as a missing image and is retried with a fresh
URL. Its cursor never advances past unfinished work. Provider sessions use the
same encrypted storage as the other camera accounts.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import uuid
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PIL import Image as PillowImage
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app import geo, jobs, media
from app.core.config import settings
from app.core.db import error_name
from app.core.logging import get_logger
from app.enrichment.enrich import enrich_image
from app.ingestion import logins
from app.ingestion.nordic import (
    NordicAuthError,
    NordicCamera,
    NordicClient,
    NordicError,
    NordicPhoto,
)
from app.models import Camera, CameraAccount, Estate, Image, SyncLog

log = get_logger(__name__)
INITIAL_DAYS = 7
OVERLAP = timedelta(hours=48)
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000


def photo_key(photo: NordicPhoto) -> str:
    # IDs from two cameras must never collide, even if the provider uses counters.
    return json.dumps([photo.camera_id, photo.photo_id], separators=(",", ":"))


def upsert_camera(db: Session, estate_id, device: NordicCamera, account_id) -> Camera:
    camera = db.scalar(select(Camera).where(Camera.nordic_id == device.nordic_id)
                       .with_for_update().execution_options(populate_existing=True))
    if camera is None:
        name = device.name or "Nordic Gamekeeper"
        camera = Camera(estate_id=estate_id, nordic_id=device.nordic_id,
                        name=name, provider_name=name)
        db.add(camera)
    elif camera.estate_id != estate_id:
        raise NordicError("This Nordic Gamekeeper camera already belongs to another estate.")
    camera.account_id = account_id
    camera.active = True
    if device.name:
        camera.provider_name = device.name
        if not camera.name_is_custom:
            camera.name = device.name
    if geo.plausible_position(device.lat, device.lng):
        camera.provider_lat, camera.provider_lon = device.lat, device.lng
        if not camera.location_is_custom:
            camera.lat, camera.lon = device.lat, device.lng
    camera.model = device.model or "Nordic Gamekeeper"
    camera.battery_pct = device.battery_pct
    camera.signal_pct = device.signal_pct
    if device.last_report_at:
        camera.last_report_at = device.last_report_at
    db.flush()
    return camera


def _jpeg(data: bytes) -> tuple[int, int]:
    if not data or len(data) > MAX_BYTES:
        raise NordicError("Nordic Gamekeeper returned an empty or oversized photo.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PillowImage.DecompressionBombWarning)
            with PillowImage.open(io.BytesIO(data)) as image:
                if image.format != "JPEG" or image.width * image.height > MAX_PIXELS:
                    raise NordicError("Nordic Gamekeeper returned an unsupported photo.")
                dimensions = image.size
                image.verify()
            with PillowImage.open(io.BytesIO(data)) as image:
                image.load()
        return dimensions
    except NordicError:
        raise
    except Exception as exc:
        raise NordicError("Nordic Gamekeeper returned an unreadable photo.") from exc


def _ingest_photo(db, client, camera, photo, created_paths) -> str:
    key = photo_key(photo)
    row = db.scalar(select(Image).where(Image.nordic_photo_id == key))
    if row is not None and row.camera_id != camera.id:
        raise NordicError("Nordic Gamekeeper photo belongs to a different camera.")
    if row is not None and row.original_path:
        return "duplicate"
    if row is None:
        row = Image(camera_id=camera.id, nordic_photo_id=key,
                    captured_at=photo.captured_at, download_attempts=0)
        db.add(row)
        db.flush()
    row.cdn_url = photo.url
    try:
        data = client.download(photo.url)
        width, height = _jpeg(data)
        digest = hashlib.sha256(data).hexdigest()
        duplicate = db.scalar(select(Image.id).where(
            Image.camera_id == camera.id, Image.file_hash == digest,
            Image.id != row.id, Image.original_path.isnot(None),
        ))
        if duplicate:
            db.delete(row)
            db.flush()
            return "duplicate"
        folder = Path(settings.media_root) / str(camera.estate_id) / str(camera.id)
        folder /= photo.captured_at.strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("nordic_" + hashlib.sha256(key.encode()).hexdigest() + ".jpg")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=folder, suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
            os.replace(temporary, path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        created_paths.append(path)
        row.original_path = media.stored(path)
        row.file_hash, row.width, row.height = digest, width, height
        if not row.reviewed:
            row.processed_at = row.is_empty_frame = row.animal_conf = None
        db.flush()
    except (NordicError, OSError) as exc:
        row.download_attempts = (row.download_attempts or 0) + 1
        log.warning("nordic.download_failed", image=str(row.id), error=type(exc).__name__)
        return "failed"
    try:
        with db.begin_nested():
            enrich_image(db, row)
    except Exception as exc:
        log.warning("nordic.enrich_failed", image=str(row.id), error=type(exc).__name__)
    return "downloaded"


def _sync_camera(db, client, account, device, now, created_paths, *, days=None) -> dict:
    key = int.from_bytes(hashlib.sha256(f"nordic:{device.nordic_id}".encode()).digest()[:8],
                         signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    camera = upsert_camera(db, account.estate_id, device, account.id)
    since = (now - timedelta(days=days or INITIAL_DAYS)
             if days is not None or camera.last_sync_at is None
             else camera.last_sync_at - OVERLAP)
    result = {"camera_id": str(camera.id), "camera": camera.name,
              "seen": 0, "downloaded": 0, "duplicate": 0, "failed": 0,
              "interrupted": False}
    hold = None
    # Materialize before advancing any cursor: a page-limit error must never be
    # mistaken for an exhausted gallery. A later fetch can safely retry the window.
    photos = client.list_photos(device.nordic_id, since, now)
    for photo in sorted(photos, key=lambda p: (p.captured_at, p.photo_id), reverse=True):
        if jobs.lock_lost():
            hold = since
            result["interrupted"] = True
            break
        if photo.camera_id != device.nordic_id:
            raise NordicError("Nordic Gamekeeper returned photos for a different camera.")
        if not since <= photo.captured_at <= now:
            continue
        result["seen"] += 1
        with db.begin_nested():
            outcome = _ingest_photo(db, client, camera, photo, created_paths)
        result[outcome] += 1
        if outcome == "failed":
            hold = min(hold or photo.captured_at, photo.captured_at)
            if result["failed"] >= 5:
                hold = since  # the unprocessed remainder is still due
                break
        elif not camera.last_report_at or photo.captured_at > camera.last_report_at:
            camera.last_report_at = photo.captured_at
    # Never move backwards by another overlap on each outage/retry.
    if hold is None:
        camera.last_sync_at = now
    elif days is not None:
        # An explicit older history import must leave its failed/unprocessed
        # interval due, even when the ordinary cursor had already reached today.
        camera.last_sync_at = hold
    else:
        camera.last_sync_at = max(camera.last_sync_at or since, hold)
    camera.fetch_error = (
        "Photo import will resume next fetch." if result["interrupted"] else
        "Some Nordic Gamekeeper photos could not be downloaded; retrying."
        if result["failed"] else None
    )
    db.flush()
    return result


def _cleanup(db, paths):
    for path in paths:
        try:
            exists = db.scalar(select(Image.id).where(media.same_file(Image.original_path, path)))
            if not exists:
                path.unlink(missing_ok=True)
        except Exception:
            db.rollback()
            log.warning("nordic.file_cleanup_deferred")
            break


def _devices(db, client, account):
    session = logins.saved_session(db, account)
    if session:
        try:
            client.use_token(session)
            return client.list_cameras()
        except NordicAuthError:
            pass  # only expired/rejected authentication warrants a new sign-in
    client.login()
    return client.list_cameras()


def _run(db: Session, *, account_id=None, days=None) -> dict:
    query = select(CameraAccount).where(CameraAccount.provider == "nordic",
                                        CameraAccount.active.is_(True))
    if account_id is not None:
        query = query.where(CameraAccount.id == uuid.UUID(str(account_id)))
    accounts = list(db.scalars(query.order_by(CameraAccount.created_at)).all())
    if not accounts:
        return {"status": "skipped", "reason": "No active Nordic Gamekeeper accounts configured"}
    now = datetime.now(UTC)
    sync = SyncLog(status="running", started_at=now, details={"provider": "nordic"})
    db.add(sync)
    db.commit()
    results, summaries = [], []
    processed = set()
    # Track ownership and disappearance independently for every estate.
    estates: dict = {}
    for account in accounts:
        state = estates.setdefault(account.estate_id, {"listed": set(), "answered": set(),
                                                       "tried": set()})
        state["tried"].add(account.id)
    for account in accounts:
        if jobs.lock_lost():
            break
        state = estates[account.estate_id]
        summary = {"account_id": str(account.id), "label": account.label or account.username,
                   "status": "ok", "error": None}
        summaries.append(summary)
        devices = []
        session = None
        try:
            if db.get(Estate, account.estate_id) is None:
                raise NordicError("This Nordic Gamekeeper login has no estate.")
            with NordicClient(account.username, logins.read_password(db, account)) as client:
                devices = _devices(db, client, account)
                if devices:
                    state["answered"].add(account.id)
                state["listed"].update(device.nordic_id for device in devices)
                for device in devices:
                    if jobs.lock_lost():
                        summary.update(status="partial",
                                       error="Photo import will resume next fetch.")
                        break
                    identity = (account.estate_id, device.nordic_id)
                    if identity in processed:
                        continue
                    paths = []
                    try:
                        with db.begin_nested():
                            result = _sync_camera(
                                db, client, account, device, now, paths, days=days,
                            )
                        db.commit()
                        processed.add(identity)
                        results.append(result)
                        if result.get("interrupted"):
                            summary.update(status="partial",
                                           error="Photo import will resume next fetch.")
                        elif result["failed"]:
                            summary.update(
                                status="partial",
                                error="Some Nordic Gamekeeper photos are waiting to retry.",
                            )
                    except Exception as exc:
                        db.rollback()
                        _cleanup(db, paths)
                        words = logins.login_error(exc, "nordic")
                        summary.update(status="partial", error=words)
                        # Listing succeeded even though download failed. Keep this
                        # camera connected and tell its owner what went wrong.
                        db.execute(update(Camera).where(
                            Camera.nordic_id == device.nordic_id,
                            Camera.estate_id == account.estate_id,
                        ).values(fetch_error=words).execution_options(synchronize_session=False))
                        db.commit()
                        log.warning("nordic.camera_failed", error=error_name(exc))
                session = client.token
        except Exception as exc:
            db.rollback()
            summary.update(status="error", error=logins.login_error(exc, "nordic"))
            log.warning("nordic.account_failed", error=error_name(exc))
        with logins.bookkeeping(
            db, summary, event="nordic.login_not_saved", account=str(account.id),
        ):
            if session:
                logins.keep_session(db, account, session)
            elif summary["status"] == "error":
                logins.keep_session(db, account, None)
            logins.record(db, account, cameras=len(devices), error=summary["error"])
            if summary["status"] == "ok":
                account.last_sync_at = now
    if account_id is None:
        for estate_id, state in estates.items():
            logins.disconnect_unlisted(db, estate_id, "nordic", **state)
    totals = {key: sum(r[key] for r in results)
              for key in ("seen", "downloaded", "duplicate", "failed")}
    sync.status = logins.run_status([s["status"] for s in summaries], totals["downloaded"])
    sync.error = "; ".join(s["error"] for s in summaries if s["error"]) or None
    sync.finished_at = datetime.now(UTC)
    sync.images_downloaded, sync.photos_synced = totals["downloaded"], totals["seen"]
    sync.details = {"provider": "nordic", "accounts": summaries, "cameras": results, **totals}
    db.commit()
    return {"status": sync.status, "total": totals["downloaded"], **sync.details}


def sync_nordic_all(db: Session) -> dict:
    return _run(db)


def backfill_nordic_account(db: Session, account_id, *, days: int = INITIAL_DAYS) -> dict:
    if not 1 <= days <= 62:
        raise ValueError("Nordic Gamekeeper history import must be between 1 and 62 days")
    return _run(db, account_id=account_id, days=days)
