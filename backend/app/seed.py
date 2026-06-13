"""Idempotent seed — default estate + admin user. Run on first start."""
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.models import Estate, User

log = get_logger(__name__)


def seed() -> None:
    configure_logging()
    with SessionLocal() as db:
        estate = db.scalar(select(Estate).where(Estate.name == settings.estate_name))
        if estate is None:
            estate = Estate(
                name=settings.estate_name,
                timezone=settings.estate_timezone,
                centroid=f"SRID=4326;POINT({settings.estate_lon} {settings.estate_lat})",
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

        db.commit()


if __name__ == "__main__":
    seed()
