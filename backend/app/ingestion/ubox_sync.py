"""UBox snapshots enter the ordinary gallery/AI pipeline with bounded admission.

Limits are per camera and estate-local calendar day, including already stored
photos. They deliberately discard surplus events before download or inference.
No cloud files or previously imported images are deleted.
"""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
import uuid
import warnings
from bisect import bisect_left, insort
from collections import Counter
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image as PillowImage
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt
from app.core.logging import get_logger
from app.enrichment.enrich import enrich_image
from app.ingestion.ubox import UboxClient, UboxDevice, UboxError, UboxEvent, UboxPageLimitError
from app.models import Camera, CameraAccount, Estate, Image, SyncLog

log = get_logger(__name__)
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000


class ImportBudget:
    """Track persisted and newly admitted captures, independent of API ordering."""

    def __init__(self, times, interval_seconds: int, daily_limit: int, timezone_name: str):
        self.zone = ZoneInfo(timezone_name)
        self.interval = interval_seconds
        self.limit = daily_limit
        self.times = sorted(times)
        self.days = Counter(t.astimezone(self.zone).date() for t in self.times)

    def reason(self, captured_at: datetime) -> str | None:
        if self.days[captured_at.astimezone(self.zone).date()] >= self.limit:
            return "daily_limit_skipped"
        index = bisect_left(self.times, captured_at)
        neighbors = self.times[max(0, index - 1):index + 1]
        if any(abs((t - captured_at).total_seconds()) < self.interval for t in neighbors):
            return "interval_skipped"
        return None

    def record(self, captured_at: datetime) -> None:
        insort(self.times, captured_at)
        self.days[captured_at.astimezone(self.zone).date()] += 1


def _ubox_accounts(db: Session, account_id=None) -> list[CameraAccount]:
    query = select(CameraAccount).where(
        CameraAccount.active.is_(True), CameraAccount.provider == "ubox",
    )
    if account_id is not None:
        query = query.where(CameraAccount.id == uuid.UUID(str(account_id)))
    return list(db.scalars(query.order_by(CameraAccount.created_at)).all())


def upsert_camera(db: Session, estate_id, device: UboxDevice, account_id=None) -> Camera:
    # Serialize metadata changes with app renames, refreshing any cached ORM row.
    camera = db.scalar(select(Camera).where(Camera.ubox_uid == device.uid)
                       .with_for_update().execution_options(populate_existing=True))
    if camera is None:
        default_name = device.name or "UBox"
        camera = Camera(estate_id=estate_id, ubox_uid=device.uid,
                        name=default_name, provider_name=default_name)
        db.add(camera)
    elif camera.estate_id != estate_id:
        raise UboxError("This UBox camera is already linked to another estate")
    camera.account_id = account_id
    if device.name:
        camera.provider_name = device.name
        if not camera.name_is_custom:
            camera.name = device.name
    camera.model = f"UBox {device.model}".strip() if device.model else "UBox"
    camera.battery_pct = device.battery_pct
    # UBIA's documented sample signal=1 has no established scale. Keep unknown
    # rather than displaying an invented percentage on the Cameras page.
    camera.signal_pct = None
    camera.photo_count = camera.photo_limit = None
    if device.last_active_at:
        camera.last_report_at = device.last_active_at
    elif device.online:
        camera.last_report_at = datetime.now(UTC)
    db.flush()
    return camera


def _jpeg(data: bytes) -> tuple[int, int]:
    if not data or len(data) > MAX_BYTES:
        raise UboxError("Snapshot is empty or exceeds the 20 MB limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PillowImage.DecompressionBombWarning)
            with PillowImage.open(io.BytesIO(data)) as image:
                if image.format != "JPEG" or image.width * image.height > MAX_PIXELS:
                    raise UboxError("Snapshot must be a JPEG of at most 40 megapixels")
                size = image.size
                image.verify()
            with PillowImage.open(io.BytesIO(data)) as image:
                image.load()
        return size
    except UboxError:
        raise
    except Exception as exc:
        raise UboxError("Snapshot is not a readable JPEG") from exc


def _ingest_photo(
    db: Session, client: UboxClient, camera: Camera, event: UboxEvent, created_paths=None,
) -> bool:
    if db.scalar(select(Image.id).where(Image.ubox_event_id == event.event_id)):
        return False
    urls = dict.fromkeys(u for u in (event.image_url, event.fallback_image_url) if u)
    data = None
    for url in urls:
        try:
            data = client.download(url)
            width, height = _jpeg(data)
            break
        except Exception:
            data = None
    if data is None:
        raise UboxError("Could not download a readable snapshot")
    digest = hashlib.sha256(data).hexdigest()
    if db.scalar(select(Image.id).where(
        Image.camera_id == camera.id, Image.file_hash == digest,
    )):
        return False
    folder = Path(settings.media_root) / str(camera.estate_id) / str(camera.id)
    folder /= event.captured_at.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    # Vendor IDs may contain colons/slashes; never use one as a Windows basename.
    basename = hashlib.sha256(event.event_id.encode()).hexdigest()
    path = folder / f"ubox_{basename}.jpg"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
        image = Image(
            camera_id=camera.id, ubox_event_id=event.event_id,
            captured_at=event.captured_at, original_path=str(path), cdn_url=event.image_url,
            file_hash=digest, width=width, height=height,
        )
        db.add(image)
        db.flush()
        try:
            with db.begin_nested():
                enrich_image(db, image)
        except Exception as exc:
            log.warning("ubox.enrich_failed", image=str(image.id), error=type(exc).__name__)
        if created_paths is not None:
            created_paths.append(path)
        return True
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _event_windows(client, uid, since, until):
    """Split saturated query periods before importing, retaining oldest-first order."""
    try:
        events = client.list_events(uid, since, until, page_size=100)
    except UboxPageLimitError:
        if until - since <= timedelta(minutes=1):
            raise
        middle = since + (until - since) / 2
        yield from _event_windows(client, uid, since, middle)
        yield from _event_windows(client, uid, middle, until)
    else:
        yield events


def _cleanup_uncommitted(db, paths) -> None:
    """A failed commit may have succeeded remotely; check before removing a file."""
    for path in paths:
        try:
            exists = db.scalar(select(Image.id).where(Image.original_path == str(path)))
            if not exists:
                path.unlink(missing_ok=True)
        except Exception:
            # The database/filesystem may still be unavailable. Deterministic
            # paths let a later retry reuse these bytes without growing duplicates.
            db.rollback()
            log.warning("ubox.file_cleanup_deferred")
            break


def _sync_camera(
    db, client, account, estate, device, since, until, hours=24, created_paths=None,
) -> dict:
    # Serialize competing background/scheduled imports, including the initial
    # camera creation, so independent runs cannot each consume the same allowance.
    key = int.from_bytes(hashlib.sha256(device.uid.encode()).digest()[:8], signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    camera = upsert_camera(db, estate.id, device, account.id)
    if since is None:
        cutoff = until - timedelta(hours=hours)
        since = max(camera.last_sync_at - timedelta(hours=2), cutoff) if (
            camera.last_sync_at
        ) else cutoff
    zone = ZoneInfo(estate.timezone)
    # Include the entire first/last local day (and interval neighbors across midnight).
    start = datetime.combine(since.astimezone(zone).date(), time.min, zone)
    end = datetime.combine(until.astimezone(zone).date() + timedelta(days=1), time.min, zone)
    margin = timedelta(seconds=account.ubox_min_interval_seconds)
    existing = db.execute(select(Image.captured_at, Image.ubox_event_id).where(
        Image.camera_id == camera.id,
        Image.captured_at >= start - margin, Image.captured_at < end + margin,
    )).all()
    budget = ImportBudget(
        [r.captured_at for r in existing], account.ubox_min_interval_seconds,
        account.ubox_max_images_per_day, estate.timezone,
    )
    known = {r.ubox_event_id for r in existing if r.ubox_event_id}
    result = dict.fromkeys(
        ("seen", "downloaded", "duplicate", "interval_skipped", "daily_limit_skipped",
         "no_image", "failed"), 0,
    )
    result.update(account_id=str(account.id), camera_id=str(camera.id), camera=camera.name)
    window_end = until
    while window_end > since:
        window_start = max(window_end - timedelta(days=1), since)
        window_failures = 0
        events = (event for window in _event_windows(client, device.uid, window_start, window_end)
                  for event in window)
        # Current sightings must not be starved by expired historical snapshots.
        # The budget checks both neighbors, so reverse order has the same gap bound.
        for event in sorted(events, key=lambda e: (e.captured_at, e.event_id), reverse=True):
            if event.device_uid != device.uid or not (
                window_start <= event.captured_at <= window_end
            ):
                continue
            result["seen"] += 1
            if event.event_id in known:
                result["duplicate"] += 1
                continue
            if not event.image_url:
                result["no_image"] += 1
                continue
            reason = budget.reason(event.captured_at)
            if reason:
                result[reason] += 1
                continue
            try:
                with db.begin_nested():
                    saved = _ingest_photo(db, client, camera, event, created_paths)
                known.add(event.event_id)
                if saved:
                    budget.record(event.captured_at)
                    result["downloaded"] += 1
                    if not camera.last_report_at or event.captured_at > camera.last_report_at:
                        camera.last_report_at = event.captured_at
                else:
                    result["duplicate"] += 1
                    # Identical bytes under different event IDs still consume a
                    # sampling slot for this pass; don't download a noisy burst.
                    budget.record(event.captured_at)
            except Exception as exc:
                result["failed"] += 1
                window_failures += 1
                log.warning("ubox.snapshot_failed", camera=str(camera.id),
                            error=type(exc).__name__)
                if window_failures >= 5:
                    break  # stale links/outages must not cause thousands of GETs
        window_end = window_start
    if not result["failed"]:
        camera.last_sync_at = until
    log.info("ubox.camera_synced", **result)
    return result


def _run(db: Session, *, hours: int = 24, account_id=None, days: int | None = None) -> dict:
    accounts = _ubox_accounts(db, account_id)
    if not accounts:
        return {"status": "skipped", "reason": "No active UBox accounts configured"}
    now = datetime.now(UTC)
    sync = SyncLog(status="running", started_at=now, details={"provider": "ubox"})
    db.add(sync)
    db.commit()
    results = []
    errors = []
    account_results = []
    for account in accounts:
        account_ok = True
        account_errors = []
        try:
            estate = db.get(Estate, account.estate_id)
            if estate is None:
                raise UboxError("Account has no estate")
            with UboxClient(account.username, decrypt(account.password_enc)) as client:
                client.login()
                devices = client.list_devices()
                for device in devices:
                    created_paths = []
                    try:
                        # A connection made while the pipeline was busy still gets
                        # its seven-day initial import on the next scheduled run.
                        since = now - timedelta(days=days or 7) if (
                            days is not None or account.last_sync_at is None
                        ) else None
                        with db.begin_nested():
                            result = _sync_camera(
                                db, client, account, estate, device, since, now, hours,
                                created_paths,
                            )
                        db.commit()
                        results.append(result)
                        account_ok = account_ok and not result["failed"]
                        if result["failed"]:
                            account_errors.append("Some snapshots could not be imported")
                    except Exception as exc:
                        db.rollback()
                        _cleanup_uncommitted(db, created_paths)
                        account_ok = False
                        account_errors.append(f"Camera import failed ({type(exc).__name__})")
                        log.error("ubox.camera_failed", account=str(account.id),
                                  error=type(exc).__name__)
                if account_ok:
                    account.last_sync_at = now
                    db.commit()
        except Exception as exc:
            db.rollback()
            account_ok = False
            account_errors.append(f"Account connection failed ({type(exc).__name__})")
            log.error("ubox.account_failed", account=str(account.id), error=type(exc).__name__)
        errors.extend(account_errors)
        account_results.append({
            "account_id": str(account.id), "status": "ok" if account_ok else "error",
            "error": "; ".join(account_errors) or None,
        })
    totals = {key: sum(r[key] for r in results) for key in (
        "seen", "downloaded", "duplicate", "interval_skipped", "daily_limit_skipped",
        "no_image", "failed",
    )}
    sync.status = "error" if errors or totals["failed"] else "ok"
    sync.error = "; ".join(errors) or None
    sync.finished_at = datetime.now(UTC)
    sync.images_downloaded = totals["downloaded"]
    sync.photos_synced = totals["seen"]
    sync.details = {"provider": "ubox", "accounts": account_results,
                    "cameras": results, **totals}
    db.commit()
    return {"status": sync.status, "total": totals["downloaded"], **sync.details}


def sync_ubox_all(db: Session, *, hours: int = 24) -> dict:
    return _run(db, hours=hours)


def backfill_ubox_account(db: Session, account_id, *, days: int = 7) -> dict:
    if not 1 <= days <= 31:
        raise ValueError("UBox backfill must be between 1 and 31 days")
    return _run(db, account_id=account_id, days=days)
