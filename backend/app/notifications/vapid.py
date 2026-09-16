"""VAPID key pair for Web Push — generated once, kept in app_settings.

Push services require the application server to identify itself with an EC key pair
(RFC 8292). The private half signs every push; the public half is handed to the
browser when it subscribes, and the subscription is bound to it — rotate the key and
every phone has to subscribe again. So the pair is made on first use and then never
touched, and it lives in the database rather than .env so a fresh install needs no
hand-editing on the server before notifications work.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AppSetting

KEY = "vapid"


@dataclass(frozen=True)
class VapidKeys:
    private_pem: str
    # base64url of the uncompressed P-256 point — exactly what PushManager.subscribe()
    # takes as applicationServerKey.
    public_key: str


def _generate_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def public_key_from_pem(private_pem: str) -> str:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def get_vapid(db: Session) -> VapidKeys:
    """The estate's key pair, creating it on first call.

    The API and the pipeline are separate processes and could both arrive here first;
    the primary key on app_settings makes one of them lose, and the loser re-reads.
    """
    row = db.get(AppSetting, KEY)
    if row is None:
        row = AppSetting(key=KEY, value={"private_pem": _generate_pem()})
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.get(AppSetting, KEY)
            if row is None:  # pragma: no cover — the conflicting insert must have won
                raise
    pem = row.value["private_pem"]
    return VapidKeys(private_pem=pem, public_key=public_key_from_pem(pem))


def subject() -> str:
    """The contact a push service may use if this sender misbehaves (RFC 8292 §2.1)."""
    return settings.vapid_subject or f"mailto:{settings.admin_email}"
