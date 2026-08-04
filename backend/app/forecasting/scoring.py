"""Forecast persistence and verification — the loop that makes the app falsifiable.

Until now `Forecast`, `ForecastOutcome` and `ModelRun` existed in the schema and
were written by nothing. An advisor that never records what it said and never
learns what happened is not an uncertain advisor, it is an *unfalsifiable* one, and
that is why the product could never improve past day one.

Two jobs:

* ``persist_tonight`` writes what the app is claiming, at the moment it claims it,
  stamped with the code version that produced it. The app can then no longer
  silently rewrite its own history.
* ``evaluate_night`` scores yesterday's claims the next morning.

**What is scored, and why it is not sits.** The outcome is "was this species
detected at this camera during the forecast window", checked against the exposure
table. That arrives automatically, roughly 750 camera-nights a season across five
cameras, and is distinguishable from useless within a single season. Scoring
against *sit outcomes* would need 150-310 logged sits — four to eight seasons — so
a hit rate built on those would be a coin flip presented as a verdict on the
model's competence. Nights the camera was not demonstrably watching are excluded,
never counted as a miss.

Skill is reported against two baselines, because a Brier score alone means nothing:
per-camera climatology (its own base rate) and persistence (seen here last night).
A model that cannot beat both is not earning its place on the screen.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.forecasting.exposure import night_expr
from app.models import (
    Camera,
    CameraNight,
    Detection,
    Forecast,
    ForecastOutcome,
    Image,
    ModelRun,
)
from app.version import __version__

log = get_logger(__name__)

MIN_EVALUATED = 30  # below this, a hit rate is noise and is not shown


def persist_tonight(db: Session, forecast: dict, *, target: date | None = None) -> ModelRun:
    """Write tonight's claims so they can be scored tomorrow.

    Append-only: a re-run records a *new* claim rather than editing the old one, so
    the app can never quietly rewrite what it said. Scoring deduplicates — see
    `_claims_for`.
    """
    target = target or date.today()
    run = ModelRun(
        kind="forecast",
        name="presence_baseline",
        version=__version__,
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()

    cameras = {c.name: c.id for c in db.scalars(select(Camera)).all()}
    written = 0

    # One row per camera we made a claim about, not just the headline. Scoring only
    # the recommended stand would grade the model exclusively on its best guess.
    for entry in forecast.get("where") or []:
        cam_id = cameras.get(entry["camera"])
        if cam_id is None:
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


def _detected(db: Session, camera_id, species_id, night: date) -> bool:
    q = (
        select(func.count(Detection.id))
        .join(Image, Image.id == Detection.image_id)
        .where(Image.camera_id == camera_id, night_expr() == night)
    )
    if species_id:
        q = q.where(Detection.species_id == species_id)
    return bool(db.scalar(q) or 0)


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
    """Score the forecasts made for `night` against what the cameras recorded."""
    night = night or (date.today() - timedelta(days=1))

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

        occurred = _detected(db, fc.camera_id, fc.species_id, night)
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


def calibration(db: Session, *, days: int = 90) -> dict:
    """Brier score and skill against climatology and persistence.

    Returns ``available: False`` rather than a number until there is enough to say
    anything — a hit rate on a handful of nights is theatre.
    """
    since = date.today() - timedelta(days=days)
    rows = db.execute(
        select(Forecast, ForecastOutcome.occurred)
        .join(ForecastOutcome, ForecastOutcome.forecast_id == Forecast.id)
        .where(Forecast.target_date >= since, ForecastOutcome.occurred.isnot(None))
    ).all()

    n = len(rows)
    if n < MIN_EVALUATED:
        return {
            "available": False,
            "n_evaluated": n,
            "needed": MIN_EVALUATED,
            "statement": (
                f"{n} scored night{'s' if n != 1 else ''} so far — a hit rate needs at least "
                f"{MIN_EVALUATED} before it means anything."
            ),
        }

    ys = [1.0 if occurred else 0.0 for _, occurred in rows]
    ps = [min(1.0, max(0.0, fc.probability)) for fc, _ in rows]
    base = sum(ys) / n

    brier = sum((p - y) ** 2 for p, y in zip(ps, ys)) / n
    clim = sum((base - y) ** 2 for y in ys) / n

    # Persistence: per camera, did the previous forecast's outcome recur?
    by_camera: dict = {}
    for fc, occurred in rows:
        by_camera.setdefault(fc.camera_id, []).append((fc.target_date, 1.0 if occurred else 0.0))
    pers_terms = []
    for series in by_camera.values():
        series.sort()
        for i in range(1, len(series)):
            pers_terms.append((series[i - 1][1] - series[i][1]) ** 2)
    persistence = sum(pers_terms) / len(pers_terms) if pers_terms else None

    def skill(reference: float | None) -> float | None:
        if not reference:
            return None
        return round(1.0 - brier / reference, 3)

    hit_rate = sum(1 for p, y in zip(ps, ys) if (p >= 0.5) == (y == 1.0)) / n
    bss_clim = skill(clim)

    return {
        "available": True,
        "n_evaluated": n,
        "brier": round(brier, 4),
        "climatology_brier": round(clim, 4),
        "persistence_brier": round(persistence, 4) if persistence else None,
        "skill_vs_climatology": bss_clim,
        "skill_vs_persistence": skill(persistence),
        "hit_rate": round(hit_rate, 3),
        "beats_baseline": bool(bss_clim and bss_clim > 0),
        "statement": (
            f"Right on {round(hit_rate * 100)}% of {n} scored camera-nights"
            + (
                f", {'better' if bss_clim and bss_clim > 0 else 'no better'} than simply "
                "assuming each camera's usual rate."
                if bss_clim is not None
                else "."
            )
        ),
    }
