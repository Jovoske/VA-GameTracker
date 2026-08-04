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

from datetime import date, datetime, timedelta

from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import Camera, CameraNight, Detection, Image

log = get_logger(__name__)

_TZ = settings.estate_timezone

# A "night" is keyed by its EVENING date: 18:00 D through 06:00 D+1. Shifting the
# local timestamp back 6h before taking the date puts post-midnight activity on the
# night it belongs to — the same key the overnight weather aggregation uses.
NIGHT_SHIFT = text("interval '6 hours'")

# Gap after which the same species at the same camera counts as a new arrival.
# 30 minutes is the common camera-trap convention for independence; it is a
# convention, not a measurement, so it is named here rather than buried.
VISIT_GAP = timedelta(minutes=30)

# How far back from the end of an exhausted billing cycle to treat nights as
# known-blind. Conservative: better to exclude a few real nights than to record a
# throttled camera's silence as an observation of absence.
CREDIT_BLIND_DAYS = 7


def night_expr(col=Image.captured_at):
    """SQL expression for the night an image belongs to."""
    return func.date(func.timezone(_TZ, col) - NIGHT_SHIFT)


def local_hour(col=Image.captured_at):
    return cast(func.extract("hour", func.timezone(_TZ, col)), Integer)


# ── exposure ────────────────────────────────────────────────────────────────


def recompute_camera_nights(db: Session, *, camera_id=None) -> dict:
    """Rebuild the exposure table. Idempotent — safe to run as often as you like."""
    cameras = db.scalars(
        select(Camera).where(Camera.id == camera_id) if camera_id else select(Camera)
    ).all()

    totals: dict[str, int] = {}
    for cam in cameras:
        for state, count in _recompute_one(db, cam).items():
            totals[state] = totals.get(state, 0) + count
    db.commit()
    log.info("exposure.recomputed", cameras=len(cameras), **totals)
    return totals


def _recompute_one(db: Session, cam: Camera) -> dict[str, int]:
    night = night_expr()
    rows = db.execute(
        select(
            night.label("night"),
            func.count(Image.id).label("frames"),
            func.count(Image.id).filter(Image.is_empty_frame.is_(True)).label("empty"),
            func.count(Image.id).filter(Image.processed_at.is_(None)).label("unprocessed"),
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
            # No frames at all. If the camera produced frames on both sides it was
            # almost certainly up and simply saw nothing — a real zero. Otherwise we
            # genuinely do not know, and guessing is what caused the original bug.
            has_before = any(n < cur for n in observed)
            has_after = any(n > cur for n in observed)
            state = "PRESUMED_UP" if (has_before and has_after) else "UNKNOWN"
            states[cur] = (state, 0, 0)
        elif row.unprocessed:
            # Frames exist but the detector has not seen them. Counting this as
            # "no animals" is the backlog artefact; it is not an observation yet.
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


def visits_by_night(db: Session, *, camera_id=None, species_id=None) -> dict:
    """{(night, camera_id, species_id): {frames, visits, animals}}

    A visit is an arrival: consecutive detections of the same species at the same
    camera separated by more than VISIT_GAP. `animals` uses group_size, which the
    pipeline already computes per frame and which nothing has ever used.
    """
    gap_seconds = int(VISIT_GAP.total_seconds())
    where = ["1=1"]
    params: dict = {"gap": gap_seconds, "tz": _TZ}
    if camera_id:
        where.append("i.camera_id = :camera_id")
        params["camera_id"] = camera_id
    if species_id:
        where.append("d.species_id = :species_id")
        params["species_id"] = species_id

    sql = text(
        f"""
        WITH ordered AS (
            SELECT
                i.camera_id,
                d.species_id,
                i.captured_at,
                COALESCE(d.group_size, 1) AS group_size,
                date(timezone(:tz, i.captured_at) - interval '6 hours') AS night,
                LAG(i.captured_at) OVER (
                    PARTITION BY i.camera_id, d.species_id ORDER BY i.captured_at
                ) AS prev_at
            FROM detections d
            JOIN images i ON i.id = d.image_id
            WHERE {' AND '.join(where)}
        ), marked AS (
            SELECT *,
                CASE
                    WHEN prev_at IS NULL
                      OR EXTRACT(EPOCH FROM (captured_at - prev_at)) > :gap
                    THEN 1 ELSE 0
                END AS is_new_visit
            FROM ordered
        )
        SELECT night, camera_id, species_id,
               COUNT(*)                AS frames,
               SUM(is_new_visit)       AS visits,
               MAX(group_size)         AS animals
        FROM marked
        GROUP BY night, camera_id, species_id
        """
    )
    out: dict = {}
    for r in db.execute(sql, params).all():
        out[(r.night, r.camera_id, r.species_id)] = {
            "frames": int(r.frames),
            "visits": int(r.visits or 0),
            # Largest group seen that night, not a sum: the same sounder returning
            # three times is not thirty-six boar.
            "animals": int(r.animals or 0),
        }
    return out
