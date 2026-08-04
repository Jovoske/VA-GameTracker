"""Bedding-aware wind advice: where your scent goes, and whether it lands on deer.

The wind module already does the trigonometry, but it stays silent without approach
arcs, and arcs never got entered because nobody thinks in bearings. Bedding does the
job instead: if they lie up over there, that is the direction they come from, and it
is also the ground your scent must not reach.

Three products, in decreasing order of how much they can be trusted:

1. **Approach bearings per stand** — derived, not guessed: the bearing from the stand
   to each bedding area within range. This is plain geometry over ground the hunter
   drew, so it is as good as the drawing.
2. **Safe ground for tonight** — a grid of where a person could sit without their
   scent drifting into bedding. Also plain geometry, but it knows nothing about
   terrain, cover, access or safe backstops, so it narrows the choice rather than
   making it.
3. **Routes** — which bedding areas feed which cameras, from detection history. The
   weakest of the three and gated on evidence; a straight line between two points is
   a cartoon of how an animal actually moves.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import geo
from app.core.config import settings
from app.forecasting.wind import SCENT_CONE_DEG
from app.models import Camera, Detection, Image, Zone

# How far a hunter's scent stays concentrated enough for a deer to act on it. A
# working figure, not a measurement: it varies with humidity, cover and the animal.
# Deliberately generous, because the cost of a false "clean" is a burnt stand.
SCENT_RANGE_M = 800.0

# Bedding further than this from a stand is not what that stand is hunting, and
# including it would make every stand look compromised from every wind.
BEDDING_RELEVANT_M = 1500.0

# Route inference: a camera must have seen this much to be called a destination.
MIN_ROUTE_DETECTIONS = 5
_TZ = settings.estate_timezone


def bedding_zones(db: Session) -> list[Zone]:
    return list(db.scalars(select(Zone).where(Zone.kind == "bedding")).all())


def _zone_point(z: Zone) -> tuple[float, float] | None:
    return geo.centroid(z.polygon)


def scent_hits_zone(
    lat: float, lon: float, zone: Zone, scent_bearing: float, *, max_range: float = SCENT_RANGE_M
) -> tuple[bool, float]:
    """Does scent from (lat, lon) drift into this zone? Returns (hit, distance_m).

    The cone is centred on where the scent goes, half-width SCENT_CONE_DEG/2. Being
    inside the polygon counts as a hit at any wind — you are in their bedroom.
    """
    pt = _zone_point(zone)
    if pt is None:
        return (False, float("inf"))
    dist = geo.distance_to_polygon_m(zone.polygon, lat, lon)
    if dist == 0.0:
        return (True, 0.0)
    if dist > max_range:
        return (False, dist)
    to_zone = geo.bearing(lat, lon, pt[0], pt[1])
    return (geo.angular_distance(to_zone, scent_bearing) <= SCENT_CONE_DEG / 2.0, dist)


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
        return {"status": "no_position", "text": f"{stand_name} has no position on the map yet."}
    if not zones:
        return {
            "status": "no_bedding",
            "text": "No bedding drawn yet — draw where they lie up and this turns into advice.",
        }
    if wind_dir_deg is None or wind_speed_kmh is None:
        return {"status": "no_wind_data", "text": "No wind forecast for tonight — check it yourself."}

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
            "text": (
                f"Wind {compass(wind_dir_deg)} {round(wind_speed_kmh)} km/h — too light to call. "
                + (reg.get("text") or "Thermals will decide this one; read them at the truck.")
            ),
        }

    eff_dir = float(reg["wind_dir_deg"])
    eff_speed = float(reg["wind_speed_kmh"])
    scent_bearing = (eff_dir + 180.0) % 360.0

    hits = []
    for z in zones:
        hit, dist = scent_hits_zone(lat, lon, z, scent_bearing)
        if hit:
            hits.append({"zone": z.name, "zone_id": str(z.id), "distance_m": round(dist)})
    hits.sort(key=lambda h: h["distance_m"])

    # Name what is moving the air before what it does, so a slope-driven verdict is
    # never mistaken for a forecast one — but say it once. The regime module's own
    # sentence is for the map headline; repeating it here read as a stutter.
    slope_pct = (reg.get("slope") or {}).get("slope_pct")
    if source == "synoptic":
        lead = f"Wind {compass(eff_dir)} {round(eff_speed)} km/h"
    elif source == "katabatic":
        lead = (
            f"Forecast calm, so the slope decides — cold air drains "
            f"{compass(scent_bearing)} at ~{round(eff_speed, 1)} km/h"
            + (f" ({slope_pct}% fall)" if slope_pct else "")
        )
    else:
        lead = (
            f"Calm and sunny — air is drawn upslope {compass(scent_bearing)} "
            f"at ~{round(eff_speed, 1)} km/h"
        )

    # A drainage call is only as good as the conditions holding; dusk is when it turns.
    caveat = ""
    if source != "synoptic":
        caveat = (
            " It reverses around dusk, so check it on the ground."
            if reg.get("confidence") == "low"
            else " A ~90 m terrain model sees the hillside, not your gully."
        )

    if hits:
        first = hits[0]
        return {
            "status": "scent_carries",
            "source": source,
            "confidence": reg.get("confidence"),
            "scent_bearing": round(scent_bearing),
            "slope": reg.get("slope"),
            "hit_zones": hits,
            "text": (
                f"{lead}, carrying your scent into {first['zone']} "
                f"{first['distance_m']} m away.{caveat}"
                if source != "synoptic"
                else f"{lead} — your scent runs {compass(scent_bearing)} into "
                     f"{first['zone']}, {first['distance_m']} m away."
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
        "slope": reg.get("slope"),
        "hit_zones": [],
        "text": (
            f"{lead}, away from bedding ({round(nearest)} m to the nearest).{caveat}"
            if source != "synoptic"
            else f"{lead} — clean. Scent goes {compass(scent_bearing)}, away from "
                 f"bedding ({round(nearest)} m to the nearest)."
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
        return {"status": "no_bedding", "cells": [], "note": "Draw bedding to see this."}
    if wind_dir_deg is None or wind_speed_kmh is None:
        return {"status": "no_wind_data", "cells": [], "note": "No wind forecast for tonight."}

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
            "note": probe.get("text") or "Wind too light to map — thermals decide on an evening like this.",
        }
    tgrid = get_grid(db) if mode != "synoptic" else None

    b = geo.bounds([z.polygon for z in zones])
    if b is None:
        return {"status": "no_bedding", "cells": [], "note": "Draw bedding to see this."}
    min_lat, min_lon, max_lat, max_lon = b
    # Expand the box by roughly the scent range so the useful ground around the
    # bedding is included, not just the bedding itself.
    pad_lat = SCENT_RANGE_M / 111_000.0
    pad_lon = pad_lat * 1.4
    min_lat, max_lat = min_lat - pad_lat, max_lat + pad_lat
    min_lon, max_lon = min_lon - pad_lon, max_lon + pad_lon

    uniform_bearing = (float(probe["wind_dir_deg"]) + 180.0) % 360.0
    cells = []
    for i in range(steps):
        for j in range(steps):
            lat = min_lat + (max_lat - min_lat) * (i + 0.5) / steps
            lon = min_lon + (max_lon - min_lon) * (j + 0.5) / steps
            inside = any(geo.contains(z.polygon, lat, lon) for z in zones)
            if inside:
                continue  # standing in the bedding is not a "spot", safe or otherwise
            near = min(geo.distance_to_polygon_m(z.polygon, lat, lon) for z in zones)
            if near > SCENT_RANGE_M * 1.5:
                continue  # too far away to be a decision about this bedding

            if tgrid is not None:
                # Drainage: scent follows this cell's own fall line, not one bearing
                # for the whole estate. Cells with no slope get no verdict rather
                # than a borrowed one.
                sl = slope_at(tgrid, lat, lon)
                if sl is None or sl.get("downhill_deg") is None:
                    continue
                cell_bearing = float(sl["downhill_deg"])
            else:
                cell_bearing = uniform_bearing

            hit = any(scent_hits_zone(lat, lon, z, cell_bearing)[0] for z in zones)
            cells.append({"lat": round(lat, 6), "lon": round(lon, 6),
                          "safe": not hit, "nearest_m": round(near),
                          "bearing": round(cell_bearing)})

    note = (
        "Geometry only — this knows nothing about cover, access or a safe backstop. "
        "It narrows where to look; it does not pick the seat."
    )
    if mode != "synoptic":
        note = (
            "Forecast is calm, so this follows the ground: each square uses its own "
            "fall line, because cold air drains downhill after dark. A ~90 m terrain "
            "model sees the hillside, not the gully you are sitting in."
        )
    return {
        "status": "ok",
        "source": mode,
        "scent_bearing": round(uniform_bearing),
        "cells": cells,
        "note": note,
    }


def routes(db: Session) -> list[dict]:
    """Which bedding areas feed which cameras, from detection history.

    A straight line between a bedding outline and a camera is a cartoon of how an
    animal moves - it will not follow the contour, the cover or the track. It is
    shown because knowing *that* a link exists is useful even when the drawn line is
    wrong, and it is gated on repeat evidence so a single wanderer is not a route.
    """
    zones = [z for z in bedding_zones(db) if _zone_point(z)]
    if not zones:
        return []
    cams = [
        c for c in db.scalars(select(Camera)).all() if c.lat is not None and c.lon is not None
    ]
    if not cams:
        return []

    counts = dict(
        db.execute(
            select(Image.camera_id, func.count(Detection.id))
            .join(Detection, Detection.image_id == Image.id)
            .group_by(Image.camera_id)
        ).all()
    )
    # The hour animals show at a camera hints at how far along the move it sits:
    # early evening near the bed, later further out.
    hour_expr = func.avg(
        func.extract("hour", func.timezone(_TZ, Image.captured_at))
    )
    hours = dict(
        db.execute(
            select(Image.camera_id, hour_expr)
            .join(Detection, Detection.image_id == Image.id)
            .group_by(Image.camera_id)
        ).all()
    )

    out = []
    for z in zones:
        pt = _zone_point(z)
        for c in cams:
            n = int(counts.get(c.id, 0) or 0)
            if n < MIN_ROUTE_DETECTIONS:
                continue
            dist = geo.distance_to_polygon_m(z.polygon, c.lat, c.lon)
            if dist > BEDDING_RELEVANT_M:
                continue
            avg_hour = hours.get(c.id)
            out.append({
                "zone": z.name,
                "zone_id": str(z.id),
                "camera": c.name,
                "camera_id": str(c.id),
                "from": {"lat": pt[0], "lon": pt[1]},
                "to": {"lat": c.lat, "lon": c.lon},
                "detections": n,
                "distance_m": round(dist),
                "avg_hour": round(float(avg_hour)) if avg_hour is not None else None,
                "confidence": "low",  # one month of data; never claim more than this
            })
    return sorted(out, key=lambda r: -r["detections"])
