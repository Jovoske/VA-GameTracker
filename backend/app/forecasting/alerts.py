"""Alerts — notable events worth surfacing: recent sightings of the animals that
matter, a flat battery, and a usually-busy camera gone quiet.

This is the in-app feed on Tonight, recomputed on every read, so it is kept cheap:
it never works out the plan again (the plan and its "Cameras not sending" card come
from the forecast, which Tonight already has). Push to phones lives in
app.notifications: it announces new sightings per species as they are classified,
filtered by what each person asked to hear about.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.forecasting.exposure import current_night, night_key_start
from app.forecasting.model import sentence_case
from app.models import Camera, CameraNight, Species

# A camera with at least this many visits in the last month is "usually busy", and
# this many watched nights in a row without one is worth a look.
QUIET_USUAL_VISITS = 15
QUIET_NIGHTS = 3
QUIET_LOOKBACK = 30


def _ago(dt: datetime | None, now: datetime) -> str:
    if dt is None:
        return "unknown"
    if (now - dt).total_seconds() < 60:
        return "just now"
    return _dur(dt, now) + " ago"


def _dur(dt: datetime, now: datetime) -> str:
    """Bare duration ("9d", "5h", "32m") for phrases like 'quiet for 9d'.

    Never below nothing: a camera whose clock runs ahead (left on summer time after
    the clocks go back) stamps photos in the future, which read "-40m ago" (G-23)."""
    s = max(0.0, (now - dt).total_seconds())
    if s < 3600:
        return f"{int(s // 60)}m"
    if s < 86400:
        return f"{int(s // 3600)}h"
    return f"{int(s // 86400)}d"


def compute_alerts(db: Session) -> list[dict]:
    from app.forecasting.visits import visit_rows

    now = datetime.now(timezone.utc)
    alerts: list[dict] = []
    # A retired camera is in a drawer: nothing it did or didn't see is news.
    cams = db.scalars(select(Camera).where(Camera.retired_at.is_(None))).all()
    cam_ids = [c.id for c in cams]

    # 1. Recent sightings of the animals marked as the ones that matter (last 48h),
    # in visits: a boar that sat in front of the camera for twenty minutes came once.
    # Hidden species and photos marked "nothing in it" are not sightings.
    v = visit_rows(start=now - timedelta(hours=48), camera_ids=cam_ids)
    rows = db.execute(
        select(Species.common_name, func.count(), func.max(v.c.last_at))
        .select_from(v)
        .join(Species, Species.id == v.c.species_id)
        .where(Species.is_priority.is_(True), Species.hidden.is_(False))
        .group_by(Species.common_name)
        .order_by(func.count().desc(), Species.common_name)
    ).all()
    for name, cnt, last in rows[:4]:
        alerts.append({
            "type": "sighting", "severity": "info", "title": sentence_case(name),
            "text": f"Seen {int(cnt)} time{'s' if cnt != 1 else ''} in the last 2 days, "
                    f"last one {_ago(last, now)}.",
        })

    # 2. Camera faults the plan's own "Cameras not sending" card can't say: a flat
    # battery on a camera still sending. A camera that is offline, out of credits,
    # silent or whose photos are not coming in is on that card already, with its
    # reason, and a login that stopped is named in the line above the plan (with the
    # way to Settings), so none of them is listed here a second or third time (J-12).
    from app.health import camera_health
    from app.ingestion.logins import camera_logins

    login_states = camera_logins(db, cams, now)
    for c in cams:
        if camera_health(c, now, login_states.get(c.id))["status"] == "low_battery":
            alerts.append({
                "type": "camera", "severity": "warn", "title": f"{c.name} battery low",
                "text": f"{c.battery_pct}% left. Bring batteries on your next visit.",
            })

    # 3. Pattern break: a usually-busy camera whose last few WATCHED nights had no
    # visit. Only a night the camera was demonstrably watching counts as quiet, so a
    # flat battery or a backlog of unchecked photos is never "the animals left".
    tonight = current_night(now)
    since = tonight - timedelta(days=QUIET_LOOKBACK)
    watched: dict = {}
    for cam_id, night in db.execute(
        select(CameraNight.camera_id, CameraNight.night).where(
            CameraNight.camera_id.in_(cam_ids), CameraNight.night >= since,
            CameraNight.night < tonight,
            CameraNight.exposure_state.in_(("CONFIRMED", "PRESUMED_UP")),
        )
    ).all():
        watched.setdefault(cam_id, set()).add(night)
    recent = visit_rows(start=night_key_start(since - timedelta(days=1)),
                        end=night_key_start(tonight), camera_ids=cam_ids)
    busy = db.execute(
        select(recent.c.camera_id, recent.c.night, func.count())
        .where(recent.c.night >= since)
        .group_by(recent.c.camera_id, recent.c.night)
    ).all()
    per_camera: dict = {}
    for cam_id, night, n in busy:
        per_camera.setdefault(cam_id, {})[night] = int(n)
    for c in cams:
        nights = per_camera.get(c.id, {})
        if not c.active or sum(nights.values()) < QUIET_USUAL_VISITS:
            continue
        run = 0
        for night in sorted(watched.get(c.id, set()), reverse=True):
            if nights.get(night):
                break
            run += 1
        if run >= QUIET_NIGHTS:
            last = max(nights)
            # `camera` lets Tonight leave it out when its "Changed" line is already
            # about this camera, rather than say it twice (or the opposite).
            alerts.append({
                "type": "quiet", "severity": "warn", "title": f"{c.name} quiet", "camera": c.name,
                "text": f"Nothing on its last {run} watched nights, since the night of "
                        f"{last.day} {last.strftime('%b')}. This camera usually sees more.",
            })

    return alerts
