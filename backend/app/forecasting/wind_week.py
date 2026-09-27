"""The wind hour by hour through the evening, and the evenings this week it is right.

One wind value at the sit covered the whole evening, though the forecast holds
every hour and a calm evening's drainage turns around dusk: a hunter couldn't see
the wind going wrong at 21:00, or that Thursday is the evening for Charca, without
another app (audit J-19). This judges every hour from 17:00 to 24:00, tonight and
the next six evenings, for every stand, with the one wind verdict the rest of the
app gives (conditions.wind_verdict): the same bedding, slope and scent cone, so the
hour of tonight's sit on the strip says what Stands, the map and Sit mode say.

What a hunter reads first is one line: "Right wind for Charca: tonight 19–21 h, Thu,
Sat". The hours are behind a fold.

- **Right** is the verdict "clean": the scent goes away from where they lie up (or
  from the stand's approach arcs). Too light to call is not right; nor is a stand
  that can't be judged, which says why instead.
- **Tonight** lists its right hours still to come (the hour under way counts): the
  runs a sit fits in first, the longest of them, then a single hour if there is
  room, two at most, in time order. Another evening is listed when it has at least
  two right hours in a row, a sit's worth. Every hour is on the strip.
- **Cached hourly.** 56 verdicts a stand is real work, so an answer is kept for the
  rest of the hour, and made again sooner only when something it rests on changes:
  a stand moved or its arcs set, bedding drawn, the hill shape loaded, a newer
  forecast.
"""
from __future__ import annotations

import hashlib
import threading
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Text, cast, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.enrichment.weather import forecast_hours
from app.forecasting.conditions import release, sun_times, wind_verdict
from app.forecasting.exposure import current_night
from app.models import Stand, TerrainGrid, Zone

# 17:00 to 24:00 on the estate's clock: an evening sit, from before sunset in
# midwinter to the last of a summer one.
FIRST_HOUR = 17
LAST_HOUR = 24
EVENINGS = 7
# A later evening counts as a right one with this many right hours in a row.
MIN_RUN = 2
# Tonight's line names this many runs of right hours at most; the rest are on the strip.
NAMED = 2
RIGHT = "clean"
# The stand itself can't be judged, whatever the wind: said once, not every hour.
UNJUDGED = ("no_position", "no_bedding", "no_geometry")
# Forecast days fetched: the evenings, the 00:00 after the last one, and one more
# for a request between midnight and 06:00, when tonight is still the evening before.
FORECAST_DAYS = EVENINGS + 2

# The evenings by name, whatever language the server's own clock speaks.
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

_CACHE: dict = {}
_CACHE_GUARD = threading.Lock()


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.estate_timezone)


def _hours_of(night: date) -> list[tuple[int, datetime]]:
    """(hour label, instant) for 17:00 to 24:00 of the evening of `night`."""
    tz = _tz()
    out = []
    for h in range(FIRST_HOUR, LAST_HOUR + 1):
        day, hh = (night, h) if h < 24 else (night + timedelta(days=1), 0)
        out.append((h, datetime.combine(day, time(hh), tzinfo=tz).astimezone(UTC)))
    return out


def _span(run: list[int]) -> str:
    """"19–21 h", or "21 h" for one hour."""
    return f"{run[0]} h" if len(run) == 1 else f"{run[0]}–{run[-1]} h"


def _runs(hours: list[dict]) -> list[list[int]]:
    """The right hours in a row, as lists of hour labels, among those still to come."""
    runs: list[list[int]] = []
    last = None
    for h in hours:
        if h["gone"] or h["status"] != RIGHT:
            last = None
            continue
        if last is not None and h["hour"] == last + 1 and runs:
            runs[-1].append(h["hour"])
        else:
            runs.append([h["hour"]])
        last = h["hour"]
    return runs


def _named(runs: list[list[int]]) -> list[list[int]]:
    """The runs tonight's line names: those a sit fits in (MIN_RUN hours or more),
    longest first, then single hours if there is room; in time order. Naming the
    first two used to drop the evening's real window behind two stray hours: right
    at 17, 19 and 21–23 read "tonight 17 h and 19 h" (review R6FE-2)."""
    ranked = sorted(runs, key=lambda r: (len(r) < MIN_RUN, -len(r), r[0]))
    return sorted(ranked[:NAMED], key=lambda r: r[0])


def _fingerprint(db: Session, stand_id) -> str:
    """What the answer rests on besides the forecast: the stands, the bedding and
    the hill shape. A change to any of them makes the answer again."""
    q = (select(Stand.id, Stand.name, Stand.lat, Stand.lon, Stand.approach_dirs_deg)
         .order_by(Stand.id))
    if stand_id is not None:
        q = q.where(Stand.id == stand_id)
    rows = [tuple(r) for r in db.execute(q)]
    rows += [tuple(r) for r in db.execute(
        select(Zone.id, func.md5(cast(Zone.polygon, Text)))
        .where(Zone.kind == "bedding").order_by(Zone.id))]
    rows += [tuple(r) for r in db.execute(
        select(TerrainGrid.id, TerrainGrid.steps, TerrainGrid.min_lat, TerrainGrid.max_lat,
               TerrainGrid.min_lon, TerrainGrid.max_lon,
               func.md5(cast(TerrainGrid.elevations, Text))))]
    return hashlib.sha1(repr(rows).encode()).hexdigest()


def _line(name: str, status: str, tonight: str | None, days: list[str], has_forecast: bool) -> str:
    """The one line up front."""
    if status == "no_position":
        return f"{name} isn’t on the map yet, so its wind can’t be judged."
    if status == "no_bedding":
        return f"No bedding drawn yet, so the wind can’t be judged for {name}."
    if status == "no_geometry":
        return f"{name} has no approach directions set, so judge its wind yourself."
    if not has_forecast:
        return "No wind forecast for the week yet."
    right = ([f"tonight {tonight}"] if tonight else []) + days
    if right:
        return f"Right wind for {name}: {', '.join(right)}"
    return f"No right wind for {name} this week."


def _judge(
    db: Session, stands: list[Stand], forecast: dict, bucket: datetime, now: datetime
) -> dict:
    tonight = current_night(now)
    tz = _tz()
    # The evenings with an hour still to come: after midnight tonight's are all gone,
    # and the week starts at the coming evening.
    nights = [tonight + timedelta(days=d) for d in range(EVENINGS + 1)]
    if all(at < bucket for _, at in _hours_of(nights[0])):
        nights = nights[1:]
    nights = nights[:EVENINGS]
    evenings = [{
        "night": n.isoformat(),
        "day": "Tonight" if n == tonight else DAYS[n.weekday()],
        "tonight": n == tonight,
        "sunset_local": sun_times(n)["sunset_local"],
    } for n in nights]
    hours_of = {n: _hours_of(n) for n in nights}
    hours = forecast["hours"]

    out = []
    for s in stands:
        rows, statuses, tonight_right = [], set(), None
        for n in nights:
            evening = []
            for label, at in hours_of[n]:
                w = hours.get(int(at.timestamp())) or {}
                cond = {"wind_dir_deg": w.get("wind_dir_deg"),
                        "wind_speed_kmh": w.get("wind_speed_kmh"),
                        "cloud_cover_pct": w.get("cloud_cover_pct"),
                        "wind_at": at.isoformat(), "wind_now": False}
                v = wind_verdict(db, s, cond, now=now)
                statuses.add(v["status"])
                evening.append({
                    "hour": label, "at": at.isoformat(),
                    "at_local": at.astimezone(tz).strftime("%H:%M"),
                    "gone": at < bucket,
                    "status": v["status"],
                    # What the forecast says for the hour; the slope's own air, when it
                    # is what decides, is in `source`.
                    "wind_dir_deg": w.get("wind_dir_deg"),
                    "wind_speed_kmh": w.get("wind_speed_kmh"),
                    "source": v.get("source"),
                })
            runs = _runs(evening)
            rows.append({"night": n.isoformat(), "hours": evening,
                         "right": [_span(r) for r in runs],
                         "right_evening": any(len(r) >= MIN_RUN for r in runs)})
            if n == tonight:
                tonight_right = " and ".join(_span(r) for r in _named(runs)) or None
        stand_status = next(
            (u for u in UNJUDGED if u in statuses and statuses <= {u, "no_wind_data"}), "ok")
        has_forecast = statuses != {"no_wind_data"}
        days = [ev["day"] for ev, row in zip(evenings, rows, strict=True)
                if not ev["tonight"] and row["right_evening"]]
        out.append({
            "stand_id": str(s.id), "stand": s.name, "status": stand_status,
            "line": _line(s.name, stand_status, tonight_right, days, has_forecast),
            "right_tonight": tonight_right, "right_days": days,
            "evenings": rows,
        })
    return {"evenings": evenings, "hours": list(range(FIRST_HOUR, LAST_HOUR + 1)), "stands": out}


def week(db: Session, *, stand_id=None, now: datetime | None = None) -> dict:
    """Every stand's (or one stand's) hour-by-hour wind for tonight and the next six
    evenings, and its one line. Kept for the rest of the hour (see the module)."""
    now = now or datetime.now(UTC)
    bucket = now.replace(minute=0, second=0, microsecond=0)
    q = select(Stand).order_by(Stand.name)
    if stand_id is not None:
        q = q.where(Stand.id == stand_id)
    stands = list(db.scalars(q).all())
    fingerprint = _fingerprint(db, stand_id)
    # The forecast with no database connection held while Open-Meteo answers (K-04).
    release(db)
    forecast = forecast_hours(settings.estate_lat, settings.estate_lon, current_night(now),
                              FORECAST_DAYS, tz=settings.estate_timezone)
    fetched = forecast["fetched_at"]
    key = (bucket, fingerprint, fetched, forecast["stale"], str(stand_id) if stand_id else None)
    with _CACHE_GUARD:
        hit = _CACHE.get(key)
    if hit is None:
        hit = _judge(db, stands, forecast, bucket, now)
        with _CACHE_GUARD:
            # Answers from an earlier hour are never asked for again.
            for old in [k for k in _CACHE if k[0] != bucket]:
                _CACHE.pop(old, None)
            if len(_CACHE) > 64:
                _CACHE.clear()
            _CACHE[key] = hit
    return {
        **hit,
        "forecast_fetched_at": fetched.isoformat() if fetched else None,
        "forecast_stale": forecast["stale"],
    }
