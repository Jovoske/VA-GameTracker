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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Camera, CameraNight
from app.forecasting.exposure import visits_by_night

LOOKBACK_NIGHTS = 30
QUIET_RUN = 4       # nights of silence before a return is notable
SILENCE_RUN = 3     # nights of silence at a normally-active camera


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return float(s[mid]) if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def whats_changed(db: Session, *, today: date | None = None) -> dict:
    """A single ranked statement. Always returns something."""
    last_night = (today or date.today()) - timedelta(days=1)
    window_start = last_night - timedelta(days=LOOKBACK_NIGHTS)

    # Exposure per camera-night, so a silent night can be told apart from a blind one.
    exposure: dict[tuple, str] = {
        (r.camera_id, r.night): r.exposure_state
        for r in db.scalars(
            select(CameraNight).where(CameraNight.night > window_start)
        ).all()
    }

    cameras = {c.id: c.name for c in db.scalars(select(Camera).where(Camera.active.is_(True))).all()}
    if not cameras:
        return {"kind": "none", "camera": None, "text": "No cameras configured yet."}

    # A camera that has gone off the air outranks everything else on this screen.
    for cam_id, name in cameras.items():
        state = exposure.get((cam_id, last_night))
        if state in ("UNKNOWN", "UNPROCESSED") or state is None:
            if any(exposure.get((cam_id, last_night - timedelta(days=d))) == "CONFIRMED"
                   for d in range(1, 5)):
                return {
                    "kind": "camera_down",
                    "camera": name,
                    "text": f"{name} sent nothing last night — treat its silence as unknown, "
                            "not as an empty wood.",
                }

    visits = visits_by_night(db)
    per_night: dict[tuple, int] = {}
    species_seen: dict[tuple, set] = {}
    for (night, cam_id, species_id), row in visits.items():
        if night <= window_start:
            continue
        per_night[(cam_id, night)] = per_night.get((cam_id, night), 0) + row["visits"]
        species_seen.setdefault((cam_id, night), set()).add(species_id)

    best: tuple[float, dict] | None = None
    for cam_id, name in cameras.items():
        history = [
            per_night.get((cam_id, last_night - timedelta(days=d)), 0)
            for d in range(1, LOOKBACK_NIGHTS + 1)
            if exposure.get((cam_id, last_night - timedelta(days=d))) in ("CONFIRMED", "PRESUMED_UP")
        ]
        if len(history) < 5:
            continue  # too little to call anything a change
        if exposure.get((cam_id, last_night)) not in ("CONFIRMED", "PRESUMED_UP"):
            continue

        tonight_count = per_night.get((cam_id, last_night), 0)
        median = _median(history)

        quiet_run = 0
        for d in range(1, LOOKBACK_NIGHTS + 1):
            night = last_night - timedelta(days=d)
            if exposure.get((cam_id, night)) not in ("CONFIRMED", "PRESUMED_UP"):
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
            silent = 1
            for d in range(1, SILENCE_RUN + 1):
                night = last_night - timedelta(days=d)
                if per_night.get((cam_id, night), 0) == 0:
                    silent += 1
            if silent < SILENCE_RUN:
                continue
            cand = {
                "kind": "gone_quiet",
                "camera": name,
                "text": f"{name} has been quiet {silent} nights — it usually sees "
                        f"{median:.0f} a night.",
            }
            score = 50 + silent
        elif median > 0 and abs(tonight_count - median) / max(median, 1) >= 0.5:
            direction = "up" if tonight_count > median else "down"
            cand = {
                "kind": "shift",
                "camera": name,
                "text": f"{name} was {direction} last night: {tonight_count} vs a usual "
                        f"{median:.0f}.",
            }
            score = 10 + abs(tonight_count - median)
        else:
            continue

        if best is None or score > best[0]:
            best = (score, cand)

    if best:
        return best[1]
    return {
        "kind": "none",
        "camera": None,
        "text": "Nothing changed — much the same as the last few nights.",
    }
