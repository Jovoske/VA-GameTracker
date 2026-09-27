"""UBox snapshots enter the ordinary gallery/AI pipeline with bounded admission.

Limits are per camera and estate-local calendar day, including already stored
photos. They deliberately discard surplus events before download or inference.
No cloud files or previously imported images are deleted.

Catching up: a routine fetch reads back to where the last complete one stopped (less
two hours), however long ago that was, up to the week UBox keeps listing. A snapshot
that will not download is a warning, not a failed login: it is tried again on the
next MAX_SNAPSHOT_ATTEMPTS fetches (Camera.import_failures) and then given up on, so
one dead link can neither hold the camera's catch-up back for good nor turn every
fetch red. What each login did is recorded for Settings (app.ingestion.logins).
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
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app import jobs, media
from app.core.config import settings
from app.core.logging import get_logger
from app.enrichment.enrich import enrich_image
from app.ingestion.logins import (
    disconnect_unlisted,
    keep_session,
    login_error,
    read_password,
    record,
    run_status,
    saved_session,
)
from app.ingestion.ubox import UboxClient, UboxDevice, UboxError, UboxEvent, UboxPageLimitError
from app.models import Camera, CameraAccount, Estate, Image, SyncLog

log = get_logger(__name__)
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
# How far back a fetch reaches after an outage: about what UBox keeps listing.
CATCH_UP = timedelta(days=7)
# A snapshot that will not download is tried on this many fetches, then given up on.
MAX_SNAPSHOT_ATTEMPTS = 3
COUNTERS = ("seen", "downloaded", "duplicate", "interval_skipped", "daily_limit_skipped",
            "no_image", "failed", "given_up")


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
    camera.active = True  # a login lists it, so it is connected (again)
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
            captured_at=event.captured_at, original_path=media.stored(path),
            cdn_url=event.image_url,
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
            exists = db.scalar(select(Image.id).where(media.same_file(Image.original_path, path)))
            if not exists:
                path.unlink(missing_ok=True)
        except Exception:
            # The database/filesystem may still be unavailable. Deterministic
            # paths let a later retry reuse these bytes without growing duplicates.
            db.rollback()
            log.warning("ubox.file_cleanup_deferred")
            break


def _snapshot_note(failed: int, retried: int) -> str:
    """Snapshots that would not download: whether they are tried again or let go."""
    note = f"{failed} photo{'s' if failed != 1 else ''} wouldn't download."
    if retried == failed:
        return f"{note} {'It is' if failed == 1 else 'They are'} tried again on the next fetch."
    if retried == 0:
        return (f"{note} {'It was' if failed == 1 else 'They were'} tried "
                f"{MAX_SNAPSHOT_ATTEMPTS} times, so {'it is' if failed == 1 else 'they are'} "
                "left out.")
    return (f"{note} {retried} {'is' if retried == 1 else 'are'} tried again on the next "
            f"fetch; the rest were tried {MAX_SNAPSHOT_ATTEMPTS} times and are left out.")


def _list_devices(db: Session, client: UboxClient, account: CameraAccount) -> list[UboxDevice]:
    """The login's cameras, signed in with the sign-in kept from the last fetch while it
    is valid (UBox gives it for weeks), so a login is not signed in afresh every 15
    minutes (E-21). One UBox has let lapse is signed in again."""
    token = saved_session(db, account)
    if token is not None:
        client.use_token(token)
        try:
            return client.list_devices()
        except UboxError as exc:
            if "rejected the account or password" in str(exc):
                raise
            log.info("ubox.session_retry", account=str(account.id), error=type(exc).__name__)
    client.login()
    return client.list_devices()


def _sync_camera(
    db, client, account, estate, device, since, until, hours=24, created_paths=None,
) -> dict:
    # Serialize competing background/scheduled imports, including the initial
    # camera creation, so independent runs cannot each consume the same allowance.
    key = int.from_bytes(hashlib.sha256(device.uid.encode()).digest()[:8], signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    camera = upsert_camera(db, estate.id, device, account.id)
    if since is None:
        # Back to where the last complete fetch of this camera (or login) stopped,
        # however long ago, up to what UBox still lists: an outage leaves no hole.
        marks = [m for m in (camera.last_sync_at, account.last_sync_at) if m is not None]
        since = (max(min(marks) - timedelta(hours=2), until - CATCH_UP) if marks
                 else until - timedelta(hours=hours))
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
    # Snapshots that would not download before: {event_id: [attempts, captured_at]}.
    failures = {
        event_id: entry for event_id, entry in (camera.import_failures or {}).items()
        if datetime.fromisoformat(entry[1]) >= until - CATCH_UP - timedelta(days=1)
    }
    # The oldest capture this pass left unfinished, which the next fetch must reach.
    hold = None
    result = dict.fromkeys(COUNTERS, 0)
    result["retried"] = 0  # of the failed, those the next fetch tries again
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
                failures.pop(event.event_id, None)
                continue
            if not event.image_url:
                result["no_image"] += 1
                continue
            attempts = failures.get(event.event_id, [0])[0]
            if attempts >= MAX_SNAPSHOT_ATTEMPTS:
                result["given_up"] += 1
                continue
            reason = budget.reason(event.captured_at)
            if reason:
                result[reason] += 1
                continue
            try:
                with db.begin_nested():
                    saved = _ingest_photo(db, client, camera, event, created_paths)
                known.add(event.event_id)
                failures.pop(event.event_id, None)
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
                failures[event.event_id] = [attempts + 1, event.captured_at.isoformat()]
                if attempts + 1 < MAX_SNAPSHOT_ATTEMPTS:
                    result["retried"] += 1
                    hold = min(hold or event.captured_at, event.captured_at)
                log.warning("ubox.snapshot_failed", camera=str(camera.id),
                            attempt=attempts + 1, error=type(exc).__name__)
                if window_failures >= 5:
                    # Stale links/outages must not cause thousands of GETs; what is
                    # left of this window is read again next time.
                    hold = min(hold or window_start, window_start)
                    break
        window_end = window_start
    camera.import_failures = failures
    camera.last_sync_at = hold or until
    camera.fetch_error = None
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
    account_results = []
    listed: set[str] = set()
    answered: set = set()  # logins that listed their cameras
    for account in accounts:
        if jobs.lock_lost():
            break  # another run took the lock over and fetches now
        label = account.label or account.username
        summary = {"account_id": str(account.id), "label": label, "status": "ok", "error": None}
        account_results.append(summary)
        failures: list[str] = []
        failed_snapshots = retried_snapshots = 0
        devices: list[UboxDevice] = []
        kept = saved_session(db, account)
        try:
            estate = db.get(Estate, account.estate_id)
            if estate is None:
                raise UboxError("Account has no estate")
            with UboxClient(account.username, read_password(db, account)) as client:
                devices = _list_devices(db, client, account)
                session = (client.token, client.token_valid_hours)
                listed.update(device.uid for device in devices)
                if devices:
                    answered.add(account.id)
                for device in devices:
                    if jobs.lock_lost():
                        break
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
                        failed_snapshots += result["failed"]
                        retried_snapshots += result["retried"]
                    except Exception as exc:
                        db.rollback()
                        _cleanup_uncommitted(db, created_paths)
                        words = login_error(exc, "ubox")
                        failures.append(words)
                        # Its login works: say on the camera's card that its photos
                        # could not be fetched.
                        db.execute(update(Camera).where(Camera.ubox_uid == device.uid)
                                   .values(fetch_error=words)
                                   .execution_options(synchronize_session=False))
                        db.commit()
                        results.append({"account_id": str(account.id), "camera": device.name,
                                        "error": type(exc).__name__})
                        log.error("ubox.camera_failed", account=str(account.id),
                                  error=type(exc).__name__)
        except Exception as exc:
            db.rollback()
            words = login_error(exc, "ubox")
            summary.update(status="error", error=words)
            log.error("ubox.account_failed", account=str(account.id), error=type(exc).__name__)
            if (row := db.get(CameraAccount, account.id)) is not None:
                record(db, row, error=words)
                if account.id not in answered:
                    keep_session(db, row, None)  # sign in afresh next time
                db.commit()
            continue
        if session[0] != kept:
            keep_session(db, account, session[0], valid_hours=session[1])
        if failures:
            everything = len(failures) == len(devices)
            summary["status"] = "error" if everything else "partial"
            summary["error"] = (failures[0] if everything else
                                f"{len(failures)} of {len(devices)} cameras failed. {failures[0]}")
        elif failed_snapshots:
            summary.update(status="partial",
                           error=_snapshot_note(failed_snapshots, retried_snapshots))
        if not failures:
            # Every camera was listed: the login's history is in, even if some
            # snapshots are still being retried (their cameras hold their own place).
            account.last_sync_at = now
        record(db, account, cameras=len(devices),
               error=summary["error"] if summary["status"] == "error" else None)
        db.commit()
    if account_id is None and accounts:
        # A camera no login listed is no longer connected, once the login that
        # fetched it has answered (a failing one might still list it).
        disconnect_unlisted(db, accounts[0].estate_id, "ubox", listed, answered=answered,
                            tried={a.id for a in accounts})
    totals = {key: sum(r.get(key, 0) for r in results) for key in COUNTERS}
    sync.status = run_status([a["status"] for a in account_results], totals["downloaded"])
    sync.error = "; ".join(f"{a['label']}: {a['error']}" for a in account_results
                           if a["error"]) or None
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
