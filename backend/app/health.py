"""Camera health — turn raw SPYPOINT fields into a plain status, and decide whether a
camera's missing photos are real ("no animals") or a fault ("dead / out of credits").

The `producing` flag is the one the forecast cares about: a camera that isn't producing
must not have its silence read as an absence of game.

Three things that look like a dead camera are not one, and each gets its own words:
- the camera login stopped working, or the fetch could not list this camera's photos
  although its login works (not_syncing): the camera may be fine, its photos just are
  not reaching us, so the hunter is sent to Settings, not to the batteries;
- no login fetches it any more, say its login was removed (disconnected): nothing
  to check at the camera, and it is left out of the ranking;
- a Suntek camera sending by FTP or email has no check-in, only photos, so a quiet
  spell is normal and only a long one (quiet) is worth a look.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.models import Camera

OFFLINE_HOURS = 36  # SPYPOINT and UBox cameras check in at least daily
# A Suntek (FTP or email) camera sends photos and nothing else, so days without game
# look exactly like a flat battery. Only this long a silence is called out.
QUIET_DAYS = 7
LOW_BATTERY_PCT = 20

NOT_SYNCING = "Photos not coming in. The camera login needs attention."
# No login error, just no good fetch for hours: the scheduled fetch itself has stopped
# (or is stuck behind a long job), so the login is not blamed.
NOT_FETCHED = "Photos not coming in. No photo fetch has worked for over 2 hours."


def _day(when: datetime) -> str:
    return f"{when.day} {when.strftime('%b')}"


def camera_health(cam: Camera, now: datetime | None = None, login: dict | None = None) -> dict:
    """`login` is the state of the login that fetches this camera (logins.camera_logins)."""
    now = now or datetime.now(UTC)
    last = cam.last_report_at
    hours = (now - last).total_seconds() / 3600 if last is not None else None
    heartbeat = cam.spypoint_id is not None or cam.ubox_uid is not None
    offline = last is None or (hours is not None and hours > OFFLINE_HOURS)
    quiet = last is None or (hours is not None and hours > QUIET_DAYS * 24)

    credits_left = None
    if cam.photo_limit is not None and cam.photo_count is not None:
        credits_left = max(0, cam.photo_limit - cam.photo_count)
    out_of_credits = credits_left is not None and credits_left <= 0

    low_battery = cam.battery_pct is not None and cam.battery_pct < LOW_BATTERY_PCT
    login_down = login is not None and login.get("state") in ("failing", "stale")
    fetch_error = getattr(cam, "fetch_error", None)

    if cam.active is False:
        status = "disconnected"
        detail = "Not connected: no camera login here fetches it now"
    elif login_down:
        status = "not_syncing"
        detail = NOT_SYNCING if login.get("state") == "failing" else NOT_FETCHED
    elif fetch_error:
        # Its login works, but the fetch could not list this camera's photos.
        status = "not_syncing"
        detail = f"Photos not coming in. {fetch_error}"
    elif not heartbeat:
        # Photo-only: its last photo is the only sign of life, and a week of none is
        # "have a look", never "check the battery" (it may just be quiet ground).
        status = "quiet" if quiet else "ok"
        if quiet:
            detail = f"No photos since {_day(last)}" if last else "No photos yet"
        else:
            detail = "Sends photos only, no check-ins"
    elif offline:
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
    # so the forecast must exclude them instead of scoring them as empty; nor is a
    # camera whose photos we cannot fetch, or a photo-only camera silent for a week.
    if status in ("disconnected", "not_syncing", "quiet"):
        producing = False
    elif heartbeat:
        producing = not offline and not out_of_credits
    else:
        producing = True
    out = {
        "status": status,
        "detail": detail,
        "producing": producing,
        "credits_left": credits_left,
        "hours_since_report": round(hours) if hours is not None else None,
    }
    if status == "not_syncing" and login_down:
        out["login"] = {"label": login.get("label"), "error": login.get("error")}
    elif status == "not_syncing":
        # `camera`: the login is fine, only this camera's listing failed.
        out["login"] = {"label": (login or {}).get("label"), "error": fetch_error,
                        "camera": True}
    return out
