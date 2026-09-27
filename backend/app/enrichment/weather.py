"""Per-sighting weather from Open-Meteo at the photo's REAL capture time.

This is the direct fix for the legacy bug where every sighting was stamped with
the weather at processing time instead of when the animal was photographed.
"""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = (
    "temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,"
    "wind_gusts_10m,wind_direction_10m,precipitation,cloud_cover"
)
_FIELDS = {
    "temp_c": "temperature_2m",
    "humidity_pct": "relative_humidity_2m",
    "pressure_hpa": "surface_pressure",
    "wind_speed_kmh": "wind_speed_10m",
    "wind_gust_kmh": "wind_gusts_10m",
    "wind_dir_deg": "wind_direction_10m",
    "rain_mm": "precipitation",
    "cloud_cover_pct": "cloud_cover",
}


# One day's hourly data per (lat, lng, day, archive or forecast), so a backfill of
# many photos from the same camera-day makes a single Open-Meteo call instead of one
# per photo. Each entry is (fetched_at, monotonic time fetched, hourly).
#
# An archive day never changes and is kept. A forecast day does: it used to be kept
# for the life of the server too, so at dusk Tonight, the map and a reservation all
# read whatever forecast the first request after midnight had fetched (audit F-03,
# G-08, J-07). A forecast copy older than FORECAST_TTL_SECONDS is fetched again; if
# that fails, the old copy is served (marked stale, with when it was fetched) rather
# than nothing, so the wind doesn't vanish when the link drops at dusk.
_DAY_CACHE: dict = {}
FORECAST_TTL_SECONDS = 30 * 60
# A forecast copy older than this is not served even when nothing newer can be had.
STALE_LIMIT_SECONDS = 24 * 3600

# Weather is looked up while photos are stored and on every Tonight, map and
# reservation, so a slow Open-Meteo held all of them back by its timeout. A short
# timeout, and after a failure no calls for a while: photos are stored without
# weather, and the end of every fetch fills it in once Open-Meteo answers again
# (enrich.refill_unavailable); Tonight serves its last good forecast.
TIMEOUT_SECONDS = 5
CONNECT_SECONDS = 3
TIMEOUT = httpx.Timeout(TIMEOUT_SECONDS, connect=CONNECT_SECONDS)
PAUSE_AFTER_FAILURE_SECONDS = 600
_down_until = 0.0

# One fetch per day's data at a time: sixteen phones opening Tonight at dusk as the
# forecast expires make one call, not sixteen. The others serve the copy they have,
# or wait for this one when they have none.
_FETCHING: dict = {}
_FETCHING_GUARD = threading.Lock()


def _lock_for(key) -> threading.Lock:
    with _FETCHING_GUARD:
        return _FETCHING.setdefault(key, threading.Lock())


def _fresh(entry, recent: bool) -> bool:
    return not recent or time.monotonic() - entry[1] < FORECAST_TTL_SECONDS


def _fetch_day_hourly(lat: float, lng: float, day: str, recent: bool, tz: str) -> tuple:
    """(hourly, fetched_at, stale) for one day; ({}, None, False) when there is none."""
    global _down_until
    key = (lat, lng, day, recent, tz)
    had = _DAY_CACHE.get(key)
    if had is not None and _fresh(had, recent):
        return had[2], had[0], False

    def fallback():
        # The last good forecast, marked stale, rather than no wind at all.
        if had is not None and time.monotonic() - had[1] < STALE_LIMIT_SECONDS:
            return had[2], had[0], True
        return {}, None, False

    if time.monotonic() < _down_until:
        return fallback()
    lock = _lock_for(key)
    # Somebody else is fetching it: serve the copy there is, or wait for theirs.
    got = (lock.acquire(timeout=TIMEOUT_SECONDS + CONNECT_SECONDS + 1) if had is None
           else lock.acquire(blocking=False))
    if not got:
        return fallback()
    try:
        now_had = _DAY_CACHE.get(key)
        if now_had is not None and now_had is not had and _fresh(now_had, recent):
            return now_had[2], now_had[0], False  # fetched while this one waited
        if time.monotonic() < _down_until:
            return fallback()
        url = FORECAST_URL if recent else ARCHIVE_URL
        params = {
            "latitude": lat, "longitude": lng, "hourly": HOURLY,
            "timezone": tz, "start_date": day, "end_date": day,
            # Instants, not wall-clock strings: on the night the clocks go back the
            # two 02:00-03:00 hours are two different hours (audit F-22).
            "timeformat": "unixtime",
        }
        try:
            resp = httpx.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            hourly = resp.json().get("hourly", {})
        except Exception as e:
            log.warning("weather.fetch_failed", error=str(e))
            # The pause is the failure's cache: nobody waits on Open-Meteo again
            # until it is over.
            _down_until = time.monotonic() + PAUSE_AFTER_FAILURE_SECONDS
            return fallback()
        if len(_DAY_CACHE) > 8192:
            _DAY_CACHE.clear()
        fetched_at = datetime.now(UTC)
        _DAY_CACHE[key] = (fetched_at, time.monotonic(), hourly)
        return hourly, fetched_at, False
    finally:
        lock.release()
        with _FETCHING_GUARD:
            if not lock.locked():
                _FETCHING.pop(key, None)


def weather_at(lat: float, lng: float, when: datetime, tz: str = "Europe/Madrid") -> dict:
    """The hour nearest `when`. A forecast answer also says when it was fetched
    (`fetched_at`) and whether it is an old copy served because Open-Meteo didn't
    answer (`stale`)."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    local = when.astimezone(ZoneInfo(tz))
    # Archive lags ~5 days; use the forecast endpoint for recent captures.
    recent = (datetime.now(timezone.utc) - when).days < 5
    hourly, fetched_at, stale = _fetch_day_hourly(
        round(lat, 4), round(lng, 4), local.date().isoformat(), recent, tz
    )
    if not hourly:
        return {"source": "unavailable"}
    idx = _closest_hour_index(hourly.get("time", []), local)
    if idx is None:
        return {"source": "unavailable"}
    out: dict = {"source": "open-meteo-forecast" if recent else "open-meteo-archive"}
    for key, field in _FIELDS.items():
        arr = hourly.get(field) or []
        out[key] = arr[idx] if idx < len(arr) else None
    if recent:
        out["fetched_at"] = fetched_at.isoformat() if fetched_at else None
        out["stale"] = stale
    return out


def _closest_hour_index(times: list, when: datetime) -> int | None:
    """The hour nearest `when`. Unix seconds (timeformat=unixtime) are matched on
    the instant; local ISO strings (an older answer) on the wall clock, which gives
    both passes of 02:00-03:00 on the night the clocks go back the same hour."""
    wall = when.replace(tzinfo=None)
    best_i: int | None = None
    best_diff: float | None = None
    for i, t in enumerate(times):
        if isinstance(t, int | float) and not isinstance(t, bool):
            if when.tzinfo is None:
                continue
            diff = abs(t - when.timestamp())
        else:
            try:
                ts = datetime.fromisoformat(t)
            except (TypeError, ValueError):
                continue
            diff = abs((ts - wall).total_seconds())
        if best_diff is None or diff < best_diff:
            best_i, best_diff = i, diff
    return best_i
