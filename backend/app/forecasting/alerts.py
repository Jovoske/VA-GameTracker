"""Alerts — notable events worth surfacing: recent sightings of the animals that
matter, a flat battery, and a usually-busy camera gone quiet.

This is the in-app feed on Tonight, recomputed on every read, so it is kept cheap:
it never works out the plan again (the plan and its "Cameras not sending" card come
from the forecast, which Tonight already has). Push to phones lives in
app.notifications: it announces new sightings per species as they are classified,
filtered by what each person asked to hear about.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.forecasting.changes import quiet_cameras, usual
from app.forecasting.exposure import current_night
from app.forecasting.model import sentence_case
from app.models import Camera, Species


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

    now = datetime.now(UTC)
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
    # flat battery or a backlog of unchecked photos is never "the animals left". The
    # rule is the Changed line's own (changes.quiet_cameras): it used to be a total
    # over the month here and a nightly median there, so Tonight could say "Nothing
    # changed" beside "Puente quiet" (G-23).
    quiet = quiet_cameras(db, tonight=current_night(now))
    for c in cams:
        q = quiet.get(c.id)
        if q is None:
            continue
        last = q["last_seen"]
        since = f", since the night of {last.day} {last.strftime('%b')}" if last else ""
        # `camera` lets Tonight leave it out when its "Changed" line is already
        # about this camera, rather than say it twice.
        alerts.append({
            "type": "quiet", "severity": "warn", "title": f"{c.name} quiet", "camera": c.name,
            "text": f"Nothing on its last {q['silent']} watched nights{since}. "
                    f"It usually sees {usual(q['usual'])} a night.",
        })

    return alerts
