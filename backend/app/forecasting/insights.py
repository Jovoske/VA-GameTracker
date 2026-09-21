"""Insights — sun/moon calendar and summaries of recorded sightings.

Weather and moon comparisons come from patterns.py so the page uses one
consistent comparison for each condition.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, cast, extract, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.enrichment.astro import moon_phase, solar
from app.forecasting.model import _best_window, class_label
from app.models import Camera, Detection, Image, Species

_TZ = settings.estate_timezone


def _local_hour():
    return cast(extract("hour", func.timezone(_TZ, Image.captured_at)), Integer).label("h")


def _outlook(days: int = 7) -> list[dict]:
    """Sun and moon for the coming nights. Deliberately carries no forecast.

    This used to copy tonight's probability into all seven days and nudge it by
    +/-0.05 on moon illumination, then render seven cards with per-day verdicts and
    percentages. It was one number wearing a costume — and its hardcoded moon
    direction could contradict the app's own learned moon driver on an adjacent tab.
    Predicting a specific night a week out needs a covariate model that has been
    scored against outcomes; until that exists, an almanac is the honest thing to
    show.
    """
    now = datetime.now(timezone.utc)
    out = []
    for i in range(days):
        night = (now + timedelta(days=i)).replace(hour=23, minute=0, second=0, microsecond=0)
        phase, illum = moon_phase(night)
        s = solar(settings.estate_lat, settings.estate_lon, night.date())
        out.append({
            "date": night.date().isoformat(),
            "moon_phase": phase,
            "moon_illum": illum,
            "darkness_minutes": s.get("darkness_minutes"),
            "sunset": s.get("sunset"),
            "civil_twilight_end": s.get("civil_twilight_end"),
        })
    return out


def _clock(hour: int) -> str:
    """Plain clock time for a sentence: 0 reads as midnight, 21 as 21:00."""
    return "midnight" if hour == 0 else f"{hour:02d}:00"


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
    w = _best_window(by_hour, sittable_only=False)
    out.append({
        "kind": "time",
        "statement": f"Your cameras are busiest between {_clock(w['start_hour'])} "
                     f"and {_clock(w['end_hour'])}.",
        "strength": w["share_pct"] / 100, "sample": total,
    })

    # 2. Top-2 species, their own peak windows
    sp_rows = db.execute(
        select(Detection.species_id, Species.common_name, func.count(Detection.id))
        .join(Species, Species.id == Detection.species_id)
        .where(Species.hidden.is_(False))
        .group_by(Detection.species_id, Species.common_name)
        .order_by(func.count(Detection.id).desc()).limit(2)
    ).all()
    for sid, name, cnt in sp_rows:
        rows = db.execute(
            select(h, func.count()).select_from(Detection).join(Image, Image.id == Detection.image_id)
            .where(Detection.species_id == sid).group_by(h)
        ).all()
        sw = _best_window({int(x): int(c) for x, c in rows}, sittable_only=False)
        out.append({
            "kind": "time",
            "statement": f"The cameras see {name.lower()} mostly between "
                         f"{_clock(sw['start_hour'])} and {_clock(sw['end_hour'])}.",
            "strength": sw["share_pct"] / 100, "sample": int(cnt),
        })

    # 3. Camera concentration. Moon comparisons live in patterns.py, where the
    # denominator also includes quiet recording days.
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
        statement = (
            f"Most of the action is at {names}. The other cameras see far less."
            if share >= 50 else f"{names} are your busiest cameras."
        )
        out.append({
            "kind": "location",
            "statement": statement,
            "strength": share / 100, "sample": total,
        })
    return out


def _composition(db: Session) -> list[dict]:
    """Herd makeup: stags vs hinds, sows-with-piglets vs sounders, and where each concentrates."""
    rows = db.execute(
        select(
            Detection.species_id, Species.common_name, Detection.sex,
            Detection.group_type, Camera.name, func.count(Detection.id),
        )
        .join(Image, Image.id == Detection.image_id)
        .join(Species, Species.id == Detection.species_id)
        .join(Camera, Camera.id == Image.camera_id)
        .where(Species.hidden.is_(False))
        .group_by(
            Detection.species_id, Species.common_name, Detection.sex,
            Detection.group_type, Camera.name,
        )
    ).all()
    totals: dict[str, int] = {}
    where: dict[str, dict[str, int]] = {}
    for sp, cn, sex, gt, cam, c in rows:
        lbl = class_label(sp, cn, sex, gt)
        totals[lbl] = totals.get(lbl, 0) + int(c)
        where.setdefault(lbl, {})[cam] = where.setdefault(lbl, {}).get(cam, 0) + int(c)
    items = []
    for lbl, cnt in sorted(totals.items(), key=lambda kv: -kv[1]):
        cams = where.get(lbl, {})
        top_cam = max(cams.items(), key=lambda kv: kv[1])[0] if cams else None
        items.append({"label": lbl, "count": cnt, "top_camera": top_cam})
    return items


def compute_insights(db: Session) -> dict:
    return {
        "outlook": _outlook(),
        "composition": _composition(db),
        "correlations": _correlations(db),
    }
