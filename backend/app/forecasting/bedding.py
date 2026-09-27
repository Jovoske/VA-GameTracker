"""Bedding-aware wind advice: where your scent goes, and whether it lands on deer.

The wind module already does the trigonometry, but it stays silent without approach
arcs, and arcs never got entered because nobody thinks in bearings. Bedding does the
job instead: if they lie up over there, that is the direction they come from, and it
is also the ground your scent must not reach.

Two products, in decreasing order of how much they can be trusted:

1. **Approach bearings per stand** — derived, not guessed: the bearing from the stand
   to each bedding area within range. This is plain geometry over ground the hunter
   drew, so it is as good as the drawing.
2. **Safe ground for tonight** — a grid of where a person could sit without their
   scent drifting into bedding. Also plain geometry, but it knows nothing about
   terrain, cover, access or safe backstops, so it narrows the choice rather than
   making it.

The "routes" from each bedding area to every camera near it are gone: they encoded
distance, not movement (audit G-25). The map's likely paths come from the cameras'
own sequence of visits (activity.usual_paths).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import geo
from app.forecasting.wind import SCENT_CONE_DEG
from app.i18n import t
from app.models import Zone

# How far a hunter's scent stays concentrated enough for a deer to act on it. A
# working figure, not a measurement: it varies with humidity, cover and the animal.
# Deliberately generous, because the cost of a false "clean" is a burnt stand.
SCENT_RANGE_M = 800.0

# Bedding further than this from a stand is not what that stand is hunting, and
# including it would make every stand look compromised from every wind.
BEDDING_RELEVANT_M = 1500.0



def bedding_zones(db: Session) -> list[Zone]:
    return list(db.scalars(select(Zone).where(Zone.kind == "bedding")).all())


def _zone_point(z: Zone) -> tuple[float, float] | None:
    return geo.centroid(z.polygon)


def scent_geometry(speed_kmh: float, source: str, confidence: str | None = None) -> dict:
    """How far and how wide the plume reaches, given the air that is moving it.

    A fixed cone was drawn the same in a gale and a drift, which flattered both. Two
    honest dependencies:

    - **Range grows with speed.** Faster air pushes scent further before it dilutes
      below the point a deer reacts to.
    - **Width grows with uncertainty.** A steady strong wind holds a tight line;
      light air wanders, and drainage meanders with the ground it is running over,
      so both deserve a wider cone than a confident forecast does.

    Returned to the client as well as used for the hit test, so the shape drawn on
    the map is exactly the shape that was tested — a cone that looked narrower than
    the test would quietly excuse a stand the app had already condemned.
    """
    range_m = max(350.0, min(1100.0, 300.0 + speed_kmh * 40.0))
    if source != "synoptic":
        half = 32.0          # drainage follows the ground, not a straight line
    elif speed_kmh >= 20:
        half = 16.0
    elif speed_kmh >= 12:
        half = 20.0
    else:
        half = 28.0
    if confidence == "low":
        half += 8.0          # dusk reversal, or a regime still turning over
    return {"range_m": round(range_m), "half_deg": round(min(half, 45.0), 1)}


def scent_hits_zone(
    lat: float, lon: float, zone: Zone, scent_bearing: float, *,
    max_range: float = SCENT_RANGE_M, half_deg: float = SCENT_CONE_DEG / 2.0,
) -> tuple[bool, float]:
    """Does scent from (lat, lon) drift into this zone? Returns (hit, distance_m):
    on a hit, how far to the nearest bedding the plume reaches; otherwise how far to
    the bedding at all.

    Tested against the outline, not its middle, so scent blowing into the near end
    of a long strip is a hit (audit B-03). Being inside the polygon counts as a hit
    at any wind — you are in their bedroom.
    """
    if not geo.ring(zone.polygon):
        return (False, float("inf"))
    reach = geo.cone_reaches_polygon(zone.polygon, lat, lon, scent_bearing, half_deg, max_range)
    if reach is not None:
        return (True, reach)
    return (False, geo.distance_to_polygon_m(zone.polygon, lat, lon))


def approach_bearings(db: Session, lat: float | None, lon: float | None) -> list[dict]:
    """Directions animals approach from, derived from drawn bedding.

    `approach_dirs_deg` on a stand means "where they come FROM", which is exactly
    the bearing from the stand to the bedding.
    """
    if lat is None or lon is None:
        return []
    out = []
    for z in bedding_zones(db):
        pt = _zone_point(z)
        if pt is None:
            continue
        dist = geo.distance_to_polygon_m(z.polygon, lat, lon)
        if dist > BEDDING_RELEVANT_M:
            continue
        out.append({
            "zone_id": str(z.id),
            "zone": z.name,
            "approach_deg": round(geo.bearing(lat, lon, pt[0], pt[1])),
            "distance_m": round(dist),
        })
    return sorted(out, key=lambda r: r["distance_m"])


def stand_wind_report(
    db: Session, *, stand_name: str, lat: float | None, lon: float | None,
    wind_dir_deg: float | None, wind_speed_kmh: float | None,
    cloud_pct: float | None = None, when: datetime | None = None,
) -> dict:
    """Tonight's verdict for one position, using bedding as the thing to protect.

    When the forecast is too light to mean anything, the slope is consulted instead:
    on a clear calm evening cold air drains downhill and takes the hunter's scent
    with it, which is a far more useful answer than "read it at the truck". The
    refusal is kept for the cases that genuinely cannot be called — flat ground,
    heavy cloud, or no terrain loaded.
    """
    from app.forecasting import thermal
    from app.forecasting.wind import LIGHT_WIND_KMH, compass

    zones = [z for z in bedding_zones(db) if _zone_point(z)]
    if lat is None or lon is None:
        return {"status": "no_position", "text": t("bedding.no_position", stand=stand_name)}
    if not zones:
        return {"status": "no_bedding", "text": t("bedding.none")}
    if wind_dir_deg is None or wind_speed_kmh is None:
        return {"status": "no_wind_data", "text": t("wind.no_forecast")}

    reg = thermal.regime(
        db, lat=lat, lon=lon, when=when or datetime.now(timezone.utc),
        wind_dir_deg=wind_dir_deg, wind_speed_kmh=wind_speed_kmh, cloud_pct=cloud_pct,
    )
    source = reg["source"]
    if source == "unknown":
        return {
            "status": "too_light",
            "source": "unknown",
            "scent_bearing": round((wind_dir_deg + 180.0) % 360.0),
            "text": t("bedding.too_light", dir=compass(wind_dir_deg),
                      speed=round(wind_speed_kmh),
                      why=reg.get("text") or t("bedding.thermals_decide")),
        }

    eff_dir = float(reg["wind_dir_deg"])
    eff_speed = float(reg["wind_speed_kmh"])
    scent_bearing = (eff_dir + 180.0) % 360.0
    geom = scent_geometry(eff_speed, source, reg.get("confidence"))

    hits = []
    for z in zones:
        hit, dist = scent_hits_zone(
            lat, lon, z, scent_bearing,
            max_range=geom["range_m"], half_deg=geom["half_deg"],
        )
        if hit:
            hits.append({"zone": z.name, "zone_id": str(z.id), "distance_m": round(dist)})
    hits.sort(key=lambda h: h["distance_m"])

    # Name what is moving the air before what it does, so a slope-driven verdict is
    # never mistaken for a forecast one — but say it once. The regime module's own
    # sentence is for the map headline; repeating it here read as a stutter.
    slope_pct = (reg.get("slope") or {}).get("slope_pct")
    if source == "synoptic":
        lead = t("wind.reading", dir=compass(eff_dir), speed=round(eff_speed))
    elif source == "katabatic":
        lead = t("bedding.lead.katabatic", dir=compass(scent_bearing),
                 speed=round(eff_speed, 1),
                 fall=t("bedding.fall", pct=slope_pct) if slope_pct else "")
    else:
        lead = t("bedding.lead.anabatic", dir=compass(scent_bearing), speed=round(eff_speed, 1))

    # A drainage call is only as good as the conditions holding; dusk is when it turns.
    caveat = ""
    if source != "synoptic":
        caveat = (t("bedding.caveat.dusk") if reg.get("confidence") == "low"
                  else t("bedding.caveat.dem"))

    if hits:
        first = hits[0]
        # A seat drawn inside the bedding is in it whatever the wind: "0 m away" read
        # like a measuring error.
        where = (t("bedding.into_own", zone=first["zone"])
                 if first["distance_m"] == 0 else None)
        return {
            "status": "scent_carries",
            "source": source,
            "confidence": reg.get("confidence"),
            "scent_bearing": round(scent_bearing),
            "speed_kmh": round(eff_speed, 1),
            "range_m": geom["range_m"],
            "half_deg": geom["half_deg"],
            "slope": reg.get("slope"),
            "hit_zones": hits,
            "text": (
                t("bedding.carries.thermal", lead=lead, caveat=caveat,
                  where=where or t("bedding.into_near", zone=first["zone"],
                                   m=first["distance_m"]))
                if source != "synoptic"
                else t("bedding.carries.wind", lead=lead, dir=compass(scent_bearing),
                       where=where or t("bedding.into_far", zone=first["zone"],
                                        m=first["distance_m"]))
            ),
        }
    nearest = min(
        (geo.distance_to_polygon_m(z.polygon, lat, lon) for z in zones), default=float("inf")
    )
    return {
        "status": "clean",
        "source": source,
        "confidence": reg.get("confidence"),
        "scent_bearing": round(scent_bearing),
        "speed_kmh": round(eff_speed, 1),
        "range_m": geom["range_m"],
        "half_deg": geom["half_deg"],
        "slope": reg.get("slope"),
        "hit_zones": [],
        "text": (
            t("bedding.clean.thermal", lead=lead, m=round(nearest), caveat=caveat)
            if source != "synoptic"
            else t("bedding.clean.wind", lead=lead, dir=compass(scent_bearing), m=round(nearest))
        ),
    }


def safe_ground(
    db: Session, *, wind_dir_deg: float | None, wind_speed_kmh: float | None, steps: int = 26,
    cloud_pct: float | None = None, when: datetime | None = None,
) -> dict:
    """Grid of ground where scent would not reach bedding tonight.

    Returned as points with a safe flag rather than a polygon: the honest shape is
    ragged, and smoothing it into a tidy outline would imply precision the inputs
    (one weather grid point, a hand-drawn outline) do not have.
    """
    zones = [z for z in bedding_zones(db) if _zone_point(z)]
    if not zones:
        return {"status": "no_bedding", "cells": [], "note": t("bedding.draw")}
    if wind_dir_deg is None or wind_speed_kmh is None:
        return {"status": "no_wind_data", "cells": [], "note": t("bedding.no_forecast")}

    # Under a real wind every cell shares one scent bearing. Under drainage they do
    # not: air follows the fall line, which differs across the estate, so each cell
    # is evaluated against its own slope.
    from app.forecasting import thermal
    from app.terrain import get_grid, slope_at

    at = when or datetime.now(timezone.utc)
    # Probe the regime once, at the first bedding area, to decide which wind is
    # running tonight. Each cell then gets its own bearing below.
    probe_lat, probe_lon = _zone_point(zones[0])
    probe = thermal.regime(
        db, lat=probe_lat, lon=probe_lon, when=at,
        wind_dir_deg=wind_dir_deg, wind_speed_kmh=wind_speed_kmh, cloud_pct=cloud_pct,
    )
    mode = probe["source"]
    if mode == "unknown":
        return {
            "status": "too_light",
            "cells": [],
            "note": probe.get("text") or t("bedding.too_light_map"),
        }
    tgrid = get_grid(db) if mode != "synoptic" else None

    b = geo.bounds([z.polygon for z in zones])
    if b is None:
        return {"status": "no_bedding", "cells": [], "note": t("bedding.draw")}
    min_lat, min_lon, max_lat, max_lon = b
    # Expand the box by roughly the scent range so the useful ground around the
    # bedding is included, not just the bedding itself.
    pad_lat = SCENT_RANGE_M / 111_000.0
    pad_lon = pad_lat * 1.4
    min_lat, max_lat = min_lat - pad_lat, max_lat + pad_lat
    min_lon, max_lon = min_lon - pad_lon, max_lon + pad_lon

    uniform_bearing = (float(probe["wind_dir_deg"]) + 180.0) % 360.0
    # Same plume shape the stand verdicts use, so the shading and the markers can
    # never tell different stories about the same evening (audit B-14). Under a real
    # wind that is one shape for every square; under drainage each square's own
    # slope sets its speed, as it would for a stand placed there.
    geom = scent_geometry(float(probe["wind_speed_kmh"]), mode, probe.get("confidence"))
    cells = []
    for i in range(steps):
        for j in range(steps):
            lat = min_lat + (max_lat - min_lat) * (i + 0.5) / steps
            lon = min_lon + (max_lon - min_lon) * (j + 0.5) / steps
            inside = any(geo.contains(z.polygon, lat, lon) for z in zones)
            if inside:
                continue  # standing in the bedding is not a "spot", safe or otherwise
            near = min(geo.distance_to_polygon_m(z.polygon, lat, lon) for z in zones)
            if near > geom["range_m"] * 1.5:
                continue  # too far away to be a decision about this bedding

            cell_geom = geom
            if tgrid is not None:
                # Drainage: scent follows this cell's own fall line, not one bearing
                # for the whole estate. Cells too flat for a stand to get a verdict
                # get none either, rather than a borrowed one.
                sl = slope_at(tgrid, lat, lon)
                if (sl is None or sl.get("downhill_deg") is None
                        or sl["slope_pct"] < thermal.MIN_SLOPE_PCT):
                    continue
                downhill = float(sl["downhill_deg"])
                # Scent drains downhill after dark, and drifts uphill by day.
                cell_bearing = downhill if mode == "katabatic" else (downhill + 180.0) % 360.0
                cell_geom = scent_geometry(thermal._speed_estimate(sl["slope_pct"]), mode,
                                           probe.get("confidence"))
            else:
                cell_bearing = uniform_bearing

            hit = any(
                scent_hits_zone(lat, lon, z, cell_bearing, max_range=cell_geom["range_m"],
                                half_deg=cell_geom["half_deg"])[0]
                for z in zones
            )
            cells.append({"lat": round(lat, 6), "lon": round(lon, 6),
                          "safe": not hit, "nearest_m": round(near),
                          "bearing": round(cell_bearing)})

    note = t("bedding.safe.note") if mode == "synoptic" else t("bedding.safe.note_calm")
    return {
        "status": "ok",
        "source": mode,
        "scent_bearing": round(uniform_bearing),
        "cells": cells,
        "note": note,
    }

