"""Symmetric encryption for stored third-party credentials (guest SPYPOINT passwords).

Fernet with a key derived from JWT_SECRET — no extra secret to manage, and the values
are useless without the server's .env. Not a substitute for a real KMS, but a clear step
up from plaintext in the database.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import settings


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode()).digest())
    return Fernet(key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
