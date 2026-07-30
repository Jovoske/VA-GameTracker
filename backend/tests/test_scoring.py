"""Forecast persistence and verification tests.

The point of this loop is that the app can be shown wrong. So the tests care most
about the ways it could dodge that: silently rewriting an old claim, scoring itself
on nights the camera wasn't watching, or printing a hit rate off a handful of
nights.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.forecasting.exposure import recompute_camera_nights
from app.forecasting.model import SITTABLE_HOURS, _best_window
from app.forecasting.scoring import (
    MIN_EVALUATED,
    calibration,
    evaluate_night,
    persist_tonight,
)
from app.models import (
    Camera,
    Detection,
    Estate,
    Forecast,
    ForecastOutcome,
    Image,
    ModelRun,
    Species,
)

from .conftest import requires_db

NIGHT = date(2025, 11, 1)


@pytest.fixture
def cam(db_session):
    estate = Estate(name="E", timezone="Europe/Madrid", lat=39.0, lon=-1.3)
    db_session.add(estate)
    db_session.flush()
    c = Camera(estate_id=estate.id, name="Puente", active=True)
    db_session.add(c)
    db_session.add(Species(id="wild_boar", common_name="Wild boar", is_priority=True))
    db_session.flush()
    return c


def _forecast_payload(cam, prob=0.7):
    return {
        "where": [
            {
                "camera": cam.name,
                "camera_id": str(cam.id),
                "species_id": "wild_boar",
                "verdict": "BEST_ODDS",
                "probability": prob,
                "nights_present": 11,
                "camera_nights": 30,
                "best_window": {"start_hour": 20, "end_hour": 23},
            }
        ]
    }


def _frame(db, cam, when, *, animal=False):
    img = Image(camera_id=cam.id, captured_at=when, is_empty_frame=not animal,
                processed_at=when, reviewed=False)
    db.add(img)
    db.flush()
    if animal:
        db.add(Detection(image_id=img.id, species_id="wild_boar", sex="unknown",
                         age_class="unknown", group_size=1))
    return img


# ── the window must be sittable ─────────────────────────────────────────────


def test_best_window_is_restricted_to_hours_somebody_could_sit():
    """Peak camera activity at 03:00 is a true fact and a useless recommendation."""
    by_hour = {3: 100, 4: 100, 5: 100, 21: 10, 22: 10, 23: 10}
    w = _best_window(by_hour)
    assert w["start_hour"] in SITTABLE_HOURS
    assert w["start_hour"] != 3

    # The unrestricted search still finds the true peak, for analysis rather than advice.
    raw = _best_window(by_hour, sittable_only=False)
    assert raw["start_hour"] == 3


# ── persistence ─────────────────────────────────────────────────────────────


@requires_db
def test_persisting_writes_the_claim_and_a_model_run(db_session, cam):
    run = persist_tonight(db_session, _forecast_payload(cam), target=NIGHT)

    assert isinstance(run, ModelRun)
    assert run.metrics["forecasts_written"] == 1
    fc = db_session.scalar(select(Forecast))
    assert fc.target_date == NIGHT
    assert fc.probability == pytest.approx(0.7)
    assert fc.model_run_id == run.id
    # Version stamped, so a number can always be traced to the code that made it.
    assert run.version


@requires_db
def test_a_past_claim_is_never_rewritten(db_session, cam):
    """Re-running must add a new run, not silently edit yesterday's prediction."""
    persist_tonight(db_session, _forecast_payload(cam, prob=0.7), target=NIGHT)
    persist_tonight(db_session, _forecast_payload(cam, prob=0.2), target=NIGHT)

    probs = sorted(f.probability for f in db_session.scalars(select(Forecast)).all())
    assert probs == pytest.approx([0.2, 0.7])
    assert db_session.query(ModelRun).count() == 2


# ── verification ────────────────────────────────────────────────────────────


@requires_db
def test_a_hit_and_a_miss_are_scored(db_session, cam):
    persist_tonight(db_session, _forecast_payload(cam), target=NIGHT)
    # Animal present on the forecast night.
    _frame(db_session, cam, datetime(2025, 11, 1, 21, 0, tzinfo=timezone.utc), animal=True)
    db_session.commit()
    recompute_camera_nights(db_session)

    res = evaluate_night(db_session, night=NIGHT)
    assert res["evaluated"] == 1
    assert db_session.scalar(select(ForecastOutcome)).occurred is True


@requires_db
def test_nights_the_camera_could_not_vouch_for_are_not_scored(db_session, cam):
    """Scoring a blind night as a miss would grade the model on the hardware."""
    persist_tonight(db_session, _forecast_payload(cam), target=NIGHT)
    # No frames at all for that night, and none either side, so exposure is UNKNOWN.
    db_session.commit()
    recompute_camera_nights(db_session)

    res = evaluate_night(db_session, night=NIGHT)
    assert res["evaluated"] == 0
    assert res["skipped_unverifiable"] == 1
    assert db_session.query(ForecastOutcome).count() == 0


@requires_db
def test_evaluation_is_idempotent(db_session, cam):
    persist_tonight(db_session, _forecast_payload(cam), target=NIGHT)
    _frame(db_session, cam, datetime(2025, 11, 1, 21, 0, tzinfo=timezone.utc), animal=True)
    db_session.commit()
    recompute_camera_nights(db_session)

    evaluate_night(db_session, night=NIGHT)
    evaluate_night(db_session, night=NIGHT)
    assert db_session.query(ForecastOutcome).count() == 1


# ── calibration ─────────────────────────────────────────────────────────────


@requires_db
def test_no_hit_rate_is_shown_on_thin_evidence(db_session, cam):
    """A hit rate on a handful of nights is theatre, so it is withheld."""
    persist_tonight(db_session, _forecast_payload(cam), target=NIGHT)
    _frame(db_session, cam, datetime(2025, 11, 1, 21, 0, tzinfo=timezone.utc), animal=True)
    db_session.commit()
    recompute_camera_nights(db_session)
    evaluate_night(db_session, night=NIGHT)

    cal = calibration(db_session)
    assert cal["available"] is False
    assert cal["n_evaluated"] < MIN_EVALUATED
    assert "at least" in cal["statement"]


@requires_db
def test_calibration_reports_skill_against_climatology(db_session, cam):
    """With enough scored nights, the number that appears is a measured hit rate."""
    base = date(2025, 9, 1)
    for i in range(MIN_EVALUATED + 5):
        night = base + timedelta(days=i)
        # A well-calibrated-ish model: high probability on nights animals appear.
        animal = i % 2 == 0
        fc = Forecast(
            camera_id=cam.id,
            target_date=night,
            species_id="wild_boar",
            probability=0.8 if animal else 0.2,
        )
        db_session.add(fc)
        db_session.flush()
        db_session.add(
            ForecastOutcome(
                forecast_id=fc.id, occurred=animal, evaluated_at=datetime.now(timezone.utc)
            )
        )
    db_session.commit()

    cal = calibration(db_session, days=365)
    assert cal["available"] is True
    assert cal["n_evaluated"] == MIN_EVALUATED + 5
    assert cal["hit_rate"] == pytest.approx(1.0)
    # It must beat "just assume this camera's usual rate".
    assert cal["skill_vs_climatology"] > 0
    assert cal["beats_baseline"] is True
    assert "scored camera-nights" in cal["statement"]


@requires_db
def test_a_useless_model_does_not_claim_skill(db_session, cam):
    """A constant forecast must not report itself as beating the baseline."""
    base = date(2025, 9, 1)
    for i in range(MIN_EVALUATED + 5):
        fc = Forecast(
            camera_id=cam.id,
            target_date=base + timedelta(days=i),
            species_id="wild_boar",
            probability=0.5,          # says the same thing every night
        )
        db_session.add(fc)
        db_session.flush()
        db_session.add(
            ForecastOutcome(
                forecast_id=fc.id, occurred=(i % 2 == 0), evaluated_at=datetime.now(timezone.utc)
            )
        )
    db_session.commit()

    cal = calibration(db_session, days=365)
    assert cal["available"] is True
    assert cal["skill_vs_climatology"] <= 0
    assert cal["beats_baseline"] is False
