"""Insights — sun/moon calendar and summaries of recorded sightings.

Weather and moon comparisons come from patterns.py so the page uses one
consistent comparison for each condition.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.enrichment.astro import moon_phase, solar
from app.forecasting.exposure import current_night, local_hour, night_key_start
from app.forecasting.model import _best_window, sentence_case
from app.models import Camera

_TZ = settings.estate_timezone
# How far back Insights reads: the season, not every photo ever taken.
HISTORY_NIGHTS = 365


def _since():
    return night_key_start(current_night() - timedelta(days=HISTORY_NIGHTS + 1))


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


def _summaries(rows: list[tuple], names: dict | None = None) -> list[dict]:
    """The plain-sentence summaries, from visits per (camera, species id, species
    name, local hour of arrival). Visits, not photos: one boar loitering for thirty
    frames is one arrival, and a camera that fires often no longer counts for more.

    The camera is a key `names` turns into its name (the key itself without it): two
    cameras that share a name are still two cameras (audit I-26)."""
    names = names or {}

    def name_of(camera) -> str:
        return names.get(camera, camera)

    out: list[dict] = []
    total = sum(n for *_, n in rows)
    if total < 20:
        return out

    # 1. Overall peak window
    by_hour: dict[int, int] = {}
    per_species: dict[str, dict] = {}
    per_camera: dict[str, int] = {}
    for camera, species_id, name, hour, n in rows:
        by_hour[hour] = by_hour.get(hour, 0) + n
        per_camera[camera] = per_camera.get(camera, 0) + n
        if species_id:
            sp = per_species.setdefault(species_id, {"name": name, "n": 0, "by_hour": {}})
            sp["n"] += n
            sp["by_hour"][hour] = sp["by_hour"].get(hour, 0) + n
    w = _best_window(by_hour, sittable_only=False)
    out.append({
        "kind": "time",
        "statement": f"Your cameras are busiest between {_clock(w['start_hour'])} "
                     f"and {_clock(w['end_hour'])}.",
        "strength": w["share_pct"] / 100, "sample": total,
    })

    # 2. Top-2 species, their own peak windows
    top = sorted(per_species.values(), key=lambda sp: (-sp["n"], sp["name"]))[:2]
    for sp in top:
        sw = _best_window(sp["by_hour"], sittable_only=False)
        out.append({
            "kind": "time",
            "statement": f"The cameras see {sp['name'].lower()} mostly between "
                         f"{_clock(sw['start_hour'])} and {_clock(sw['end_hour'])}.",
            "strength": sw["share_pct"] / 100, "sample": sp["n"],
        })

    # 3. Camera concentration. Moon comparisons live in patterns.py, where the
    # denominator also includes quiet recording nights. "The other cameras see far
    # less" only when there are others, and they do: with two cameras the top two
    # always hold everything, and 30/25/25/20 is not "far less".
    cams = sorted(per_camera.items(), key=lambda kv: (-kv[1], str(name_of(kv[0]))))
    if len(cams) >= 2:
        top2 = cams[0][1] + cams[1][1]
        share = round(top2 / total * 100)
        both = f"{name_of(cams[0][0])} and {name_of(cams[1][0])}"
        concentrated = len(cams) >= 3 and cams[2][1] < cams[1][1] / 2
        statement = (
            f"Most of the action is at {both}. The other cameras see far less."
            if concentrated else f"{both} are your busiest cameras."
        )
        out.append({
            "kind": "location",
            "statement": statement,
            "strength": share / 100, "sample": total,
        })
    return out


def _correlations(db: Session) -> list[dict]:
    """Summaries of the season's visits at cameras nobody retired, in words.

    Hidden species and photos marked "nothing in it" are not visits (visit_rows)."""
    from app.forecasting.visits import visit_rows

    v = visit_rows(start=_since())
    hour = local_hour(v.c.first_at).label("h")
    # By camera id, named afterwards: two cameras called "SPYPOINT" are two cameras.
    rows = db.execute(
        select(Camera.id, v.c.species_id, v.c.common_name, hour, func.count())
        .select_from(v)
        .join(Camera, Camera.id == v.c.camera_id)
        .where(Camera.retired_at.is_(None))
        .group_by(Camera.id, v.c.species_id, v.c.common_name, hour)
    ).all()
    names = dict(db.execute(select(Camera.id, Camera.name)).all())
    return _summaries([
        (cam, sid, sentence_case(name) if name else None, int(h), int(n))
        for cam, sid, name, h, n in rows
    ], names)


def _composition(db: Session) -> list[dict]:
    """Herd makeup: stags vs hinds, sows-with-piglets vs sounders, and where each
    concentrates, in visits (photos alongside, for the numbers behind the fold)."""
    from app.forecasting.visits import class_visits

    names = dict(db.execute(select(Camera.id, Camera.name)).all())
    totals: dict[str, dict] = {}
    where: dict[str, dict] = {}
    for r in class_visits(db, start=_since()):
        lbl = r["label"]
        t = totals.setdefault(lbl, {"visits": 0, "photos": 0})
        t["visits"] += r["visits"]
        t["photos"] += r["photos"]
        cams = where.setdefault(lbl, {})
        cams[r["camera_id"]] = cams.get(r["camera_id"], 0) + r["visits"]
    items = []
    for lbl, t in sorted(totals.items(), key=lambda kv: (-kv[1]["visits"], kv[0])):
        cams = where.get(lbl, {})
        top_cam = max(cams.items(), key=lambda kv: kv[1])[0] if cams else None
        items.append({"label": lbl, "count": t["visits"], "visits": t["visits"],
                      "photos": t["photos"], "top_camera": names.get(top_cam)})
    return items


def compute_insights(db: Session) -> dict:
    return {
        "outlook": _outlook(),
        "composition": _composition(db),
        "correlations": _correlations(db),
    }
