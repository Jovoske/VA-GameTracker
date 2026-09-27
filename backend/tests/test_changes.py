"""Tests for "what changed since yesterday"."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.forecasting import changes
from app.forecasting.changes import LOOKBACK_NIGHTS, whats_changed
from app.forecasting.exposure import night_key_start, recompute_camera_nights, visits_by_night
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
    db_session.add(Species(id="wild_boar", common_name="Wild boar", is_priority=True,
                           huntable=True))
    db_session.flush()
    return c


def _night_at(night: date, hour: int = 21) -> datetime:
    """A UTC instant that falls inside the given night (evening-keyed)."""
    return datetime(night.year, night.month, night.day, hour, tzinfo=UTC)


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


@requires_db
def test_it_reads_the_nights_it_compares_not_the_whole_archive(db_session, cam, monkeypatch):
    """Tonight asks this on every load: it must not grow with years of photos.

    It reads from the start of the night before the ones it compares, so a visit
    already under way at 06:00 stays on the night it began, as it would unbounded.
    """
    first_kept = LAST_NIGHT - timedelta(days=LOOKBACK_NIGHTS - 1)
    for d in range(0, 12):
        _add(db_session, cam, LAST_NIGHT - timedelta(days=d), animals=2)
    _add(db_session, cam, LAST_NIGHT - timedelta(days=200), animals=5)  # years back, in effect
    # A boar from 05:50 to 06:10 local: it began on the night before the first kept one.
    dawn = datetime(first_kept.year, first_kept.month, first_kept.day, 3, 50, tzinfo=UTC)
    for at in (dawn, dawn + timedelta(minutes=20)):
        img = Image(camera_id=cam.id, captured_at=at, is_empty_frame=False, processed_at=at)
        db_session.add(img)
        db_session.flush()
        db_session.add(Detection(image_id=img.id, species_id="wild_boar", group_size=1))
    db_session.commit()
    recompute_camera_nights(db_session)

    asked = {}

    def spy(db, **kw):
        asked.update(kw)
        return visits_by_night(db, **kw)

    monkeypatch.setattr(changes, "visits_by_night", spy)
    whats_changed(db_session, today=TODAY)
    window_start = LAST_NIGHT - timedelta(days=LOOKBACK_NIGHTS)
    assert asked == {"start": night_key_start(window_start)}

    bounded = visits_by_night(db_session, start=asked["start"])
    everything = visits_by_night(db_session)
    kept = {k: v for k, v in everything.items() if k[0] > window_start}
    assert {k: v for k, v in bounded.items() if k[0] > window_start} == kept
    assert (first_kept, cam.id, "wild_boar") not in kept, "the 05:50 boar is on the night before"
    assert min(k[0] for k in bounded) == window_start
