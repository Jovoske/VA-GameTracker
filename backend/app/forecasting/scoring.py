"""Forecast persistence and verification — the loop that makes the app falsifiable.

Until now `Forecast`, `ForecastOutcome` and `ModelRun` existed in the schema and
were written by nothing. An advisor that never records what it said and never
learns what happened is not an uncertain advisor, it is an *unfalsifiable* one, and
that is why the product could never improve past day one.

Two jobs:

* ``persist_tonight`` writes what the app is claiming, at the moment it claims it,
  stamped with the code version that produced it. The app can then no longer
  silently rewrite its own history.
* ``evaluate_night`` scores yesterday's claims the next morning, and
  ``evaluate_pending`` catches up any night of the last two weeks that was never
  scored (a skipped run, or a night whose photos were still being checked).

**What is scored, and why it is not sits.** The outcome is "was this species
detected at this camera during the forecast window", checked against the exposure
table. That arrives automatically, roughly 750 camera-nights a season across five
cameras, and is distinguishable from useless within a single season. Scoring
against *sit outcomes* would need 150-310 logged sits — four to eight seasons — so
a hit rate built on those would be a coin flip presented as a verdict on the
model's competence. Nights the camera was not demonstrably watching are excluded,
never counted as a miss.

**What the hunter reads is graded, per verdict.** The screen says Best odds, Worth a
look or Quiet, so the track record says how each of those turned out: "When it
said Best odds, animals came 7 of 9 nights." Grading every claim as a yes/no at 50%
punished a correct "Worth a look" as a failed prediction of no animals. "Not enough
to say" is not a prediction, and is not graded.

Skill is reported against two baselines, because a Brier score alone means nothing:
per-camera climatology (each camera's own base rate) and persistence (seen here last
night). A model that cannot beat both is not earning its place on the screen.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.visibility import VISIBLE_SIGHTING
from app.core.config import settings
from app.core.logging import get_logger
from app.forecasting.exposure import current_night
from app.models import (
    Camera,
    CameraNight,
    Detection,
    Forecast,
    ForecastOutcome,
    Image,
    ModelRun,
    Species,
)
from app.version import __version__

log = get_logger(__name__)

# Nights scored before any track record shows: a tally of a handful is theatre, and
# with several cameras a night the row count alone would pass that in days.
MIN_SCORED_NIGHTS = 14
# Claims of one verdict graded before "When it said X" is said.
MIN_PER_VERDICT = 5
# Nights scored before it says whether its odds beat each camera's usual rate.
MIN_SKILL_NIGHTS = 30
# Below this many graded claims a camera's own base rate is noise: the estate's is used.
MIN_CAMERA_ROWS = 10
# Kept for callers that read it: the row count behind the old hit rate.
MIN_EVALUATED = 30
GRADED = ("BEST_ODDS", "WORTH_A_LOOK", "QUIET")
VERDICT_WORDS = {"BEST_ODDS": "Best odds", "WORTH_A_LOOK": "Worth a look", "QUIET": "Quiet"}
# The evening a claim is about starts here, local time: a boar photographed at 09:00
# was already known to the plan written at 17:00, and is not a hit.
NIGHT_STARTS = time(18)
NIGHT_ENDS = time(6)
# How far back the morning run looks for nights nobody scored. A night drops out of
# reach after this, so a gap of more than two weeks in scoring stays a gap.
CATCH_UP_DAYS = 14


def local_today() -> date:
    """The estate's date: the server's clock need not be on Madrid time."""
    return datetime.now(ZoneInfo(settings.estate_timezone)).date()


def persist_tonight(db: Session, forecast: dict, *, target: date | None = None) -> ModelRun:
    """Write tonight's claims so they can be scored tomorrow.

    Append-only: a re-run records a *new* claim rather than editing the old one, so
    the app can never quietly rewrite what it said. Scoring deduplicates — see
    `_claims_for`.
    """
    # Before 06:00 the night under way is still "tonight" (exposure.current_night).
    target = target or current_night()
    run = ModelRun(
        kind="forecast",
        name="presence_baseline",
        version=__version__,
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()

    # By id: two cameras can share a name (a vendor default, a rename), and a claim
    # matched by name was written against the wrong one. A retired camera makes no
    # claims: it is in a drawer.
    cameras = set(db.scalars(select(Camera.id).where(Camera.retired_at.is_(None))).all())
    written = 0

    # One row per camera we made a claim about, not just the headline. Scoring only
    # the recommended stand would grade the model exclusively on its best guess.
    for entry in forecast.get("where") or []:
        try:
            cam_id = uuid.UUID(str(entry.get("camera_id")))
        except ValueError:
            continue
        if cam_id not in cameras:
            continue
        w = entry.get("best_window") or {}
        db.add(
            Forecast(
                camera_id=cam_id,
                target_date=target,
                species_id=entry.get("species_id"),
                probability=float(entry.get("probability") or 0.0),
                best_window_start=time(hour=int(w.get("start_hour", 0))),
                best_window_end=time(hour=int(w.get("end_hour", 0))),
                factors={
                    "verdict": entry.get("verdict"),
                    "nights_present": entry.get("nights_present"),
                    "active_nights": entry.get("active_nights"),
                },
                model_run_id=run.id,
            )
        )
        written += 1

    run.finished_at = datetime.now(timezone.utc)
    run.metrics = {"forecasts_written": written, "target_date": target.isoformat()}
    db.commit()
    log.info("forecast.persisted", written=written, target=str(target))
    return run


def night_window(night: date, claimed_at: datetime | None = None) -> tuple[datetime, datetime]:
    """The stretch a claim for `night` is graded on: 18:00 that evening to 06:00 the
    next morning, local time (13 hours on the night the clocks go back), or from when
    the claim was made if that was later, so it takes no credit for what it saw
    first. A claim written after the night was over (by hand) is graded on the night."""
    tz = ZoneInfo(settings.estate_timezone)
    start = datetime.combine(night, NIGHT_STARTS, tzinfo=tz)
    end = datetime.combine(night + timedelta(days=1), NIGHT_ENDS, tzinfo=tz)
    if claimed_at is not None and start < claimed_at < end:
        start = claimed_at
    return start, end


def _detected(db: Session, camera_id, species_id, night: date,
              claimed_at: datetime | None = None) -> bool:
    start, end = night_window(night, claimed_at)
    q = (
        select(Detection.id)
        .join(Image, Image.id == Detection.image_id)
        .join(Species, Species.id == Detection.species_id)
        .where(
            Image.camera_id == camera_id,
            Image.captured_at >= start, Image.captured_at < end,
            # A hidden species, or a photo a hunter marked "nothing in it", is not
            # an animal that came.
            VISIBLE_SIGHTING,
        )
        .limit(1)
    )
    if species_id:
        q = q.where(Detection.species_id == species_id)
    return db.scalar(q) is not None


def _claims_for(rows: list[Forecast]) -> list[Forecast]:
    """One claim per camera-night: the earliest, which is the one made before the night.

    Persistence is append-only, and the scheduler can fire twice. Scoring every row
    would count one camera-night as several independent observations — inflating
    `n_evaluated` past the threshold that gates the hit rate, and weighting whichever
    night the job happened to double-run. The first claim is the one that was on the
    screen when the hunter decided; a claim written after dark is not a forecast.
    """
    first: dict[tuple, Forecast] = {}
    for fc in sorted(rows, key=lambda f: (f.generated_at is None, f.generated_at)):
        first.setdefault((fc.camera_id, fc.target_date, fc.species_id), fc)
    return list(first.values())


def evaluate_night(db: Session, *, night: date | None = None) -> dict:
    """Score the forecasts made for `night` against what the cameras recorded.

    Idempotent, so a night can be graded again when a hunter corrects a photo."""
    night = night or (current_night() - timedelta(days=1))

    rows = _claims_for(
        list(db.scalars(select(Forecast).where(Forecast.target_date == night)).all())
    )
    if not rows:
        return {"night": night.isoformat(), "evaluated": 0, "reason": "no forecasts for that night"}

    exposure = {
        cn.camera_id: cn.exposure_state
        for cn in db.scalars(select(CameraNight).where(CameraNight.night == night)).all()
    }

    evaluated = skipped = 0
    for fc in rows:
        state = exposure.get(fc.camera_id)
        if state not in ("CONFIRMED", "PRESUMED_UP"):
            # The camera cannot vouch for that night. Counting it as a miss would
            # score the model on the hardware, which is the original sin here.
            skipped += 1
            continue

        occurred = _detected(db, fc.camera_id, fc.species_id, night, fc.generated_at)
        existing = db.get(ForecastOutcome, fc.id)
        if existing is None:
            db.add(
                ForecastOutcome(
                    forecast_id=fc.id,
                    occurred=occurred,
                    evaluated_at=datetime.now(timezone.utc),
                )
            )
        else:
            existing.occurred = occurred
            existing.evaluated_at = datetime.now(timezone.utc)
        evaluated += 1

    db.commit()
    log.info("forecast.evaluated", night=str(night), evaluated=evaluated, skipped=skipped)
    return {
        "night": night.isoformat(),
        "evaluated": evaluated,
        "skipped_unverifiable": skipped,
    }


def evaluate_pending(db: Session, *, days: int = CATCH_UP_DAYS, today: date | None = None) -> dict:
    """Score every finished night of the last `days` that has a claim with no outcome.

    The morning run used to score only yesterday, so a run that did not happen (the
    server was busy or down at 11:00), or a night whose photos were still being
    checked, was never graded and the track record quietly stalled. A night the
    cameras cannot vouch for yet stays unscored and is tried again the next morning,
    until it falls out of the window.
    """
    # Nights before the one under way are over; before 06:00 that is last evening's.
    today = today or current_night()
    since = today - timedelta(days=days)
    nights = db.scalars(
        select(Forecast.target_date)
        .outerjoin(ForecastOutcome, ForecastOutcome.forecast_id == Forecast.id)
        .where(
            Forecast.target_date >= since, Forecast.target_date < today,
            ForecastOutcome.forecast_id.is_(None),
        )
        .distinct()
        .order_by(Forecast.target_date)
    ).all()
    results = [evaluate_night(db, night=n) for n in nights]
    return {
        "nights": [r["night"] for r in results],
        "evaluated": sum(r.get("evaluated", 0) for r in results),
        "skipped_unverifiable": sum(r.get("skipped_unverifiable", 0) for r in results),
    }


def _verdict_of(fc: Forecast) -> str:
    """The verdict the hunter read for this claim, as stored when it was made."""
    from app.forecasting.model import _verdict

    verdict = (fc.factors or {}).get("verdict")
    if verdict:
        return verdict
    return _verdict(fc.probability, (fc.factors or {}).get("active_nights"))


def calibration(db: Session, *, days: int = 90, today: date | None = None) -> dict:
    """How each verdict turned out, and the Brier score and skill behind the fold.

    Returns ``available: False`` rather than numbers until there is enough to say
    anything: a track record on a handful of nights is theatre. A retired camera's
    claims stay graded (they were on the screen), and "Not enough to say" is not a
    claim about the ground, so it is not graded.
    """
    today = today or current_night()
    since = today - timedelta(days=days)
    rows = [
        (fc, occurred)
        for fc, occurred in db.execute(
            select(Forecast, ForecastOutcome.occurred)
            .join(ForecastOutcome, ForecastOutcome.forecast_id == Forecast.id)
            .where(Forecast.target_date >= since, ForecastOutcome.occurred.isnot(None))
        ).all()
        if _verdict_of(fc) in GRADED
    ]

    n = len(rows)
    nights = len({fc.target_date for fc, _ in rows})
    if nights < MIN_SCORED_NIGHTS:
        return {
            "available": False,
            "n_evaluated": n,
            "nights": nights,
            "needed": MIN_SCORED_NIGHTS,
            "statement": (
                f"{nights} night{'s' if nights != 1 else ''} checked so far. How often it "
                f"was right shows after {MIN_SCORED_NIGHTS}."
            ),
        }

    by_verdict = []
    lines = []
    for verdict in GRADED:
        graded = [occurred for fc, occurred in rows if _verdict_of(fc) == verdict]
        came = sum(1 for occurred in graded if occurred)
        by_verdict.append({"verdict": verdict, "nights": len(graded), "came": came})
        if len(graded) >= MIN_PER_VERDICT:
            lines.append(
                f"When it said {VERDICT_WORDS[verdict]}, animals came {came} of "
                f"{len(graded)} nights."
            )

    ys = [1.0 if occurred else 0.0 for _, occurred in rows]
    ps = [min(1.0, max(0.0, fc.probability)) for fc, _ in rows]
    brier = sum((p - y) ** 2 for p, y in zip(ps, ys, strict=True)) / n

    # Climatology: each camera's own base rate over these nights, so a model that only
    # knows "this camera is usually busy" gains nothing. A camera with few graded
    # claims uses the estate's rate: its own would be noise.
    pooled = sum(ys) / n
    per_camera: dict = {}
    for fc, occurred in rows:
        per_camera.setdefault(fc.camera_id, []).append(1.0 if occurred else 0.0)
    base = {
        cam: (sum(v) / len(v) if len(v) >= MIN_CAMERA_ROWS else pooled)
        for cam, v in per_camera.items()
    }
    clim = sum((base[fc.camera_id] - y) ** 2 for (fc, _), y in zip(rows, ys, strict=True)) / n

    # Persistence: per camera, did the previous forecast's outcome recur?
    series_by_camera: dict = {}
    for fc, occurred in rows:
        series_by_camera.setdefault(fc.camera_id, []).append(
            (fc.target_date, 1.0 if occurred else 0.0))
    pers_terms = []
    for series in series_by_camera.values():
        series.sort()
        for i in range(1, len(series)):
            pers_terms.append((series[i - 1][1] - series[i][1]) ** 2)
    persistence = sum(pers_terms) / len(pers_terms) if pers_terms else None

    def skill(reference: float | None) -> float | None:
        if not reference:
            return None
        return round(1.0 - brier / reference, 3)

    bss_clim = skill(clim)
    # Beating the camera's own rate by a hair is not beating it.
    beats = bool(bss_clim is not None and bss_clim > 0.02)
    if nights >= MIN_SKILL_NIGHTS and bss_clim is not None:
        lines.append(
            "Its odds were closer to what happened than each camera's usual rate."
            if beats else
            "Its odds were no closer to what happened than each camera's usual rate."
        )
    if not lines:
        lines.append(f"{nights} nights checked, too few of any one verdict to say yet.")

    return {
        "available": True,
        "n_evaluated": n,
        "nights": nights,
        "by_verdict": by_verdict,
        "lines": lines,
        "brier": round(brier, 4),
        "climatology_brier": round(clim, 4),
        "persistence_brier": round(persistence, 4) if persistence else None,
        "skill_vs_climatology": bss_clim,
        "skill_vs_persistence": skill(persistence),
        "beats_baseline": beats if nights >= MIN_SKILL_NIGHTS else None,
        "statement": " ".join(lines),
    }
