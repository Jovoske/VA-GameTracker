"""Extra SPYPOINT accounts — guests connect their own login; its cameras join the estate.

Credentials are verified against SPYPOINT before saving (no dead logins in the sync loop)
and stored encrypted. Any signed-in user can add an account; only the owner or an admin
can remove it. Removing stops future syncing but keeps the photos already ingested.
"""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.crypto import encrypt
from app.core.db import get_db
from app.ingestion.spypoint import SpypointClient, SpypointError
from app.models import Camera, CameraAccount, User

router = APIRouter(prefix="/camera-accounts", tags=["camera-accounts"])


@router.get("")
def list_accounts(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(CameraAccount).order_by(CameraAccount.created_at)).all()
    cam_counts = dict(
        db.execute(
            select(Camera.account_id, func.count(Camera.id))
            .where(Camera.account_id.isnot(None))
            .group_by(Camera.account_id)
        ).all()
    )
    owners = {u.id: u.email for u in db.scalars(select(User)).all()}
    return [
        {
            "id": str(a.id),
            "label": a.label or a.username,
            "username": a.username,
            "owner": owners.get(a.owner_user_id),
            "active": a.active,
            "cameras": int(cam_counts.get(a.id, 0)),
            "last_sync_at": a.last_sync_at,
            "can_remove": user.role == "admin" or a.owner_user_id == user.id,
        }
        for a in rows
    ]


class AddAccountBody(BaseModel):
    username: str
    password: str
    label: str | None = None


@router.post("")
def add_account(
    body: AddAccountBody,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(400, "SPYPOINT email and password are required")
    if db.scalar(select(CameraAccount).where(CameraAccount.username == username)):
        raise HTTPException(400, "That SPYPOINT account is already connected")

    # Verify against SPYPOINT before saving — a typo'd login should fail loudly now,
    # not silently every 15 minutes in the sync log.
    client = SpypointClient(username, body.password)
    try:
        client.login()
        n_cams = len(client.list_cameras())
    except SpypointError as e:
        raise HTTPException(400, f"SPYPOINT rejected that login: {e}")
    finally:
        client.close()

    acct = CameraAccount(
        estate_id=user.estate_id,
        owner_user_id=user.id,
        label=(body.label or "").strip() or None,
        username=username,
        password_enc=encrypt(body.password),
    )
    db.add(acct)
    db.commit()

    # Pull this account's cameras + recent history right away (respects the pipeline lock;
    # if busy, the 15-min scheduled sync picks the new account up automatically).
    from app.api.routes_cameras import _pipeline_busy, _run_locked

    started = False
    if not _pipeline_busy():
        def work(session: Session) -> None:
            from app.ai.empty_filter import scan_unprocessed
            from app.ai.species import classify_unclassified
            from app.ingestion.sync import backfill_account

            backfill_account(session, str(acct.id))
            scan_unprocessed(session)
            classify_unclassified(session)

        background.add_task(_run_locked, work)
        started = True

    return {
        "id": str(acct.id), "username": acct.username, "spypoint_cameras": n_cams,
        "import_started": started,
        "note": f"Connected — SPYPOINT reports {n_cams} camera(s). "
                + ("Importing photos now; they'll appear over the next minutes."
                   if started else "Photos will import on the next scheduled sync."),
    }


@router.delete("/{account_id}")
def remove_account(
    account_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    acct = db.get(CameraAccount, account_id)
    if acct is None:
        raise HTTPException(404, "Account not found")
    if user.role != "admin" and acct.owner_user_id != user.id:
        raise HTTPException(403, "Only the owner or an admin can remove this account")
    # Keep the cameras and every photo already ingested — history belongs to the estate.
    db.execute(update(Camera).where(Camera.account_id == acct.id).values(account_id=None))
    db.delete(acct)
    db.commit()
    return {"status": "removed", "username": acct.username}
