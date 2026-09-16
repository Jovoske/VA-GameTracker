"""Camera accounts — guests connect a provider login and its cameras join the estate.

Credentials are verified against their provider before saving
and stored encrypted. Any signed-in user can add an account; only the owner or an admin
can remove it. Removing stops future syncing but keeps the photos already ingested.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.crypto import encrypt
from app.core.db import get_db
from app.ingestion.spypoint import SpypointClient, SpypointError
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


@router.get("")
def list_accounts(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
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
    return [
        {
            "id": str(a.id),
            "label": a.label or a.username,
            "username": a.username,
            "provider": a.provider,
            "owner": owners.get(a.owner_user_id),
            "active": a.active,
            "cameras": int(cam_counts.get(a.id, 0)),
            "last_sync_at": a.last_sync_at,
            "can_remove": user.role == "admin" or a.owner_user_id == user.id,
            "can_edit": user.role == "admin" or a.owner_user_id == user.id,
            "ubox_min_interval_seconds": a.ubox_min_interval_seconds,
            "ubox_max_images_per_day": a.ubox_max_images_per_day,
            "last_import": _last_ubox_import(db, a.id) if a.provider == "ubox" else None,
        }
        for a in rows
    ]


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
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    username = body.username.strip()
    provider_label = "UBox Pro" if body.provider == "ubox" else "SPYPOINT"
    if not username or not body.password:
        raise HTTPException(400, f"{provider_label} email and password are required")
    if user.estate_id is None:
        raise HTTPException(400, "Join an estate before connecting a camera account")
    if db.scalar(
        select(CameraAccount).where(
            CameraAccount.username == username,
            CameraAccount.provider == body.provider,
        )
    ):
        raise HTTPException(400, f"That {provider_label} account is already connected")

    # Verify before saving — a typo'd login should fail loudly now,
    # not silently every 15 minutes in the sync log.
    if body.provider == "ubox":
        try:
            with UboxClient(username, body.password) as client:
                client.login()
                n_cams = len(client.list_devices())
        except UboxError as e:
            raise HTTPException(400, f"Could not connect to UBox Pro: {e}") from e
    else:
        client = SpypointClient(username, body.password)
        try:
            client.login()
            n_cams = len(client.list_cameras())
        except SpypointError as e:
            raise HTTPException(400, f"SPYPOINT rejected that login: {e}") from e
        finally:
            client.close()

    acct = CameraAccount(
        estate_id=user.estate_id,
        owner_user_id=user.id,
        label=(body.label or "").strip() or None,
        username=username,
        provider=body.provider,
        password_enc=encrypt(body.password),
        ubox_min_interval_seconds=body.ubox_min_interval_seconds,
        ubox_max_images_per_day=body.ubox_max_images_per_day,
    )
    db.add(acct)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "This account could not be saved; refresh and try again") from e
    account_id = str(acct.id)

    # Pull this account's cameras + recent history right away (respects the pipeline lock;
    # if busy, the 15-min scheduled sync picks the new account up automatically).
    from app.api.routes_cameras import _pipeline_busy, _run_locked

    started = False
    if not _pipeline_busy():

        def work(session: Session) -> None:
            from app.ai.empty_filter import scan_unprocessed
            from app.ai.species import classify_unclassified
            from app.forecasting.exposure import recompute_camera_nights

            if body.provider == "ubox":
                from app.ingestion.ubox_sync import backfill_ubox_account

                backfill_ubox_account(session, account_id)
            else:
                from app.ingestion.sync import backfill_account

                backfill_account(session, account_id)
            scan_unprocessed(session)
            classify_unclassified(session)
            recompute_camera_nights(session)

        background.add_task(_run_locked, work)
        started = True

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
        + (
            "Importing photos now; they'll appear over the next minutes."
            if started
            else "Photos will import on the next scheduled sync."
        ),
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
        raise HTTPException(403, "Only the owner or an admin can change import settings")
    if acct.provider != "ubox":
        raise HTTPException(400, "Import limits apply to UBox Pro accounts only")
    acct.ubox_min_interval_seconds = body.ubox_min_interval_seconds
    acct.ubox_max_images_per_day = body.ubox_max_images_per_day
    db.commit()
    return {
        "id": str(acct.id),
        "ubox_min_interval_seconds": acct.ubox_min_interval_seconds,
        "ubox_max_images_per_day": acct.ubox_max_images_per_day,
        "note": "Import limits saved. They apply on the next sync; existing photos stay.",
    }


@router.delete("/{account_id}")
def remove_account(
    account_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    acct = db.get(CameraAccount, account_id)
    if acct is None or acct.estate_id != user.estate_id:
        raise HTTPException(404, "Account not found")
    if user.role != "admin" and acct.owner_user_id != user.id:
        raise HTTPException(403, "Only the owner or an admin can remove this account")
    # Keep the cameras and every photo already ingested — history belongs to the estate.
    db.execute(update(Camera).where(Camera.account_id == acct.id).values(account_id=None))
    db.delete(acct)
    db.commit()
    return {"status": "removed", "username": acct.username}
