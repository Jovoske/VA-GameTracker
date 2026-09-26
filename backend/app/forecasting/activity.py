"""Where the game is, and what happened on one night: the map's two views of visits.

**Activity.** A circle at each camera, sized by visits per night the camera was
watching. A night it wasn't working is left out rather than counted as a quiet one:
a flat battery is not "the boar left". Which nights count comes from camera_nights,
and where that table hasn't caught up yet (it is rebuilt hourly, so at 06:30 last
night's row can be missing or still say UNPROCESSED) from the frames themselves, the
same judgement the camera sheet makes. A night the camera ran out of photo credits
never counts: what it did send is not a fair sample.

**Replay.** The visits of one night in order, and a guess at where the animals went:
when the same species turns up at another camera within three hours, and could have
walked there in the time, the two visits are linked. The map labels that a guess.

Both count visits from visits.list_visits, so their numbers agree with each other
and with the camera sheet.

**Last night.** The app's new day starts at 06:00, but the map's night runs on to
08:00, so from 06:00 to 08:00 "last night" is still going. It is shown anyway, marked
`so_far`: that is when the team first looks at what came past, and last night so far
says more than the night before it.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.forecasting.visits import (
    PARTS,
    in_map_night,
    list_visits,
    map_night_expr,
    map_night_of,
    map_night_window,
    part_hours,
)
from app.models import Camera, CameraNight, Image

WATCHED = ("CONFIRMED", "PRESUMED_UP")
# The same species at another camera within this long may be the same animals.
LINK_WINDOW = timedelta(hours=3)
# ...but only if they could have got there: a boar trots, it doesn't teleport. Two
# sounders seen ten minutes apart at cameras two kilometres apart are two sounders.
LINK_MAX_KMH = 15.0
# "Mostly 21-23 h" needs more than half the visits in those two hours, "busiest
# 21-23 h" at least a third of them (evenly spread over the night, two hours would
# hold a seventh). Below that there is no set time to name.
MOSTLY_SHARE = 0.5
BUSY_SHARE = 1 / 3
# Up to this many visits, their times say more than any window.
LIST_TIMES = 3
PART_WORDS = {
    "dusk": "at dusk", "night": "in the middle of the night", "dawn": "at dawn", "all": "",
}


def _local(at: datetime) -> datetime:
    return at.astimezone(ZoneInfo(settings.estate_timezone))


def still_running(night: date, now: datetime | None = None) -> bool:
    """Whether the map's night of `night` hasn't reached 08:00 yet."""
    return (now or datetime.now(UTC)) < map_night_window(night)[1]


def peak_window(hours: list[int], part: str) -> tuple[str | None, float]:
    """The two-hour window with the most visits ('21–23'), and its share of them.

    `hours` are the local hours the visits began. Windows run in night order, so
    '23–01' is a window. Of two windows as busy, the one that starts on a busy hour
    wins (visits at 21:10 and 21:50 are '21–23', not '20–22'), then the earlier.
    """
    if not hours:
        return None, 0.0
    counts = Counter(hours)
    order = part_hours(part)
    best, score = order[0], (-1, -1)
    for first, second in zip(order, order[1:], strict=False):
        this = (counts[first] + counts[second], counts[first])
        if this > score:
            best, score = first, this
    return f"{best:02d}–{(best + 2) % 24:02d}", score[0] / len(hours)


# ── which nights count ──────────────────────────────────────────────────────


def watched_nights(db: Session, camera_ids: list, nights: list[date]) -> dict:
    """{camera_id: {night: 'watched' | 'checking' | 'blind'}} for each night.

    watched   camera_nights says it was working, or, where that table has no word
              yet, it sent frames that night and the detector has checked them all
    checking  frames from that night are still waiting for the detector, so its
              visits aren't all known yet
    blind     it wasn't working, ran out of photo credits, or nothing says either way
    """
    if not camera_ids or not nights:
        return {}
    states = {
        (r.camera_id, r.night): r.exposure_state
        for r in db.execute(
            select(CameraNight.camera_id, CameraNight.night, CameraNight.exposure_state).where(
                CameraNight.camera_id.in_(camera_ids),
                CameraNight.night.in_(nights),
            )
        ).all()
    }
    start, end = map_night_window(min(nights))[0], map_night_window(max(nights))[1]
    unchecked = and_(Image.is_empty_frame.is_(None), Image.original_path.isnot(None))
    night = map_night_expr()
    sent = {
        (r[0], r[1]): (int(r[2]), int(r[3]))
        for r in db.execute(
            select(
                Image.camera_id, night, func.count(Image.id),
                func.count(Image.id).filter(unchecked),
            )
            .where(
                Image.camera_id.in_(camera_ids), Image.captured_at >= start,
                Image.captured_at < end, in_map_night(),
            )
            .group_by(Image.camera_id, night)
        ).all()
    }
    out: dict = {}
    for cam in camera_ids:
        per: dict = {}
        for n in nights:
            state = states.get((cam, n))
            frames, waiting = sent.get((cam, n), (0, 0))
            if waiting:
                per[n] = "checking"
            elif state in WATCHED:
                per[n] = "watched"
            elif state is None or state == "UNPROCESSED":
                # The hourly rebuild hasn't caught up: checked frames prove it was awake.
                per[n] = "watched" if frames else "blind"
            else:
                per[n] = "blind"
        out[cam] = per
    return out


# ── the activity map ────────────────────────────────────────────────────────


def activity_read(*, who: str, visits: int, watched: int, nights: int, nights_with: int,
                  blind: int, checking: int, part: str, peak: str | None, share: float,
                  times: list[datetime], so_far: bool = False) -> str:
    """The one line the card leads with: "Wild boar on 5 of 7 nights, mostly 21–23 h".

    `who` is the species ("Wild boar") or "Animals" for all of them. The count of
    nights is the nights that counted; when that is fewer than the period, it says
    why ("it was working", "checked so far"), so 3 of 5 never reads as 3 of 7.
    A few visits are given by their times, which say more than a window. `so_far`:
    last night hasn't reached 08:00 yet, and the one-night read says so.
    """
    when = PART_WORDS[part]
    # Mid-sentence: "No roe deer", not the stored "Roe Deer".
    lower = who.lower()
    if not watched:
        if checking:
            return ("Still checking last night’s photos." if nights == 1
                    else "Still checking the photos.")
        return ("Not counted: the camera may not have been working last night." if nights == 1
                else "Not counted: the camera wasn’t working on these nights.")
    tail = ""
    if 0 < len(times) <= LIST_TIMES:
        # In the order of the night: 23:10 comes before 02:15.
        local = sorted((_local(t) for t in times), key=lambda t: (t.hour < 12, t.time()))
        clocks = [f"{t:%H:%M}" for t in local]
        tail = ", at " + (", ".join(clocks[:-1]) + " and " if len(clocks) > 1 else "") + clocks[-1]
    elif peak:
        tail = f", {'mostly' if share > MOSTLY_SHARE else 'busiest'} {peak} h"
    elif visits > 1:
        tail = ", at no set time"
    if nights == 1:
        night = "last night so far" if so_far else "last night"
        if not visits:
            nothing = "Nothing on camera" if who == "Animals" else f"No {lower}"
            return f"{nothing}{' ' + when if when else ''} {night}."
        noun = "animal" if who == "Animals" else lower
        plural = "" if visits == 1 else "s"
        return f"{visits} {noun} visit{plural}{' ' + when if when else ''} {night}{tail}"
    qualifier = " it was working" if blind else " checked so far" if checking else ""
    if not visits:
        none = "No animals" if who == "Animals" else f"No {lower}"
        return f"{none}{' ' + when if when else ''} on the {watched} nights{qualifier}."
    return f"{who} on {nights_with} of {watched} nights{qualifier}{tail}"


def activity(db: Session, *, cameras: list[Camera], last_night: date, nights: int, part: str,
             species: str | None = None, species_label: str | None = None,
             now: datetime | None = None) -> dict:
    """Per camera: visits per watched night over the last `nights`, and a one-line read.

    `species` None is every species, and `species_label` is the chosen one's name
    ("Wild boar"). `part` is a key of visits.PARTS. Only visits on nights the camera
    was watching count, so visits / watched_nights is honest. `species_options` are
    the named species seen in the period whatever the filters, busiest first, for
    the filter chips. `so_far` is true while the last night hasn't reached 08:00.
    """
    period = [last_night - timedelta(days=i) for i in range(nights - 1, -1, -1)]
    so_far = still_running(last_night, now)
    ids = [c.id for c in cameras]
    start, end = map_night_window(period[0])[0], map_night_window(period[-1])[1]
    visits = list_visits(db, start=start, end=end, camera_ids=ids) if ids else []
    watched = watched_nights(db, ids, period)
    hours = set(part_hours(part))

    seen: Counter = Counter()
    labels: dict = {}
    for v in visits:
        # Never None: list_visits reads no daytime frames.
        v["map_night"] = map_night_of(v["first_at"])
        v["hour"] = _local(v["first_at"]).hour
        if v["species_id"] and v["map_night"] is not None:
            seen[v["species_id"]] += 1
            labels[v["species_id"]] = v["label"]
    who = (species_label or labels.get(species) or species) if species else "Animals"

    out = []
    for cam in cameras:
        state = watched.get(cam.id, {})
        counted = {n for n, s in state.items() if s == "watched"}
        mine = [
            v for v in visits
            if v["camera_id"] == cam.id and v["map_night"] in counted and v["hour"] in hours
            and (species is None or v["species_id"] == species)
        ]
        by_species: Counter = Counter(v["species_id"] for v in mine)
        names = {v["species_id"]: v["label"] for v in mine}
        nights_with = len({v["map_night"] for v in mine})
        peak, share = peak_window([v["hour"] for v in mine], part)
        peak = peak if len(mine) > 1 and share >= BUSY_SHARE else None
        blind = sum(1 for s in state.values() if s == "blind")
        checking = sum(1 for s in state.values() if s == "checking")
        out.append({
            "camera_id": str(cam.id),
            "name": cam.name,
            "lat": cam.lat,
            "lon": cam.lon,
            "visits": len(mine),
            "watched_nights": len(counted),
            "blind_nights": blind,
            "checking_nights": checking,
            "nights_with": nights_with,
            "per_night": round(len(mine) / len(counted), 2) if counted else None,
            "peak": peak,
            "by_species": [
                {"species_id": sid, "label": names[sid], "visits": n}
                # Busiest first, and an animal nobody has named after the named ones.
                for sid, n in sorted(
                    by_species.items(), key=lambda kv: (-kv[1], kv[0] is None, names[kv[0]]),
                )
            ],
            "read": activity_read(
                who=who, visits=len(mine), watched=len(counted), nights=nights,
                nights_with=nights_with, blind=blind, checking=checking, part=part, peak=peak,
                share=share, times=[v["first_at"] for v in mine], so_far=so_far,
            ),
        })
    return {
        "nights": nights,
        "part": part,
        "hours": list(PARTS[part]),
        "species": species or "all",
        "species_label": who if species else None,
        "first_night": period[0].isoformat(),
        "last_night": period[-1].isoformat(),
        "so_far": so_far,
        "species_options": [
            {"species_id": sid, "label": labels[sid], "visits": n}
            for sid, n in sorted(seen.items(), key=lambda kv: (-kv[1], labels[kv[0]]))
        ],
        "cameras": out,
    }


# ── replaying a night ───────────────────────────────────────────────────────


def _km(a: Camera, b: Camera) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def likely_paths(visits: list[dict], cameras: dict) -> list[dict]:
    """Consecutive visits of the same species at two different cameras, joined.

    For each named species, in time order: a visit and the next one of that species
    are linked when they are at different cameras, both on the map, the second
    began after the first ended and within LINK_WINDOW of it, and the animals could
    have covered the distance at LINK_MAX_KMH. A visit at the same camera breaks
    the chain: the next link starts from there. Unnamed animals are never linked.
    """
    links = []
    by_species: dict = defaultdict(list)
    for v in visits:
        if v["species_id"]:
            by_species[v["species_id"]].append(v)
    for sid, seq in by_species.items():
        seq.sort(key=lambda v: (v["first_at"], str(v["camera_id"])))
        for a, b in zip(seq, seq[1:], strict=False):
            if a["camera_id"] == b["camera_id"]:
                continue
            ca, cb = cameras.get(a["camera_id"]), cameras.get(b["camera_id"])
            if not ca or not cb or None in (ca.lat, ca.lon, cb.lat, cb.lon):
                continue
            gap = b["first_at"] - a["last_at"]
            if gap <= timedelta(0) or gap > LINK_WINDOW:
                continue
            if _km(ca, cb) / (gap.total_seconds() / 3600) > LINK_MAX_KMH:
                continue
            links.append({
                "from_camera_id": str(a["camera_id"]),
                "to_camera_id": str(b["camera_id"]),
                "species_id": sid,
                "label": b["label"],
                "from_at": a["last_at"],
                "to_at": b["first_at"],
            })
    links.sort(key=lambda link: link["to_at"])
    return links


def replay(db: Session, *, cameras: list[Camera], night: date) -> dict:
    """One night's visits in order, 18:00 to 08:00, and the likely paths between them."""
    start, end = map_night_window(night)
    ids = [c.id for c in cameras]
    visits = list_visits(db, start=start, end=end, camera_ids=ids) if ids else []
    return {
        "night": night.isoformat(),
        "start": start,
        "end": end,
        "visits": [
            {
                "at": v["first_at"],
                "last_at": v["last_at"],
                "camera_id": str(v["camera_id"]),
                "species_id": v["species_id"],
                "label": v["label"],
                "group_size": v["max_group"],
                "frames": v["frames"],
                "image_id": str(v["image_id"]),
            }
            for v in visits
        ],
        "links": likely_paths(visits, {c.id: c for c in cameras}),
    }


def replay_nights(db: Session, *, cameras: list[Camera], last_night: date,
                  limit: int, now: datetime | None = None) -> list[dict]:
    """The last `limit` nights, newest first, with how many visits each had.

    Each has `so_far`, true for a night that hasn't reached 08:00 yet (only last
    night, and only from 06:00 to 08:00): its count is still growing.
    """
    ids = [c.id for c in cameras]
    first = last_night - timedelta(days=limit - 1)
    counts: Counter = Counter()
    if ids:
        start, end = map_night_window(first)[0], map_night_window(last_night)[1]
        for v in list_visits(db, start=start, end=end, camera_ids=ids):
            night = map_night_of(v["first_at"])
            if night is not None:
                counts[night] += 1
    nights = [last_night - timedelta(days=i) for i in range(limit)]
    return [
        {"night": n.isoformat(), "visits": counts[n], "so_far": still_running(n, now)}
        for n in nights
    ]

