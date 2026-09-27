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


def usual(median: float) -> str:
    """"about 3", or "about 1.5": a whole number only where rounding says little."""
    return f"about {median:.0f}" if median >= 2 else f"about {median:.1f}".replace(".0", "")


class _Nights:
    """Visits and exposure per camera over the nights compared, read once."""

    def __init__(self, db: Session, last_night: date):
        self.last_night = last_night
        window_start = last_night - timedelta(days=LOOKBACK_NIGHTS)
        # Exposure per camera-night, so a silent night can be told apart from a blind one.
        self.exposure: dict[tuple, str] = {
            (r.camera_id, r.night): r.exposure_state
            for r in db.scalars(
                select(CameraNight).where(CameraNight.night > window_start)
            ).all()
        }
        # Only the nights compared, read from the start of the one before them: a visit
        # already under way at 06:00 on the first stays on its own night. Unbounded,
        # this read every photo ever taken on every load of Tonight. Hidden species and
        # photos marked "nothing in it" are not visits (visits.visit_rows).
        visits = visits_by_night(db, start=night_key_start(window_start))
        self.per_night: dict[tuple, int] = {}
        for (night, cam_id, _species_id), row in visits.items():
            if night <= window_start:
                continue
            self.per_night[(cam_id, night)] = self.per_night.get((cam_id, night), 0) + row["visits"]

    def watched(self, cam_id, night: date) -> bool:
        return self.exposure.get((cam_id, night)) in WATCHED

    def before(self):
        """The nights before last night, newest first."""
        return (self.last_night - timedelta(days=d) for d in range(1, LOOKBACK_NIGHTS + 1))

    def history(self, cam_id) -> list[int]:
        """Visits on each watched night before last night."""
        return [self.per_night.get((cam_id, n), 0) for n in self.before()
                if self.watched(cam_id, n)]

    def quiet_run(self, cam_id) -> int:
        """Watched nights with nothing, back to the last one with a visit. A night
        nobody could see neither lengthens the run nor ends it."""
        run = 0
        for night in self.before():
            if not self.watched(cam_id, night):
                continue
            if self.per_night.get((cam_id, night), 0) > 0:
                break
            run += 1
        return run

    def last_seen(self, cam_id) -> date | None:
        return next((n for n in self.before() if self.per_night.get((cam_id, n), 0) > 0),
                    None)


def _gone_quiet(n: _Nights, cam_id) -> dict | None:
    """A camera that usually sees at least one visit a night and has had nothing on
    its last SILENCE_RUN watched nights, last night included: {"silent", "usual",
    "last_seen"}. The one rule for "gone quiet", on Tonight's Changed line and under
    its Alerts, so the two can never disagree (audit G-23)."""
    history = n.history(cam_id)
    if len(history) < 5 or not n.watched(cam_id, n.last_night):
        return None
    if n.per_night.get((cam_id, n.last_night), 0) > 0:
        return None
    median = _median(history)
    silent = n.quiet_run(cam_id) + 1  # last night too
    if median < 1 or silent < SILENCE_RUN:
        return None
    return {"silent": silent, "usual": median, "last_seen": n.last_seen(cam_id)}


def _active(db: Session) -> dict:
    return {c.id: c.name for c in db.scalars(
        select(Camera).where(Camera.active.is_(True), Camera.retired_at.is_(None))
    ).all()}


def quiet_cameras(db: Session, *, tonight: date | None = None) -> dict:
    """{camera_id: {"silent", "usual", "last_seen"}} for every camera gone quiet by
    the rule the Changed line uses (_gone_quiet)."""
    last_night = (tonight or current_night()) - timedelta(days=1)
    cameras = _active(db)
    if not cameras:
        return {}
    n = _Nights(db, last_night)
    out = {}
    for cam_id in cameras:
        q = _gone_quiet(n, cam_id)
        if q is not None:
            out[cam_id] = q
    return out


def whats_changed(db: Session, *, tonight: date | None = None) -> dict:
    """A single ranked statement. Always returns something.

    `tonight` is the night key now (exposure.current_night): "last night" is the
    one before it, so between midnight and 06:00 it is never the night still under
    way, whatever the server's clock is set to.
    """
    last_night = (tonight or current_night()) - timedelta(days=1)
    cameras = _active(db)
    if not cameras:
        return {"kind": "none", "camera": None, "text": "No cameras set up yet."}
    n = _Nights(db, last_night)

    # A camera that has gone off the air outranks everything else on this screen.
    for cam_id, name in cameras.items():
        state = n.exposure.get((cam_id, last_night))
        if state == "UNKNOWN" or state is None:
            if any(n.exposure.get((cam_id, last_night - timedelta(days=d))) == "CONFIRMED"
                   for d in range(1, 5)):
                return {
                    "kind": "camera_down",
                    "camera": name,
                    "text": f"{name} sent nothing last night. Unknown whether anything "
                            "came through.",
                }

    best: tuple[float, dict] | None = None
    unchecked: list[str] = []
    for cam_id, name in cameras.items():
        if n.exposure.get((cam_id, last_night)) == "UNPROCESSED":
            # Photos arrived and the AI has not been through them yet: not "sent
            # nothing", and not a quiet night either.
            unchecked.append(name)
            continue
        history = n.history(cam_id)
        if len(history) < 5:
            continue  # too little to call anything a change
        if not n.watched(cam_id, last_night):
            continue

        tonight_count = n.per_night.get((cam_id, last_night), 0)
        median = _median(history)
        quiet_run = n.quiet_run(cam_id)

        if tonight_count > 0 and quiet_run >= QUIET_RUN:
            cand = {
                "kind": "return",
                "camera": name,
                "text": f"Animals back at {name} after {quiet_run} quiet nights.",
            }
            score = 100 + quiet_run
        elif tonight_count == 0 and median >= 1:
            quiet = _gone_quiet(n, cam_id)
            if quiet is None:
                continue
            cand = {
                "kind": "gone_quiet",
                "camera": name,
                "text": f"{name} has been quiet for {quiet['silent']} nights. It usually sees "
                        f"{usual(median)} a night.",
            }
            score = 50 + quiet["silent"]
        elif median >= 1 and abs(tonight_count - median) >= SHIFT_MIN_VISITS:
            direction = "busier" if tonight_count > median else "quieter"
            cand = {
                "kind": "shift",
                "camera": name,
                "text": f"{name} was {direction} than usual last night: "
                        f"{_visits(tonight_count)} against a usual {usual(median)}.",
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
