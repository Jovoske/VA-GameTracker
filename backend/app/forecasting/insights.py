"""Insights — multi-day outlook + plain-language correlations.

Correlations are stated as sentences with a sample size and honest hedging.
With ~1 season of data these are early signals, not laws.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, and_, cast, extract, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.enrichment.astro import moon_phase, solar
from app.forecasting.model import _best_window, _verdict, forecast_tonight
from app.models import Camera, Detection, EnvSnapshot, Image, Species

_TZ = settings.estate_timezone


def _local_hour():
    return cast(extract("hour", func.timezone(_TZ, Image.captured_at)), Integer).label("h")


def _det_env():
    """Base join: detections → their image → the env snapshot at capture time."""
    return (
        select(Detection)
        .join(Image, Image.id == Detection.image_id)
        .join(
            EnvSnapshot,
            and_(
                EnvSnapshot.camera_id == Image.camera_id,
                EnvSnapshot.observed_at == Image.captured_at,
            ),
        )
    )


def _outlook(db: Session, base: dict, days: int = 7) -> list[dict]:
    rec = base.get("recommended")
    now = datetime.now(timezone.utc)
    out = []
    for i in range(days):
        night = (now + timedelta(days=i)).replace(hour=23, minute=0, second=0, microsecond=0)
        phase, illum = moon_phase(night)
        s = solar(settings.estate_lat, settings.estate_lon, night.date())
        prob = None
        verdict = "SKIP"
        if rec:
            prob = rec["probability"]
            # nocturnal species do a touch better on dark nights
            if illum < 25:
                prob = min(0.97, prob + 0.05)
            elif illum > 70:
                prob = max(0.05, prob - 0.05)
            verdict = _verdict(prob)
        out.append({
            "date": night.date().isoformat(),
            "moon_phase": phase, "moon_illum": illum,
            "darkness_minutes": s.get("darkness_minutes"),
            "camera": rec["camera"] if rec else None,
            "species": rec["species"] if rec else None,
            "probability": round(prob, 2) if prob is not None else None,
            "verdict": verdict,
        })
    return out


def _correlations(db: Session) -> list[dict]:
    out: list[dict] = []
    total = db.scalar(select(func.count(Detection.id))) or 0
    if total < 20:
        return out

    # 1. Overall peak window
    h = _local_hour()
    hour_rows = db.execute(
        select(h, func.count()).select_from(Detection).join(Image, Image.id == Detection.image_id).group_by(h)
    ).all()
    by_hour = {int(x): int(c) for x, c in hour_rows}
    w = _best_window(by_hour)
    out.append({
        "statement": f"Activity peaks {w['start_hour']:02d}:00–{w['end_hour']:02d}:00 — "
                     f"{w['share_pct']}% of all sightings.",
        "strength": w["share_pct"] / 100, "sample": total,
    })

    # 2. Top-2 species, their own peak windows
    sp_rows = db.execute(
        select(Detection.species_id, Species.common_name, func.count(Detection.id))
        .join(Species, Species.id == Detection.species_id)
        .group_by(Detection.species_id, Species.common_name)
        .order_by(func.count(Detection.id).desc()).limit(2)
    ).all()
    for sid, name, cnt in sp_rows:
        rows = db.execute(
            select(h, func.count()).select_from(Detection).join(Image, Image.id == Detection.image_id)
            .where(Detection.species_id == sid).group_by(h)
        ).all()
        sw = _best_window({int(x): int(c) for x, c in rows})
        out.append({
            "statement": f"{name} are most active {sw['start_hour']:02d}:00–{sw['end_hour']:02d}:00.",
            "strength": sw["share_pct"] / 100, "sample": int(cnt),
        })

    # 3. Moon: dark vs bright nights (per-night rate)
    def _moon(lo, hi):
        det = db.scalar(
            _det_env().with_only_columns(func.count(Detection.id))
            .where(EnvSnapshot.moon_illum_pct >= lo, EnvSnapshot.moon_illum_pct < hi)
        ) or 0
        nights = db.scalar(
            _det_env().with_only_columns(
                func.count(func.distinct(func.date(func.timezone(_TZ, Image.captured_at))))
            ).where(EnvSnapshot.moon_illum_pct >= lo, EnvSnapshot.moon_illum_pct < hi)
        ) or 0
        return det, nights

    dark_d, dark_n = _moon(0, 25)
    bright_d, bright_n = _moon(50, 101)
    if dark_n >= 3 and bright_n >= 3:
        dr, br = dark_d / dark_n, bright_d / bright_n
        if dr >= br * 1.25:
            out.append({
                "statement": f"~{round((dr / br - 1) * 100)}% more activity on dark nights "
                             f"(<25% moon) than bright ones.",
                "strength": min(1.0, dr / br - 1), "sample": dark_d + bright_d,
            })
        elif br >= dr * 1.25:
            out.append({
                "statement": f"~{round((br / dr - 1) * 100)}% more activity on bright nights "
                             f"(>50% moon) than dark ones.",
                "strength": min(1.0, br / dr - 1), "sample": dark_d + bright_d,
            })

    # 4. Camera concentration
    cam_rows = db.execute(
        select(Camera.name, func.count(Detection.id))
        .select_from(Detection).join(Image, Image.id == Detection.image_id)
        .join(Camera, Camera.id == Image.camera_id)
        .group_by(Camera.name).order_by(func.count(Detection.id).desc())
    ).all()
    if len(cam_rows) >= 2:
        top2 = sum(int(c) for _, c in cam_rows[:2])
        share = round(top2 / total * 100)
        names = " and ".join(n for n, _ in cam_rows[:2])
        out.append({
            "statement": f"{names} account for {share}% of all activity.",
            "strength": share / 100, "sample": total,
        })
    return out


def compute_insights(db: Session) -> dict:
    base = forecast_tonight(db)
    return {"outlook": _outlook(db, base), "correlations": _correlations(db)}
