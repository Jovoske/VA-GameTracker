"""The ground the estate covers: where its stands, cameras and bedding are.

Two things need a box around the estate rather than one point at its centre:

- the hill shape (terrain.fetch_grid), which used to be a fixed 5 km square round the
  configured centre, so a stand 3 km out was told its ground was flat (audit B-20);
- the map saved on a phone for use with no signal, which should cover the estate and
  nothing more (tile providers' terms, and the phone's storage).

The box for the phone is the one an admin set (Map sheet: "Use this view as the
estate"), else one drawn round everything placed, with a margin. Kept in
app_settings: one small document, no table of its own.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import geo
from app.core.config import settings
from app.models import AppSetting, Camera, Stand, Zone

BOX_KEY = "estate_offline_box"
# Round what is placed, so a stand on the edge has ground around it on the map.
MARGIN_M = 500.0
# Nothing much smaller than this is worth saving, and nothing larger is one estate:
# a phone keeps roughly a thousand map squares at the useful zooms for 15 km across.
MIN_SIDE_M = 1_000.0
MAX_SIDE_M = 15_000.0
# With nothing placed yet: a square this wide round the configured centre.
DEFAULT_SIDE_M = 4_000.0

Box = dict  # {"south", "west", "north", "east"} in degrees


def _m_per_deg_lon(lat: float) -> float:
    return 111_320.0 * max(0.1, math.cos(math.radians(lat)))


def side_m(box: Box) -> tuple[float, float]:
    """(east-west, north-south) size of a box in metres."""
    mid = (box["south"] + box["north"]) / 2
    return ((box["east"] - box["west"]) * _m_per_deg_lon(mid),
            (box["north"] - box["south"]) * 111_320.0)


def around(points: list[tuple[float, float]], margin_m: float) -> Box | None:
    """The box round (lat, lon) points, grown by margin_m on every side."""
    pts = [p for p in points if geo.plausible_position(p[0], p[1])]
    if not pts:
        return None
    south, north = min(p[0] for p in pts), max(p[0] for p in pts)
    west, east = min(p[1] for p in pts), max(p[1] for p in pts)
    mid = (south + north) / 2
    dlat, dlon = margin_m / 111_320.0, margin_m / _m_per_deg_lon(mid)
    return {"south": south - dlat, "west": west - dlon, "north": north + dlat, "east": east + dlon}


def square(lat: float, lon: float, side: float) -> Box:
    half_lat, half_lon = side / 2 / 111_320.0, side / 2 / _m_per_deg_lon(lat)
    return {"south": lat - half_lat, "west": lon - half_lon,
            "north": lat + half_lat, "east": lon + half_lon}


def placed_points(db: Session) -> list[tuple[float, float]]:
    """(lat, lon) of every placed stand and camera and every bedding corner."""
    pts = [(s.lat, s.lon) for s in db.scalars(select(Stand)).all()]
    pts += [(c.lat, c.lon) for c in db.scalars(select(Camera)).all()]
    for z in db.scalars(select(Zone)).all():
        pts += geo.ring(z.polygon)
    return [p for p in pts if geo.plausible_position(p[0], p[1])]


def _fit(box: Box, min_side: float, max_side: float) -> Box:
    """Grow a box to at least min_side a side, and cut one over max_side down round
    its middle."""
    ew, ns = side_m(box)
    mid_lat, mid_lon = (box["south"] + box["north"]) / 2, (box["west"] + box["east"]) / 2
    ew2, ns2 = min(max(ew, min_side), max_side), min(max(ns, min_side), max_side)
    half_lat, half_lon = ns2 / 2 / 111_320.0, ew2 / 2 / _m_per_deg_lon(mid_lat)
    return {"south": mid_lat - half_lat, "west": mid_lon - half_lon,
            "north": mid_lat + half_lat, "east": mid_lon + half_lon}


def suggested_box(db: Session) -> Box:
    """Everything placed plus MARGIN_M, or a DEFAULT_SIDE_M square round the centre."""
    box = around(placed_points(db), MARGIN_M)
    if box is None:
        return square(settings.estate_lat, settings.estate_lon, DEFAULT_SIDE_M)
    return _fit(box, MIN_SIDE_M, MAX_SIDE_M)


def saved_box(db: Session) -> dict | None:
    row = db.get(AppSetting, BOX_KEY)
    value = row.value if row else None
    return value if value and all(k in value for k in ("south", "west", "north", "east")) else None


def check_box(box: Box) -> Box:
    """A box an admin asked for, or ValueError saying what is wrong with it."""
    s, w, n, e = (box.get(k) for k in ("south", "west", "north", "east"))
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (s, w, n, e)):
        raise ValueError("The box needs four numbers: south, west, north and east.")
    if not (-90 <= s < n <= 90 and -180 <= w < e <= 180):
        raise ValueError("That box is off the map.")
    ew, ns = side_m({"south": s, "west": w, "north": n, "east": e})
    if max(ew, ns) > MAX_SIDE_M:
        raise ValueError(
            f"That is {max(ew, ns) / 1000:.0f} km across, more than a phone should keep. "
            f"Zoom in so the estate is under {MAX_SIDE_M / 1000:.0f} km across."
        )
    if min(ew, ns) < MIN_SIDE_M / 4:
        raise ValueError("That is too small to be the estate. Zoom out a little.")
    return {"south": s, "west": w, "north": n, "east": e}


def save_box(db: Session, box: Box, by: str) -> dict:
    value = {**check_box(box), "set_by": by, "set_at": datetime.now(UTC).isoformat()}
    row = db.get(AppSetting, BOX_KEY)
    if row is None:
        db.add(AppSetting(key=BOX_KEY, value=value))
    else:
        row.value = value
    db.commit()
    return value


def clear_box(db: Session) -> None:
    row = db.get(AppSetting, BOX_KEY)
    if row is not None:
        db.delete(row)
        db.commit()


def terrain_box(db: Session, centre_lat: float, centre_lon: float, base_side_m: float,
                max_side_m: float) -> Box:
    """What the hill shape should cover: the square round the centre it always had,
    grown to take in everything placed (plus a margin), up to max_side_m a side."""
    base = square(centre_lat, centre_lon, base_side_m)
    placed = around(placed_points(db), MARGIN_M)
    if placed is None:
        return base
    union = {k: min(base[k], placed[k]) for k in ("south", "west")}
    union |= {k: max(base[k], placed[k]) for k in ("north", "east")}
    return _fit(union, base_side_m, max_side_m)
