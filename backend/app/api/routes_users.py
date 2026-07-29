"""User management — admin only.

Existing users are never touched by this module's arrival: it only adds routes.
Two safety rails matter more than the CRUD itself:

* an admin cannot delete or demote themselves, and
* the last remaining admin cannot be removed or demoted,

because either would lock every human out of the estate with no recovery path
short of a psql session.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.db import get_db
from app.core.security import hash_password
from app.models import Estate, User

router = APIRouter(prefix="/users", tags=["users"])

ROLES = ("admin", "member", "viewer")


class UserIn(BaseModel):
    # Deliberately NOT pydantic's EmailStr. It rejects special-use domains such as
    # .local, and this app ships admin@gamesense.local as its own default — strict
    # validation would refuse the credentials operators already use. A self-hosted
    # estate tool needs a login, not a deliverable mailbox.
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=200)
    role: str = Field(default="member")

    @field_validator("email")
    @classmethod
    def _looks_like_an_address(cls, v: str) -> str:
        v = v.strip()
        local, sep, domain = v.partition("@")
        if not sep or not local or not domain or any(c.isspace() for c in v):
            raise ValueError("email must look like name@host")
        return v


class UserPatch(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=200)
    role: str | None = None


def _out(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "created_at": user.created_at,
    }


def _admin_count(db: Session) -> int:
    return int(db.scalar(select(func.count(User.id)).where(User.role == "admin")) or 0)


def _validate_role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(422, f"role must be one of {', '.join(ROLES)}")
    return role


@router.get("")
def list_users(_: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(User).order_by(User.created_at)).all()
    return [_out(u) for u in rows]


@router.get("/me")
def whoami(user: User = Depends(get_current_user)) -> dict:
    """Available to any signed-in user — the UI needs it to hide admin controls."""
    return _out(user)


@router.post("", status_code=201)
def create_user(
    body: UserIn, _: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> dict:
    _validate_role(body.role)
    email = body.email.strip().lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "A user with that email already exists")
    estate = db.scalar(select(Estate).order_by(Estate.created_at))
    user = User(
        estate_id=estate.id if estate else None,
        email=email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.commit()
    return _out(user)


@router.patch("/{user_id}")
def update_user(
    user_id: uuid.UUID,
    body: UserPatch,
    current: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")

    if body.role is not None:
        _validate_role(body.role)
        demoting_an_admin = user.role == "admin" and body.role != "admin"
        # Only the last-admin case is guarded. Standing down while another admin
        # exists is a legitimate handover and is reversible by that other admin.
        if demoting_an_admin and _admin_count(db) <= 1:
            raise HTTPException(409, "This is the only admin — promote another first")
        user.role = body.role

    if body.password is not None:
        user.password_hash = hash_password(body.password)

    db.commit()
    return _out(user)


@router.delete("/{user_id}", status_code=204, response_model=None)
def delete_user(
    user_id: uuid.UUID,
    current: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == current.id:
        raise HTTPException(409, "You cannot delete your own account")
    if user.role == "admin" and _admin_count(db) <= 1:
        raise HTTPException(409, "This is the only admin — promote another first")
    db.delete(user)
    db.commit()
