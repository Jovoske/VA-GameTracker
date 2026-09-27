"""Password hashing (Argon2), sign-in tokens and photo passes (JWT).

Two kinds of token, told apart by their `scope` claim:

* A sign-in token (no scope): what the app sends as `Authorization: Bearer`. It
  carries the person's token version (`tv`, users.token_version); one made under an
  older version is refused, which is how a password change signs every other phone
  out (audit D-07).
* A photo pass (scope "img"): the only token a photo address may carry. An <img> tag
  can't send a header, so the photo's URL has to hold something; it used to hold the
  30-day sign-in token itself, which then sat in server logs, copied links and the
  tunnel's logs as a working login to the whole API (audit C-19, D-08, H-13). A pass
  opens photos and nothing else, for hours, not a month, and dies with the sign-in
  (same version, same person).
"""
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from app.core.config import settings

_hasher = PasswordHasher()

# A photo pass is the same text for everyone's requests in one window, so a photo's
# address doesn't change with every answer (it would be fetched again each time, on
# a weak signal): it lasts until the end of the window after the one it was made in,
# so between PASS_WINDOW and twice that.
IMAGE_SCOPE = "img"
PASS_WINDOW = timedelta(hours=6)

# A sign-in older than this is renewed on its next use (deps.get_current_user), so a
# hunter using the app daily is never thrown out mid-evening at the 30-day mark
# (audit D-11). A password change still ends it: the renewal carries the version.
RENEW_AFTER = timedelta(days=7)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except Argon2Error:
        return False


def create_access_token(subject: str, extra: dict | None = None, *, version: int = 0) -> str:
    now = datetime.now(UTC)
    payload: dict = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "tv": version,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def session_token(user) -> str:
    """A sign-in token for `user`, under their current token version."""
    return create_access_token(str(user.id), {"role": user.role}, version=user.token_version or 0)


def pass_expiry(now: datetime | None = None) -> datetime:
    """When a photo pass made at `now` stops working: the end of the next window."""
    now = now or datetime.now(UTC)
    window = PASS_WINDOW.total_seconds()
    start = int(now.timestamp() // window * window)
    return datetime.fromtimestamp(start + 2 * window, UTC)


def image_token(user, now: datetime | None = None) -> str:
    """The photo pass for `user` now. The same text all through one window."""
    return jwt.encode(
        {"sub": str(user.id), "scope": IMAGE_SCOPE, "tv": user.token_version or 0,
         "exp": pass_expiry(now)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
