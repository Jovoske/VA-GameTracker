"""What changed since yesterday — the one comparison a hunter cannot make from memory.

Every expert who reviewed this product asked for it and none of them defined it, so
the definition is stated here rather than left to the caller:

* compare **last night's independent visits per camera** against that camera's
  **trailing-30-night median**, computed over nights the camera was demonstrably
  watching (CONFIRMED or PRESUMED_UP). Nights we cannot vouch for are excluded,
  never imputed as zero — otherwise a flat battery reads as "the animals left".
* a camera that has stopped reporting outranks any change in animal numbers,
  because it changes what the rest of the screen is worth.
* it is **never blank**. A decision aid that goes silent on quiet nights teaches
  the user that silence means broken, so "nothing changed" is said out loud.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.forecasting.exposure import current_night, night_key_start, visits_by_night
from app.models import Camera, CameraNight

LOOKBACK_NIGHTS = 30
QUIET_RUN = 4       # nights of silence before a return is notable
SILENCE_RUN = 3     # nights of silence at a normally-active camera
# A night's count differs from the usual by at least this many visits, and the usual
# is at least one a night, before it is news. One boar more than a usual of half a
# visit is not a change, and it used to be one every other night.
SHIFT_MIN_VISITS = 2
WATCHED = ("CONFIRMED", "PRESUMED_UP")


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return float(s[mid]) if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def _visits(n: int) -> str:
    return f"{n} visit{'' if n == 1 else 's'}"


def _usual(median: float) -> str:
    """"about 3", or "about 1.5": a whole number only where rounding says little."""
    return f"about {median:.0f}" if median >= 2 else f"about {median:.1f}".replace(".0", "")


def whats_changed(db: Session, *, tonight: date | None = None) -> dict:
    """A single ranked statement. Always returns something.

    `tonight` is the night key now (exposure.current_night): "last night" is the
    one before it, so between midnight and 06:00 it is never the night still under
    way, whatever the server's clock is set to.
    """
    last_night = (tonight or current_night()) - timedelta(days=1)
    window_start = last_night - timedelta(days=LOOKBACK_NIGHTS)

    # Exposure per camera-night, so a silent night can be told apart from a blind one.
    exposure: dict[tuple, str] = {
        (r.camera_id, r.night): r.exposure_state
        for r in db.scalars(
            select(CameraNight).where(CameraNight.night > window_start)
        ).all()
    }

    active = db.scalars(
        select(Camera).where(Camera.active.is_(True), Camera.retired_at.is_(None))
    ).all()
    cameras = {c.id: c.name for c in active}
    if not cameras:
        return {"kind": "none", "camera": None, "text": "No cameras set up yet."}

    # A camera that has gone off the air outranks everything else on this screen.
    for cam_id, name in cameras.items():
        state = exposure.get((cam_id, last_night))
        if state == "UNKNOWN" or state is None:
            if any(exposure.get((cam_id, last_night - timedelta(days=d))) == "CONFIRMED"
                   for d in range(1, 5)):
                return {
                    "kind": "camera_down",
                    "camera": name,
                    "text": f"{name} sent nothing last night. Unknown whether anything "
                            "came through.",
                }

    # Only the nights compared, read from the start of the one before them: a visit
    # already under way at 06:00 on the first stays on its own night. Unbounded,
    # this read every photo ever taken on every load of Tonight. Hidden species and
    # photos marked "nothing in it" are not visits (visits.visit_rows).
    visits = visits_by_night(db, start=night_key_start(window_start))
    per_night: dict[tuple, int] = {}
    for (night, cam_id, _species_id), row in visits.items():
        if night <= window_start:
            continue
        per_night[(cam_id, night)] = per_night.get((cam_id, night), 0) + row["visits"]

    def watched(cam_id, night) -> bool:
        return exposure.get((cam_id, night)) in WATCHED

    best: tuple[float, dict] | None = None
    unchecked: list[str] = []
    for cam_id, name in cameras.items():
        if exposure.get((cam_id, last_night)) == "UNPROCESSED":
            # Photos arrived and the AI has not been through them yet: not "sent
            # nothing", and not a quiet night either.
            unchecked.append(name)
            continue
        history = [
            per_night.get((cam_id, last_night - timedelta(days=d)), 0)
            for d in range(1, LOOKBACK_NIGHTS + 1)
            if watched(cam_id, last_night - timedelta(days=d))
        ]
        if len(history) < 5:
            continue  # too little to call anything a change
        if not watched(cam_id, last_night):
            continue

        tonight_count = per_night.get((cam_id, last_night), 0)
        median = _median(history)

        # Watched nights with nothing, back to the last one with a visit. A night
        # nobody could see neither lengthens the run nor ends it.
        quiet_run = 0
        for d in range(1, LOOKBACK_NIGHTS + 1):
            night = last_night - timedelta(days=d)
            if not watched(cam_id, night):
                continue
            if per_night.get((cam_id, night), 0) > 0:
                break
            quiet_run += 1

        if tonight_count > 0 and quiet_run >= QUIET_RUN:
            cand = {
                "kind": "return",
                "camera": name,
                "text": f"Animals back at {name} after {quiet_run} quiet nights.",
            }
            score = 100 + quiet_run
        elif tonight_count == 0 and median >= 1:
            silent = quiet_run + 1  # last night too
            if silent < SILENCE_RUN:
                continue
            cand = {
                "kind": "gone_quiet",
                "camera": name,
                "text": f"{name} has been quiet for {silent} nights. It usually sees "
                        f"{_usual(median)} a night.",
            }
            score = 50 + silent
        elif median >= 1 and abs(tonight_count - median) >= SHIFT_MIN_VISITS:
            direction = "busier" if tonight_count > median else "quieter"
            cand = {
                "kind": "shift",
                "camera": name,
                "text": f"{name} was {direction} than usual last night: "
                        f"{_visits(tonight_count)} against a usual {_usual(median)}.",
            }
            score = 10 + abs(tonight_count - median)
        else:
            continue

        if best is None or score > best[0]:
            best = (score, cand)

    if best:
        return best[1]
    if unchecked:
        names = " and ".join(unchecked) if len(unchecked) <= 2 else "some cameras"
        return {
            "kind": "checking",
            "camera": unchecked[0] if len(unchecked) == 1 else None,
            "text": f"Last night's photos from {names} are still being checked.",
        }
    return {
        "kind": "none",
        "camera": None,
        "text": "Nothing changed. Much the same as the last few nights.",
    }
