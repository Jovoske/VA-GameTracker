"""SPYPOINT sync orchestration: pull → download → enrich → log.

Two entry points share the same per-photo ingest logic:
- sync_all:     incremental, every 15 min. Pages back from the newest photo until it
                reaches photos already listed (Camera.photos_listed_to), so a fetch
                after an outage leaves no hole instead of reading only the newest 100.
                A fetch reads at most MAX_PAGES pages per camera; what an outage left
                beyond that is kept as the camera's gap (photos_gap_from/to), which
                the next fetches page on through until it is closed.
- backfill_all: pages backward through the full history to seed pattern data.

A camera two logins list belongs to the first that lists it in a run (the main login
comes first), so a guest sharing it, or a copy of the main login, can't make it look
stopped. A camera whose own listing fails while its login works says so on its card
(Camera.fetch_error).

A photo whose file fails to download is stored without one and tried again on later
fetches, up to MAX_DOWNLOAD_ATTEMPTS. One photo's database error rolls back that photo
only, each page is committed as it lands, and one login or camera failing never
stops the others. What each login did is recorded for Settings (app.ingestion.logins).
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import uuid as uuidlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import geo, jobs, media
from app.core.config import settings
from app.core.logging import get_logger
from app.enrichment.enrich import enrich_image
from app.ingestion.logins import (
    PRIMARY_LABEL,
    LoginProblem,
    disconnect_unlisted,
    keep_session,
    login_error,
    primary_configured,
    read_password,
    record,
    run_status,
    saved_session,
)
from app.ingestion.spypoint import (
    SpypointAuthError,
    SpypointCamera,
    SpypointClient,
    SpypointError,
    SpypointPhoto,
)
from app.models import Camera, CameraAccount, Estate, Image, SyncLog

log = get_logger(__name__)

# A photo whose file would not download is tried again on this many fetches.
MAX_DOWNLOAD_ATTEMPTS = 5
# Photos with no file that a fetch retries per camera, beyond those it lists anyway.
REPAIR_PER_CAMERA = 20
# How far back a camera new to us is read. SPYPOINT keeps about a month.
LOOKBACK = timedelta(days=62)
# Pages go back past the last listed capture by this much: a camera out of signal
# uploads late, and a late photo is filed under when it was taken. At most
# OVERLAP_PAGES pages of it, so a busy camera doesn't spend its page cap re-reading.
OVERLAP = timedelta(hours=48)
OVERLAP_PAGES = 3
# A routine fetch reads at most this many pages (of 100) per camera.
MAX_PAGES = 20

DUPLICATE_OF_PRIMARY = (
    "This is the estate's main SPYPOINT login, which is fetched already. Remove this copy."
)
# upsert_camera's account_id when the camera stays with the login it has: another
# login listed it first in this run.
KEEP = object()


def _accounts(db: Session) -> list[dict]:
    """Every SPYPOINT login to sync: the primary .env account + active guest accounts.

    A login whose saved password can't be read, or that repeats the main login, is
    listed with its problem instead of being dropped, so Settings can say so.
    """
    out: list[dict] = []
    primary = settings.spypoint_username.strip().lower() if primary_configured() else None
    if primary:
        out.append({"id": None, "label": PRIMARY_LABEL, "username": settings.spypoint_username,
                    "password": settings.spypoint_password, "imported": True})
    for a in db.scalars(select(CameraAccount).where(
        CameraAccount.active.is_(True), CameraAccount.provider == "spypoint",
    ).order_by(CameraAccount.created_at)).all():
        entry = {"id": a.id, "label": a.label or a.username, "username": a.username,
                 "imported": a.last_sync_at is not None}
        if primary and a.username.strip().lower() == primary:
            entry["problem"] = DUPLICATE_OF_PRIMARY
            entry["copy_of_primary"] = True  # the main login lists its cameras
        else:
            try:
                entry["password"] = read_password(db, a)
            except LoginProblem as e:
                log.error("sync.account_decrypt_failed", account=a.username)
                entry["problem"] = str(e)
        out.append(entry)
    return out


def _media_path(estate_id, camera_id, captured_at: datetime, photo_id: str) -> str:
    folder = os.path.join(
        settings.media_root, str(estate_id), str(camera_id), captured_at.strftime("%Y-%m-%d")
    )
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{photo_id}.jpg")


def upsert_camera(db: Session, estate_id, cam: SpypointCamera, account_id=KEEP) -> Camera:
    """The camera's row, refreshed from what SPYPOINT says about it.

    account_id is the login that fetches it (None: the main .env login); KEEP leaves
    the one it has.
    """
    # Refresh even an already-loaded instance after acquiring the row lock: a
    # rename in another transaction must not be overwritten by a stale sync.
    row = db.scalar(select(Camera).where(Camera.spypoint_id == cam.spypoint_id)
                    .with_for_update().execution_options(populate_existing=True))
    if row is None:
        default_name = cam.name or "SPYPOINT"
        row = Camera(estate_id=estate_id, spypoint_id=cam.spypoint_id,
                     name=default_name, provider_name=default_name)
        db.add(row)
    if account_id is not KEEP:
        row.account_id = account_id
    row.active = True  # a login lists it, so it is connected (again)
    if cam.name:
        row.provider_name = cam.name
        if not row.name_is_custom:
            row.name = cam.name
    if cam.battery_pct is not None:
        row.battery_pct = cam.battery_pct
    if cam.signal_pct is not None:
        row.signal_pct = cam.signal_pct
    if cam.model:
        row.model = cam.model
    # The provider's position is kept as its own, and moves the map's only while
    # nobody has placed the camera by hand: that is usually a cell-tower guess, and a
    # hand placement snapped back to it every 15 minutes (audit B-09, E-16). A (0, 0)
    # or impossible fix is a camera with no GPS lock, not a position.
    if geo.plausible_position(cam.lat, cam.lng):
        row.provider_lat, row.provider_lon = cam.lat, cam.lng
        if not row.location_is_custom or row.lat is None or row.lon is None:
            row.lat, row.lon = cam.lat, cam.lng
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
    row.last_sync_at = datetime.now(UTC)
    db.flush()
    return row


def _download(client: SpypointClient, photo_id: str | None, url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        return client.download(url) or None
    except Exception as e:
        log.warning("spypoint.download_failed", photo=photo_id, error=str(e))
        return None


def _store_file(estate_id, camera: Camera, image: Image, data: bytes) -> None:
    """Write the photo beside its camera's others; whole or not at all."""
    path = _media_path(estate_id, camera.id, image.captured_at, image.spypoint_photo_id)
    handle, temporary = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    image.original_path = media.stored(path)
    image.file_hash = hashlib.sha256(data).hexdigest()


def _stored(estate_id, camera: Camera, image: Image, data: bytes) -> bool:
    """_store_file, but a full disk or a locked folder only costs this photo its file
    for now (it is tried again like a failed download), never the camera's listing."""
    try:
        _store_file(estate_id, camera, image, data)
        return True
    except OSError as e:
        log.warning("spypoint.store_failed", photo=image.spypoint_photo_id, error=str(e))
        return False


def _retry_file(client, estate_id, camera: Camera, image: Image) -> bool:
    """Try again for the file of a photo stored without one. True if it came."""
    data = _download(client, image.spypoint_photo_id, image.cdn_url)
    if data is None or not _stored(estate_id, camera, image, data):
        image.download_attempts += 1
        return False
    if not image.reviewed:
        # The detector may have passed it over for having no file: look at it now.
        image.processed_at = image.is_empty_frame = image.animal_conf = None
    log.info("spypoint.download_repaired", photo=image.spypoint_photo_id,
             attempts=image.download_attempts)
    return True


def _ingest_photo(
    db: Session, client: SpypointClient, estate_id, camera: Camera, photo: SpypointPhoto,
    tried: set | None = None,
) -> bool:
    """Download + store + enrich one photo. True if its file is newly on disk.

    A photo already stored without its file (the download failed last time) is tried
    again with the link this listing gave, so a CDN hiccup no longer loses it.
    """
    if not photo.spypoint_id:
        return False
    existing = db.scalar(select(Image).where(Image.spypoint_photo_id == photo.spypoint_id))
    if existing is not None:
        if existing.original_path or existing.download_attempts >= MAX_DOWNLOAD_ATTEMPTS:
            return False  # dedupe — already have it, or have given up on its file
        if photo.url:
            existing.cdn_url = photo.url  # the freshest link
        if tried is not None:
            tried.add(existing.id)
        return _retry_file(client, estate_id, camera, existing)

    data = _download(client, photo.spypoint_id, photo.url)
    image = Image(
        camera_id=camera.id,
        spypoint_photo_id=photo.spypoint_id,
        captured_at=photo.captured_at,
        cdn_url=photo.url,
        download_attempts=0 if data or not photo.url else 1,
    )
    try:
        # One photo's database error rolls back that photo, not the camera's run.
        with db.begin_nested():
            db.add(image)
            db.flush()
    except IntegrityError:
        log.info("spypoint.photo_stored_elsewhere", photo=photo.spypoint_id)
        return False
    if data and not _stored(estate_id, camera, image, data):
        image.download_attempts = 1
        data = None
    if tried is not None:
        tried.add(image.id)
    try:
        with db.begin_nested():
            enrich_image(db, image)
    except Exception as e:
        log.warning("enrich.failed", image=str(image.id), error=str(e))
    return bool(data)


def repair_missing(
    db: Session, client, estate_id, camera: Camera, *, skip=(), limit: int = REPAIR_PER_CAMERA,
) -> int:
    """Retry the files of this camera's recent photos stored without one.

    These are photos this fetch did not list again (older than its pages). Their
    saved link may have expired; each failure counts towards the cap.
    """
    query = select(Image).where(
        Image.camera_id == camera.id, Image.spypoint_photo_id.isnot(None),
        Image.original_path.is_(None), Image.cdn_url.isnot(None), Image.cdn_url != "",
        Image.download_attempts < MAX_DOWNLOAD_ATTEMPTS,
        Image.captured_at >= datetime.now(UTC) - LOOKBACK,
    )
    if skip:
        query = query.where(Image.id.not_in(list(skip)))
    rows = db.scalars(query.order_by(Image.captured_at.desc()).limit(limit)).all()
    return sum(_retry_file(client, estate_id, camera, image) for image in rows)


def _newest_stored(db: Session, camera: Camera, now: datetime) -> datetime | None:
    """The newest capture on file for the camera (a clock running ahead aside)."""
    return db.scalar(select(func.max(Image.captured_at)).where(
        Image.camera_id == camera.id, Image.captured_at <= now))


def _set_gap(camera: Camera, gap: tuple[datetime, datetime] | None) -> None:
    camera.photos_gap_from, camera.photos_gap_to = gap or (None, None)


def _page_back(
    db: Session, client: SpypointClient, estate_id, camera: Camera, cam: SpypointCamera, *,
    stop_at: datetime, cutoff: datetime, page_size: int, max_pages: int | None,
    tried: set, gap: bool = False, top: datetime | None = None,
) -> dict:
    """Page backward until `stop_at`, committing each page with how far it got.

    From the newest photo, or with `gap` from the top of the camera's gap. Each page
    commits the camera's marks along with its photos, so a fetch cut short by the
    page cap or an error leaves a true record of what is still to list:
    - from the newest photo: photos_listed_to moves up to the newest listed, and
      until the listing reaches `stop_at` the stretch below where it got to is kept
      as the gap (with any gap already there). `top` is the newest capture listed
      before: past it, only OVERLAP_PAGES pages are read;
    - through the gap: its top moves down as pages come, and it closes at `stop_at`.
    Returns counts, and whether the listing reached `stop_at` (or the end of the
    camera's photos).
    """
    now = datetime.now(UTC)
    before = (camera.photos_gap_from, camera.photos_gap_to) if camera.photos_gap_to else None
    date_end = client.date_cursor(camera.photos_gap_to) if gap else None
    seen_oldest: datetime | None = None
    pages = seen = downloaded = past_top = 0
    complete = False
    while max_pages is None or pages < max_pages:
        photos = client.list_photos(cam.spypoint_id, limit=page_size, date_end=date_end)
        pages += 1
        oldest = min((p.captured_at for p in photos), default=None)
        for photo in photos:
            if photo.captured_at >= cutoff:
                downloaded += _ingest_photo(db, client, estate_id, camera, photo, tried)
        seen += len(photos)
        if top is not None and oldest is not None and oldest <= top:
            past_top += 1
        # Reached photos already listed (and enough of the overlap), the cutoff, the
        # end, or no progress.
        complete = (oldest is None or oldest <= stop_at or oldest == seen_oldest
                    or past_top >= OVERLAP_PAGES)
        if gap:
            _set_gap(camera, None if complete else (camera.photos_gap_from, oldest))
        else:
            if photos:
                # Never past now: a camera clock running ahead must not hide what follows.
                mark = min(max(p.captured_at for p in photos), now)
                if camera.photos_listed_to is None or mark > camera.photos_listed_to:
                    camera.photos_listed_to = mark
            if complete:
                # A gap older than where this listing began stays to be read.
                _set_gap(camera, before if before and before[0] < stop_at else None)
            else:
                _set_gap(camera, (min(before[0], stop_at) if before else stop_at, oldest))
        db.commit()  # each page lands on its own; an interrupted fetch keeps what it got
        log.info("spypoint.page", camera=cam.name, page=pages, oldest=str(oldest),
                 new=downloaded, gap=gap)
        if complete:
            break
        seen_oldest = oldest
        date_end = client.date_cursor(oldest)
    return {"pages": pages, "seen": seen, "downloaded": downloaded, "complete": complete}


def sync_camera(
    db: Session, client: SpypointClient, estate_id, cam: SpypointCamera, *,
    limit: int = 100, account_id=KEEP, max_pages: int | None = None,
) -> dict:
    """What came in since the last fetch, then on through the camera's gap, if any,
    with what is left of the page cap; then the files that did not come last time."""
    camera = upsert_camera(db, estate_id, cam, account_id=account_id)
    now = datetime.now(UTC)
    cutoff = now - LOOKBACK
    budget = max_pages or MAX_PAGES
    # A camera fetched before this was kept has no mark: its newest stored photo is
    # as far as the old fetch listed, so it pages back to that, not the whole cutoff.
    listed_to = camera.photos_listed_to or _newest_stored(db, camera, now)
    stop_at = max(listed_to - OVERLAP, cutoff) if listed_to else cutoff
    tried: set = set()
    res = _page_back(db, client, estate_id, camera, cam, stop_at=stop_at, cutoff=cutoff,
                     page_size=limit, max_pages=budget, tried=tried, top=listed_to)
    pages, seen, downloaded = res["pages"], res["seen"], res["downloaded"]
    if camera.photos_gap_to is not None and camera.photos_gap_to <= cutoff:
        _set_gap(camera, None)  # older than SPYPOINT keeps: nothing left to fetch there
    if res["complete"] and camera.photos_gap_to is not None and pages < budget:
        more = _page_back(db, client, estate_id, camera, cam,
                          stop_at=max(camera.photos_gap_from, cutoff), cutoff=cutoff,
                          page_size=limit, max_pages=budget - pages, tried=tried, gap=True)
        pages, seen = pages + more["pages"], seen + more["seen"]
        downloaded += more["downloaded"]
    downloaded += repair_missing(db, client, estate_id, camera, skip=tried)
    camera.fetch_error = None
    db.flush()
    return {"camera": cam.name, "photos_seen": seen, "downloaded": downloaded,
            "pages": pages, "complete": camera.photos_gap_to is None}


def backfill_camera(
    db: Session, client: SpypointClient, estate_id, cam: SpypointCamera, *,
    months: int = 13, page_size: int = 100, account_id=KEEP,
) -> dict:
    """Page backward through a camera's full history via the dateEnd cursor."""
    camera = upsert_camera(db, estate_id, cam, account_id=account_id)
    cutoff = datetime.now(UTC) - timedelta(days=months * 31)
    tried: set = set()
    res = _page_back(db, client, estate_id, camera, cam, stop_at=cutoff, cutoff=cutoff,
                     page_size=page_size, max_pages=None, tried=tried)
    new = res["downloaded"] + repair_missing(db, client, estate_id, camera, skip=tried)
    camera.fetch_error = None
    db.flush()
    return {"camera": cam.name, "pages": res["pages"], "new": new}


def _account_row(db: Session, acct: dict) -> CameraAccount | None:
    return db.get(CameraAccount, acct["id"]) if acct["id"] is not None else None


def _record(db: Session, acct: dict, **outcome) -> None:
    """Keep what this fetch learnt about the login (a removed one has nowhere to go)."""
    if acct["id"] is None:
        record(db, None, **outcome)  # the main .env login
    elif (row := _account_row(db, acct)) is not None:
        record(db, row, **outcome)


def _camera_failed(db: Session, spypoint_id: str, words: str) -> None:
    """Say on the camera's card that its photos could not be listed (its login works)."""
    db.execute(update(Camera).where(Camera.spypoint_id == spypoint_id)
               .values(fetch_error=words).execution_options(synchronize_session=False))


def _session(db: Session, acct: dict) -> str | None:
    if acct["id"] is None:
        return saved_session(db, None)
    row = _account_row(db, acct)
    return saved_session(db, row) if row is not None else None


def _keep(db: Session, acct: dict, token: str | None) -> None:
    """Keep the login's sign-in for the next fetch (a removed login has nowhere to go)."""
    if acct["id"] is None:
        keep_session(db, None, token)
    elif (row := _account_row(db, acct)) is not None:
        keep_session(db, row, token)


def _list_cameras(db: Session, client: SpypointClient, acct: dict) -> list[SpypointCamera]:
    """The login's cameras, signed in with the sign-in kept from the last fetch if there
    is one, so a login is not signed in afresh every 15 minutes (E-21). An expired one
    is signed in again: on SPYPOINT's refusal (SpypointClient._request), or, should it
    answer anything else, once here."""
    token = _session(db, acct)
    if token is not None:
        client.use_token(token)
        try:
            return client.list_cameras()
        except SpypointAuthError:
            raise
        except SpypointError as e:
            log.info("spypoint.session_retry", account=acct["username"], error=str(e))
    client.login()
    return client.list_cameras()


def _run(db: Session, *, label: str, per_camera, per_new_camera=None) -> dict:
    """Sync every connected SPYPOINT account (.env primary + guests') into one estate.

    `per_new_camera` fetches the cameras of a login whose history was never imported
    (connected while the pipeline was busy), in place of `per_camera`.
    """
    accounts = _accounts(db)
    if not accounts:
        return {"status": "skipped", "reason": "No SPYPOINT accounts configured"}
    estate = db.scalar(select(Estate).order_by(Estate.created_at))
    if estate is None:
        return {"status": "error", "reason": "no estate seeded"}

    sync_row = SyncLog(status="running", started_at=datetime.now(UTC),
                       details={"provider": "spypoint"})
    db.add(sync_row)
    db.commit()  # so a camera that fails and rolls back cannot take the log with it

    total = 0
    results: list[dict] = []
    account_results: list[dict] = []
    listed: set[str] = set()
    fetched: set[str] = set()  # cameras whose photos some login listed this run
    answered: set = set()  # logins that listed their cameras (None: the main login)
    tried: set = set()
    copies: set = set()
    for acct in accounts:
        if jobs.lock_lost():
            break  # another run took the lock over and fetches now
        key = str(acct["id"]) if acct["id"] else None
        summary = {"account_id": key, "label": acct["label"], "status": "ok", "error": None}
        account_results.append(summary)
        tried.add(acct["id"])
        if acct.get("problem"):
            if acct.get("copy_of_primary"):
                copies.add(acct["id"])
            summary.update(status="error", error=acct["problem"])
            _record(db, acct, error=acct["problem"])
            db.commit()
            continue
        client = SpypointClient(acct["username"], acct["password"])
        try:
            try:
                cameras = _list_cameras(db, client, acct)
            except Exception as e:
                db.rollback()
                words = login_error(e, "spypoint")
                summary.update(status="error", error=words)
                log.error(f"{label}.account_failed", account=acct["username"], error=str(e))
                _record(db, acct, error=words)
                _keep(db, acct, None)  # sign in afresh next time
                db.commit()
                continue
            log.info(f"{label}.cameras_found", account=acct["username"], count=len(cameras))
            if cameras:
                answered.add(acct["id"])
            fetch = per_camera if acct["imported"] or per_new_camera is None else per_new_camera
            failures: list[str] = []
            for cam in cameras:
                if jobs.lock_lost():
                    break
                # A camera two logins list belongs to the first: the main login, then
                # guests' in the order they were added.
                owner = acct["id"] if cam.spypoint_id not in listed else KEEP
                listed.add(cam.spypoint_id)
                # One commit per camera (and per page inside it), as the UBox sync does:
                # its photos show as soon as they are in, and one camera's failure
                # rolls back only its own unfinished page.
                try:
                    res = fetch(db, client, estate.id, cam, owner)
                    db.commit()
                    fetched.add(cam.spypoint_id)
                    res["account_id"] = key
                    results.append(res)
                    total += res.get("downloaded", res.get("new", 0))
                except Exception as e:
                    db.rollback()
                    words = login_error(e, "spypoint")
                    failures.append(words)
                    if cam.spypoint_id not in fetched:
                        _camera_failed(db, cam.spypoint_id, words)
                        db.commit()
                    log.error(f"{label}.camera_failed", camera=cam.name, error=str(e))
                    results.append({"camera": cam.name, "account_id": key, "error": str(e)})
            if failures:
                summary["status"] = "error" if len(failures) == len(cameras) else "partial"
                summary["error"] = (
                    failures[0] if summary["status"] == "error"
                    else f"{len(failures)} of {len(cameras)} cameras failed. {failures[0]}"
                )
            row = _account_row(db, acct)
            # Its history import has been tried: a camera whose listing failed has no
            # photos listed yet, so the routine fetch pages back through its two
            # months (bounded per fetch) without walking the others' again.
            if row is not None:
                row.last_sync_at = datetime.now(UTC)
            # A login whose every camera fails is not bringing photos in either.
            _record(db, acct, cameras=len(cameras),
                    error=summary["error"] if summary["status"] == "error" else None)
            _keep(db, acct, client.token)
            db.commit()
        finally:
            client.close()

    if None in answered:
        answered |= copies  # a copy's cameras are the main login's
    # A camera no login listed is no longer connected, once the login that fetched it
    # has answered (a failing one might still list it).
    disconnect_unlisted(db, estate.id, "spypoint", listed, answered=answered, tried=tried)
    sync_row.status = run_status([a["status"] for a in account_results], total)
    sync_row.error = "; ".join(
        f"{a['label']}: {a['error']}" for a in account_results if a["error"]
    ) or None
    sync_row.images_downloaded = total
    sync_row.details = {"provider": "spypoint", "accounts": account_results, "cameras": results}
    sync_row.finished_at = datetime.now(UTC)
    db.commit()
    return {"status": sync_row.status, "total": total,
            "accounts_ok": sum(a["status"] == "ok" for a in account_results),
            "accounts_failed": sum(a["status"] != "ok" for a in account_results),
            "accounts": account_results, "cameras": results}


def _backfill_new(d, c, e, cam, acct):
    return backfill_camera(d, c, e, cam, months=2, account_id=acct)


def sync_all(db: Session, *, limit: int = 100) -> dict:
    return _run(
        db,
        label="spypoint",
        per_camera=lambda d, c, e, cam, acct: sync_camera(
            d, c, e, cam, limit=limit, account_id=acct),
        per_new_camera=_backfill_new,
    )


def backfill_all(db: Session, *, months: int = 13) -> dict:
    return _run(
        db,
        label="backfill",
        per_camera=lambda d, c, e, cam, acct: backfill_camera(
            d, c, e, cam, months=months, account_id=acct),
    )


def backfill_account(db: Session, account_id: str, *, months: int = 2) -> dict:
    """Initial import for ONE newly-connected guest account (SPYPOINT keeps ~1 month).

    Each camera commits on its own, and the login counts as imported once each has
    been tried: a camera that failed has nothing listed yet, so the routine fetch
    pages back through its history, a page cap at a time.
    """
    acct = db.get(CameraAccount, uuidlib.UUID(account_id))
    if acct is None:
        return {"status": "gone"}
    entry = {"id": acct.id}
    username = acct.username
    estate = db.scalar(select(Estate).order_by(Estate.created_at))
    try:
        password = read_password(db, acct)
    except LoginProblem as e:
        record(db, acct, error=str(e))
        db.commit()
        return {"status": "error", "error": str(e)}
    client = SpypointClient(username, password)
    results = []
    failed = 0
    try:
        try:
            client.login()
            cameras = client.list_cameras()
        except Exception as e:
            db.rollback()
            words = login_error(e, "spypoint")
            _record(db, entry, error=words)
            db.commit()
            return {"status": "error", "error": words}
        for cam in cameras:
            # A camera another login fetches already stays with it.
            known = db.scalar(select(Camera.active).where(Camera.spypoint_id == cam.spypoint_id))
            try:
                results.append(backfill_camera(db, client, estate.id, cam, months=months,
                                               account_id=KEEP if known else entry["id"]))
                db.commit()
            except Exception as e:
                db.rollback()
                failed += 1
                _camera_failed(db, cam.spypoint_id, login_error(e, "spypoint"))
                db.commit()
                log.error("backfill_account.camera_failed", camera=cam.name, error=str(e))
                results.append({"camera": cam.name, "error": str(e)})
        row = _account_row(db, entry)
        if row is not None:
            row.last_sync_at = datetime.now(UTC)
        _record(db, entry, cameras=len(cameras))
        _keep(db, entry, client.token)
        db.commit()
    finally:
        client.close()
    log.info("backfill_account.done", account=username, cameras=len(results), failed=failed)
    return {"status": "ok" if not failed else "partial", "cameras": results}
