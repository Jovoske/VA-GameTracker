"""Tonight forecast — an honest, data-grounded recommendation per camera/species.

With ~1 season of data this is deliberately a transparent statistical model
(historical presence rate + recency + darkness), not a fragile ML net. It says
how sure it is and why, and never claims certainty. The factors feed the card's
"why" expander. A calibrated GBT can replace this once many more nights exist.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, and_, case, cast, func, literal, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.enrichment.astro import moon_phase, solar
from app.enrichment.weather import weather_at
from app.forecasting.changes import whats_changed
from app.forecasting.exposure import current_night, local_hour, night_key_start
from app.forecasting.scoring import calibration
from app.forecasting.wind import assess
from app.models import Camera, CameraNight, Image, Species, Stand

log = get_logger(__name__)

_TZ = settings.estate_timezone


# Hours a person can realistically sit an evening stand. Searching all 24 returned
# windows like 03:00-06:00: genuinely where camera activity peaked, and genuinely
# useless as a recommendation, because nobody is sitting then. The constraint is
# what a hunter can do, not what the sensor saw.
SITTABLE_HOURS = tuple(range(16, 24)) + (0, 1)


def _best_window(by_hour: dict[int, int], *, sittable_only: bool = True) -> dict:
    """Best 3-hour block, restricted to hours somebody could actually be there."""
    total = sum(by_hour.values()) or 1
    starts = SITTABLE_HOURS if sittable_only else tuple(range(24))
    best_start, best_sum = starts[0], -1
    for start in starts:
        block = sum(by_hour.get((start + d) % 24, 0) for d in range(3))
        if block > best_sum:
            best_start, best_sum = start, block
    return {"start_hour": best_start, "end_hour": (best_start + 3) % 24,
            "share_pct": round(best_sum / total * 100)}


MIN_NIGHTS_TO_JUDGE = 15


def _verdict(prob: float, active_nights: int | None = None) -> str:
    """Describe the ground, don't instruct the hunter.

    GO/MARGINAL/SKIP read as commands, which turns every blank evening into a broken
    promise and hands the hunter someone to blame. These labels state what the camera
    has seen and leave the decision where it belongs.

    NO_DATA is a distinct state, not a bad one: a camera with too few watched nights
    is a hardware report, and calling that "QUIET" claims knowledge of the ground we
    do not have. Note this keys on nights WATCHED, so a camera that is merely out of
    photo credits keeps its historical ranking rather than disappearing.
    """
    if active_nights is not None and active_nights < MIN_NIGHTS_TO_JUDGE:
        return "NO_DATA"
    if prob >= 0.5:
        return "BEST_ODDS"
    if prob >= 0.2:
        return "WORTH_A_LOOK"
    return "QUIET"


def _is_nocturnal(window: dict) -> bool:
    h = window["start_hour"]
    return h >= 20 or h <= 5


# How far back the plan reads: the season is the evidence. Older than a year is
# another camera position, another crop, another herd.
HISTORY_NIGHTS = 365
# "Recent" is the last seven nights that are over, never the one under way.
RECENT_NIGHTS = 7
# Fewer watched nights than this among the last seven, and the week says nothing
# either way: no nudge up, and no penalty for a silence nobody was watching.
MIN_RECENT_WATCHED = 4
# A camera with no photo at all for longer than this is not ranked: a camera in a
# drawer used to top Tonight for weeks on what it saw in August.
SILENT_DAYS = 7
# The nights a camera can be judged on (exposure.py): it was demonstrably watching.
WATCHED = ("CONFIRMED", "PRESUMED_UP")


def _evidence(
    db: Session, cams: list[Camera], species_ids: list[str] | None, tonight
) -> dict:
    """What the ranking reads, for every camera at once: the nights each camera was
    watching, the nights it can't vouch for, and its visits per species, night and
    hour. A visit is an arrival (visits.py), so a boar loitering for thirty frames
    counts once; hidden species and photos marked "nothing in it" never count."""
    from app.forecasting.visits import visit_rows

    first = tonight - timedelta(days=HISTORY_NIGHTS)
    cam_ids = [c.id for c in cams]
    ev: dict = {
        c.id: {"watched": set(), "left_out": {}, "species": {}, "newest": None} for c in cams
    }
    if not cam_ids:
        return ev
    for cam_id, night, state in db.execute(
        select(CameraNight.camera_id, CameraNight.night, CameraNight.exposure_state).where(
            CameraNight.camera_id.in_(cam_ids),
            CameraNight.night >= first, CameraNight.night < tonight,
        )
    ).all():
        if state in WATCHED:
            ev[cam_id]["watched"].add(night)
        else:
            ev[cam_id]["left_out"][night] = state

    # Frames up to 06:00 this morning: tonight's night is not over, so it is neither
    # a night seen nor one missed.
    wanted = select(Species.id).where(Species.huntable.is_(True), Species.hidden.is_(False))
    if species_ids:
        wanted = wanted.where(Species.id.in_(species_ids))
    v = visit_rows(start=night_key_start(first - timedelta(days=1)),
                   end=night_key_start(tonight), camera_ids=cam_ids,
                   species_ids=list(db.scalars(wanted).all()))
    hour = local_hour(v.c.first_at).label("h")
    rows = db.execute(
        select(
            v.c.camera_id, v.c.species_id, v.c.common_name, v.c.night, hour,
            func.count().label("visits"), cast(func.sum(v.c.frames), Integer).label("frames"),
        )
        .where(v.c.night >= first)
        .group_by(v.c.camera_id, v.c.species_id, v.c.common_name, v.c.night, hour)
    ).tuples().all()
    for cam_id, species_id, name, night, h, visits, frames in rows:
        sp = ev[cam_id]["species"].get(species_id)
        if sp is None:
            sp = ev[cam_id]["species"][species_id] = {
                "name": name, "nights": {}, "by_hour": {}, "frames": {}}
        nights, by_hour = sp["nights"], sp["by_hour"]
        nights[night] = nights.get(night, 0) + visits
        sp["frames"][night] = sp["frames"].get(night, 0) + frames
        by_hour[h] = by_hour.get(h, 0) + visits

    for cam_id, newest in db.execute(
        select(Image.camera_id, func.max(Image.captured_at))
        .where(Image.camera_id.in_(cam_ids), Image.captured_at <= datetime.now(timezone.utc))
        .group_by(Image.camera_id)
    ).all():
        ev[cam_id]["newest"] = newest
    return ev


def _camera_forecast(
    cam: Camera, ev: dict, tonight, *, producing: bool = True,
) -> dict | None:
    """Best huntable species at this camera tonight, from its evidence (_evidence).

    Presence is the share of the nights this camera was demonstrably watching on
    which the species came: never a night keyed by calendar date (a visit either side
    of midnight is one night, not two), never a night whose photos the AI hasn't
    checked, and never the night still under way.
    """
    watched = ev["watched"]
    best = None
    for species_id, sp in ev["species"].items():
        seen = {n for n, visits in sp["nights"].items() if visits and n in watched}
        visits = sum(sp["nights"][n] for n in seen)
        key = (len(seen), visits)
        if best is None or key > best[0]:
            best = (key, species_id, sp, seen)
    if best is None or not best[3]:
        return None
    (_, visits), species_id, sp, seen = best
    others = sorted(
        (
            (len({n for n, c in o["nights"].items() if c and n in watched}), o["name"])
            for sid, o in ev["species"].items() if sid != species_id
        ),
        reverse=True,
    )
    runner_up = sentence_case(others[0][1]) if others and others[0][0] else None

    active_nights = len(watched)
    presence = min(1.0, len(seen) / active_nights) if active_nights else 0.0
    recent_keys = {tonight - timedelta(days=d) for d in range(1, RECENT_NIGHTS + 1)}
    recent_watched = len(recent_keys & watched)
    recent_nights = len(recent_keys & seen)
    recent_unchecked = sum(
        1 for n in recent_keys if ev["left_out"].get(n) == "UNPROCESSED"
    )

    window = _best_window(sp["by_hour"])

    # Probability tonight: base presence rate, nudged by the last week, but only when
    # the camera is producing and enough of that week was watched. A camera that's
    # out of credits or offline has no fresh photos, and a week the AI hasn't checked
    # yet has none either: neither silence is an absence of game.
    prob = presence
    if producing and recent_watched >= MIN_RECENT_WATCHED:
        if recent_nights >= 4:
            prob = min(0.97, prob + 0.1)
        elif recent_nights == 0:
            prob = max(0.02, prob - 0.15)

    return {
        "camera": cam.name, "camera_id": str(cam.id),
        "species": sentence_case(sp["name"]), "species_id": species_id,
        "runner_up": runner_up,
        "probability": round(prob, 2), "presence": round(presence, 2),
        "nights_present": len(seen), "recent_nights": recent_nights,
        "recent_watched": recent_watched, "recent_unchecked": recent_unchecked,
        "active_nights": active_nights, "producing": producing,
        "judgeable": active_nights >= MIN_NIGHTS_TO_JUDGE,
        "visits": visits, "photos": sum(sp["frames"].get(n, 0) for n in seen),
        "best_window": window,
        "nocturnal": _is_nocturnal(window),
    }


def _rank_key(f: dict) -> tuple:
    """Cameras that can be judged first, then by their odds. A camera added a few
    nights ago with boar on all three is "Not enough to say", and must not push a
    proven Best-odds spot off the headline."""
    return (f["judgeable"], f["probability"], f["active_nights"])


# The names older builds of the classifier stored, in title case ("Wild Boar", "Roe
# Deer"). Migration 0025 moved them to the app's names, but a copy restored from
# before it, or a seed, can still hold one. Written out, not worked out from
# name.title(): an admin's "Iberian Ibex" is a name somebody typed and keeps its capitals.
_OLD_TITLE_CASE = frozenset({"Wild Boar", "Red Deer", "Roe Deer", "Fallow Deer"})


def sentence_case(name: str) -> str:
    """"Roe Deer" -> "Roe deer": a name as an older build stored it, written as words
    in a sentence, the way "Wild boar" and "Red deer" read.

    Any other name is left as it was written (an admin's "Iberian Ibex", "Big
    Tusker's sow"), bar a capital to start it, so a tile writes it as Settings does.
    """
    if name in _OLD_TITLE_CASE:
        return name[:1] + name[1:].lower()
    return name[:1].upper() + name[1:]


def class_label(species_id: str | None, common_name: str | None, sex: str | None, group_type: str | None) -> str:
    """Human class from species + sex + group composition (mirrors the gallery chip).

    Stag / Hind / Boar / Sow / Sounder are what the animal is; a boar or red deer
    nobody could sex is called by the species' name, so an admin's rename in Settings
    reaches those tiles too. Every other species is its name ("Roe deer", "Fallow
    deer"), so the Photos tiles, the map and the alerts all write it the same way.
    """
    if species_id == "red_deer":
        if group_type == "hind_with_calf":
            return "Hind + calf"
        if sex == "male":
            return "Stag"
        if sex == "female":
            return "Hind"
        name = sentence_case(common_name) if common_name else "Red deer"
        return f"{name} (herd)" if group_type == "herd" else name
    if species_id == "wild_boar":
        if group_type == "sow_with_piglets":
            return "Sow + piglets"
        if sex == "male":
            return "Boar"
        if sex == "female":
            return "Sow"
        if group_type == "sounder":
            return "Sounder"
        return sentence_case(common_name) if common_name else "Wild boar"
    return sentence_case(common_name) if common_name else (species_id or "Animal")


def sentence_case_sql(name):
    """sentence_case in SQL, on a species' name column: what the tiles call it."""
    return case(
        (name.in_(sorted(_OLD_TITLE_CASE)),
         func.concat(func.left(name, 1), func.lower(func.substr(name, 2)))),
        else_=func.concat(func.upper(func.left(name, 1)), func.substr(name, 2)),
    )


def class_label_sql(species_id, sex, group_type, common_name=None):
    """SQL for class_label's split of red deer and wild boar ("Stag", "Sow + piglets"),
    NULL where the class is the species' own name (every other species, and a boar or
    red deer the sex and group pass said nothing about), so that name is the one an
    admin gave it in Settings. Mirrors class_label, so a visit can be counted per
    class in the database: keep the two in step. `common_name` (the species' name
    column) names a red deer herd as its tiles do."""
    deer = literal("Red deer") if common_name is None else func.coalesce(
        func.nullif(sentence_case_sql(common_name), ""), "Red deer")
    return case(
        (and_(species_id == "red_deer", group_type == "hind_with_calf"), "Hind + calf"),
        (and_(species_id == "red_deer", sex == "male"), "Stag"),
        (and_(species_id == "red_deer", sex == "female"), "Hind"),
        (and_(species_id == "red_deer", group_type == "herd"), func.concat(deer, " (herd)")),
        (and_(species_id == "wild_boar", group_type == "sow_with_piglets"), "Sow + piglets"),
        (and_(species_id == "wild_boar", sex == "male"), "Boar"),
        (and_(species_id == "wild_boar", sex == "female"), "Sow"),
        (and_(species_id == "wild_boar", group_type == "sounder"), "Sounder"),
        else_=None,
    )


def _classes(rows: list[dict], camera_id: str, species_ids=None, nights=None,
             limit: int | None = 4) -> list[dict]:
    """The commonest classes at a camera, by visits, photos alongside.

    Only visits on `nights` (the nights the camera was watching, which is what its
    visits are counted over), so the classes of one animal add up to its visits.
    """
    agg: dict[str, dict] = {}
    for r in rows:
        if str(r["camera_id"]) != camera_id or (species_ids and r["species_id"] not in species_ids):
            continue
        if nights is not None and r["night"] not in nights:
            continue
        c = agg.setdefault(r["label"], {"label": r["label"], "visits": 0, "photos": 0})
        c["visits"] += r["visits"]
        c["photos"] += r["photos"]
    return sorted(agg.values(), key=lambda c: (-c["visits"], -c["photos"], c["label"]))[:limit]


def _expectations(
    db: Session, forecasts: list[dict], species_ids: list[str] | None, tonight,
    watched: dict[str, set],
) -> tuple[list[dict], list[dict]]:
    """Per ranked camera: which classes (stag/hind/sow+piglets/…) to expect there.

    Counted in visits, the unit a hunter reads: a sow and her piglets loitering for
    forty frames are one visit, not "×40". Each visit is of one class
    (visits.class_visits) and only the nights the camera was watching count, so the
    classes of an animal add up to its visits. The class rows come back too, so the
    top card can list only the animal it names."""
    from app.forecasting.visits import class_visits

    if not forecasts:
        return [], []
    wanted = select(Species.id).where(Species.huntable.is_(True), Species.hidden.is_(False))
    if species_ids:
        # Asked for boar, be shown boar: listing every class at the stand would bury
        # the thing the hunter came for.
        wanted = wanted.where(Species.id.in_(species_ids))
    first = tonight - timedelta(days=HISTORY_NIGHTS)
    rows = class_visits(
        db, start=night_key_start(first - timedelta(days=1)), end=night_key_start(tonight),
        camera_ids=[uuid.UUID(f["camera_id"]) for f in forecasts],
        species_ids=list(db.scalars(wanted).all()),
    )
    out = []
    for f in forecasts:
        out.append({
            "camera": f["camera"], "camera_id": f["camera_id"],
            "species_id": f["species_id"],  # needed to score the claim later
            "verdict": _verdict(f["probability"], f["active_nights"]),
            "probability": f["probability"],
            "nights_present": f["nights_present"], "active_nights": f["active_nights"],
            "visits": f["visits"], "photos": f["photos"],
            "best_window": f["best_window"],
            "classes": _classes(rows, f["camera_id"], nights=watched.get(f["camera_id"])),
        })
    return out, rows


def _tonight_conditions(now: datetime) -> dict:
    phase, illum = moon_phase(now)
    s = solar(settings.estate_lat, settings.estate_lon, now.date())
    wind_dir = wind_speed = temp = pressure = cloud = rain = None
    try:
        # `now` is UTC and the service sets no TZ, so .astimezone() was a no-op:
        # this sampled 22:00 UTC, which is midnight the following day in Madrid.
        local_22 = now.astimezone(ZoneInfo(_TZ)).replace(
            hour=22, minute=0, second=0, microsecond=0
        )
        w = weather_at(settings.estate_lat, settings.estate_lon, local_22, tz=_TZ)
        wind_dir, wind_speed, temp = w.get("wind_dir_deg"), w.get("wind_speed_kmh"), w.get("temp_c")
        pressure, cloud, rain = w.get("pressure_hpa"), w.get("cloud_cover_pct"), w.get("rain_mm")
    except Exception:
        pass
    return {
        "moon_phase": phase, "moon_illum": illum,
        "darkness_minutes": s.get("darkness_minutes"),
        "wind_dir_deg": wind_dir, "wind_speed_kmh": wind_speed, "temp_c": temp,
        "pressure_hpa": pressure, "cloud_cover_pct": cloud, "rain_mm": rain,
    }


def _factors(top: dict, cond: dict) -> list[dict]:
    out = []
    unwatched = RECENT_NIGHTS - top["recent_watched"]
    if not top.get("producing", True):
        out.append({
            "text": (
                f"Camera is not sending photos right now. Going on "
                f"{top['nights_present']} nights of history."
            ),
            "impact": "•",
        })
    elif top["recent_watched"] < MIN_RECENT_WATCHED:
        # Not a quiet week: a week nobody could see. It neither helps nor counts against.
        if top.get("recent_unchecked"):
            text = (f"Photos from {top['recent_unchecked']} of the last 7 nights are still "
                    "being checked. Going on its history.")
        else:
            text = (f"Only {top['recent_watched']} of the last 7 nights watched here. "
                    "Going on its history.")
        out.append({"text": text, "impact": "•"})
    else:
        gap = f" ({unwatched} not watched)" if unwatched else ""
        if top["recent_nights"] > 0:
            out.append({
                "text": (f"{top['species']} seen {top['recent_nights']} of the last 7 nights "
                         f"here{gap}"),
                "impact": "+++" if top["recent_nights"] >= 4 else "++",
            })
        else:
            out.append({"text": f"No {top['species'].lower()} here in the last 7 nights{gap}",
                        "impact": "--"})
    # Moon/weather are handled by the data-driven tonight drivers (condition_reasons),
    # so they're not hardcoded here — keeps the "why" consistent with the learned patterns.
    w = top["best_window"]
    out.append({
        "text": f"Best hours {w['start_hour']:02d}:00 to {w['end_hour']:02d}:00",
        "impact": "++",
    })
    return out


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _left_out_note(top: dict, ev: dict) -> tuple[int, str]:
    """The nights at the recommended camera not counted, and why, in words.

    The whole point of the exposure table is that these are left out rather than
    silently averaged in as "no animals", and an exclusion nobody is told about is
    indistinguishable from the bug it replaced. It used to be an estate-wide count
    over all time, next to a camera it said nothing about."""
    states = list(ev["left_out"].values())
    unchecked = states.count("UNPROCESSED")
    blind = len(states) - unchecked
    total = unchecked + blind
    if not total:
        return 0, ""
    why = []
    if unchecked:
        why.append(f"{unchecked} with photos not checked yet" if blind
                   else "photos not checked yet")
    if blind:
        why.append(f"{blind} the camera may not have been watching" if unchecked
                   else "the camera may not have been watching")
    return total, f"{_plural(total, 'night')} at {top['camera']} left out: {', '.join(why)}."


def _freshness(db: Session, now: datetime) -> dict | None:
    """How old the photos behind the plan are, and whether fetching them has stopped.

    "Plan from just now" says when the answer was worked out, not how current its
    photos are; with a login broken or the scheduled fetch stopped, those can be days
    old while the plan still looks fresh (app.ingestion.logins.freshness).
    """
    from app.ingestion.logins import freshness

    try:
        with db.begin_nested():
            return freshness(db, now=now)
    except Exception as e:  # never let the extra line break the verdict
        log.warning("freshness.failed", error=str(e))
        return None


def forecast_tonight(db: Session, species_ids: list[str] | None = None) -> dict:
    now = datetime.now(timezone.utc)
    tonight = current_night(now)

    # A camera that isn't producing data (dead battery / no check-in / out of photo credits)
    # must not have its silence scored as "no animals". We keep it in the ranking on its
    # HISTORICAL presence (skipping the recent-activity penalty) and also surface it as an
    # alert — so a strong spot whose camera is merely capped isn't hidden or downgraded.
    # Not for ever, though: with no photo at all for over SILENT_DAYS it is left out
    # of the ranking (and so out of the claims scored), and said so. A camera whose
    # login was removed, or one an admin retired, is not ranked at all.
    from app.health import camera_health
    from app.ingestion.logins import camera_logins

    cams = db.scalars(
        select(Camera)
        .where(Camera.active.is_(True), Camera.retired_at.is_(None))
        .order_by(Camera.name)
    ).all()
    login_states = camera_logins(db, cams, now)
    health = {c.id: camera_health(c, now, login_states.get(c.id)) for c in cams}
    fresh = _freshness(db, now)
    ev = _evidence(db, cams, species_ids, tonight)

    alerts, ranked = [], []
    for c in cams:
        newest = ev[c.id]["newest"]
        silent = newest is None or now - newest > timedelta(days=SILENT_DAYS)
        h = health[c.id]
        if silent and newest is not None:
            days = (now - newest).days
            alerts.append({
                "camera": c.name, "camera_id": str(c.id), "status": h["status"],
                "detail": (h["detail"] + ". " if not h["producing"] else "")
                + f"No photos for {days} days, so it is left out of tonight's ranking",
                "ranked": False,
            })
            continue
        if not h["producing"]:
            alerts.append({"camera": c.name, "camera_id": str(c.id), "status": h["status"],
                           "detail": h["detail"], "ranked": not silent})
        if not silent:
            ranked.append(c)
    forecasts = [
        f for f in (
            _camera_forecast(c, ev[c.id], tonight, producing=health[c.id]["producing"])
            for c in ranked
        ) if f
    ]
    # The learned weather/moon "drivers" used to be multiplied into this number.
    # They were removed after a null simulation run against the real _driver() code:
    # on counts generated to be independent of every covariate, it still found at
    # least one "driver" in 97.8-99.8% of runs, at a median reported effect of
    # 46-108% against an advertised MIN_EFFECT floor of 15. Those coefficients were
    # moving the headline verdict. Tonight's conditions are still shown as facts;
    # they no longer silently move the ranking.
    forecasts.sort(key=_rank_key, reverse=True)
    # Nights at least one ranked camera was watching: what the plan stands on.
    nights_of_data = len(set().union(*(ev[c.id]["watched"] for c in ranked)))

    cond = _tonight_conditions(now)
    if not forecasts:
        if species_ids:
            reason = "No camera has seen the animals you picked yet."
        else:
            reason = (
                "The cameras that are sending have not seen any animals yet."
                if alerts else "No sightings yet."
            )
        # NO_DATA, not SKIP: we have nothing to say about the ground, which is not the
        # same as telling somebody their evening isn't worth having.
        return {"verdict": "NO_DATA", "reason": reason, "nights_of_data": nights_of_data,
                "conditions": cond, "alternates": [], "alerts": alerts, "freshness": fresh}

    top = forecasts[0]
    watched = {str(c.id): ev[c.id]["watched"] for c in ranked}
    where, class_rows = _expectations(db, forecasts, species_ids, tonight, watched)
    # The top card names one animal, so it lists that animal's classes only, all of
    # them, adding up to its visits; the mixed list stays in the per-camera fold
    # (audit I-20).
    top_classes = _classes(class_rows, top["camera_id"], {top["species_id"]},
                           watched[top["camera_id"]], limit=None)

    # One line of news beats a wall of unchanged numbers. A hunter who opened the app
    # yesterday needs to know what moved, not to re-read what didn't.
    try:
        changed = whats_changed(db, tonight=tonight)
    except Exception as e:  # never let the extra line break the verdict
        log.warning("changed.failed", error=str(e))
        changed = {"kind": "none", "camera": None, "text": ""}

    # Wind is deterministic geometry against the stand linked to the top camera — not a
    # fitted coefficient. It states its own competence boundary rather than producing a
    # confident bearing on a calm night that a single weather grid point cannot see.
    stand = db.scalar(select(Stand).where(Stand.camera_id == uuid.UUID(top["camera_id"])))
    alt = forecasts[1]["camera"] if len(forecasts) > 1 else None
    wind_verdict = assess(
        stand_name=stand.name if stand else top["camera"],
        wind_dir_deg=cond.get("wind_dir_deg"),
        wind_speed_kmh=cond.get("wind_speed_kmh"),
        approach_dirs_deg=stand.approach_dirs_deg if stand else None,
        alternative_stand=alt,
    )

    # The honest replacement for the deleted confidence figure: not how much data went
    # in, but how often this model has actually been right when it was checked.
    try:
        track_record = calibration(db)
    except Exception as e:
        log.warning("calibration.failed", error=str(e))
        track_record = {"available": False, "n_evaluated": 0}

    skipped, note = _left_out_note(top, ev[uuid.UUID(top["camera_id"])])

    return {
        "exposure": {"excluded_nights": skipped, "note": note},
        # Only when no camera can be judged is the headline "Not enough to say".
        "verdict": _verdict(top["probability"], top["active_nights"]),
        "changed": changed,
        "calibration": track_record,
        "wind": {
            "status": wind_verdict.status,
            "text": wind_verdict.text,
            "is_advice": wind_verdict.is_advice,
        },
        "recommended": {
            "camera": top["camera"], "camera_id": top["camera_id"],
            "species": top["species"], "runner_up": top["runner_up"],
            "probability": top["probability"], "best_window": top["best_window"],
            "expect": top_classes[0]["label"] if top_classes else top["species"],
            "classes": top_classes,
            "nights_present": top["nights_present"], "active_nights": top["active_nights"],
            "visits": top["visits"], "photos": top["photos"],
            "reason": (
                f"{top['species']} seen {top['nights_present']} of "
                f"{top['active_nights']} nights at this camera."
            ),
            # The reference class belongs in the sentence, not a footnote: a bare
            # percentage reads as "my chance of a shot tonight", which is not what
            # was measured.
            "caveat": (
                "The camera watches all night. You will be there a few hours, "
                "so pick the best hours and mind the wind."
            ),
        },
        "conditions": cond,
        "factors": _factors(top, cond),
        "where": where,
        "alternates": [
            {"camera": f["camera"], "camera_id": f["camera_id"], "species": f["species"],
             "verdict": _verdict(f["probability"], f["active_nights"]),
             "nights_present": f["nights_present"], "active_nights": f["active_nights"]}
            for f in forecasts[1:3]
        ],
        "alerts": alerts,
        "nights_of_data": nights_of_data,
        "freshness": fresh,
    }
