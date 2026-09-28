"""Camera exposure and independent visits — the denominator and the unit of count.

Two things in this module fix the arithmetic underneath every statistic in the app.

**Exposure.** A night with no detections is not evidence of no animals unless the
camera was demonstrably awake. Flat batteries, lost signal, a full card, a knocked
camera, a web across the lens and an unprocessed classification backlog all produce
exactly zero detections. The old code walked the calendar imputing 0 for every one
of them, so a battery curve became a moon-phase finding. Here, a night only counts
if we can show the camera was watching, and a night we cannot vouch for is excluded
and *reported as excluded* rather than silently averaged in.

Empty frames are the evidence. Each one proves the camera was awake, aimed and
triggering at a known second — which is why the pipeline's discarded output is the
most valuable liveness signal in the system.

**Visits.** `species.py` writes one Detection row per *image*, so counting rows
measures burst settings and how long an animal loitered in front of a PIR sensor: a
single boar over thirty frames counts thirty, while a herd of twelve in one frame
counts one. Collapsing to visits (same camera, same species, gap > VISIT_GAP)
counts arrivals instead, and `group_size` recovers the herd.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, cast, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import Camera, CameraNight, Image

log = get_logger(__name__)

_TZ = settings.estate_timezone

# A "night" is keyed by its EVENING date. Shifting the local timestamp back 6h before
# taking the date puts post-midnight activity on the night it belongs to — the same
# key the overnight weather aggregation uses. The key itself runs 06:00 D to 06:00
# D+1, so it files the day under the evening after it; what a hunter reads as the
# night is 18:00 D through 06:00 D+1 (in_night), and every statistic reads only
# frames inside it: the Changed line, Tonight, Insights and the track record count
# the same visits on the same night.
NIGHT_SHIFT = text("interval '6 hours'")
NIGHT_START_HOUR, NIGHT_END_HOUR = 18, 6

# Gap after which the same species at the same camera counts as a new arrival.
# 30 minutes is the common camera-trap convention for independence; it is a
# convention, not a measurement, so it is named here rather than buried.
VISIT_GAP = timedelta(minutes=30)

# How far back from the end of an exhausted billing cycle to treat nights as
# known-blind. Conservative: better to exclude a few real nights than to record a
# throttled camera's silence as an observation of absence.
CREDIT_BLIND_DAYS = 7

# The longest run of frameless nights still presumed watched, with frames on the
# nights either side. A live camera fires on wind and sun most days, so a longer
# silence is a flat battery, a full card or a wrong clock, and counting it as
# "watched, saw nothing" is how a dead week became a run of empty nights.
MAX_PRESUMED_GAP_NIGHTS = 2


def night_expr(col=Image.captured_at):
    """SQL expression for the night an image belongs to."""
    return func.date(func.timezone(_TZ, col) - NIGHT_SHIFT)


def in_night(col=Image.captured_at):
    """SQL: whether a moment is inside a night (18:00-06:00 local), the stretch the
    statistics count. A morning roe deer at 07:30 or a fox at noon is a real photo,
    but it is not a night's visit: night_expr would file it under the evening after
    it, and the track record (scoring.night_window) never grades it."""
    hour = func.extract("hour", func.timezone(_TZ, col))
    return or_(hour >= NIGHT_START_HOUR, hour < NIGHT_END_HOUR)


def current_night(now: datetime | None = None) -> date:
    """The night key of `now`: before 06:00 it is still last evening's night.

    Nights before this one are over; this one is still to come, or under way. Never
    date.today(): the server's clock need not be on Madrid time, and between midnight
    and 06:00 the calendar date is already the next night.
    """
    now = now or datetime.now(UTC)
    return (now.astimezone(ZoneInfo(_TZ)) - timedelta(hours=6)).date()


def night_key_start(night: date) -> datetime:
    """The first moment night_expr puts on `night`: 06:00 local that morning."""
    return datetime.combine(night, time(6), tzinfo=ZoneInfo(_TZ))


def local_hour(col=Image.captured_at):
    return cast(func.extract("hour", func.timezone(_TZ, col)), Integer)


# ── exposure ────────────────────────────────────────────────────────────────


def recompute_camera_nights(db: Session, *, camera_id=None) -> dict:
    """Rebuild the exposure table. Idempotent — safe to run as often as you like."""
    # A retired camera is left out of everything that reads this table, so the
    # routine rebuild skips it; asked for by name (a hidden photo), it is rebuilt.
    cameras = db.scalars(
        select(Camera).where(Camera.id == camera_id) if camera_id
        else select(Camera).where(Camera.retired_at.is_(None))
    ).all()

    totals: dict[str, int] = {}
    for cam in cameras:
        for state, count in _recompute_one(db, cam).items():
            totals[state] = totals.get(state, 0) + count
    db.commit()
    log.info("exposure.recomputed", cameras=len(cameras), **totals)
    return totals


def _recompute_one(db: Session, cam: Camera) -> dict[str, int]:
    # Not checked: waiting for the detector or the species model, or given up on after
    # failing. A model failure used to be stored as "checked, nothing named", so a
    # broken AI read as nights watched with no animals in them.
    from app.ai.checking import NOT_CHECKED

    night = night_expr()
    rows = db.execute(
        select(
            night.label("night"),
            func.count(Image.id).label("frames"),
            func.count(Image.id).filter(Image.is_empty_frame.is_(True)).label("empty"),
            func.count(Image.id).filter(NOT_CHECKED).label("unprocessed"),
        )
        .where(Image.camera_id == cam.id)
        .group_by(night)
        .order_by(night)
    ).all()
    if not rows:
        return {}

    by_night = {r.night: r for r in rows}
    first, last = rows[0].night, rows[-1].night
    observed = sorted(by_night)
    tonight = current_night()

    # SPYPOINT reports each camera's photo-credit usage and billing cycle. A camera
    # that hit its monthly limit stopped *sending*, not necessarily stopped seeing —
    # so nights inside an exhausted cycle are known-blind rather than known-empty.
    # This is telemetry we could not infer from the frame stream alone.
    exhausted_from: date | None = None
    if (
        cam.photo_count is not None
        and cam.photo_limit
        and cam.photo_count >= cam.photo_limit
    ):
        # Credits are consumed over the cycle; treat the tail of it as suspect.
        exhausted_from = (
            (cam.cycle_end.date() - timedelta(days=CREDIT_BLIND_DAYS))
            if cam.cycle_end
            else (last - timedelta(days=CREDIT_BLIND_DAYS))
        )

    states: dict[date, tuple[str, int, int]] = {}
    cur = first
    while cur <= last:
        row = by_night.get(cur)
        out_of_credits = exhausted_from is not None and cur >= exhausted_from
        if row is None:
            # No frames at all. A night or two without frames between nights with
            # frames is a camera that was up and simply saw nothing — a real zero.
            # Otherwise we genuinely do not know, and guessing is what caused the
            # original bug: a flat battery for a fortnight, or one frame from a reset
            # camera clock, would make weeks or years of "watched, saw nothing". Never
            # for a night that is not over yet (a clock running ahead).
            at = bisect_left(observed, cur)
            before = observed[at - 1] if at > 0 else None
            after = observed[at] if at < len(observed) else None
            presumed = (
                before is not None and after is not None
                and (after - before).days - 1 <= MAX_PRESUMED_GAP_NIGHTS and cur < tonight
            )
            states[cur] = ("PRESUMED_UP" if presumed else "UNKNOWN", 0, 0)
        elif row.unprocessed:
            # Frames exist but the AI has not seen them, or could not. Counting this
            # as "no animals" is the backlog artefact; it is not an observation yet.
            states[cur] = ("UNPROCESSED", int(row.frames), int(row.empty))
        elif out_of_credits:
            # SPYPOINT telemetry says this camera hit its monthly photo limit and
            # stopped sending. It may well have been triggered by animals it could
            # not transmit, so the few frames we did get are not a fair sample of
            # the night. Known-blind, not known-empty.
            states[cur] = ("UNKNOWN", int(row.frames), int(row.empty))
        else:
            states[cur] = ("CONFIRMED", int(row.frames), int(row.empty))
        cur += timedelta(days=1)

    existing = {
        cn.night: cn
        for cn in db.scalars(select(CameraNight).where(CameraNight.camera_id == cam.id)).all()
    }
    tally: dict[str, int] = {}
    for night_date, (state, frames, empty) in states.items():
        tally[state] = tally.get(state, 0) + 1
        row = existing.get(night_date)
        if row is None:
            db.add(
                CameraNight(
                    camera_id=cam.id, night=night_date, exposure_state=state,
                    frames=frames, empty_frames=empty,
                )
            )
        else:
            row.exposure_state, row.frames, row.empty_frames = state, frames, empty
            row.computed_at = datetime.now(tz=None).astimezone()
    return tally


def observed_nights(db: Session, camera_id) -> int:
    """Nights this camera can be judged on. The honest denominator."""
    return int(
        db.scalar(
            select(func.count(CameraNight.id)).where(
                CameraNight.camera_id == camera_id,
                CameraNight.exposure_state.in_(("CONFIRMED", "PRESUMED_UP")),
            )
        )
        or 0
    )


def excluded_nights(db: Session, camera_id=None) -> int:
    """Nights deliberately not counted. Surfaced to the user, never hidden."""
    q = select(func.count(CameraNight.id)).where(
        CameraNight.exposure_state.in_(("UNKNOWN", "UNPROCESSED"))
    )
    if camera_id:
        q = q.where(CameraNight.camera_id == camera_id)
    return int(db.scalar(q) or 0)


# ── independent visits ──────────────────────────────────────────────────────


def visits_by_night(db: Session, *, camera_id=None, species_id=None,
                    start: datetime | None = None, end: datetime | None = None) -> dict:
    """{(night, camera_id, species_id): {frames, visits, animals}}

    A visit is an arrival: consecutive detections of the same species at the same
    camera separated by more than VISIT_GAP. The visits themselves come from
    visits.visit_rows, the rule every map view counts with, so this agrees with
    them: only checked animal photos, never a hidden species, and a kept photo
    nobody has named is an unnamed (None) visit. A visit belongs to the night of its
    first frame. `animals` uses group_size, which the pipeline already computes per
    frame and which nothing has ever used.

    Only frames inside the nights (in_night, 18:00-06:00) count, and only those in
    [start, end). Without a range this is every photo ever taken, which grows with
    the archive: a caller that wants a month should start a whole night before the
    first night it keeps (night_key_start of that night before), so a visit already
    under way is counted on its own night, not cut in two at `start`.
    """
    # Imported here: visits reads VISIT_GAP and night_expr from this module.
    from app.forecasting.visits import visit_rows

    v = visit_rows(start=start, end=end, camera_ids=[camera_id] if camera_id else None,
                   species_id=species_id, nights=True)
    rows = db.execute(
        select(
            v.c.night, v.c.camera_id, v.c.species_id,
            func.sum(v.c.frames).label("frames"),
            func.count().label("visits"),
            func.max(v.c.max_group).label("animals"),
        ).group_by(v.c.night, v.c.camera_id, v.c.species_id)
    ).all()
    out: dict = {}
    for r in rows:
        out[(r.night, r.camera_id, r.species_id)] = {
            "frames": int(r.frames),
            "visits": int(r.visits or 0),
            # Largest group seen that night, not a sum: the same sounder returning
            # three times is not thirty-six boar.
            "animals": int(r.animals or 0),
        }
    return out
