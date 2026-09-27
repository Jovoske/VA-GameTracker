"""Shared API dependencies — current user / admin from a Bearer token."""
import uuid
from datetime import UTC, datetime

import jwt
from fastapi import Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import RENEW_AFTER, decode_token, image_token, session_token
from app.models import User

bearer_scheme = HTTPBearer(auto_error=True)

# Answer headers the app reads on every call (src/api.ts): the photo pass for photo
# addresses, and a renewed sign-in when the one in use is getting old.
IMAGE_TOKEN_HEADER = "X-Image-Token"
SESSION_TOKEN_HEADER = "X-Session-Token"

SIGNED_OUT = "You were signed out. Sign in again."


def user_from_token(raw: str, db: Session, *, scope: str | None = None) -> tuple[User, dict]:
    """The person a token belongs to, and its claims; a 401 otherwise.

    `scope` None wants a sign-in token, IMAGE_SCOPE a photo pass: neither opens the
    other's door. A token made before the person's password changed (an older token
    version) is refused, as is one whose person was removed.
    """
    try:
        payload = decode_token(raw)
        subject = payload.get("sub")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    if payload.get("scope") != scope:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    # A token whose subject is not a UUID is a bad token, not a server fault:
    # uuid.UUID() raises ValueError, which surfaced as a 500 instead of a 401.
    try:
        user_id = uuid.UUID(subject) if subject else None
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token subject")

    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    # A token from before the version existed carries none: that is version 0.
    if payload.get("tv", 0) != (user.token_version or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, SIGNED_OUT)
    return user, payload


def get_current_user(
    response: Response,
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    user, payload = user_from_token(creds.credentials, db)
    # Every answer carries the photo pass (the same text all window, so photo
    # addresses stay put), and a fresh sign-in once this one is a week old.
    response.headers[IMAGE_TOKEN_HEADER] = image_token(user)
    issued = payload.get("iat")
    if isinstance(issued, int | float) and (
        datetime.now(UTC) - datetime.fromtimestamp(issued, UTC) > RENEW_AFTER
    ):
        response.headers[SESSION_TOKEN_HEADER] = session_token(user)
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the estate admin can do that.")
    return user
