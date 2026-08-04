"""Camera health — turn raw SPYPOINT fields into a plain status, and decide whether a
camera's missing photos are real ("no animals") or a fault ("dead / out of credits").

The `producing` flag is the one the forecast cares about: a camera that isn't producing
must not have its silence read as an absence of game.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import Camera

OFFLINE_HOURS = 36  # cameras check in at least daily; beyond this it's not reporting
LOW_BATTERY_PCT = 20


def camera_health(cam: Camera, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    last = cam.last_report_at
    hours = (now - last).total_seconds() / 3600 if last is not None else None
    offline = last is None or (hours is not None and hours > OFFLINE_HOURS)

    credits_left = None
    if cam.photo_limit is not None and cam.photo_count is not None:
        credits_left = max(0, cam.photo_limit - cam.photo_count)
    out_of_credits = credits_left is not None and credits_left <= 0

    low_battery = cam.battery_pct is not None and cam.battery_pct < LOW_BATTERY_PCT

    if offline:
        status = "offline"
        detail = "No check-in" + (f" for {round(hours)}h" if hours is not None else " yet")
    elif out_of_credits:
        status = "out_of_credits"
        detail = f"Photo limit reached ({cam.photo_count}/{cam.photo_limit})"
    elif low_battery:
        status = "low_battery"
        detail = f"Battery low ({cam.battery_pct}%)"
    else:
        status = "ok"
        detail = "Reporting normally"

    # Producing = we can trust the recent absence of photos as genuine (few animals),
    # rather than a camera fault. Offline or out-of-credits cameras are NOT producing,
    # so the forecast must exclude them instead of scoring them as empty.
    producing = not offline and not out_of_credits
    return {
        "status": status,
        "detail": detail,
        "producing": producing,
        "credits_left": credits_left,
        "hours_since_report": round(hours) if hours is not None else None,
    }
