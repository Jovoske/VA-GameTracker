"""Tests for "what changed since yesterday"."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.forecasting.changes import whats_changed
from app.forecasting.exposure import recompute_camera_nights
from app.models import Camera, Detection, Estate, Image, Species

from .conftest import requires_db

TODAY = date(2025, 11, 1)
LAST_NIGHT = TODAY - timedelta(days=1)


@pytest.fixture
def cam(db_session):
    estate = Estate(name="E", timezone="Europe/Madrid", lat=39.0, lon=-1.3)
    db_session.add(estate)
    db_session.flush()
    c = Camera(estate_id=estate.id, name="Puente", active=True)
    db_session.add(c)
    db_session.add(Species(id="wild_boar", common_name="Wild boar", is_priority=True, huntable=True))
    db_session.flush()
    return c


def _night_at(night: date, hour: int = 21) -> datetime:
    """A UTC instant that falls inside the given night (evening-keyed)."""
    return datetime(night.year, night.month, night.day, hour, tzinfo=timezone.utc)


def _add(db, cam, night: date, *, animals: int, processed=True):
    """One frame for exposure, plus `animals` detections spread across the night."""
    img = Image(camera_id=cam.id, captured_at=_night_at(night), is_empty_frame=animals == 0,
                processed_at=_night_at(night) if processed else None, reviewed=False)
    db.add(img)
    db.flush()
    for i in range(animals):
        # Separated well beyond the 30-minute gap so each is its own visit.
        extra = Image(camera_id=cam.id, captured_at=_night_at(night) + timedelta(hours=i),
                      is_empty_frame=False, processed_at=_night_at(night), reviewed=False)
        db.add(extra)
        db.flush()
        db.add(Detection(image_id=extra.id, species_id="wild_boar", sex="unknown",
                         age_class="unknown", group_size=1))


@requires_db
def test_it_is_never_blank(db_session, cam):
    """Silence must be stated, not implied — otherwise it reads as broken."""
    for d in range(1, 12):
        _add(db_session, cam, LAST_NIGHT - timedelta(days=d), animals=2)
    _add(db_session, cam, LAST_NIGHT, animals=2)
    db_session.commit()
    recompute_camera_nights(db_session)

    got = whats_changed(db_session, today=TODAY)
    assert got["text"], "must always say something"
    assert got["kind"] == "none"
    assert "Nothing changed" in got["text"]


@requires_db
def test_a_return_after_quiet_nights_is_reported(db_session, cam):
    for d in range(6, 16):
        _add(db_session, cam, LAST_NIGHT - timedelta(days=d), animals=2)
    for d in range(1, 6):  # five quiet-but-watching nights
        _add(db_session, cam, LAST_NIGHT - timedelta(days=d), animals=0)
    _add(db_session, cam, LAST_NIGHT, animals=3)
    db_session.commit()
    recompute_camera_nights(db_session)

    got = whats_changed(db_session, today=TODAY)
    assert got["kind"] == "return"
    assert got["camera"] == "Puente"
    assert "quiet nights" in got["text"]


@requires_db
def test_a_camera_that_sent_nothing_outranks_animal_changes(db_session, cam):
    """A dead camera changes what the rest of the screen is worth."""
    for d in range(1, 12):
        _add(db_session, cam, LAST_NIGHT - timedelta(days=d), animals=2)
    # Nothing at all for last night: no frames, so exposure cannot vouch for it.
    db_session.commit()
    recompute_camera_nights(db_session)

    got = whats_changed(db_session, today=TODAY)
    assert got["kind"] == "camera_down"
    assert "unknown" in got["text"].lower()


@requires_db
def test_a_blind_night_is_not_reported_as_animals_leaving(db_session, cam):
    """The failure this whole layer exists to prevent."""
    for d in range(1, 12):
        _add(db_session, cam, LAST_NIGHT - timedelta(days=d), animals=3)
    # Frames arrived but were never classified — not an observation of absence.
    _add(db_session, cam, LAST_NIGHT, animals=0, processed=False)
    db_session.commit()
    recompute_camera_nights(db_session)

    got = whats_changed(db_session, today=TODAY)
    assert got["kind"] != "gone_quiet", "an unprocessed night must not read as absence"
    assert got["kind"] == "camera_down"


@requires_db
def test_too_little_history_makes_no_claim(db_session, cam):
    _add(db_session, cam, LAST_NIGHT, animals=1)
    _add(db_session, cam, LAST_NIGHT - timedelta(days=1), animals=1)
    db_session.commit()
    recompute_camera_nights(db_session)

    got = whats_changed(db_session, today=TODAY)
    assert got["kind"] == "none"
