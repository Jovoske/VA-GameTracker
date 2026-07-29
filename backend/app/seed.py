"""Idempotent seed — default estate + admin user. Run on first start."""
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging, get_logger
from app.core.security import encrypt_secret, hash_password
from app.models import Estate, SpypointAccount, User

log = get_logger(__name__)


def seed() -> None:
    configure_logging()
    with SessionLocal() as db:
        estate = db.scalar(select(Estate).where(Estate.name == settings.estate_name))
        if estate is None:
            estate = Estate(
                name=settings.estate_name,
                timezone=settings.estate_timezone,
                lat=settings.estate_lat,
                lon=settings.estate_lon,
            )
            db.add(estate)
            db.flush()
            log.info("seed.estate_created", name=estate.name)

        admin = db.scalar(select(User).where(User.email == settings.admin_email))
        if admin is None:
            db.add(
                User(
                    estate_id=estate.id,
                    email=settings.admin_email,
                    password_hash=hash_password(settings.admin_password),
                    role="admin",
                )
            )
            log.info("seed.admin_created", email=settings.admin_email)

        _seed_spypoint_account(db, estate)

        db.commit()


def _seed_spypoint_account(db, estate: Estate) -> None:
    """Adopt SPYPOINT_USERNAME/PASSWORD as an account row, once.

    Migration 0005 does this too, but on a fresh install it runs before the estate
    exists, so the adoption lands here instead. Both paths are idempotent, and
    neither ever overwrites a password already stored — an operator who changed the
    credentials through the API keeps that change even if a stale value is still
    sitting in .env.
    """
    username = (settings.spypoint_username or "").strip()
    if not username:
        return
    existing = db.scalar(select(SpypointAccount).where(SpypointAccount.username == username))
    if existing is not None:
        return
    db.add(
        SpypointAccount(
            estate_id=estate.id,
            label="Main account",
            username=username,
            password_enc=encrypt_secret(settings.spypoint_password)
            if settings.spypoint_password
            else None,
            active=True,
        )
    )
    db.flush()
    log.info("seed.spypoint_account_adopted", username=username)


if __name__ == "__main__":
    seed()
