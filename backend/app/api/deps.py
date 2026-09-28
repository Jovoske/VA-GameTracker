"""Shared API dependencies — current user / admin from a Bearer token."""
import uuid
from datetime import UTC, datetime

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.refusal import Refusal
from app.core.db import get_db
from app.core.security import RENEW_AFTER, decode_token, image_token, session_token
from app.i18n import set_current, t
from app.models import User


class _Bearer(HTTPBearer):
    """FastAPI's Bearer check, with its two refusals ("Not authenticated", "Invalid
    authentication credentials") said in the caller's language (Accept-Language:
    nobody is signed in yet). Same status codes as before."""

    async def __call__(self, request: Request) -> HTTPAuthorizationCredentials | None:
        try:
            return await super().__call__(request)
        except HTTPException as e:
            key = "auth.not_authenticated" if e.detail == "Not authenticated" else (
                "auth.bad_credentials")
            raise HTTPException(e.status_code, t(key), headers=e.headers) from None


bearer_scheme = _Bearer(auto_error=True)

# Answer headers the app reads on every call (src/api.ts): the photo pass for photo
# addresses, and a renewed sign-in when the one in use is getting old.
IMAGE_TOKEN_HEADER = "X-Image-Token"
SESSION_TOKEN_HEADER = "X-Session-Token"


# The code on every refusal of a sign-in that no longer works (api.refusal): the app
# sends its person to sign in again, whatever the words say in their language.
SIGNED_OUT = "signed_out"


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
        raise Refusal(status.HTTP_401_UNAUTHORIZED, SIGNED_OUT, t("auth.token_invalid"))
    if payload.get("scope") != scope:
        raise Refusal(status.HTTP_401_UNAUTHORIZED, SIGNED_OUT, t("auth.token_invalid"))

    # A token whose subject is not a UUID is a bad token, not a server fault:
    # uuid.UUID() raises ValueError, which surfaced as a 500 instead of a 401.
    try:
        user_id = uuid.UUID(subject) if subject else None
    except (ValueError, AttributeError, TypeError):
        raise Refusal(status.HTTP_401_UNAUTHORIZED, SIGNED_OUT, t("auth.token_subject"))

    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise Refusal(status.HTTP_401_UNAUTHORIZED, SIGNED_OUT, t("auth.user_not_found"))
    # A token from before the version existed carries none: that is version 0.
    if payload.get("tv", 0) != (user.token_version or 0):
        raise Refusal(status.HTTP_401_UNAUTHORIZED, SIGNED_OUT, t("auth.signed_out"))
    return user, payload


def get_current_user(
    response: Response,
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    user, payload = user_from_token(creds.credentials, db)
    # From here on the answer is in this person's language (app.i18n).
    set_current(user.language)
    # Every answer carries the photo pass (the same text all window, so photo
    # addresses stay put), and a fresh sign-in once this one is a week old. Not for
    # a sign-in from before token versions (no `tv`): those sat in photo addresses,
    # in logs and copied links, and renewed they would never end. It works until its
    # own end, so nobody is signed out by the upgrade.
    response.headers[IMAGE_TOKEN_HEADER] = image_token(user)
    issued = payload.get("iat")
    if "tv" in payload and isinstance(issued, int | float) and (
        datetime.now(UTC) - datetime.fromtimestamp(issued, UTC) > RENEW_AFTER
    ):
        response.headers[SESSION_TOKEN_HEADER] = session_token(user)
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, t("auth.admin_only"))
    return user
