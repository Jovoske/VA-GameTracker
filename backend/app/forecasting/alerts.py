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
    s = (now - dt).total_seconds()
    if s < 3600:
        return f"{int(s // 60)}m ago"
    if s < 86400:
        return f"{int(s // 3600)}h ago"
    return f"{int(s // 86400)}d ago"


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

    # 3. Pattern break — a usually-active camera gone quiet
    cam_rows = db.execute(
        select(Camera.name, func.count(Detection.id), func.max(Image.captured_at))
        .select_from(Detection)
        .join(Image, Image.id == Detection.image_id)
        .join(Camera, Camera.id == Image.camera_id)
        .group_by(Camera.name)
    ).all()
    for name, cnt, last in cam_rows:
        if int(cnt) >= 15 and last and last < now - timedelta(days=3):
            alerts.append({
                "type": "quiet", "severity": "warn", "title": f"{name} quiet",
                "text": f"No animals for {_ago(last, now)} — unusual for this camera.",
            })

    return alerts
