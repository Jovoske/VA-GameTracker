"""Alerts — notable events worth surfacing: opportunity nights, recent target-species
sightings, and pattern breaks (a usually-active camera gone quiet).

In-app feed for now; browser push (VAPID via the PWA service worker) is the next
delivery upgrade and reuses these same events.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.forecasting.model import forecast_tonight
from app.models import Camera, Detection, Image, Species

PRIORITY = {"wild_boar", "red_deer", "roe_deer", "fallow_deer", "fox", "mouflon", "ibex", "badger"}


def _ago(dt: datetime | None, now: datetime) -> str:
    if dt is None:
        return "unknown"
    return _dur(dt, now) + " ago"


def _dur(dt: datetime, now: datetime) -> str:
    """Bare duration ("9d", "5h", "32m") for phrases like 'quiet for 9d'."""
    s = (now - dt).total_seconds()
    if s < 3600:
        return f"{int(s // 60)}m"
    if s < 86400:
        return f"{int(s // 3600)}h"
    return f"{int(s // 86400)}d"


def compute_alerts(db: Session) -> list[dict]:
    now = datetime.now(timezone.utc)
    alerts: list[dict] = []

    # 1. Opportunity tonight (from the forecast)
    fc = forecast_tonight(db)
    rec = fc.get("recommended")
    if fc.get("verdict") == "GO" and rec and rec["probability"] >= 0.7:
        w = rec["best_window"]
        alerts.append({
            "type": "opportunity", "severity": "high", "title": "Strong night ahead",
            "text": f"{round(rec['probability'] * 100)}% {rec['species']} at {rec['camera']}, "
                    f"best {w['start_hour']:02d}:00–{w['end_hour']:02d}:00.",
        })

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

    # 3. Camera health — a camera that can't send photos is a fault, never a "pattern".
    from app.health import camera_health

    cams = db.scalars(select(Camera)).all()
    health = {c.id: camera_health(c, now) for c in cams}
    for c in cams:
        h = health[c.id]
        if h["status"] == "out_of_credits":
            reset_on = f"{c.cycle_end.day} {c.cycle_end.strftime('%b')}" if c.cycle_end else "next cycle"
            reset = f" Resets {reset_on}."
            alerts.append({
                "type": "camera", "severity": "warn", "title": f"{c.name} out of photo credits",
                "text": f"Hit its monthly limit ({c.photo_count}/{c.photo_limit}) and stopped sending.{reset}",
            })
        elif h["status"] == "offline":
            alerts.append({
                "type": "camera", "severity": "warn", "title": f"{c.name} offline",
                "text": f"{h['detail']} — check battery and signal on your next visit.",
            })
        elif h["status"] == "low_battery":
            alerts.append({
                "type": "camera", "severity": "warn", "title": f"{c.name} battery low",
                "text": f"{c.battery_pct}% left — bring batteries on your next visit.",
            })

    # 4. Pattern break — a HEALTHY camera gone quiet (only then is silence meaningful)
    cam_rows = db.execute(
        select(Camera.id, Camera.name, func.count(Detection.id), func.max(Image.captured_at))
        .select_from(Detection)
        .join(Image, Image.id == Detection.image_id)
        .join(Camera, Camera.id == Image.camera_id)
        .group_by(Camera.id, Camera.name)
    ).all()
    for cid, name, cnt, last in cam_rows:
        producing = health.get(cid, {}).get("producing", True)
        if producing and int(cnt) >= 15 and last and last < now - timedelta(days=3):
            alerts.append({
                "type": "quiet", "severity": "warn", "title": f"{name} quiet",
                "text": f"No animals in {_dur(last, now)} — unusual for this camera.",
            })

    return alerts
