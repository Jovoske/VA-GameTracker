"""Solar (sun/twilight) and lunar data. Sun via astral (offline); moon via synodic calc."""
from __future__ import annotations

import math
from datetime import date, datetime, timezone

from astral import Observer
from astral.sun import dusk, sunrise, sunset

MOON_PHASES = [
    "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
]
_REF_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
_SYNODIC_SECONDS = 29.53058867 * 86400


def moon_phase(dt: datetime) -> tuple[str, float]:
    """(phase name, illumination %) for an instant."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    frac = ((dt - _REF_NEW_MOON).total_seconds() % _SYNODIC_SECONDS) / _SYNODIC_SECONDS
    illum = (1 - math.cos(2 * math.pi * frac)) / 2
    return MOON_PHASES[int(frac * 8) % 8], round(illum * 100, 1)


def _safe(fn, obs: Observer, on_date: date, **kw) -> datetime | None:
    try:
        return fn(obs, date=on_date, **kw)
    except Exception:
        return None


def solar(lat: float, lng: float, on_date: date) -> dict:
    obs = Observer(latitude=lat, longitude=lng)
    out: dict = {
        "sunrise": _safe(sunrise, obs, on_date),
        "sunset": _safe(sunset, obs, on_date),
        "civil_twilight_end": _safe(dusk, obs, on_date, depression=6),
        "nautical_twilight_end": _safe(dusk, obs, on_date, depression=12),
    }
    sr, ss = out["sunrise"], out["sunset"]
    if sr and ss and ss > sr:
        daylight_min = (ss - sr).total_seconds() / 60
        out["darkness_minutes"] = int(round(1440 - daylight_min))
    else:
        out["darkness_minutes"] = None
    return out
