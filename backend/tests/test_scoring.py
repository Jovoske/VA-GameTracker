"""Forecast persistence and verification tests.

The point of this loop is that the app can be shown wrong. So the tests care most
about the ways it could dodge that: silently rewriting an old claim, scoring itself
on nights the camera wasn't watching, or printing a hit rate off a handful of
nights.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.forecasting.exposure import recompute_camera_nights
from app.forecasting.model import SITTABLE_HOURS, _best_window
from app.forecasting.scoring import (
    MIN_SCORED_NIGHTS,
    MIN_SKILL_NIGHTS,
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
    db_session.add(Species(id="wild_boar", common_name="Wild boar", is_priority=True, huntable=True))
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
                "active_nights": 30,
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
    """A track record on a handful of nights is theatre, so it is withheld."""
    persist_tonight(db_session, _forecast_payload(cam), target=NIGHT)
    _frame(db_session, cam, datetime(2025, 11, 1, 21, 0, tzinfo=timezone.utc), animal=True)
    db_session.commit()
    recompute_camera_nights(db_session)
    evaluate_night(db_session, night=NIGHT)

    cal = calibration(db_session, days=3650)
    assert cal["available"] is False
    assert cal["nights"] < MIN_SCORED_NIGHTS
    assert cal["statement"] == (
        f"1 night checked so far. How often it was right shows after {MIN_SCORED_NIGHTS}.")


def _graded(db, cam, night, probability, occurred, verdict=None):
    fc = Forecast(camera_id=cam.id, target_date=night, species_id="wild_boar",
                  probability=probability,
                  factors={"verdict": verdict} if verdict else None)
    db.add(fc)
    db.flush()
    db.add(ForecastOutcome(forecast_id=fc.id, occurred=occurred,
                           evaluated_at=datetime.now(UTC)))


@requires_db
def test_the_track_record_is_graded_per_verdict_and_against_each_cameras_rate(db_session, cam):
    """What the hunter read is what is graded: "When it called a camera Best odds,
    animals came there X of N times", and behind that whether the odds beat each
    camera's usual rate."""
    base = date.today() - timedelta(days=MIN_SKILL_NIGHTS + 5)
    for i in range(MIN_SKILL_NIGHTS + 5):
        animal = i % 2 == 0
        _graded(db_session, cam, base + timedelta(days=i), 0.8 if animal else 0.2, animal)
    db_session.commit()

    cal = calibration(db_session, days=365)
    assert cal["available"] is True
    assert cal["n_evaluated"] == MIN_SKILL_NIGHTS + 5
    assert {v["verdict"]: (v["came"], v["times"]) for v in cal["by_verdict"]} == {
        "BEST_ODDS": (18, 18), "WORTH_A_LOOK": (0, 17), "QUIET": (0, 0)}
    assert cal["lines"] == [
        "When it called a camera Best odds, animals came there 18 of 18 times.",
        "When it called a camera Worth a look, animals came there 0 of 17 times.",
        "Its odds were closer to what happened than each camera's usual rate.",
    ]
    assert cal["skill_vs_climatology"] > 0
    assert cal["beats_baseline"] is True
    assert "%" not in cal["statement"]


@requires_db
def test_a_useless_model_does_not_claim_skill(db_session, cam):
    """A constant forecast must not report itself as beating the baseline."""
    base = date.today() - timedelta(days=MIN_SKILL_NIGHTS + 5)
    for i in range(MIN_SKILL_NIGHTS + 5):
        _graded(db_session, cam, base + timedelta(days=i), 0.5, i % 2 == 0)
    db_session.commit()

    cal = calibration(db_session, days=365)
    assert cal["available"] is True
    assert cal["skill_vs_climatology"] <= 0
    assert cal["beats_baseline"] is False
    assert "no closer to what happened" in cal["statement"]


@requires_db
def test_knowing_each_cameras_usual_rate_is_not_skill(db_session, cam):
    """G-14: a model that says 0.8 at a camera busy 80% of nights and 0.1 at one busy
    10% of nights has learnt nothing a hunter doesn't know. Against one pooled
    estate rate it looked skilful; against each camera's own rate it is not."""
    other = Camera(estate_id=cam.estate_id, name="Loma", active=True)
    db_session.add(other)
    db_session.flush()
    base = date.today() - timedelta(days=45)
    for i in range(40):
        night = base + timedelta(days=i)
        _graded(db_session, cam, night, 0.8, i % 5 != 0)      # came 32 of 40
        _graded(db_session, other, night, 0.1, i % 10 == 0)   # came 4 of 40
    db_session.commit()

    cal = calibration(db_session, days=365)
    assert cal["available"] is True
    assert cal["beats_baseline"] is False
    assert "no closer" in cal["statement"]


@requires_db
def test_worth_a_look_is_not_graded_as_a_prediction_of_no_animals(db_session, cam):
    """K-10: 30 "Worth a look" nights on which boar came every time used to read
    "Right on 0%". It said worth a look, and they came: that is the record."""
    base = date.today() - timedelta(days=35)
    for i in range(30):
        _graded(db_session, cam, base + timedelta(days=i), 0.35, True, "WORTH_A_LOOK")
    db_session.commit()

    cal = calibration(db_session, days=365)
    assert cal["lines"][0] == (
        "When it called a camera Worth a look, animals came there 30 of 30 times.")
    assert "Right on" not in cal["statement"] and "0%" not in cal["statement"]


@requires_db
def test_several_cameras_a_night_are_times_not_nights(db_session, cam):
    """Four cameras over 14 checked nights are 56 claims. The fold said "animals came
    56 of 56 nights" to a hunter who knew only 14 nights had been checked."""
    cams = [cam]
    for name in ("Loma", "Pinar", "Charca"):
        other = Camera(estate_id=cam.estate_id, name=name, active=True)
        db_session.add(other)
        db_session.flush()
        cams.append(other)
    base = date.today() - timedelta(days=MIN_SCORED_NIGHTS + 1)
    for i in range(MIN_SCORED_NIGHTS):
        for c in cams:
            _graded(db_session, c, base + timedelta(days=i), 0.8, True)
    db_session.commit()

    cal = calibration(db_session, days=365)
    assert cal["available"] is True and cal["nights"] == MIN_SCORED_NIGHTS
    best = next(v for v in cal["by_verdict"] if v["verdict"] == "BEST_ODDS")
    assert (best["came"], best["times"], best["nights"]) == (
        4 * MIN_SCORED_NIGHTS, 4 * MIN_SCORED_NIGHTS, MIN_SCORED_NIGHTS)
    n = 4 * MIN_SCORED_NIGHTS
    assert cal["lines"][0] == (
        f"When it called a camera Best odds, animals came there {n} of {n} times.")
    assert "nights." not in cal["lines"][0]


@requires_db
def test_not_enough_to_say_is_not_graded(db_session, cam):
    """A camera too new to judge made no claim about the ground: grading it would pad
    the record with nights the app said nothing about."""
    base = date.today() - timedelta(days=25)
    for i in range(20):
        _graded(db_session, cam, base + timedelta(days=i), 0.9, False, "NO_DATA")
    db_session.commit()

    cal = calibration(db_session, days=365)
    assert cal["available"] is False
    assert cal["n_evaluated"] == 0


# ── the claim is about one camera and the night itself ─────────────────────


@requires_db
def test_claims_are_matched_to_cameras_by_id_not_name(db_session, cam):
    """H-12: two cameras called Feeder each keep their own claim."""
    twin = Camera(estate_id=cam.estate_id, name=cam.name, active=True)
    db_session.add(twin)
    db_session.flush()
    payload = _forecast_payload(cam, prob=0.9)
    payload["where"].append({**_forecast_payload(twin, prob=0.1)["where"][0]})
    persist_tonight(db_session, payload, target=NIGHT)

    claims = {fc.camera_id: fc.probability for fc in db_session.scalars(select(Forecast))}
    assert claims == {cam.id: pytest.approx(0.9), twin.id: pytest.approx(0.1)}

    # A retired camera makes no claims, whatever a stale plan still lists.
    twin.retired_at = datetime.now(UTC)
    db_session.commit()
    run = persist_tonight(db_session, payload, target=NIGHT + timedelta(days=1))
    assert run.metrics["forecasts_written"] == 1


@requires_db
def test_a_claim_is_graded_on_its_evening_not_on_the_morning_before_it(db_session, cam):
    """G-13: a boar at 09:00 was already known to the plan written at 17:00. Only
    18:00 to 06:00 counts, and a photo marked "nothing in it" never does."""
    persist_tonight(db_session, _forecast_payload(cam), target=NIGHT)
    _frame(db_session, cam, datetime(2025, 11, 1, 8, 0, tzinfo=UTC), animal=True)
    _frame(db_session, cam, datetime(2025, 11, 1, 21, 0, tzinfo=UTC))
    db_session.commit()
    recompute_camera_nights(db_session)
    evaluate_night(db_session, night=NIGHT)
    assert db_session.scalar(select(ForecastOutcome)).occurred is False

    bush = _frame(db_session, cam, datetime(2025, 11, 1, 22, 0, tzinfo=UTC), animal=True)
    db_session.commit()
    evaluate_night(db_session, night=NIGHT)
    assert db_session.scalar(select(ForecastOutcome)).occurred is True
    bush.is_empty_frame = True  # a hunter: "nothing in it"
    db_session.commit()
    evaluate_night(db_session, night=NIGHT)
    assert db_session.scalar(select(ForecastOutcome)).occurred is False


@requires_db
def test_the_night_the_clocks_go_back_is_thirteen_hours(db_session):
    from app.forecasting.scoring import night_window

    def hours(night):
        start, end = night_window(night)
        return end.astimezone(UTC) - start.astimezone(UTC)

    assert hours(date(2026, 10, 24)) == timedelta(hours=13)
    assert hours(date(2026, 10, 20)) == timedelta(hours=12)
    # A plan written after dusk takes no credit for the hour before it.
    late = datetime(2026, 10, 20, 19, 30, tzinfo=UTC)
    assert night_window(date(2026, 10, 20), late)[0] == late


@requires_db
def test_a_double_run_is_recorded_twice_but_scored_once(db_session, cam):
    """The scheduler can fire twice. History stays append-only; the sample does not.

    Scoring every row would count one camera-night as several independent
    observations — inflating n_evaluated past the threshold that gates the hit
    rate, and weighting whichever night the job happened to double-run.
    """
    persist_tonight(db_session, _forecast_payload(cam, prob=0.7), target=NIGHT)
    persist_tonight(db_session, _forecast_payload(cam, prob=0.2), target=NIGHT)
    assert db_session.query(Forecast).count() == 2, "history must stay append-only"

    _frame(db_session, cam, datetime(2025, 11, 1, 21, 0, tzinfo=UTC), animal=True)
    db_session.commit()
    recompute_camera_nights(db_session)

    res = evaluate_night(db_session, night=NIGHT)
    assert res["evaluated"] == 1, "one camera-night is one observation"
    assert db_session.query(ForecastOutcome).count() == 1

    # The claim that was scored is the one made first — the one on the screen
    # before the night, not a revision written after dark.
    scored = db_session.scalar(select(ForecastOutcome))
    assert db_session.get(Forecast, scored.forecast_id).probability == pytest.approx(0.7)
