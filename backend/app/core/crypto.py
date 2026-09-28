"""Symmetric encryption for stored third-party credentials (guest camera passwords).

Fernet, with the key derived from CREDENTIALS_KEY when it is set and from JWT_SECRET
otherwise, so a default install has no extra secret to manage. The values are useless
without the server's .env. Not a substitute for a real KMS, but a clear step up from
plaintext in the database.

Reading tries every key this server has had: CREDENTIALS_KEY, then JWT_SECRET, then
each of PREVIOUS_JWT_SECRET (comma-separated, newest first: `python -m app.manage
new-secret` adds the secret it replaces and keeps the older ones). A password read with
an older key is saved again under the current one on the next fetch
(app.ingestion.logins.read_password). So setting CREDENTIALS_KEY, letting one fetch
run, and only then changing JWT_SECRET keeps every saved login working; a password no
key can read is reported as "re-enter it", never dropped in silence.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings

__all__ = ["InvalidToken", "decrypt", "encrypt", "is_current", "previous_secrets"]


def _key(secret: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def previous_secrets(raw: str | None = None) -> list[str]:
    """The secrets in PREVIOUS_JWT_SECRET, newest first. One set by hand with a comma
    in it still counts whole too."""
    raw = (settings.previous_jwt_secret if raw is None else raw).strip()
    out: list[str] = []
    for secret in (raw, *raw.split(",")):
        secret = secret.strip()
        if secret and secret not in out:
            out.append(secret)
    return out


def _keys() -> list[Fernet]:
    secrets: list[str] = []
    for secret in (settings.credentials_key, settings.jwt_secret, *previous_secrets()):
        if secret and secret not in secrets:
            secrets.append(secret)
    return [_key(secret) for secret in secrets]


def encrypt(value: str) -> str:
    return _keys()[0].encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    """The plain value. Raises InvalidToken when no key this server has can read it."""
    return MultiFernet(_keys()).decrypt(token.encode()).decode()


def is_current(token: str) -> bool:
    """Whether `token` is under the key new values are saved with."""
    try:
        _keys()[0].decrypt(token.encode())
        return True
    except InvalidToken:
        return False
