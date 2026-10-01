"""Approach-arc inference and dark-exit tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.forecasting.inference import MIN_SEQUENCES, bearing, dark_exit, suggest_approach_arcs
from app.models import Camera, Detection, Estate, Image, Species, Stand

from .conftest import requires_db


def _days_ago(days: int, hour: int) -> datetime:
    """That many days back, on the hour (UTC). dark_exit reads the last
    EXIT_HISTORY_NIGHTS nights, so its photos must be recent: dated 1 Oct 2025, the
    busy camera's early hours fell out of that window on 1 Oct 2026 and its test
    failed."""
    day = datetime.now(timezone.utc) - timedelta(days=days)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0)


def test_bearing_points_the_right_way():
    # Due north: same longitude, higher latitude.
    assert bearing(39.0, -1.3, 40.0, -1.3) == pytest.approx(0.0, abs=0.5)
    # Due east.
    assert bearing(39.0, -1.3, 39.0, -0.3) == pytest.approx(90.0, abs=0.5)
    assert bearing(39.0, -1.3, 38.0, -1.3) == pytest.approx(180.0, abs=0.5)


@pytest.fixture
def estate(db_session):
    e = Estate(name="E", timezone="Europe/Madrid", lat=39.0, lon=-1.3)
    db_session.add(e)
    db_session.add(Species(id="wild_boar", common_name="Wild boar", is_priority=True, huntable=True))
    db_session.flush()
    return e


@requires_db
def test_arcs_are_suggested_from_repeated_movement(db_session, estate):
    """The herd states its own approach lines by walking past two cameras."""
    target = Camera(estate_id=estate.id, name="Puente", lat=39.0, lon=-1.3, active=True)
    source = Camera(estate_id=estate.id, name="Solana", lat=40.0, lon=-1.3, active=True)  # due north
    db_session.add_all([target, source])
    db_session.flush()
    stand = Stand(estate_id=estate.id, name="Puente stand", camera_id=target.id)
    db_session.add(stand)
    db_session.flush()

    base = datetime(2025, 10, 1, 21, 0, tzinfo=timezone.utc)
    for i in range(MIN_SEQUENCES):
        for cam, offset in ((source, 0), (target, 10)):
            img = Image(
                camera_id=cam.id,
                captured_at=base + timedelta(days=i, minutes=offset),
                is_empty_frame=False,
                processed_at=base,
                reviewed=False,
            )
            db_session.add(img)
            db_session.flush()
            db_session.add(
                Detection(image_id=img.id, species_id="wild_boar", sex="unknown",
                          age_class="unknown", group_size=1)
            )
    db_session.commit()

    out = suggest_approach_arcs(db_session, stand)
    assert len(out["suggestions"]) == 1
    s = out["suggestions"][0]
    assert s["from_camera"] == "Solana"
    assert s["approach_deg"] == pytest.approx(0, abs=2)  # animals came from the north
    assert s["sequences"] >= MIN_SEQUENCES


@requires_db
def test_arcs_are_never_written_automatically(db_session, estate):
    """A guessed arc becomes confident wind advice — it must be confirmed first."""
    target = Camera(estate_id=estate.id, name="Puente", lat=39.0, lon=-1.3, active=True)
    source = Camera(estate_id=estate.id, name="Solana", lat=40.0, lon=-1.3, active=True)
    db_session.add_all([target, source])
    db_session.flush()
    stand = Stand(estate_id=estate.id, name="Puente stand", camera_id=target.id)
    db_session.add(stand)
    db_session.commit()

    suggest_approach_arcs(db_session, stand)
    db_session.refresh(stand)
    assert stand.approach_dirs_deg is None


@requires_db
def test_one_coincidence_is_not_a_route(db_session, estate):
    target = Camera(estate_id=estate.id, name="Puente", lat=39.0, lon=-1.3, active=True)
    source = Camera(estate_id=estate.id, name="Solana", lat=40.0, lon=-1.3, active=True)
    db_session.add_all([target, source])
    db_session.flush()
    stand = Stand(estate_id=estate.id, name="Puente stand", camera_id=target.id)
    db_session.add(stand)
    db_session.flush()

    base = datetime(2025, 10, 1, 21, 0, tzinfo=timezone.utc)
    for cam, offset in ((source, 0), (target, 10)):  # exactly one sequence
        img = Image(camera_id=cam.id, captured_at=base + timedelta(minutes=offset),
                    is_empty_frame=False, processed_at=base, reviewed=False)
        db_session.add(img)
        db_session.flush()
        db_session.add(Detection(image_id=img.id, species_id="wild_boar", sex="unknown",
                                 age_class="unknown", group_size=1))
    db_session.commit()

    out = suggest_approach_arcs(db_session, stand)
    assert out["suggestions"] == []
    assert "yours to solve" in out["reason"]


@requires_db
def test_a_stand_with_no_camera_says_so(db_session, estate):
    stand = Stand(estate_id=estate.id, name="Orphan")
    db_session.add(stand)
    db_session.commit()
    out = suggest_approach_arcs(db_session, stand)
    assert out["suggestions"] == []
    assert "not linked" in out["reason"]


@requires_db
def test_dark_exit_finds_a_quiet_hour(db_session, estate):
    """Stands die from how you leave them, not how you arrive."""
    cam = Camera(estate_id=estate.id, name="Puente", lat=39.0, lon=-1.3, active=True)
    db_session.add(cam)
    db_session.flush()
    stand = Stand(estate_id=estate.id, name="Puente stand", camera_id=cam.id)
    db_session.add(stand)
    db_session.flush()

    # Heavy activity at 21:00-22:00 Madrid, nothing later.
    for i in range(40):
        img = Image(camera_id=cam.id,
                    captured_at=_days_ago(60, 19) + timedelta(days=i),
                    is_empty_frame=False, processed_at=datetime.now(timezone.utc), reviewed=False)
        db_session.add(img)
        db_session.flush()
        db_session.add(Detection(image_id=img.id, species_id="wild_boar", sex="unknown",
                                 age_class="unknown", group_size=1))
    db_session.commit()

    out = dark_exit(db_session, stand)
    assert out["hour"] is not None
    assert out["reason"] is None
    assert "Dark exit" in out["text"]


@requires_db
def test_dark_exit_admits_when_there_is_no_quiet_hour(db_session, estate):
    cam = Camera(estate_id=estate.id, name="Busy", lat=39.0, lon=-1.3, active=True)
    db_session.add(cam)
    db_session.flush()
    stand = Stand(estate_id=estate.id, name="Busy stand", camera_id=cam.id)
    db_session.add(stand)
    db_session.flush()

    # A visit every 40 minutes, day and night, over four recent nights: no hour is
    # quiet. Each is its own visit (VISIT_GAP is 30 minutes), every hour of every night
    # holds one, and nights this close to tonight end as late after their sunset as
    # tonight does, so even the last hour before 06:00 is covered whatever the date.
    at, end = _days_ago(6, 0), _days_ago(2, 0)
    while at < end:
        img = Image(camera_id=cam.id, captured_at=at,
                    is_empty_frame=False, processed_at=datetime.now(timezone.utc), reviewed=False)
        db_session.add(img)
        db_session.flush()
        db_session.add(Detection(image_id=img.id, species_id="wild_boar", sex="unknown",
                                 age_class="unknown", group_size=1))
        at += timedelta(minutes=40)
    db_session.commit()

    out = dark_exit(db_session, stand)
    assert out["hour"] is not None
    assert "busy all night" in out["text"]
