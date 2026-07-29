"""Password hashing (Argon2), JWT access tokens, and reversible secret storage."""
import base64
import hashlib
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except Argon2Error:
        return False


def create_access_token(subject: str, extra: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# ── Reversible secrets ──────────────────────────────────────────────────────
# Third-party credentials (SPYPOINT logins) must be replayed to the upstream API,
# so they cannot be hashed — they are encrypted at rest instead. The key is derived
# from JWT_SECRET so operators have one secret to protect, not two.
#
# Rotating JWT_SECRET therefore invalidates stored credentials: decrypt_secret
# returns None rather than raising, and the account is reported as needing its
# password re-entered. That is the correct failure mode — it is visible and
# recoverable, unlike silently syncing with a corrupted password and tripping
# SPYPOINT's rate limiter.


def _fernet() -> Fernet:
    key = hashlib.sha256(settings.jwt_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str | None) -> str | None:
    """Plaintext, or None if the value is unreadable under the current key."""
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
