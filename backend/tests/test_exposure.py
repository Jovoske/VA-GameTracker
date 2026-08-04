"""Exposure and visit-collapsing tests.

These pin the two arithmetic errors underneath every statistic the app produced:
counting a night the camera wasn't watching as a night with no animals, and
counting photographs as if they were animals.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.forecasting.exposure import (
    excluded_nights,
    observed_nights,
    recompute_camera_nights,
    visits_by_night,
)
from app.models import Camera, CameraNight, Detection, Estate, Image, Species

from .conftest import requires_db


@pytest.fixture
def estate_and_camera(db_session):
    estate = Estate(name="E", timezone="Europe/Madrid", lat=39.0, lon=-1.3)
    db_session.add(estate)
    db_session.flush()
    cam = Camera(estate_id=estate.id, name="Puente", active=True)
    db_session.add(cam)
    db_session.add(Species(id="wild_boar", common_name="Wild boar", is_priority=True, huntable=True))
    db_session.flush()
    return estate, cam


def _frame(db, cam, when: datetime, *, empty=False, processed=True):
    img = Image(
        camera_id=cam.id,
        captured_at=when,
        is_empty_frame=empty,
        processed_at=when if processed else None,
        reviewed=False,
    )
    db.add(img)
    db.flush()
    return img


def _states(db, cam) -> dict[date, str]:
    rows = db.query(CameraNight).filter(CameraNight.camera_id == cam.id).all()
    return {r.night: r.exposure_state for r in rows}


@requires_db
def test_empty_frames_prove_the_camera_was_awake(db_session, estate_and_camera):
    """A night of nothing but blanks is a real observation, not missing data."""
    _, cam = estate_and_camera
    base = datetime(2025, 10, 1, 21, 0, tzinfo=timezone.utc)
    for i in range(3):
        _frame(db_session, cam, base + timedelta(days=i), empty=True)
    db_session.commit()

    recompute_camera_nights(db_session, camera_id=cam.id)
    assert set(_states(db_session, cam).values()) == {"CONFIRMED"}
    assert observed_nights(db_session, cam.id) == 3


@requires_db
def test_a_gap_between_active_nights_is_a_true_zero(db_session, estate_and_camera):
    """Frames either side mean the camera was there and simply saw nothing."""
    _, cam = estate_and_camera
    base = datetime(2025, 10, 1, 21, 0, tzinfo=timezone.utc)
    _frame(db_session, cam, base, empty=True)
    _frame(db_session, cam, base + timedelta(days=3), empty=True)
    db_session.commit()

    recompute_camera_nights(db_session, camera_id=cam.id)
    states = _states(db_session, cam)
    assert states[date(2025, 10, 1)] == "CONFIRMED"
    assert states[date(2025, 10, 2)] == "PRESUMED_UP"
    assert states[date(2025, 10, 3)] == "PRESUMED_UP"
    assert states[date(2025, 10, 4)] == "CONFIRMED"
    assert observed_nights(db_session, cam.id) == 4


@requires_db
def test_unprocessed_frames_are_not_an_observation(db_session, estate_and_camera):
    """The backlog artefact: unclassified frames used to read as zero animals."""
    _, cam = estate_and_camera
    base = datetime(2025, 10, 1, 21, 0, tzinfo=timezone.utc)
    _frame(db_session, cam, base, empty=True)
    _frame(db_session, cam, base + timedelta(days=1), processed=False)
    _frame(db_session, cam, base + timedelta(days=2), empty=True)
    db_session.commit()

    recompute_camera_nights(db_session, camera_id=cam.id)
    states = _states(db_session, cam)
    assert states[date(2025, 10, 2)] == "UNPROCESSED"
    # Excluded from the denominator rather than counted as a quiet night.
    assert observed_nights(db_session, cam.id) == 2
    assert excluded_nights(db_session, cam.id) == 1


@requires_db
def test_recompute_is_idempotent(db_session, estate_and_camera):
    _, cam = estate_and_camera
    base = datetime(2025, 10, 1, 21, 0, tzinfo=timezone.utc)
    for i in range(4):
        _frame(db_session, cam, base + timedelta(days=i), empty=True)
    db_session.commit()

    recompute_camera_nights(db_session, camera_id=cam.id)
    first = _states(db_session, cam)
    recompute_camera_nights(db_session, camera_id=cam.id)
    assert _states(db_session, cam) == first
    assert db_session.query(CameraNight).count() == len(first)


@requires_db
def test_night_window_puts_post_midnight_frames_on_the_previous_evening(db_session, estate_and_camera):
    _, cam = estate_and_camera
    # 22:00 Madrid on the 4th, and 02:00 Madrid on the 5th: one night.
    _frame(db_session, cam, datetime(2025, 10, 4, 20, 0, tzinfo=timezone.utc), empty=True)
    _frame(db_session, cam, datetime(2025, 10, 5, 0, 0, tzinfo=timezone.utc), empty=True)
    db_session.commit()

    recompute_camera_nights(db_session, camera_id=cam.id)
    states = _states(db_session, cam)
    assert list(states) == [date(2025, 10, 4)]
    assert states[date(2025, 10, 4)] == "CONFIRMED"


# ── visits ──────────────────────────────────────────────────────────────────


@requires_db
def test_a_burst_of_frames_is_one_visit(db_session, estate_and_camera):
    """One boar loitering through thirty frames counted thirty 'sightings'."""
    _, cam = estate_and_camera
    base = datetime(2025, 10, 4, 21, 0, tzinfo=timezone.utc)
    for i in range(30):
        img = _frame(db_session, cam, base + timedelta(seconds=5 * i))
        db_session.add(
            Detection(image_id=img.id, species_id="wild_boar", sex="unknown",
                      age_class="unknown", group_size=1)
        )
    db_session.commit()

    got = visits_by_night(db_session, camera_id=cam.id)
    (row,) = got.values()
    assert row["frames"] == 30
    assert row["visits"] == 1, "a burst is one arrival, not thirty"
    assert row["animals"] == 1


@requires_db
def test_separate_arrivals_count_separately(db_session, estate_and_camera):
    _, cam = estate_and_camera
    base = datetime(2025, 10, 4, 20, 0, tzinfo=timezone.utc)
    # Three arrivals, each well beyond the 30-minute independence gap.
    for hours in (0, 2, 5):
        for i in range(3):
            img = _frame(db_session, cam, base + timedelta(hours=hours, seconds=5 * i))
            db_session.add(
                Detection(image_id=img.id, species_id="wild_boar", sex="unknown",
                          age_class="unknown", group_size=1)
            )
    db_session.commit()

    (row,) = visits_by_night(db_session, camera_id=cam.id).values()
    assert row["frames"] == 9
    assert row["visits"] == 3


@requires_db
def test_a_herd_in_one_frame_is_not_one_animal(db_session, estate_and_camera):
    """The mirror-image error: group_size was computed and never used."""
    _, cam = estate_and_camera
    img = _frame(db_session, cam, datetime(2025, 10, 4, 21, 0, tzinfo=timezone.utc))
    db_session.add(
        Detection(image_id=img.id, species_id="wild_boar", sex="unknown",
                  age_class="unknown", group_size=12)
    )
    db_session.commit()

    (row,) = visits_by_night(db_session, camera_id=cam.id).values()
    assert row["frames"] == 1
    assert row["visits"] == 1
    assert row["animals"] == 12


@requires_db
def test_excluded_nights_are_reported_not_hidden(db_session, monkeypatch):
    """An exclusion nobody is told about is indistinguishable from the bug it replaced.

    The whole point of the exposure table is that a night the camera could not
    vouch for is left out rather than averaged in as "no animals". If the app
    never says how many it left out, the user cannot tell a quiet wood from a
    dead camera — which is exactly the confusion this replaced.
    """
    import app.forecasting.model as model
    from app.forecasting.model import forecast_tonight

    monkeypatch.setattr(model, "_tonight_conditions", lambda now: {"moon_phase": "New Moon"})

    estate = Estate(name="E", timezone="Europe/Madrid", lat=39.0, lon=-1.3)
    db_session.add(estate)
    db_session.flush()
    db_session.add(Species(id="wild_boar", common_name="Wild boar", huntable=True))
    cam = Camera(estate_id=estate.id, name="Ridge")
    db_session.add(cam)
    db_session.flush()

    base = datetime(2025, 10, 1, 21, 0, tzinfo=timezone.utc)
    for i in range(6):
        img = Image(
            camera_id=cam.id,
            captured_at=base + timedelta(days=i),
            # The last two nights are still queued for the classifier, so they are
            # not observations yet.
            processed_at=None if i >= 4 else base + timedelta(days=i),
        )
        db_session.add(img)
        db_session.flush()
        if i < 4:
            db_session.add(Detection(image_id=img.id, species_id="wild_boar"))
    db_session.commit()
    recompute_camera_nights(db_session)

    out = forecast_tonight(db_session)
    assert out["exposure"]["excluded_nights"] == 2
    assert "2 nights left out" in out["exposure"]["note"]
    assert "not counted either way" in out["exposure"]["note"]
