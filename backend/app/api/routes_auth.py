"""Authentication routes — login, current user, change password, the photo pass."""
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import IMAGE_TOKEN_HEADER, get_current_user
from app.api.throttle import HASH_WAIT_S, HASHING, client_ip, from_outside, throttle
from app.core.db import get_db
from app.core.security import (
    hash_password,
    image_token,
    known_phone,
    pass_expiry,
    phone_token,
    session_token,
    verify_password,
)
from app.core.startup import PUBLISHED_PASSWORDS, development
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]

BUSY = "The server is busy. Try again in a minute."
PUBLISHED = (
    "That is the password published with GameSense, so it can't sign in from the internet. "
    "Sign in on the server's own network and change it in Settings, or on the server run: "
    "python -m app.manage set-password {email}"
)


@lru_cache(maxsize=1)
def _no_such_hash() -> str:
    """A hash to check an unknown email's password against, so a wrong email takes
    as long to refuse as a wrong password and doesn't say which emails exist."""
    return hash_password("not anyone's password")


def check_password(password: str, hashed: str | None) -> bool:
    """Argon2, a few at a time (throttle.HASHING): each check takes 64 MB."""
    if not HASHING.acquire(timeout=HASH_WAIT_S):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, BUSY)
    try:
        ok = verify_password(password, hashed or _no_such_hash())
    finally:
        HASHING.release()
    return ok and hashed is not None


def find_user(db: Session, email: str) -> User | None:
    """The login for `email`, whatever its case or spaces: people are given
    "Marco@Finca.es" and type it that way, and logins are kept lowercase (D-23)."""
    return db.scalar(
        select(User).where(func.lower(User.email) == email.strip().lower())
        .order_by(User.created_at).limit(1)
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: DB) -> TokenResponse:
    email = body.email.strip().lower()
    known = known_phone(body.known_phone, email)
    # Booked before the password is checked, so requests sent all at once are held
    # like the same ones one after another (app.api.throttle).
    with throttle.attempt(client_ip(request), email, known=known) as attempt:
        user = find_user(db, email)
        if not check_password(body.password, user.password_hash if user else None):
            attempt.failed()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
        # An admin on the password published with this repository is the first thing
        # anyone would try on the public address: from the internet it doesn't sign
        # in; on the server's own network it does, so the owner can change it there
        # (audit H-14; the server no longer refuses to start over it).
        if (user.role == "admin" and body.password in PUBLISHED_PASSWORDS
                and not development() and from_outside(request)):
            attempt.failed()
            raise HTTPException(status.HTTP_403_FORBIDDEN, PUBLISHED.format(email=user.email))
        attempt.succeeded()
    return TokenResponse(access_token=session_token(user), image_token=image_token(user),
                         known_phone=phone_token(user))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.get("/image-token")
def get_image_token(user: CurrentUser) -> dict:
    """The photo pass, for a page whose photos stopped loading (the one it had ran
    out while the app sat in a pocket). Every answer carries it too."""
    return {"image_token": image_token(user), "expires_at": pass_expiry()}


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    body: ChangePasswordBody, response: Response, user: CurrentUser, db: DB,
) -> dict:
    """A new password signs out every other phone and browser: their sign-ins and
    photo passes were made under the old token version. This phone gets new ones in
    the answer, so it stays signed in (audit D-07)."""
    if not check_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That is not your current password")
    if len(body.new_password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must be at least 8 characters")
    user.password_hash = hash_password(body.new_password)
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    fresh = image_token(user)
    response.headers[IMAGE_TOKEN_HEADER] = fresh
    return {
        "status": "ok", "access_token": session_token(user), "image_token": fresh,
        "note": "Password changed. Every other phone signed in as you has to sign in again.",
    }
