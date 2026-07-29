"""SPYPOINT account management — admin only.

Passwords are write-only over the API: they can be set and replaced, never read
back. Responses expose whether a usable password is stored, not the value.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.db import get_db
from app.core.security import decrypt_secret, encrypt_secret
from app.models import Camera, Estate, SpypointAccount, User

router = APIRouter(prefix="/spypoint/accounts", tags=["spypoint"])


class AccountIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)
    active: bool = True


class AccountPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    password: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None


def _out(account: SpypointAccount, camera_count: int) -> dict:
    return {
        "id": str(account.id),
        "label": account.label,
        "username": account.username,
        "active": account.active,
        # Never return the secret. Surface only whether it is usable, so a broken
        # account is visible in the UI without leaking anything.
        "password_set": account.password_enc is not None,
        "password_readable": decrypt_secret(account.password_enc) is not None,
        "last_sync_at": account.last_sync_at,
        "last_error": account.last_error,
        "cameras": camera_count,
    }


@router.get("")
def list_accounts(
    _: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> list[dict]:
    counts = dict(
        db.execute(
            select(Camera.spypoint_account_id, func.count(Camera.id)).group_by(
                Camera.spypoint_account_id
            )
        ).all()
    )
    rows = db.scalars(select(SpypointAccount).order_by(SpypointAccount.created_at)).all()
    return [_out(a, int(counts.get(a.id, 0))) for a in rows]


@router.post("", status_code=201)
def create_account(
    body: AccountIn, _: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> dict:
    if db.scalar(select(SpypointAccount).where(SpypointAccount.username == body.username)):
        raise HTTPException(409, "An account with that username already exists")
    estate = db.scalar(select(Estate).order_by(Estate.created_at))
    if estate is None:
        raise HTTPException(400, "No estate configured yet")

    account = SpypointAccount(
        estate_id=estate.id,
        label=body.label,
        username=body.username,
        password_enc=encrypt_secret(body.password),
        active=body.active,
    )
    db.add(account)
    db.commit()
    return _out(account, 0)


@router.patch("/{account_id}")
def update_account(
    account_id: uuid.UUID,
    body: AccountPatch,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    account = db.get(SpypointAccount, account_id)
    if account is None:
        raise HTTPException(404, "Account not found")
    if body.label is not None:
        account.label = body.label
    if body.active is not None:
        account.active = body.active
    if body.password is not None:
        account.password_enc = encrypt_secret(body.password)
        account.last_error = None  # a new password deserves a fresh attempt
    db.commit()
    count = db.scalar(
        select(func.count(Camera.id)).where(Camera.spypoint_account_id == account.id)
    )
    return _out(account, int(count or 0))


@router.delete("/{account_id}", status_code=204, response_model=None)
def delete_account(
    account_id: uuid.UUID,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> None:
    account = db.get(SpypointAccount, account_id)
    if account is None:
        raise HTTPException(404, "Account not found")
    linked = db.scalar(
        select(func.count(Camera.id)).where(Camera.spypoint_account_id == account.id)
    )
    if linked:
        # Deleting would orphan cameras and, with them, their images and detections.
        # Deactivating stops the sync without touching a single row of history.
        raise HTTPException(
            409,
            f"{linked} camera(s) still belong to this account. Deactivate it instead, "
            "or move those cameras first — deleting would orphan their history.",
        )
    db.delete(account)
    db.commit()
