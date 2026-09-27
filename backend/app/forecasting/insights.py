"""Insights — sun/moon calendar and summaries of recorded sightings.

Weather and moon comparisons come from patterns.py so the page uses one
consistent comparison for each condition.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.enrichment.astro import moon_phase, phase_words, solar
from app.forecasting.exposure import current_night, night_key_start
from app.forecasting.model import SLOT_MIN, _best_window
from app.i18n import species_name, t
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
            "moon_phase": phase_words(phase),
            "moon_illum": illum,
            "darkness_minutes": s.get("darkness_minutes"),
            "sunset": s.get("sunset"),
            "civil_twilight_end": s.get("civil_twilight_end"),
        })
    return out


@lru_cache(maxsize=1024)
def _sun(day: date) -> tuple[datetime | None, datetime | None]:
    s = solar(settings.estate_lat, settings.estate_lon, day)
    return s.get("sunrise"), s.get("sunset")


def _on_tonight(night: date, slot: int, tonight: date) -> int:
    """The hour of tonight's clock a visit in quarter hour `slot` of `night` stands for.

    Sunset in Alatoz moves about three hours between August and late October, the
    clock change included, so a season of clock hours drifted away from the animals
    ("busiest between 20:00 and 23:00" for boar now in by 19:00, audit G-05). An
    afternoon or evening visit is put as long after tonight's sunset as it came
    after its own day's; one after midnight or in the morning as long from
    tomorrow's sunrise as it was from its own.
    """
    minute = slot * SLOT_MIN + SLOT_MIN // 2
    day = night if minute >= 6 * 60 else night + timedelta(days=1)
    at = datetime.combine(day, time(minute // 60, minute % 60), tzinfo=ZoneInfo(_TZ))
    if minute >= 12 * 60:
        theirs, ours = _sun(day)[1], _sun(tonight)[1]
    else:
        theirs, ours = _sun(day)[0], _sun(tonight + timedelta(days=1))[0]
    if theirs is None or ours is None:
        return minute // 60
    return (ours + (at - theirs)).astimezone(ZoneInfo(_TZ)).hour


def _clock(hour: int) -> str:
    """Plain clock time for a sentence: 0 reads as midnight, 21 as 21:00."""
    return t("insights.midnight") if hour == 0 else f"{hour:02d}:00"


def _summaries(rows: list[tuple], names: dict | None = None) -> list[dict]:
    """The plain-sentence summaries, from visits per (camera, species id, species
    name, hour of arrival on tonight's clock, _on_tonight). Visits, not photos: one
    boar loitering for thirty frames is one arrival, and a camera that fires often
    no longer counts for more.

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
        "statement": t("insights.busiest", start=_clock(w["start_hour"]),
                       end=_clock(w["end_hour"])),
        "strength": w["share_pct"] / 100, "sample": total,
    })

    # 2. Top-2 species, their own peak windows
    top = sorted(per_species.values(), key=lambda sp: (-sp["n"], sp["name"]))[:2]
    for sp in top:
        sw = _best_window(sp["by_hour"], sittable_only=False)
        out.append({
            "kind": "time",
            "statement": t("insights.species_mostly", species=sp["name"].lower(),
                           start=_clock(sw["start_hour"]), end=_clock(sw["end_hour"])),
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
        both = t("list.two", a=name_of(cams[0][0]), b=name_of(cams[1][0]))
        concentrated = len(cams) >= 3 and cams[2][1] < cams[1][1] / 2
        statement = (t("insights.concentrated", cameras=both) if concentrated
                     else t("insights.busiest_cameras", cameras=both))
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
    local = func.timezone(_TZ, v.c.first_at)
    slot = cast(
        func.floor((func.extract("hour", local) * 60 + func.extract("minute", local)) / SLOT_MIN),
        Integer,
    ).label("slot")
    # By camera id, named afterwards: two cameras called "SPYPOINT" are two cameras.
    # By night and quarter hour, so each visit is put on tonight's clock by its own
    # night's sun (_on_tonight).
    rows = db.execute(
        select(Camera.id, v.c.species_id, v.c.common_name, v.c.night, slot, func.count())
        .select_from(v)
        .join(Camera, Camera.id == v.c.camera_id)
        .where(Camera.retired_at.is_(None))
        .group_by(Camera.id, v.c.species_id, v.c.common_name, v.c.night, slot)
    ).all()
    names = dict(db.execute(select(Camera.id, Camera.name)).all())
    tonight = current_night()
    by_hour: dict[tuple, int] = {}
    for cam, sid, name, night, sl, n in rows:
        key = (cam, sid, species_name(sid, name) if name else None,
               _on_tonight(night, int(sl), tonight))
        by_hour[key] = by_hour.get(key, 0) + int(n)
    return _summaries([(*key, n) for key, n in by_hour.items()], names)


def _composition(db: Session) -> list[dict]:
    """Herd makeup: stags vs hinds, sows-with-piglets vs sounders, and where each
    concentrates, in visits (photos alongside, for the numbers behind the fold)."""
    from app.forecasting.visits import class_visits

    names = dict(db.execute(select(Camera.id, Camera.name)).all())
    totals: dict[str, dict] = {}
    where: dict[str, dict] = {}
    for r in class_visits(db, start=_since()):
        lbl = r["label"]
        tot = totals.setdefault(lbl, {"visits": 0, "photos": 0})
        tot["visits"] += r["visits"]
        tot["photos"] += r["photos"]
        cams = where.setdefault(lbl, {})
        cams[r["camera_id"]] = cams.get(r["camera_id"], 0) + r["visits"]
    items = []
    for lbl, tot in sorted(totals.items(), key=lambda kv: (-kv[1]["visits"], kv[0])):
        cams = where.get(lbl, {})
        top_cam = max(cams.items(), key=lambda kv: kv[1])[0] if cams else None
        items.append({"label": lbl, "count": tot["visits"], "visits": tot["visits"],
                      "photos": tot["photos"], "top_camera": names.get(top_cam)})
    return items


def compute_insights(db: Session) -> dict:
    return {
        "outlook": _outlook(),
        "composition": _composition(db),
        "correlations": _correlations(db),
    }
