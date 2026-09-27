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


def phase_words(phase: str) -> str:
    """A MOON_PHASES name ("Full Moon", kept as data) as the reader says it."""
    from app.i18n import t

    if phase not in MOON_PHASES:
        return phase
    return t(f"moon.{phase.lower().replace(' ', '_')}")
_SYNODIC_SECONDS = 29.53058867 * 86400


def moon_phase(dt: datetime) -> tuple[str, float]:
    """(phase name, illumination %) for an instant."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    frac = ((dt - _REF_NEW_MOON).total_seconds() % _SYNODIC_SECONDS) / _SYNODIC_SECONDS
    illum = (1 - math.cos(2 * math.pi * frac)) / 2
    # Each name is centred on its exact phase (the full moon night reads "Full Moon",
    # not the three nights after it, audit F-21).
    return MOON_PHASES[int(frac * 8 + 0.5) % 8], round(illum * 100, 1)


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
