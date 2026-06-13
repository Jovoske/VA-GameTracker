"""Per-sighting weather from Open-Meteo at the photo's REAL capture time.

This is the direct fix for the legacy bug where every sighting was stamped with
the weather at processing time instead of when the animal was photographed.
"""
from __future__ import annotations

from datetime import datetime, timezone
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


# Cache one day's hourly data per (lat, lng, day) so a backfill of many photos from
# the same camera-day makes a single Open-Meteo call instead of one per photo.
_DAY_CACHE: dict = {}


def _fetch_day_hourly(lat: float, lng: float, day: str, recent: bool, tz: str) -> dict:
    key = (lat, lng, day, recent, tz)
    if key in _DAY_CACHE:
        return _DAY_CACHE[key]
    url = FORECAST_URL if recent else ARCHIVE_URL
    params = {
        "latitude": lat, "longitude": lng, "hourly": HOURLY,
        "timezone": tz, "start_date": day, "end_date": day,
    }
    try:
        resp = httpx.get(url, params=params, timeout=20)
        resp.raise_for_status()
        hourly = resp.json().get("hourly", {})
    except Exception as e:
        log.warning("weather.fetch_failed", error=str(e))
        return {}  # not cached, so a transient failure is retried later
    if len(_DAY_CACHE) > 8192:
        _DAY_CACHE.clear()
    _DAY_CACHE[key] = hourly
    return hourly


def weather_at(lat: float, lng: float, when: datetime, tz: str = "Europe/Madrid") -> dict:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    local = when.astimezone(ZoneInfo(tz))
    # Archive lags ~5 days; use the forecast endpoint for recent captures.
    recent = (datetime.now(timezone.utc) - when).days < 5
    hourly = _fetch_day_hourly(round(lat, 4), round(lng, 4), local.date().isoformat(), recent, tz)
    if not hourly:
        return {"source": "unavailable"}
    idx = _closest_hour_index(hourly.get("time", []), local)
    if idx is None:
        return {"source": "unavailable"}
    out: dict = {"source": "open-meteo-forecast" if recent else "open-meteo-archive"}
    for key, field in _FIELDS.items():
        arr = hourly.get(field) or []
        out[key] = arr[idx] if idx < len(arr) else None
    return out


def _closest_hour_index(times: list[str], local: datetime) -> int | None:
    target = local.replace(tzinfo=None)
    best_i: int | None = None
    best_diff: float | None = None
    for i, t in enumerate(times):
        try:
            ts = datetime.fromisoformat(t)
        except ValueError:
            continue
        diff = abs((ts - target).total_seconds())
        if best_diff is None or diff < best_diff:
            best_i, best_diff = i, diff
    return best_i
