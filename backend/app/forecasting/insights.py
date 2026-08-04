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
from app.forecasting.model import _best_window, class_label
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
