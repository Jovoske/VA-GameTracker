"""User management — admin creates/removes guest logins (no open self-registration:
the app is internet-reachable, so accounts are handed out, never self-served)."""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.api.routes_stands import tonight
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.security import hash_password
from app.models import CameraAccount, Sit, User, Zone

router = APIRouter(prefix="/users", tags=["users"])
log = get_logger(__name__)


@router.get("")
def list_users(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(User).order_by(User.created_at)).all()
    return [
        {"id": str(u.id), "email": u.email, "role": u.role, "created_at": u.created_at,
         "is_you": u.id == admin.id}
        for u in rows
    ]


class CreateUserBody(BaseModel):
    email: str
    password: str
    role: str = "member"


@router.post("")
def create_user(
    body: CreateUserBody, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> dict:
    email = body.email.strip().lower()
    if "@" not in email or len(email) < 5:
        raise HTTPException(400, "Enter a valid email address")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if body.role not in ("member", "admin"):
        raise HTTPException(400, "Pick Member or Admin")
    taken = "Someone with that email already has a login"
    if db.scalar(select(User.id).where(func.lower(User.email) == email).limit(1)):
        raise HTTPException(400, taken)
    u = User(
        estate_id=admin.estate_id, email=email,
        password_hash=hash_password(body.password), role=body.role,
    )
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        # A second tap on a slow link got past the check with the first (audit D-24):
        # the same answer as the check's, not a server error.
        db.rollback()
        raise HTTPException(400, taken) from None
    return {"id": str(u.id), "email": u.email, "role": u.role}


@router.delete("/{user_id}")
def delete_user(
    user_id: uuid.UUID, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> dict:
    """Remove a person: they can't sign in again, on any phone, and the photo links
    they had stop working (deps.user_from_token finds no one).

    Everything they left stays the estate's (audit D-05, H-01, I-12): their sits and
    what they reported, the areas they drew, their notes and species fixes, with no
    name on them any more. Their reservations for tonight and later nights are let go
    so the stands are free, and a sit they are on now is ended.

    Camera logins they added keep fetching photos: nothing stops without anyone
    deciding it should. The admin removing them owns those logins from now, and
    Settings says who added each one, with the usual Remove, so the owner can decide.
    """
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "That person isn't on the app any more.")
    if u.id == admin.id:
        raise HTTPException(400, "You can't remove yourself")
    if u.role == "admin":
        admins = db.scalar(select(func.count(User.id)).where(User.role == "admin")) or 0
        if admins <= 1:
            raise HTTPException(400, "Keep at least one admin")
    email = u.email
    now = datetime.now(UTC)
    logins = db.execute(
        update(CameraAccount).where(CameraAccount.owner_user_id == u.id)
        # Who first added it, if that person went earlier and it passed to this one.
        .values(owner_user_id=admin.id,
                former_owner=func.coalesce(CameraAccount.former_owner, email))
        .returning(CameraAccount.id)
    ).all()
    db.execute(
        update(Sit).where(
            Sit.user_id == u.id, Sit.night >= tonight(now), Sit.started_at.is_(None),
            Sit.outcome == "unreported",
        ).values(outcome="cancelled")
    )
    db.execute(
        update(Sit).where(Sit.user_id == u.id, Sit.started_at.is_not(None),
                          Sit.ended_at.is_(None), Sit.outcome != "cancelled")
        .values(ended_at=now)
    )
    # The keys do this themselves (ON DELETE SET NULL, migration 0028); said here too
    # so a database that missed that migration still lets the person go.
    db.execute(update(Sit).where(Sit.user_id == u.id).values(user_id=None))
    db.execute(update(Zone).where(Zone.created_by == u.id).values(created_by=None))
    db.delete(u)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        log.warning("user.remove_failed", user_id=str(user_id), error=str(e.orig))
        raise HTTPException(
            409, f"Couldn't remove {email}: something on the app still points at them. "
            "Nothing was changed. Try again, or ask whoever runs the server.",
        ) from None
    moved = len(logins)
    note = f"{email} can't sign in any more. What they recorded stays."
    if moved:
        note += (f" {moved} camera login{'s' if moved > 1 else ''} they added keep"
                 f"{'' if moved > 1 else 's'} fetching photos, now under your name.")
    return {"status": "deleted", "email": email, "camera_logins_moved": moved, "note": note}
