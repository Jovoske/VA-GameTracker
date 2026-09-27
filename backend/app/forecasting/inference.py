"""Inferring stand geometry and exit timing from data already collected.

Two things the estate knows but nobody has written down.

**Approach arcs.** Asking someone to draw bearings on a map is the kind of setup
task that never gets done, and a stand with no arcs gets no wind advice. But the
herd states its own approach lines every time it walks past two cameras in
sequence: the bearing from the earlier camera to the later one is the direction it
came from. Seeded arcs are *proposals* — they are returned for confirmation, never
written silently, because a wrong arc produces confident wind advice, which is
worse than none.

**Dark exit.** Every app tells you when to arrive. Animals leave an estate because
somebody walked out through them at 21:30 with a head torch. The earliest hour
after the sit window when the approach corridor is historically empty is
computable from the same detection history, and it is the number that decides
whether a stand survives being sat.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.visibility import VISIBLE_SIGHTING
from app.core.config import settings
from app.models import Camera, Detection, Image, Species, Stand

# Two cameras seeing the same species within this gap is plausibly one animal
# moving between them rather than two unrelated visits.
MAX_TRAVEL_GAP = timedelta(minutes=45)
MIN_SEQUENCES = 3  # below this it is a coincidence, not a route

_TZ = settings.estate_timezone


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def suggest_approach_arcs(db: Session, stand: Stand) -> dict:
    """Propose approach bearings for a stand from cross-camera movement.

    Returns proposals with the evidence behind each, for a human to accept. Never
    writes: a guessed arc turns into confident wind advice, and confident wrong
    advice costs more trust than an honest "yours to solve".
    """
    if stand.camera_id is None:
        return {"suggestions": [], "reason": "This stand is not linked to a camera."}

    target = db.get(Camera, stand.camera_id)
    if target is None or target.lat is None or target.lon is None:
        return {"suggestions": [], "reason": "The linked camera has no position recorded."}

    others = [
        c
        for c in db.scalars(select(Camera).where(Camera.id != target.id)).all()
        if c.lat is not None and c.lon is not None
    ]
    if not others:
        return {"suggestions": [], "reason": "No other positioned cameras to infer movement from."}

    # Detections at the target camera, and at every other camera, by species/time.
    rows = db.execute(
        select(Image.camera_id, Detection.species_id, Image.captured_at)
        .join(Detection, Detection.image_id == Image.id)
        .join(Species, Species.id == Detection.species_id)
        .where(VISIBLE_SIGHTING)
        .order_by(Image.captured_at)
    ).all()

    by_species: dict = {}
    for cam_id, species_id, at in rows:
        by_species.setdefault(species_id, []).append((at, cam_id))

    tally: dict = {}
    for events in by_species.values():
        for i in range(1, len(events)):
            prev_at, prev_cam = events[i - 1]
            at, cam = events[i]
            # We want arrivals AT this stand's camera, from somewhere else.
            if cam != target.id or prev_cam == target.id:
                continue
            if at - prev_at > MAX_TRAVEL_GAP:
                continue
            source = next((c for c in others if c.id == prev_cam), None)
            if source is None:
                continue
            # Bearing FROM the target TO where the animal came from: the direction
            # it approached from, which is what the wind check needs.
            b = bearing(target.lat, target.lon, source.lat, source.lon)
            key = source.name
            entry = tally.setdefault(key, {"bearing": b, "count": 0})
            entry["count"] += 1

    suggestions = [
        {
            "from_camera": name,
            "approach_deg": round(v["bearing"]),
            "sequences": v["count"],
            "note": (
                f"{v['count']} times, animals reached {target.name} within "
                f"{int(MAX_TRAVEL_GAP.total_seconds() // 60)} min of passing {name}."
            ),
        }
        for name, v in sorted(tally.items(), key=lambda kv: -kv[1]["count"])
        if v["count"] >= MIN_SEQUENCES
    ]

    return {
        "suggestions": suggestions,
        "reason": None
        if suggestions
        else (
            "No repeated movement between cameras yet — not enough to propose an "
            "approach line, so the app will keep saying this one is yours to solve."
        ),
    }


# A normal evening sit ends about this long after sunset: 23:00 in late September,
# 21:00 in November. The walk out is looked for from here.
SIT_ENDS_AFTER_SUNSET = timedelta(hours=3)
# How far back the dark exit reads: the season.
EXIT_HISTORY_NIGHTS = 365


def dark_exit(db: Session, stand: Stand, *, after: timedelta = SIT_ENDS_AFTER_SUNSET) -> dict:
    """Earliest hour after the sit when this stand's ground is historically empty.

    Stands die from how you leave them, not how you arrive. This is the hour at
    which walking out is least likely to push animals off the estate.

    Counted in visits (arrivals), placed by the minutes after their own night's
    sunset and put back on tonight's clock with tonight's sunset, as best hours are:
    a fixed clock hour drifts an hour at the clock change and two over the season
    (audit J-08).
    """
    from app.forecasting.exposure import current_night, night_key_start
    from app.forecasting.model import _sunset
    from app.forecasting.visits import visit_rows

    if stand.camera_id is None:
        return {"hour": None, "reason": "This stand is not linked to a camera."}

    tonight = current_night()
    v = visit_rows(start=night_key_start(tonight - timedelta(days=EXIT_HISTORY_NIGHTS)),
                   end=night_key_start(tonight), camera_ids=[stand.camera_id])
    offsets = []
    for night, first_at in db.execute(select(v.c.night, v.c.first_at)).all():
        sunset = _sunset(night)
        if sunset is not None:
            offsets.append((first_at - sunset).total_seconds() / 60)
    sunset = _sunset(tonight)
    if not offsets or sunset is None:
        return {"hour": None, "reason": "No visits at this stand's camera yet."}

    total = len(offsets)
    start_min = after.total_seconds() / 60

    def share(k: int) -> float:
        lo = start_min + k * 60
        return sum(1 for o in offsets if lo <= o < lo + 60) / total

    def on_clock(k: int):
        at = sunset + after + timedelta(hours=k)
        # A quarter hour on the clock reads better than 22:56 and is as true.
        return datetime.fromtimestamp(round(at.timestamp() / 900) * 900, tz=UTC).astimezone(
            ZoneInfo(_TZ))

    # Walk forward from the end of a normal sit and take the first quiet hour, up to
    # 06:00: a visit after that is the next night's, so the hours past it would look
    # quiet whatever walked there.
    night_ends = datetime.combine(tonight + timedelta(days=1), time(6), tzinfo=ZoneInfo(_TZ))
    hours = [k for k in range(8) if sunset + after + timedelta(hours=k + 1) <= night_ends] or [0]
    for k in hours:
        if share(k) <= 0.02:
            at = on_clock(k)
            return {
                "hour": at.hour, "time": at.strftime("%H:%M"),
                "share_pct": round(share(k) * 100, 1),
                "reason": None,
                "text": (
                    f"Dark exit {at:%H:%M} — only {round(share(k) * 100)}% of this camera's "
                    "visits fall in the hour after, so walking out then disturbs least."
                ),
            }

    quietest = on_clock(min(hours, key=share))
    return {
        "hour": quietest.hour, "time": quietest.strftime("%H:%M"),
        "reason": "No genuinely quiet hour — this stand is busy all night.",
        "text": (
            f"No quiet hour after {on_clock(0):%H:%M} at this stand — it is busy all night. "
            f"{quietest:%H:%M} is the least-bad exit."
        ),
    }
