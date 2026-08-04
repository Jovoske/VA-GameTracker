"""Thermal (gravity) winds: what the air does when the forecast says nothing.

The synoptic forecast comes from one grid point of order 2-11 km. On a calm evening
that number is not the wind a hunter is standing in. What actually happens on a
slope is driven by the ground cooling:

- **Katabatic / drainage.** After sunset the surface radiates heat away, the air
  touching it gets dense, and it runs downhill like water. In a barranco this is
  the wind, and it is remarkably reliable: same direction, every clear calm night.
- **Anabatic / upslope.** The reverse during the day, as sun-warmed slopes lift air.
  Mostly irrelevant to an evening sit, included because the transition is what makes
  the hour before dark treacherous.

This module decides which regime is running and, when it is thermal, replaces the
forecast bearing with the one the slope dictates. It is a tendency, not a
measurement: it needs clear skies to work, it reverses around dusk and dawn, and a
~90 m DEM knows the hillside but not the gully. So it says so, every time.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.enrichment.astro import solar
from app.forecasting.wind import LIGHT_WIND_KMH, compass
from app.terrain import get_grid, slope_at

# Below this slope there is no fall line worth speaking of; flat ground gets no
# drainage verdict rather than a randomly-rounded bearing off DEM noise.
MIN_SLOPE_PCT = 1.5

# Radiative cooling is what drives drainage. Under heavy cloud the ground holds its
# heat and the effect largely fails to develop.
MAX_CLOUD_PCT = 75.0

# Drainage builds after sunset and is established within about this long.
SETTLING = timedelta(minutes=45)


def _speed_estimate(slope_pct: float) -> float:
    """Rough drainage speed in km/h from slope. Deliberately conservative.

    Katabatic flows on moderate slopes typically run 2-8 km/h. This is a scale, not
    a measurement, and it is only ever used to say "gentle" or "moving".
    """
    return round(min(8.0, 1.5 + slope_pct * 0.35), 1)


def regime(
    db: Session,
    *,
    lat: float | None,
    lon: float | None,
    when: datetime,
    wind_dir_deg: float | None,
    wind_speed_kmh: float | None,
    cloud_pct: float | None = None,
) -> dict:
    """Which wind is actually running at this spot, and where it goes.

    Returns a dict with `source` ('synoptic' | 'katabatic' | 'anabatic' | 'unknown'),
    an effective `wind_dir_deg` (the direction it blows FROM, matching the forecast
    convention so callers need no special case), and `text` explaining itself.
    """
    # A real wind overrides the slope. Thermals are a calm-evening phenomenon; once
    # the synoptic flow is up it mixes them out.
    if wind_speed_kmh is not None and wind_speed_kmh >= LIGHT_WIND_KMH:
        return {
            "source": "synoptic",
            "wind_dir_deg": wind_dir_deg,
            "wind_speed_kmh": wind_speed_kmh,
            "text": None,
        }

    if lat is None or lon is None:
        return {"source": "unknown", "wind_dir_deg": wind_dir_deg,
                "wind_speed_kmh": wind_speed_kmh, "text": None}

    grid = get_grid(db)
    if grid is None:
        return {
            "source": "unknown", "wind_dir_deg": wind_dir_deg, "wind_speed_kmh": wind_speed_kmh,
            "text": "No terrain loaded, so drainage cannot be worked out.",
        }

    slope = slope_at(grid, lat, lon)
    if slope is None or slope.get("downhill_deg") is None or slope["slope_pct"] < MIN_SLOPE_PCT:
        return {
            "source": "unknown", "wind_dir_deg": wind_dir_deg, "wind_speed_kmh": wind_speed_kmh,
            "text": "Ground is near flat here — no fall line to drain along.",
            "slope": slope,
        }

    if cloud_pct is not None and cloud_pct > MAX_CLOUD_PCT:
        return {
            "source": "unknown", "wind_dir_deg": wind_dir_deg, "wind_speed_kmh": wind_speed_kmh,
            "text": (
                f"Overcast ({round(cloud_pct)}%) holds the day's heat in, so the slope "
                "will not drain properly tonight. Nothing reliable to tell you."
            ),
            "slope": slope,
        }

    s = solar(settings.estate_lat, settings.estate_lon, when.date())
    sunset, sunrise = s.get("sunset"), s.get("sunrise")
    local = when.astimezone(__import__("zoneinfo").ZoneInfo(settings.estate_timezone))

    downhill = float(slope["downhill_deg"])
    # Air arrives FROM uphill and leaves downhill; the forecast convention is the
    # direction it blows from, so the drainage "wind_dir" is the uphill bearing.
    uphill = (downhill + 180.0) % 360.0
    speed = _speed_estimate(slope["slope_pct"])

    draining = False
    if sunset is not None:
        try:
            draining = local >= (sunset - timedelta(minutes=30))
            if sunrise is not None and local.time() < sunrise.time():
                draining = True  # still before dawn: drainage has been running all night
        except Exception:
            draining = local.hour >= 19 or local.hour <= 6
    else:
        draining = local.hour >= 19 or local.hour <= 6

    if draining:
        settled = sunset is None or local >= (sunset + SETTLING)
        return {
            "source": "katabatic",
            "wind_dir_deg": uphill,
            "wind_speed_kmh": speed,
            "slope": slope,
            "confidence": "moderate" if settled else "low",
            "text": (
                f"Forecast is calm, so the slope decides: cold air drains "
                f"{compass(downhill)} downhill at roughly {speed} km/h "
                f"({slope['slope_pct']}% fall). "
                + ("" if settled else "It is still turning over around dusk, so expect it to swing. ")
                + "Your scent goes with it."
            ),
        }

    # Daytime with a calm forecast: slopes lift air instead.
    return {
        "source": "anabatic",
        "wind_dir_deg": downhill,   # upslope flow arrives from below
        "wind_speed_kmh": speed,
        "slope": slope,
        "confidence": "low",
        "text": (
            f"Calm and sunny — air is being drawn up the slope toward "
            f"{compass(uphill)}. It will reverse and run back down within the hour "
            "either side of sunset."
        ),
    }
