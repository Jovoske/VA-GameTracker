"""Tests for the claims the forecast is now allowed — and no longer allowed — to make."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.forecasting.model import MIN_NIGHTS_TO_JUDGE, _verdict, forecast_tonight
from app.models import Camera, Detection, Estate, Image, Species

from .conftest import requires_db


def test_thin_data_is_no_data_not_quiet():
    """A camera with too few nights is a hardware report, not a statement about the wood."""
    assert _verdict(0.9, active_nights=3) == "NO_DATA"
    assert _verdict(0.01, active_nights=3) == "NO_DATA"
    assert _verdict(0.9, active_nights=MIN_NIGHTS_TO_JUDGE) == "BEST_ODDS"


def test_verdict_labels_describe_rather_than_instruct():
    n = MIN_NIGHTS_TO_JUDGE
    assert _verdict(0.60, n) == "BEST_ODDS"
    assert _verdict(0.30, n) == "WORTH_A_LOOK"
    assert _verdict(0.05, n) == "QUIET"
    # The old imperative labels must not come back.
    assert {_verdict(p, n) for p in (0.6, 0.3, 0.05)} & {"GO", "MARGINAL", "SKIP"} == set()


@requires_db
def test_late_deployed_camera_is_not_capped_by_estate_history(db_session):
    from sqlalchemy import func, select

    from app.core.config import settings

    """The denominator bug: a camera present for 10 of 200 estate-nights could not rank.

    Camera B is deployed late but fires on every night it exists. Under the old
    estate-wide denominator it was capped at 10/200 = 0.05 and could never be
    recommended. Judged on its own operating nights it is 10/10.
    """
    estate = Estate(name="E", timezone="Europe/Madrid", lat=39.0, lon=-1.3)
    db_session.add(estate)
    db_session.flush()
    db_session.add(Species(id="wild_boar", common_name="Wild boar", is_priority=True, huntable=True))

    old_cam = Camera(estate_id=estate.id, name="Old", active=True)
    new_cam = Camera(estate_id=estate.id, name="New", active=True)
    db_session.add_all([old_cam, new_cam])
    db_session.flush()

    base = datetime(2025, 6, 1, 21, 0, tzinfo=timezone.utc)

    # Old camera: present for 40 nights, animals on 8 of them.
    for i in range(40):
        img = Image(camera_id=old_cam.id, captured_at=base + timedelta(days=i), reviewed=False)
        db_session.add(img)
        db_session.flush()
        if i % 5 == 0:
            db_session.add(
                Detection(image_id=img.id, species_id="wild_boar", sex="unknown", age_class="unknown")
            )

    # New camera: only the last 10 nights, but an animal every night.
    for i in range(30, 40):
        img = Image(camera_id=new_cam.id, captured_at=base + timedelta(days=i), reviewed=False)
        db_session.add(img)
        db_session.flush()
        db_session.add(
            Detection(image_id=img.id, species_id="wild_boar", sex="unknown", age_class="unknown")
        )
    db_session.commit()

    def nights(cam_id):
        return db_session.scalar(
            select(func.count(func.distinct(
                func.date(func.timezone(settings.estate_timezone, Image.captured_at))
            ))).where(Image.camera_id == cam_id)
        )

    # Judged on its own watched nights: the late camera is 10/10, not 10/40.
    assert nights(old_cam.id) == 40
    assert nights(new_cam.id) == 10


@requires_db
def test_payload_no_longer_carries_a_fabricated_confidence(db_session, monkeypatch):
    """`confidence = 30 + nights_present*2` was a rescaled sample size in a % sign."""
    import app.forecasting.model as model

    # Keep the test offline: tonight's conditions hit a weather API otherwise.
    monkeypatch.setattr(model, "_tonight_conditions", lambda now: {"moon_phase": "New Moon"})

    estate = Estate(name="E", timezone="Europe/Madrid", lat=39.0, lon=-1.3)
    db_session.add(estate)
    db_session.flush()
    db_session.add(Species(id="wild_boar", common_name="Wild boar", is_priority=True, huntable=True))
    cam = Camera(estate_id=estate.id, name="Puente", active=True)
    db_session.add(cam)
    db_session.flush()

    base = datetime(2025, 9, 1, 21, 0, tzinfo=timezone.utc)
    for i in range(20):
        img = Image(camera_id=cam.id, captured_at=base + timedelta(days=i), reviewed=False)
        db_session.add(img)
        db_session.flush()
        if i % 2 == 0:
            db_session.add(
                Detection(image_id=img.id, species_id="wild_boar", sex="unknown", age_class="unknown")
            )
    db_session.commit()

    out = forecast_tonight(db_session)
    assert "confidence" not in out
    rec = out["recommended"]
    assert "confidence" not in rec

    # The replacement: a countable fraction with its reference class stated.
    assert rec["active_nights"] == 20
    assert rec["nights_present"] == 10
    assert "10 of 20 nights this camera was watching" in rec["reason"]
    assert "camera" in rec["caveat"].lower()


@requires_db
def test_outlook_makes_no_per_night_prediction(db_session, monkeypatch):
    """It used to repeat tonight's number seven times with a moon nudge."""
    import app.forecasting.model as model
    from app.forecasting.insights import _outlook

    monkeypatch.setattr(model, "_tonight_conditions", lambda now: {"moon_phase": "New Moon"})
    estate = Estate(name="E", timezone="Europe/Madrid", lat=39.0, lon=-1.3)
    db_session.add(estate)
    db_session.commit()

    rows = _outlook()
    assert len(rows) == 7
    for row in rows:
        assert "probability" not in row
        assert "verdict" not in row
        assert "moon_illum" in row and "civil_twilight_end" in row
