"""Alerts — notable events worth surfacing: opportunity nights, recent target-species
sightings, and pattern breaks (a usually-active camera gone quiet).

In-app feed for now; browser push (VAPID via the PWA service worker) is the next
delivery upgrade and reuses these same events.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Camera, Detection, Image, Species

PRIORITY = {"wild_boar", "red_deer", "roe_deer", "fallow_deer", "fox", "mouflon", "ibex", "badger"}


def _ago(dt: datetime | None, now: datetime) -> str:
    if dt is None:
        return "unknown"
    s = (now - dt).total_seconds()
    if s < 3600:
        return f"{int(s // 60)}m ago"
    if s < 86400:
        return f"{int(s // 3600)}h ago"
    return f"{int(s // 86400)}d ago"


def compute_alerts(db: Session) -> list[dict]:
    now = datetime.now(timezone.utc)
    alerts: list[dict] = []

    # The "Strong night ahead" alert used to fire whenever the top camera crossed
    # p >= 0.7, which on a good camera is most nights. Intermittent, unpredictable,
    # high-arousal notifications are a variable-ratio reinforcement schedule — the
    # architecture of a slot machine — and it pushed sits the hunter would not
    # otherwise have taken. Tonight's plan belongs on the Tonight screen, delivered
    # on a fixed schedule; it is not an emergency.

    # 2. Recent priority-species sightings (last 48h)
    since = now - timedelta(hours=48)
    rows = db.execute(
        select(Species.common_name, func.count(Detection.id), func.max(Image.captured_at))
        .select_from(Detection)
        .join(Image, Image.id == Detection.image_id)
        .join(Species, Species.id == Detection.species_id)
        .where(Detection.species_id.in_(PRIORITY), Image.captured_at > since)
        .group_by(Species.common_name)
        .order_by(func.count(Detection.id).desc())
    ).all()
    for name, cnt, last in rows[:4]:
        alerts.append({
            "type": "sighting", "severity": "info", "title": name,
            "text": f"{int(cnt)} sighting{'s' if cnt != 1 else ''} in 48h, latest {_ago(last, now)}.",
        })

    # A camera that has stopped reporting animals is usually a camera, not an empty
    # wood: flat battery, full card, lost signal, knocked askew, or a web across the
    # lens. The old alert said "unusual for this camera" without ever looking at
    # battery_pct, signal_pct or last_sync_at sitting on the same row. Distinguish
    # the two cases and name the likely cause, because they need opposite responses.
    cam_rows = db.execute(
        select(
            Camera.name, Camera.battery_pct, Camera.signal_pct, Camera.last_sync_at,
            func.count(Detection.id), func.max(Image.captured_at),
        )
        .select_from(Camera)
        .join(Image, Image.camera_id == Camera.id, isouter=True)
        .join(Detection, Detection.image_id == Image.id, isouter=True)
        .where(Camera.active.is_(True))
        .group_by(Camera.name, Camera.battery_pct, Camera.signal_pct, Camera.last_sync_at)
    ).all()

    for name, battery, signal, last_sync, cnt, last_animal in cam_rows:
        silent = last_animal is None or last_animal < now - timedelta(days=3)
        if not (int(cnt or 0) >= 15 and silent):
            continue

        not_reporting = last_sync is None or last_sync < now - timedelta(hours=36)
        if not_reporting:
            alerts.append({
                "type": "camera_down", "severity": "warn", "title": f"{name} not reporting",
                "text": f"No contact for {_ago(last_sync, now)}"
                        + (f", battery {battery}%" if battery is not None else "")
                        + ". Check the camera before reading anything into the silence.",
            })
        elif battery is not None and battery <= 20:
            alerts.append({
                "type": "camera_battery", "severity": "warn", "title": f"{name} battery low",
                "text": f"Battery {battery}% and no animals for {_ago(last_animal, now)}. "
                        "Low power shortens detection range — treat the gap as unknown.",
            })
        else:
            alerts.append({
                "type": "quiet", "severity": "info", "title": f"{name} quiet",
                "text": f"Reporting normally, but no animals for {_ago(last_animal, now)}.",
            })

    return alerts
