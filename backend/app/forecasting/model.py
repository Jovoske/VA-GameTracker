"""Tonight forecast — an honest, data-grounded recommendation per camera/species.

With ~1 season of data this is deliberately a transparent statistical model
(historical presence rate + recency + darkness), not a fragile ML net. It says
how sure it is and why, and never claims certainty. The factors feed the card's
"why" expander. A calibrated GBT can replace this once many more nights exist.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta, timezone
from functools import lru_cache
from typing import NamedTuple
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, and_, case, cast, false, func, literal, or_, select, true
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.enrichment.astro import solar
from app.forecasting.changes import whats_changed
from app.forecasting.conditions import (
    no_stand_verdict,
    release,
    stand_for_camera,
    tonight_conditions,
    wind_verdict,
)
from app.forecasting.exposure import current_night, night_key_start
from app.forecasting.scoring import calibration
from app.i18n import species_name, t
from app.models import Camera, CameraNight, Detection, Image, Species

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


# Best hours follow sunset, not the clock. Sunset in Alatoz moves about three hours
# between early August and late October (the clock change included), so a season's
# histogram of clock hours sent hunters out after the animals had arrived (audit
# G-05, J-08). Each visit is placed by the minutes after its own night's sunset, in
# SLOT_MIN steps, the recent weeks counting most (half as much every
# RECENT_HALF_LIFE_NIGHTS), and the best block is put back on the clock with
# tonight's sunset.
SLOT_MIN = 15
WINDOW_SLOTS = 12  # three hours
RECENT_HALF_LIFE_NIGHTS = 21


@lru_cache(maxsize=2048)
def _sunset(night: date) -> datetime | None:
    return solar(settings.estate_lat, settings.estate_lon, night).get("sunset")


def _after_sunset(night: date, slot: int) -> int | None:
    """Minutes from that night's sunset to the middle of a SLOT_MIN slot of the
    estate's clock (slot 0 is 00:00-00:15). Slots before 06:00 are the next morning."""
    sunset = _sunset(night)
    if sunset is None:
        return None
    minute = slot * SLOT_MIN + SLOT_MIN // 2
    day = night if minute >= 6 * 60 else night + timedelta(days=1)
    local = datetime.combine(day, time(minute // 60, minute % 60), tzinfo=ZoneInfo(_TZ))
    return round((local - sunset).total_seconds() / 60)


def span(minutes: int) -> str:
    """"1 h 30 min", "45 min", "2 h", in the language."""
    h, m = divmod(abs(minutes), 60)
    return " ".join(x for x in (t("time.hours", h=h) if h else "",
                                t("time.minutes", m=m) if m else "") if x)


def _relative(minutes: int) -> str:
    """"45 min after sunset", "sunset", "1 h 30 min before sunset"."""
    if abs(minutes) < 5:
        return t("sun.at_sunset")
    return t("sun.after" if minutes > 0 else "sun.before", span=span(minutes))


def _hhmm(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo(_TZ)).strftime("%H:%M")


def _sunset_window(slots: dict, tonight: date) -> dict | None:
    """Best three hours tonight, from when the animals came after each night's sunset.

    `slots` is visits per (night, SLOT_MIN slot of the clock). The block is searched
    in minutes after sunset, weighted to recent weeks, restricted to starts somebody
    could sit (SITTABLE_HOURS on tonight's clock), and returned as tonight's times,
    rounded to the quarter hour. `start_hour`/`end_hour` are the clock hours it
    covers; `after_sunset_min` is where it starts, counted from sunset.

    None when no visit falls in any block somebody could sit: every block ties at
    nothing, and the middle one read as "Best hours 21:15 to 00:15, from 1 h 15 min
    after sunset" for animals only ever seen at dawn (R4BE-5).
    """
    sunset = _sunset(tonight)
    hist: dict[int, float] = {}
    for (night, slot), visits in slots.items():
        off = _after_sunset(night, slot)
        if off is None or not visits:
            continue
        weight = visits * 0.5 ** (max(0, (tonight - night).days) / RECENT_HALF_LIFE_NIGHTS)
        b = off // SLOT_MIN
        hist[b] = hist.get(b, 0.0) + weight
    if sunset is None:
        by_hour: dict[int, int] = {}
        for (_, slot), visits in slots.items():
            by_hour[slot * SLOT_MIN // 60] = by_hour.get(slot * SLOT_MIN // 60, 0) + visits
        w = _best_window(by_hour)
        if not any(by_hour.get((h + d) % 24) for h in SITTABLE_HOURS for d in range(3)):
            return None
        return {**w, "start": f"{w['start_hour']:02d}:00", "end": f"{w['end_hour']:02d}:00",
                "after_sunset_min": None}
    total = sum(hist.values()) or 1.0
    # Every quarter hour from 6 h before sunset to 12 h after it that starts at an hour
    # somebody can sit.
    blocks = {}
    for b in range(-6 * 60 // SLOT_MIN, 12 * 60 // SLOT_MIN):
        start = sunset + timedelta(minutes=b * SLOT_MIN)
        if start.astimezone(ZoneInfo(_TZ)).hour in SITTABLE_HOURS:
            blocks[b] = sum(hist.get(b + d, 0.0) for d in range(WINDOW_SLOTS))
    best_sum = max(blocks.values(), default=0.0)
    if best_sum <= 0:
        return None
    # When the visits fit inside three hours, many starts hold them all: the middle
    # one puts them in the middle, with time to settle in before the first arrival
    # and cover after the last, rather than hours ahead of them.
    ties = [b for b, block in blocks.items() if block >= best_sum - 1e-9 * max(1.0, best_sum)]
    best_b = ties[len(ties) // 2] if ties else 0
    start = sunset + timedelta(minutes=best_b * SLOT_MIN)
    # A quarter hour on the clock reads better than 20:41 and is as true.
    start = datetime.fromtimestamp(round(start.timestamp() / 900) * 900, tz=UTC)
    end = start + timedelta(minutes=WINDOW_SLOTS * SLOT_MIN)
    end_local = end.astimezone(ZoneInfo(_TZ))
    return {
        "start": _hhmm(start), "end": _hhmm(end),
        "start_hour": start.astimezone(ZoneInfo(_TZ)).hour,
        "end_hour": (end_local.hour + (1 if end_local.minute else 0)) % 24,
        "share_pct": round(best_sum / total * 100),
        "after_sunset_min": best_b * SLOT_MIN,
    }


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


def _is_nocturnal(window: dict | None) -> bool:
    if window is None:
        return False
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
    # The quarter hour of the estate's clock each visit arrived in: best hours are
    # worked out from its minutes after that night's sunset (_sunset_window).
    local = func.timezone(_TZ, v.c.first_at)
    slot = cast(
        func.floor((func.extract("hour", local) * 60 + func.extract("minute", local)) / SLOT_MIN),
        Integer,
    ).label("slot")
    rows = db.execute(
        select(
            v.c.camera_id, v.c.species_id, v.c.common_name, v.c.night, slot,
            func.count().label("visits"), cast(func.sum(v.c.frames), Integer).label("frames"),
        )
        .where(v.c.night >= first)
        .group_by(v.c.camera_id, v.c.species_id, v.c.common_name, v.c.night, slot)
    ).tuples().all()
    for cam_id, species_id, name, night, sl, visits, frames in rows:
        sp = ev[cam_id]["species"].get(species_id)
        if sp is None:
            sp = ev[cam_id]["species"][species_id] = {
                "name": name, "nights": {}, "slots": {}, "frames": {}}
        nights, slots = sp["nights"], sp["slots"]
        nights[night] = nights.get(night, 0) + visits
        sp["frames"][night] = sp["frames"].get(night, 0) + frames
        slots[(night, sl)] = slots.get((night, sl), 0) + visits

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
            (len({n for n, c in o["nights"].items() if c and n in watched}), o["name"], sid)
            for sid, o in ev["species"].items() if sid != species_id
        ),
        reverse=True,
    )
    runner_up = species_name(others[0][2], others[0][1]) if others and others[0][0] else None

    active_nights = len(watched)
    presence = min(1.0, len(seen) / active_nights) if active_nights else 0.0
    recent_keys = {tonight - timedelta(days=d) for d in range(1, RECENT_NIGHTS + 1)}
    recent_watched = len(recent_keys & watched)
    recent_nights = len(recent_keys & seen)
    recent_unchecked = sum(
        1 for n in recent_keys if ev["left_out"].get(n) == "UNPROCESSED"
    )

    window = _sunset_window(sp["slots"], tonight)

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
        "species": species_name(species_id, sp["name"]), "species_id": species_id,
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


class _Split(NamedTuple):
    """How class_label splits red deer or wild boar: by the young one's group type,
    then the sex, then the group's; the species' own name for the rest."""

    young_type: str  # Detection.group_type of a mother with her young
    young: str
    male: str
    female: str
    group_type: str  # Detection.group_type of a group of them
    group: str

    @property
    def classes(self) -> tuple[str, str, str, str]:
        return self.young, self.male, self.female, self.group


_SPLIT = {
    "red_deer": _Split("hind_with_calf", "hind_calf", "stag", "hind", "herd", "herd"),
    "wild_boar": _Split("sow_with_piglets", "sow_piglets", "boar", "sow", "sounder", "sounder"),
}


def _class_of(species_id: str | None, sex: str | None, group_type: str | None) -> str | None:
    """"stag", "sow_piglets", "herd"… for a red deer or wild boar class_label splits
    off; None where the class is the species' own name."""
    split = _SPLIT.get(species_id or "")
    if split is None:
        return None
    if group_type == split.young_type:
        return split.young
    if sex == "male":
        return split.male
    if sex == "female":
        return split.female
    return split.group if group_type == split.group_type else None


def class_label(species_id: str | None, common_name: str | None, sex: str | None, group_type: str | None) -> str:
    """Human class from species + sex + group composition (mirrors the gallery chip),
    in the language being written in (app.i18n).

    Stag / Hind / Boar / Sow / Sounder are what the animal is; a boar or red deer
    nobody could sex is called by the species' name, so an admin's rename in Settings
    reaches those tiles too. Every other species is its name ("Roe deer", "Fallow
    deer"), so the Photos tiles, the map and the alerts all write it the same way.
    """
    cls = _class_of(species_id, sex, group_type)
    if cls == "herd":
        return t("class.herd", name=species_name(species_id, common_name))
    if cls:
        return t(f"class.{cls}")
    if common_name or species_id:
        return species_name(species_id, common_name)
    return t("class.animal")


def class_key(species_id: str | None, sex: str | None, group_type: str | None) -> str | None:
    """The class class_label names, as the app sends it back to ask for its photos:
    the same in every language, where the label is not ("Hjort" is a stag in Swedish
    and a red deer in Norwegian). "red_deer.stag", "wild_boar.sow_piglets", or the
    species' id for its own name ("red_deer", "roe_deer"); None for an unnamed animal."""
    if not species_id:
        return None
    cls = _class_of(species_id, sex, group_type)
    return f"{species_id}.{cls}" if cls else species_id


def join_class_keys(keys) -> str | None:
    """One chip's key: class_keys comma-joined, as a label that is two classes in the
    reader's language carries both (a boar an admin renamed "Boar" is the unsexed
    ones and the males)."""
    return ",".join(sorted({k for k in keys if k})) or None


def parse_class_key(key: str | None) -> tuple[str, str | None] | None:
    """(species id, class or None) of a class_key; None for one that is not."""
    if not key:
        return None
    sid, _, cls = key.strip().partition(".")
    if not sid:
        return None
    if not cls:
        return sid, None
    split = _SPLIT.get(sid)
    if split is None or cls not in split.classes:
        return None
    return sid, cls


def class_where(species_id: str, cls: str | None):
    """SQL on Detection: a sighting of `species_id` that class_label puts in class
    `cls` (None: the species' own name). Mirrors _class_of, so a class's photos are
    the ones its tiles are labelled with."""
    of_species = Detection.species_id == species_id
    split = _SPLIT.get(species_id)
    if split is None:
        return of_species if cls is None else false()
    not_young = or_(Detection.group_type.is_(None), Detection.group_type != split.young_type)
    unsexed = or_(Detection.sex.is_(None), Detection.sex.notin_(("male", "female")))
    where = {
        split.young: Detection.group_type == split.young_type,
        split.male: and_(not_young, Detection.sex == "male"),
        split.female: and_(not_young, Detection.sex == "female"),
        split.group: and_(unsexed, Detection.group_type == split.group_type),
        None: and_(unsexed, or_(
            Detection.group_type.is_(None),
            Detection.group_type.notin_((split.young_type, split.group_type)),
        )),
    }.get(cls)
    return false() if where is None else and_(of_species, where)


def class_keys_where(keys: str, species_id: str | None = None):
    """SQL on Detection for the classes a chip's key names (join_class_keys), of
    `species_id` only when given; nothing for a key that names none."""
    hits = []
    for key in keys.split(","):
        parsed = parse_class_key(key)
        if parsed is not None and (species_id is None or parsed[0] == species_id):
            hits.append(class_where(*parsed))
    return or_(*hits) if hits else false()


def class_label_filter(species_id: str, common_name: str | None, label: str):
    """SQL on Detection, among `species_id`'s sightings, for the ones class_label
    calls `label`, read in one language (i18n.reading_order): the reader's own first.
    In one language a label can be two classes (a boar an admin renamed "Boar" is the
    unsexed ones and the males both); two languages are never mixed."""
    from app.i18n import reading_order, use

    split = _SPLIT.get(species_id)
    asked: dict[str | None, tuple[str | None, str | None]] = {None: (None, None)}
    if split is not None:
        asked |= {split.young: (None, split.young_type), split.male: ("male", None),
                  split.female: ("female", None), split.group: (None, split.group_type)}
    for lang in reading_order():
        with use(lang):
            hits = [cls for cls, (sex, gt) in asked.items()
                    if class_label(species_id, common_name, sex, gt) == label]
        if hits:
            # Any other species is one class, its name: all of its sightings.
            if split is None:
                return true()
            return or_(*(class_where(species_id, cls) for cls in hits))
    return false()


# class_label_sql's words for a class, and the key each is said with.
_CLASS_KEYS = {
    "Stag": "class.stag", "Hind": "class.hind", "Hind + calf": "class.hind_calf",
    "Boar": "class.boar", "Sow": "class.sow", "Sow + piglets": "class.sow_piglets",
    "Sounder": "class.sounder",
}
_HERD = " (herd)"


def say_class(cls: str | None, species_id: str | None, common_name: str | None) -> str:
    """A class as class_label_sql names it in the database ("Sow + piglets", "Red
    deer (herd)", or empty for the species' own name), in the language being written
    in: what class_label says for the same visit."""
    if cls in _CLASS_KEYS:
        return t(_CLASS_KEYS[cls])
    if cls and cls.endswith(_HERD):
        return t("class.herd", name=species_name(species_id or "red_deer", common_name))
    if cls:
        return cls
    return class_label(species_id, common_name, None, None)


def sql_class_key(cls: str | None, species_id: str | None) -> str | None:
    """class_key for a class as class_label_sql names it ("Sow + piglets", "Red deer
    (herd)", or empty for the species' own name)."""
    if not species_id:
        return None
    if cls in _CLASS_KEYS:
        return f"{species_id}.{_CLASS_KEYS[cls].removeprefix('class.')}"
    if cls and cls.endswith(_HERD):
        return f"{species_id}.herd"
    return species_id


def labels_in_english(db: Session, label: str) -> set[str]:
    """What a class label the app sent back (a filter) may be, as class_label_sql
    and the English screens write it: the app shows labels in its person's language
    ("Uros", "Villisika"), the database compares English ("Stag", "Wild boar").

    Read in one language (i18n.reading_order), the reader's own first: "Hjort" from
    a Swedish reader is a stag, from a Norwegian one a red deer, never both. A label
    no language knows is compared as it came."""
    from app.i18n import reading_order, tr

    species = db.execute(select(Species.id, Species.common_name)).all()
    for lang in reading_order():
        out = {en for en, key in _CLASS_KEYS.items() if label == tr(lang, key)}
        for sid, stored in species:
            english = sentence_case(stored) if stored else None
            name = species_name(sid, stored, lang)
            if label == name and english:
                out.add(english)
            if sid == "red_deer" and label == tr(lang, "class.herd", name=name):
                out.add(f"{english or 'Red deer'}{_HERD}")
        if out:
            return out
    return {label}


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


def _tonight_conditions(now: datetime, *, night: date | None = None) -> dict:
    """Tonight's sun, moon and forecast at the sit time (conditions.py). Read through
    this name, so a test can stand in for the weather. `night`: a dawn sit's."""
    return tonight_conditions(now, night=night)


def _factors(top: dict, cond: dict) -> list[dict]:
    out = []
    unwatched = RECENT_NIGHTS - top["recent_watched"]
    if not top.get("producing", True):
        out.append({
            "text": t("tonight.factor.not_sending", n=top["nights_present"]),
            "impact": "•",
        })
    elif top["recent_watched"] < MIN_RECENT_WATCHED:
        # Not a quiet week: a week nobody could see. It neither helps nor counts against.
        if top.get("recent_unchecked"):
            text = t("tonight.factor.unchecked", n=top["recent_unchecked"])
        else:
            text = t("tonight.factor.few_watched", n=top["recent_watched"])
        out.append({"text": text, "impact": "•"})
    else:
        gap = t("tonight.factor.not_watched", n=unwatched) if unwatched else ""
        if top["recent_nights"] > 0:
            out.append({
                "text": t("tonight.factor.seen_week", species=top["species"],
                          n=top["recent_nights"], gap=gap),
                "impact": "+++" if top["recent_nights"] >= 4 else "++",
            })
        else:
            out.append({"text": t("tonight.factor.none_week", species=top["species"].lower(),
                                  gap=gap),
                        "impact": "--"})
    # Moon/weather are handled by the data-driven tonight drivers (condition_reasons),
    # so they're not hardcoded here — keeps the "why" consistent with the learned patterns.
    w = top["best_window"]
    if w is None:
        out.append({
            "text": t("tonight.factor.outside_hours", species=top["species"]),
            "impact": "•",
        })
        return out
    after = w.get("after_sunset_min")
    out.append({
        "text": (t("tonight.best_hours_from", start=w["start"], end=w["end"],
                   relative=_relative(after)) if after is not None
                 else t("tonight.best_hours", start=w["start"], end=w["end"])),
        "impact": "++",
    })
    return out


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
        why.append(t("tonight.left_out.unchecked_n", n=unchecked) if blind
                   else t("tonight.left_out.unchecked"))
    if blind:
        why.append(t("tonight.left_out.blind_n", n=blind) if unchecked
                   else t("tonight.left_out.blind"))
    return total, t("tonight.left_out", n=total, camera=top["camera"], why=", ".join(why))


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
    # The forecast first, with no database connection held while Open-Meteo answers
    # (audit K-04): the sign-in check has already taken one, and gives it back here.
    release(db)
    cond = _tonight_conditions(now)

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
                + t("tonight.alert.silent", n=days),
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

    if not forecasts:
        if species_ids:
            reason = t("tonight.none.picked")
        else:
            reason = t("tonight.none.sending") if alerts else t("tonight.none.yet")
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

    # The wind at the stand a hunter would sit for the top camera, judged as every
    # other screen judges it (conditions.wind_verdict), for the sit time.
    stand = stand_for_camera(db, uuid.UUID(top["camera_id"]))
    wind = (wind_verdict(db, stand, cond, now=now) if stand is not None
            else no_stand_verdict(top["camera"], cond, now=now))

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
        "wind": wind,
        "recommended": {
            "camera": top["camera"], "camera_id": top["camera_id"],
            "species": top["species"], "species_id": top["species_id"],
            "runner_up": top["runner_up"],
            "probability": top["probability"], "best_window": top["best_window"],
            "expect": top_classes[0]["label"] if top_classes else top["species"],
            "classes": top_classes,
            "nights_present": top["nights_present"], "active_nights": top["active_nights"],
            "visits": top["visits"], "photos": top["photos"],
            "reason": t("tonight.reason", species=top["species"], n=top["nights_present"],
                        total=top["active_nights"]),
            # The reference class belongs in the sentence, not a footnote: a bare
            # percentage reads as "my chance of a shot tonight", which is not what
            # was measured.
            "caveat": t("tonight.caveat"),
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
