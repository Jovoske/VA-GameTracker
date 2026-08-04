"""User management — admin creates/removes guest logins (no open self-registration:
the app is internet-reachable, so accounts are handed out, never self-served)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.db import get_db
from app.core.security import hash_password
from app.models import User

router = APIRouter(prefix="/users", tags=["users"])


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
        raise HTTPException(400, "Role must be member or admin")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(400, "A user with that email already exists")
    u = User(
        estate_id=admin.estate_id, email=email,
        password_hash=hash_password(body.password), role=body.role,
    )
    db.add(u)
    db.commit()
    return {"id": str(u.id), "email": u.email, "role": u.role}


@router.delete("/{user_id}")
def delete_user(
    user_id: uuid.UUID, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> dict:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    if u.id == admin.id:
        raise HTTPException(400, "You can't delete your own account")
    if u.role == "admin":
        admins = db.scalar(select(func.count(User.id)).where(User.role == "admin")) or 0
        if admins <= 1:
            raise HTTPException(400, "Can't delete the last admin")
    db.delete(u)
    db.commit()
    return {"status": "deleted", "email": u.email}
