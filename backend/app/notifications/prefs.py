"""Per-user notification preferences, with defaults for anyone who never set them.

A user without a row has never opened the notifications settings. They get alerts
OFF (push needs their permission anyway, so nothing can arrive until they act) and
the priority species pre-selected, so the first visit shows a sensible list rather
than an empty one.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
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
