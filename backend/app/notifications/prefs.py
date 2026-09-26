"""Per-user notification preferences, with defaults for anyone who never set them.

A user without a row has never opened the notifications settings. They get alerts
OFF (push needs their permission anyway, so nothing can arrive until they act) and
the priority species pre-selected, so the first visit shows a sensible list rather
than an empty one. Every camera is on until the person mutes it.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import NotificationPref, Species


def default_species(db: Session) -> list[str]:
    return sorted(db.scalars(select(Species.id).where(Species.is_priority.is_(True))).all())


def effective_prefs(db: Session, user_id: uuid.UUID) -> tuple[bool, list[str]]:
    """(enabled, species_ids) — the stored row, or the defaults when there is none."""
    row = db.get(NotificationPref, user_id)
    if row is not None:
        return bool(row.enabled), list(row.species_ids or [])
    return False, default_species(db)


def muted_cameras(db: Session, user_id: uuid.UUID) -> set[str]:
    """The ids (as strings) of the cameras this person hears nothing from."""
    row = db.get(NotificationPref, user_id)
    return set(row.muted_camera_ids or []) if row is not None else set()


def locked_prefs(db: Session, user_id: uuid.UUID) -> NotificationPref:
    """The person's row, created with the defaults if missing, locked for this write.

    Two quick taps (a camera muted in Settings while the map mutes another) each
    read, change and write the lists. Locking the row makes the second wait for the
    first rather than write back a list that doesn't have the first change in it.
    """
    enabled, species = effective_prefs(db, user_id)
    db.execute(
        pg_insert(NotificationPref)
        .values(user_id=user_id, enabled=enabled, species_ids=species, muted_camera_ids=[])
        .on_conflict_do_nothing(index_elements=[NotificationPref.user_id])
    )
    return db.scalars(
        select(NotificationPref)
        .where(NotificationPref.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
