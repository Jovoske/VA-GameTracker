"""Camera accounts — guests connect a provider login and its cameras join the estate.

Credentials are verified against their provider before saving and stored encrypted.
Members and admins can add an account (viewers only look); only the owner or an admin
can remove it or re-enter its password. A login added by someone since removed keeps
fetching, owned by the admin who removed them. Removing stops future syncing but keeps the
photos already ingested; its cameras show as not connected until a login lists them.

The list also says, per login, whether it is working, in words (app.ingestion.logins),
and shows the estate's main SPYPOINT login from .env first, so a broken one of those
is as visible as a guest's.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.crypto import encrypt
from app.core.db import get_db
from app.ingestion import logins
from app.ingestion.spypoint import SpypointAuthError, SpypointClient, SpypointError
from app.ingestion.ubox import UboxClient, UboxError
from app.models import Camera, CameraAccount, SyncLog, User

router = APIRouter(prefix="/camera-accounts", tags=["camera-accounts"])


def _last_ubox_import(db: Session, account_id: uuid.UUID) -> dict | None:
    log = db.scalar(
        select(SyncLog)
        .where(
            SyncLog.details.contains(
                {
                    "provider": "ubox",
                    "accounts": [{"account_id": str(account_id)}],
                }
            )
        )
        .order_by(SyncLog.started_at.desc())
        .limit(1)
    )
    if log is None:
        return None
    counters = {
        key: 0
        for key in ("downloaded", "interval_skipped", "daily_limit_skipped", "no_image", "failed")
    }
    for camera in (log.details or {}).get("cameras", []):
        if camera.get("account_id") == str(account_id):
            for key in counters:
                counters[key] += camera.get(key, 0)
    account = next(
        (
            item
            for item in (log.details or {}).get("accounts", [])
            if item.get("account_id") == str(account_id)
        ),
        {},
    )
    return {
        "at": log.started_at,
        "status": account.get("status"),
        "error": account.get("error"),
        **counters,
    }


def _status(entry: dict, failing: list[str] | None = None) -> dict:
    """The login's state in words, plus the problem a new password would fix and its
    cameras whose own photos did not come on the last fetch although it worked."""
    out = {key: entry[key] for key in ("state", "error", "last_ok_at", "last_attempt_at")}
    out["password_problem"] = entry["state"] == "failing" and logins.asks_for_password(
        entry["error"])
    out["cameras_failing"] = len(failing or [])
    out["camera_error"] = (failing or [None])[0]
    return out


def _failing_cameras(db: Session, estate_id) -> dict:
    """{login id (None: the main login): [fetch errors of its connected cameras]}."""
    out: dict = {}
    for account_id, error in db.execute(select(Camera.account_id, Camera.fetch_error).where(
        Camera.estate_id == estate_id, Camera.active.is_(True), Camera.fetch_error.isnot(None),
    ).order_by(Camera.name)).all():
        out.setdefault(account_id, []).append(error)
    return out


def _primary_row(db: Session, user: User, now: datetime, failing: dict) -> dict | None:
    """The main SPYPOINT login from .env, as a row that can't be removed here."""
    entry = logins.primary_entry(db, now)
    if entry is None:
        return None
    linked = db.scalar(select(func.count(Camera.id)).where(
        Camera.estate_id == user.estate_id, Camera.spypoint_id.isnot(None),
        Camera.account_id.is_(None), Camera.active.is_(True),
    )) or 0
    return {
        "id": "primary", "label": logins.PRIMARY_LABEL,
        "username": settings.spypoint_username if user.role == "admin" else None,
        "provider": "spypoint", "owner": None, "added_by_removed": None, "active": True,
        "primary": True,
        "cameras": int(linked), "importing": False, "last_sync_at": None,
        "can_remove": False, "can_edit": False, "status": _status(entry, failing.get(None)),
        "ubox_min_interval_seconds": None, "ubox_max_images_per_day": None,
        "last_import": None,
    }


@router.get("")
def list_accounts(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    now = datetime.now(UTC)
    rows = db.scalars(
        select(CameraAccount)
        .where(CameraAccount.estate_id == user.estate_id)
        .order_by(CameraAccount.created_at)
    ).all()
    cam_counts = dict(
        db.execute(
            select(Camera.account_id, func.count(Camera.id))
            .where(Camera.account_id.isnot(None), Camera.estate_id == user.estate_id)
            .group_by(Camera.account_id)
        ).all()
    )
    owners = {
        u.id: u.email
        for u in db.scalars(select(User).where(User.estate_id == user.estate_id)).all()
    }
    out = []
    failing = _failing_cameras(db, user.estate_id)
    primary = _primary_row(db, user, now, failing) if user.estate_id is not None else None
    if primary is not None:
        out.append(primary)
    for a in rows:
        linked = int(cam_counts.get(a.id, 0))
        # A login whose first import is still running has linked none of its cameras
        # yet: say how many the provider listed, and that photos are on their way.
        importing = a.active and a.last_sync_at is None and a.last_error is None
        out.append({
            "id": str(a.id),
            "label": a.label or a.username,
            "username": a.username,
            "provider": a.provider,
            "owner": owners.get(a.owner_user_id),
            # Added by someone since removed: it kept fetching, the admin who removed
            # them owns it, and Settings says who added it (routes_users.delete_user).
            "added_by_removed": a.former_owner,
            "active": a.active,
            "primary": False,
            "cameras": max(linked, a.reported_cameras or 0) if importing else linked,
            "importing": importing,
            "last_sync_at": a.last_sync_at,
            "can_remove": user.role == "admin" or a.owner_user_id == user.id,
            "can_edit": user.role == "admin" or a.owner_user_id == user.id,
            "status": _status(logins.account_entry(a, now),
                              failing.get(a.id) if a.active else None),
            "ubox_min_interval_seconds": a.ubox_min_interval_seconds,
            "ubox_max_images_per_day": a.ubox_max_images_per_day,
            "last_import": _last_ubox_import(db, a.id) if a.provider == "ubox" else None,
        })
    return out


class AddAccountBody(BaseModel):
    username: str
    password: str
    label: str | None = None
    provider: Literal["spypoint", "ubox"] = "spypoint"
    ubox_min_interval_seconds: int = Field(default=60, ge=10, le=3600, strict=True)
    ubox_max_images_per_day: int = Field(default=500, ge=1, le=5000, strict=True)


class ImportSettingsBody(BaseModel):
    ubox_min_interval_seconds: int = Field(ge=10, le=3600, strict=True)
    ubox_max_images_per_day: int = Field(ge=1, le=5000, strict=True)


@router.post("")
def add_account(
    body: AddAccountBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.role == "viewer":
        raise HTTPException(403, "Viewers can see the camera logins but can't add one.")
    username = body.username.strip()
    provider_label = "UBox Pro" if body.provider == "ubox" else "SPYPOINT"
    if not username or not body.password:
        raise HTTPException(400, f"Enter your {provider_label} email and password")
    if user.estate_id is None:
        raise HTTPException(400, "Join an estate before adding a camera login")
    # One login is one login whatever the case of its email; a second copy would be
    # fetched twice every run and fight over which one its cameras belong to.
    if body.provider == "spypoint" and logins.primary_configured() and (
        username.lower() == settings.spypoint_username.strip().lower()
    ):
        raise HTTPException(400, "This login is already connected as the estate's main account")
    if db.scalar(
        select(CameraAccount).where(
            func.lower(CameraAccount.username) == username.lower(),
            CameraAccount.provider == body.provider,
        )
    ):
        raise HTTPException(400, f"That {provider_label} login is already added")

    # Verify before saving — a typo'd login should fail loudly now,
    # not silently every 15 minutes in the sync log.
    n_cams = _verify(body.provider, username, body.password)

    acct = CameraAccount(
        estate_id=user.estate_id,
        owner_user_id=user.id,
        label=(body.label or "").strip() or None,
        username=username,
        provider=body.provider,
        password_enc=encrypt(body.password),
        ubox_min_interval_seconds=body.ubox_min_interval_seconds,
        ubox_max_images_per_day=body.ubox_max_images_per_day,
        reported_cameras=n_cams,
    )
    db.add(acct)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        # Most likely the same login, added a moment ago from another phone.
        raise HTTPException(
            409, f"That {provider_label} login is already added. Refresh to see it."
        ) from e
    account_id = str(acct.id)

    # Pull this account's cameras + recent history right away, as a job of its own
    # (pipeline.py login) under the pipeline lock. If a run holds it, the 15-min
    # scheduled sync picks the new account's history up automatically.
    from app import jobs
    from app.api.routes_cameras import _pipeline_busy

    started = not _pipeline_busy() and jobs.spawn("login", account_id)
    return {
        "id": account_id,
        "username": acct.username,
        "provider": acct.provider,
        "cameras": n_cams,
        **({"spypoint_cameras": n_cams} if body.provider == "spypoint" else {}),
        "ubox_min_interval_seconds": acct.ubox_min_interval_seconds,
        "ubox_max_images_per_day": acct.ubox_max_images_per_day,
        "import_started": started,
        "note": f"Connected — {provider_label} reports {n_cams} camera(s). "
        + ("Fetching photos now." if started else "Photos come in on the next fetch."),
    }


def _unreachable(name: str) -> HTTPException:
    return HTTPException(
        503, f"Couldn't reach {name} to check the password. Try again in a few minutes.")


def _verify(provider: str, username: str, password: str) -> int:
    """Sign in with the provider and count its cameras; a 400 in words if it won't,
    a 503 in words if the provider can't be reached (the password may be fine)."""
    if provider == "ubox":
        try:
            with UboxClient(username, password) as client:
                client.login()
                return len(client.list_devices())
        except UboxError as e:
            if str(e).startswith("Unable to reach UBox"):
                raise _unreachable("UBox") from e
            raise HTTPException(400, f"Could not connect to UBox Pro: {e}") from e
        except (httpx.HTTPError, OSError) as e:
            raise _unreachable("UBox") from e
    client = SpypointClient(username, password)
    try:
        client.login()
        return len(client.list_cameras())
    except SpypointAuthError as e:
        raise HTTPException(
            400, "SPYPOINT refused that email and password. Check them in the SPYPOINT app."
        ) from e
    except SpypointError as e:
        if e.status is not None and (e.status == 429 or e.status >= 500):
            raise _unreachable("SPYPOINT") from e
        raise HTTPException(400, f"SPYPOINT did not accept that login: {e}") from e
    except (httpx.HTTPError, OSError) as e:
        raise _unreachable("SPYPOINT") from e
    finally:
        client.close()


class PasswordBody(BaseModel):
    password: str


@router.put("/{account_id}/password")
def replace_password(
    account_id: uuid.UUID,
    body: PasswordBody,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Re-enter a login's password (changed at the provider, or unreadable here).

    Checked with the provider before it is saved, like a new login. Its cameras,
    photos and limits stay as they are, and the next fetch catches up on what came
    in meanwhile.
    """
    acct = db.get(CameraAccount, account_id)
    if acct is None or acct.estate_id != user.estate_id:
        raise HTTPException(404, "Account not found")
    if user.role != "admin" and acct.owner_user_id != user.id:
        raise HTTPException(
            403, "Only whoever added this login, or an admin, can change its password"
        )
    if not body.password:
        raise HTTPException(400, "Enter the password")
    n_cams = _verify(acct.provider, acct.username, body.password)
    acct.password_enc = encrypt(body.password)
    logins.keep_session(db, acct, None)  # the next fetch signs in with the new one
    logins.record(db, acct, cameras=n_cams)
    db.commit()
    return {
        "id": str(acct.id), "cameras": n_cams,
        "note": "Password saved. Photos come in on the next fetch, within 15 minutes.",
    }


@router.patch("/{account_id}/import-settings")
def update_import_settings(
    account_id: uuid.UUID,
    body: ImportSettingsBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    acct = db.get(CameraAccount, account_id)
    if acct is None or acct.estate_id != user.estate_id:
        raise HTTPException(404, "Account not found")
    if user.role != "admin" and acct.owner_user_id != user.id:
        raise HTTPException(
            403, "Only whoever added this login, or an admin, can change its limits"
        )
    if acct.provider != "ubox":
        raise HTTPException(400, "Photo limits only apply to UBox Pro logins")
    acct.ubox_min_interval_seconds = body.ubox_min_interval_seconds
    acct.ubox_max_images_per_day = body.ubox_max_images_per_day
    db.commit()
    return {
        "id": str(acct.id),
        "ubox_min_interval_seconds": acct.ubox_min_interval_seconds,
        "ubox_max_images_per_day": acct.ubox_max_images_per_day,
        "note": "Limits saved. They apply from the next fetch.",
    }


@router.delete("/{account_id}")
def remove_account(
    account_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    acct = db.get(CameraAccount, account_id)
    if acct is None or acct.estate_id != user.estate_id:
        raise HTTPException(404, "Account not found")
    if user.role != "admin" and acct.owner_user_id != user.id:
        raise HTTPException(403, "Only whoever added this login, or an admin, can remove it")
    # Keep the cameras and every photo already ingested — history belongs to the estate.
    # Its cameras show as not connected (not as flat batteries) until a login that is
    # still here lists them again.
    logins.not_reached(db, acct)
    db.flush()
    db.delete(acct)
    db.commit()
    return {"status": "removed", "username": acct.username}
