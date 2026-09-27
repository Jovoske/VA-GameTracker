"""Is each camera login still working? What a fetch learnt, kept where people look.

A login that stopped working used to show only in a log nobody reads: the fetch said
"ok" when any other login worked, the cameras stayed green for 36 hours and then the
hunter was told to check the batteries. Now every fetch records, per login, when it
last tried, when it last worked and, when it did not, what went wrong in words a
hunter can act on ("SPYPOINT refused the password. Re-enter it."). Guest logins keep
this on their camera_accounts row; the estate's main SPYPOINT login lives in .env, so
its record is an app_settings document.

Settings lists every login with it. camera_health turns a failing or stalled login
into "Photos not coming in", and the Tonight plan says when its photos are old. While
a long job holds the pipeline (the AI pass after a big import, the hourly pass), a
login that has not fetched lately is "busy", not stopped.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import InvalidToken, decrypt, encrypt, is_current
from app.core.logging import get_logger
from app.i18n import stored, t
from app.models import AppSetting, Camera, CameraAccount, Image

log = get_logger(__name__)

PRIMARY_KEY = "spypoint_primary_login"
# Its name in a fetch's summary and log; on screen it is t("login.primary_label").
PRIMARY_LABEL = "Main SPYPOINT login"
# Fetches run every 15 minutes: two hours without a good one is a stoppage, not a blip.
STALE_AFTER = timedelta(hours=2)

# Kept in English on the login's row, like every error here, and put in the reader's
# language when read (app.i18n.localize).
UNREADABLE = stored("login.unreadable")
SPYPOINT_REFUSED = stored("login.spypoint_refused")
UBOX_REFUSED = stored("login.ubox_refused")
UBOX_SIGNED_OUT = stored("login.ubox_signed_out")
# The problems a new password fixes; for the others (no answer, busy, a copy of
# the main login) typing the password again would not help.
PASSWORD_PROBLEMS = frozenset({UNREADABLE, SPYPOINT_REFUSED, UBOX_REFUSED, UBOX_SIGNED_OUT})


class LoginProblem(Exception):
    """A login that cannot be used as saved; the message is for the hunter."""


def primary_configured() -> bool:
    return bool(settings.spypoint_username and settings.spypoint_password)


def _provider_name(provider: str) -> str:
    return "UBox" if provider == "ubox" else "SPYPOINT"


def login_error(exc: BaseException, provider: str) -> str:
    """What went wrong with a login, in words that say what to do about it. In
    English, as it is kept on the login's row (app.i18n.localize says it in the
    reader's language)."""
    from app.ingestion.spypoint import SpypointAuthError, SpypointError
    from app.ingestion.ubox import UboxError

    name = _provider_name(provider)
    if isinstance(exc, LoginProblem):
        return str(exc)
    if isinstance(exc, InvalidToken):
        return UNREADABLE
    if isinstance(exc, SpypointAuthError):
        return SPYPOINT_REFUSED
    if isinstance(exc, SpypointError):
        status = exc.status or 0
        if status == 429:
            return stored("login.spypoint_throttled")
        if status >= 500:
            return stored("login.spypoint_down")
        if status >= 400:
            return stored("login.spypoint_refused_request")
        return stored("login.spypoint_unreadable")
    if isinstance(exc, UboxError):
        text = str(exc)
        if "rejected the account or password" in text:
            return UBOX_REFUSED
        if "did not recognize this account" in text:
            return stored("login.ubox_unknown")
        if "reconnect the account" in text or "authentication failed" in text:
            return UBOX_SIGNED_OUT
        if text.startswith("Unable to reach UBox"):
            return stored("login.unreachable", provider="UBox")
        if "(HTTP " in text:
            return stored("login.ubox_down")
        # UboxError text is written to be shown.
        return stored("login.other", text=text.rstrip("."))
    if isinstance(exc, httpx.HTTPError | OSError):
        return stored("login.unreachable", provider=name)
    return stored("login.failed", provider=name, error=type(exc).__name__)


def read_password(db: Session, account: CameraAccount) -> str:
    """The login's password; saved again under the current key if an older one read it."""
    try:
        password = decrypt(account.password_enc)
    except InvalidToken:
        raise LoginProblem(UNREADABLE) from None
    if not is_current(account.password_enc):
        account.password_enc = encrypt(password)
        log.info("credentials.reencrypted", account=str(account.id))
    return password


def asks_for_password(error: str | None) -> bool:
    """True when the fix is to type the login's password in again."""
    return error in PASSWORD_PROBLEMS


def _primary_doc(db: Session) -> tuple[AppSetting | None, dict]:
    row = db.get(AppSetting, PRIMARY_KEY)
    value = dict(row.value) if row is not None else {}
    if value.get("username") != settings.spypoint_username:
        value = {"username": settings.spypoint_username}  # a different login: start afresh
    return row, value


def _save_primary(db: Session, row: AppSetting | None, value: dict) -> None:
    if row is None:
        db.add(AppSetting(key=PRIMARY_KEY, value=value))
    else:
        row.value = value


def saved_session(db: Session, account: CameraAccount | None) -> str | None:
    """The sign-in kept from an earlier fetch (`account` None: the main login), or
    None to sign in afresh: none kept, it has run out, or it can't be read."""
    if account is not None:
        sealed = account.session_enc
    else:
        row = db.get(AppSetting, PRIMARY_KEY)
        value = row.value if row is not None else {}
        same = value.get("username") == settings.spypoint_username
        sealed = value.get("session_enc") if same else None
    if not sealed:
        return None
    try:
        kept = json.loads(decrypt(sealed))
    except (InvalidToken, ValueError):
        return None
    until = _when(kept.get("until"))
    if until is not None and until <= datetime.now(UTC):
        return None
    return kept.get("token") or None


def keep_session(
    db: Session, account: CameraAccount | None, token: str | None, *,
    valid_hours: int | None = None,
) -> None:
    """Keep the login's sign-in, sealed like its password, for the next fetch; None
    forgets it. `account` None is the main login. The caller commits."""
    if token and valid_hours is None and saved_session(db, account) == token:
        return  # already kept (sealing it again would only rewrite the row)
    sealed = None
    if token:
        kept = {"token": token}
        if valid_hours:
            # Renewed an hour early rather than refused mid-fetch.
            kept["until"] = (datetime.now(UTC) + timedelta(hours=valid_hours - 1)).isoformat()
        sealed = encrypt(json.dumps(kept))
    if account is not None:
        if account.session_enc != sealed:
            account.session_enc = sealed
        return
    row, value = _primary_doc(db)
    if value.get("session_enc") == sealed:
        return
    value["session_enc"] = sealed
    _save_primary(db, row, value)


def record(
    db: Session, account: CameraAccount | None, *, error: str | None = None,
    cameras: int | None = None, now: datetime | None = None,
) -> None:
    """What this fetch learnt about a login: `account` None is the main SPYPOINT login.

    The caller commits. error=None means sign-in and the camera list worked.
    """
    now = now or datetime.now(UTC)
    if account is not None:
        account.last_attempt_at = now
        account.last_error = error
        if error is None:
            account.last_ok_at = now
            if cameras is not None:
                account.reported_cameras = cameras
        return
    row, value = _primary_doc(db)
    value["last_attempt_at"] = now.isoformat()
    value["last_error"] = error
    if error is None:
        value["last_ok_at"] = now.isoformat()
        if cameras is not None:
            value["reported_cameras"] = cameras
    _save_primary(db, row, value)


def _when(value) -> datetime | None:
    if isinstance(value, datetime) or value is None:
        return value
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def primary_status(db: Session) -> dict | None:
    """The main SPYPOINT login's record, or None when .env has no SPYPOINT login."""
    if not primary_configured():
        return None
    row = db.get(AppSetting, PRIMARY_KEY)
    value = row.value if row is not None else {}
    if value.get("username") != settings.spypoint_username:
        value = {}
    return {
        "username": settings.spypoint_username,
        "last_attempt_at": _when(value.get("last_attempt_at")),
        "last_ok_at": _when(value.get("last_ok_at")),
        "last_error": value.get("last_error"),
        "reported_cameras": value.get("reported_cameras"),
    }


def pipeline_busy_since(now: datetime | None = None) -> datetime | None:
    """When the run holding the pipeline lock began, or None when none holds it.

    pipeline.py and the app's buttons share one lock (app.jobs); one left by a run
    that died stops counting within minutes. `now` is kept for the callers' sake.
    """
    from app import jobs

    return jobs.busy_since("pipeline")


def state(last_attempt_at, last_ok_at, last_error, now: datetime,
          busy_since: datetime | None = None) -> str:
    """unknown (never tried here yet), failing, stale (no good fetch lately), busy (no
    good fetch lately, but a long job holding the pipeline since explains it) or ok."""
    if last_attempt_at is None:
        return "unknown"
    if last_error:
        return "failing"
    if last_ok_at is None or now - last_ok_at > STALE_AFTER:
        # The job took the pipeline before this login was due to be called stopped.
        if busy_since is not None and last_ok_at is not None and (
            busy_since <= last_ok_at + STALE_AFTER
        ):
            return "busy"
        return "stale"
    return "ok"


def _entry(label: str, provider: str, last_attempt_at, last_ok_at, last_error, now) -> dict:
    return {
        "label": label, "provider": provider,
        "state": state(last_attempt_at, last_ok_at, last_error, now, pipeline_busy_since(now)),
        "error": last_error, "last_ok_at": last_ok_at, "last_attempt_at": last_attempt_at,
    }


def account_entry(account: CameraAccount, now: datetime) -> dict:
    if not account.active:
        return {"label": account.label or account.username, "provider": account.provider,
                "state": "off", "error": None, "last_ok_at": account.last_ok_at,
                "last_attempt_at": account.last_attempt_at}
    return _entry(account.label or account.username, account.provider,
                  account.last_attempt_at, account.last_ok_at, account.last_error, now)


def primary_entry(db: Session, now: datetime) -> dict | None:
    status = primary_status(db)
    if status is None:
        return None
    return _entry(t("login.primary_label"), "spypoint", status["last_attempt_at"],
                  status["last_ok_at"], status["last_error"], now)


def camera_logins(db: Session, cameras, now: datetime | None = None) -> dict:
    """{camera id: the state of the login that fetches it}, for camera_health.

    A camera no login reaches any more is "off". Cameras fed by FTP or email have no
    login and are left out, as is any camera whose login has no record yet.
    """
    now = now or datetime.now(UTC)
    ids = {c.account_id for c in cameras if c.account_id is not None}
    accounts = {
        a.id: a for a in db.scalars(select(CameraAccount).where(CameraAccount.id.in_(ids)))
    } if ids else {}
    main = settings.spypoint_username.strip().lower() if primary_configured() else None
    copies = {a.id for a in accounts.values()
              if main and a.provider == "spypoint" and a.username.strip().lower() == main}
    primary = None
    if any(c.spypoint_id and (c.account_id is None or c.account_id in copies) for c in cameras):
        primary = primary_entry(db, now)
    out = {}
    for c in cameras:
        if c.spypoint_id is None and c.ubox_uid is None:
            continue
        if c.account_id in copies:
            # A copy of the main login (added before copies were refused): the main
            # login fetches the camera, and the copy's own problem is not the camera's.
            if primary is not None:
                out[c.id] = primary
        elif c.account_id is not None:
            account = accounts.get(c.account_id)
            out[c.id] = account_entry(account, now) if account is not None else {
                "label": None, "provider": "ubox" if c.ubox_uid else "spypoint",
                "state": "off", "error": None, "last_ok_at": None, "last_attempt_at": None,
            }
        elif c.spypoint_id and primary is not None:
            out[c.id] = primary
    return out


def freshness(db: Session, estate_id=None, now: datetime | None = None) -> dict:
    """How current the photos behind a plan are, and whether fetching has stopped.

    newest_photo_at: the newest capture time on file (a camera clock set in the
    future does not count). last_fetch_ok_at: the latest time any login worked.
    problem: "stopped" when no login has worked for STALE_AFTER (the scheduled fetch
    itself has stopped), "login" when some login is failing or stalled (logins names
    them), else None.
    """
    now = now or datetime.now(UTC)
    newest = db.scalar(select(func.max(Image.captured_at)).where(
        Image.captured_at <= now + timedelta(hours=1)))
    query = select(CameraAccount).where(CameraAccount.active.is_(True))
    if estate_id is not None:
        query = query.where(CameraAccount.estate_id == estate_id)
    entries = [account_entry(a, now) for a in db.scalars(query.order_by(CameraAccount.created_at))]
    primary = primary_entry(db, now)
    if primary is not None:
        entries.insert(0, primary)
    entries = [e for e in entries if e["state"] != "unknown"]
    down = [e["label"] for e in entries if e["state"] in ("failing", "stale")]
    oks = [e["last_ok_at"] for e in entries if e["last_ok_at"] is not None]
    problem = None
    if entries and all(e["state"] == "stale" for e in entries):
        problem = "stopped"
    elif down:
        problem = "login"
    return {
        "newest_photo_at": newest,
        "last_fetch_ok_at": max(oks) if oks else None,
        "problem": problem,
        "logins": down,
    }


def run_status(statuses: list[str], downloaded: int) -> str:
    """ok when everything worked; error when nothing did; partial in between."""
    if all(s in ("ok", "skipped") for s in statuses):
        return "ok"
    if downloaded == 0 and all(s in ("error", "skipped") for s in statuses):
        return "error"
    return "partial"


def disconnect_unlisted(
    db: Session, estate_id, provider: str, listed: set[str], *, answered: set, tried: set,
) -> int:
    """After a run: switch off this provider's cameras that no login listed (a camera
    taken off its login, or one whose login was removed).

    Only where the login that fetches the camera (Camera.account_id, None for the
    main SPYPOINT login) listed its cameras this run (`answered`), or is not among
    the logins at all (`tried`): a login that failed, or listed nothing, which is
    more likely a hiccup than every camera gone, may still have it. Never on a run
    that listed nothing at all. Their photos stay.
    """
    if not listed:
        return 0
    column = Camera.spypoint_id if provider == "spypoint" else Camera.ubox_uid
    rows = db.scalars(select(Camera).where(
        Camera.estate_id == estate_id, Camera.active.is_(True),
        column.isnot(None), column.not_in(sorted(listed)),
    )).all()
    off = 0
    for camera in rows:
        if camera.account_id in answered or camera.account_id not in tried:
            camera.active = False
            off += 1
            log.info("camera.not_listed", camera=str(camera.id), provider=provider)
    return off


def not_reached(db: Session, account: CameraAccount) -> None:
    """The login is being removed: switch off the cameras it fetched, and leave none
    pointing at it.

    Their photos stay. A login that still lists one switches it back on at its next
    fetch (both providers' upsert_camera). A copy of the main SPYPOINT login hands its
    cameras to the main login, which lists them already, so they never stop.
    """
    main = settings.spypoint_username.strip().lower() if primary_configured() else None
    copy = main and account.provider == "spypoint" and account.username.strip().lower() == main
    for camera in db.scalars(select(Camera).where(Camera.account_id == account.id)):
        if not copy:
            camera.active = False
        camera.account_id = None
