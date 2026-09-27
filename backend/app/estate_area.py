"""The ground the estate covers: where its stands, cameras and bedding are.

Two things need a box around the estate rather than one point at its centre:

- the hill shape (terrain.fetch_grid), which used to be a fixed 5 km square round the
  configured centre, so a stand 3 km out was told its ground was flat (audit B-20);
- the map saved on a phone for use with no signal, which should cover the estate and
  nothing more (tile providers' terms, and the phone's storage).

The box for the phone is the one an admin set (Map sheet: "Use this view as the
estate"), else one drawn round everything placed, with a margin. Kept in
app_settings: one small document, no table of its own.

"Everything placed" is what is out on the estate: the stands and bedding (put on the
map by hand), and the cameras that are connected, not retired, and within
CAMERA_REACH_M of a stand, a bedding outline or the estate's centre. A SPYPOINT fix
from a cell tower can be kilometres off, and a camera taken home to charge reports
home: one such camera used to pull both boxes off the estate (review R4FE-1). Those
are named (cameras_left_out) so an admin can place them by hand.
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
# Round what is placed, so a stand on the edge has ground around it on the map, and
# a phone held upright, fitted to the estate, has its whole screen of it.
MARGIN_M = 1_000.0
# Nothing much smaller than this is worth saving, and nothing larger is one estate:
# a phone keeps roughly a thousand map squares at the useful zooms for 15 km across.
MIN_SIDE_M = 2_000.0
MAX_SIDE_M = 15_000.0
# With nothing placed yet: a square this wide round the configured centre.
DEFAULT_SIDE_M = 4_000.0
# A camera further than this from every stand, bedding corner and the estate's centre
# isn't on the estate, whatever its GPS says.
CAMERA_REACH_M = 8_000.0

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


def _hand_placed(db: Session) -> list[tuple[float, float]]:
    """(lat, lon) of every stand and every bedding corner: put on the map by hand."""
    pts = [(s.lat, s.lon) for s in db.scalars(select(Stand)).all()]
    for z in db.scalars(select(Zone)).all():
        pts += geo.ring(z.polygon)
    return [p for p in pts if geo.plausible_position(p[0], p[1])]


def _cameras(db: Session, hand: list[tuple[float, float]]
             ) -> tuple[list[Camera], list[tuple[Camera, float]]]:
    """The cameras out on the estate now, and those left out as too far from it (each
    with its distance to the nearest stand, bedding corner or the centre, in metres).
    A camera that isn't connected or is retired is in neither: it isn't out there."""
    refs = [*hand, (settings.estate_lat, settings.estate_lon)]
    kept: list[Camera] = []
    far: list[tuple[Camera, float]] = []
    rows = db.scalars(select(Camera).where(Camera.active.is_(True), Camera.retired_at.is_(None))
                      .order_by(Camera.name)).all()
    for c in rows:
        if not geo.plausible_position(c.lat, c.lon):
            continue
        near = min(geo.distance_m(c.lat, c.lon, lat, lon) for lat, lon in refs)
        if near <= CAMERA_REACH_M:
            kept.append(c)
        else:
            far.append((c, near))
    return kept, far


def estate_points(db: Session) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """(everything on the estate, the stands and bedding alone), as (lat, lon)."""
    hand = _hand_placed(db)
    kept, _ = _cameras(db, hand)
    return hand + [(c.lat, c.lon) for c in kept], hand


def cameras_left_out(db: Session) -> list[dict]:
    """Connected cameras whose position is too far from the estate to be on it: left
    out of the box a phone saves and of the hill shape."""
    _, far = _cameras(db, _hand_placed(db))
    return [{"id": str(c.id), "name": c.name, "km": round(d / 1000)} for c, d in far]


def _window(lo: float, hi: float, focus_lo: float, focus_hi: float,
            size: float) -> tuple[float, float]:
    """[lo, hi] made `size` wide (degrees). A short one grows round its middle; a long
    one is cut round the middle of [focus_lo, focus_hi], kept inside [lo, hi], so what
    goes is the far edge of the rest, not the focus."""
    if hi - lo <= size:
        mid = (lo + hi) / 2
        return mid - size / 2, mid + size / 2
    start = min(max((focus_lo + focus_hi) / 2 - size / 2, lo), hi - size)
    return start, start + size


def _fit(box: Box, min_side: float, max_side: float, focus: Box | None = None) -> Box:
    """Grow a box to at least min_side a side, and cut one over max_side down round
    `focus` (the stands and bedding, or the centre)."""
    ew, ns = side_m(box)
    f = focus or box
    mid_lat = (box["south"] + box["north"]) / 2
    ew2, ns2 = min(max(ew, min_side), max_side), min(max(ns, min_side), max_side)
    south, north = _window(box["south"], box["north"], f["south"], f["north"], ns2 / 111_320.0)
    west, east = _window(box["west"], box["east"], f["west"], f["east"],
                         ew2 / _m_per_deg_lon(mid_lat))
    return {"south": south, "west": west, "north": north, "east": east}


def suggested_box(db: Session) -> Box:
    """Everything on the estate plus MARGIN_M, or a DEFAULT_SIDE_M square round the
    centre. Cut to MAX_SIDE_M round the stands and bedding (or the centre) when wider."""
    points, hand = estate_points(db)
    home = square(settings.estate_lat, settings.estate_lon, DEFAULT_SIDE_M)
    box = around(points, MARGIN_M)
    if box is None:
        return home
    return _fit(box, MIN_SIDE_M, MAX_SIDE_M, around(hand, MARGIN_M) or home)


def saved_box(db: Session) -> dict | None:
    row = db.get(AppSetting, BOX_KEY)
    value = row.value if row else None
    return value if value and all(k in value for k in ("south", "west", "north", "east")) else None


def check_box(box: Box) -> Box:
    """A box an admin asked for, or ValueError saying what is wrong with it."""
    s, w, n, e = (box.get(k) for k in ("south", "west", "north", "east"))
    if not all(isinstance(v, int | float) and math.isfinite(v) for v in (s, w, n, e)):
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
    grown to take in everything on the estate (plus a margin), up to max_side_m a
    side, cut round the stands and bedding when it would be wider."""
    base = square(centre_lat, centre_lon, base_side_m)
    points, hand = estate_points(db)
    placed = around(points, MARGIN_M)
    if placed is None:
        return base
    union = {k: min(base[k], placed[k]) for k in ("south", "west")}
    union |= {k: max(base[k], placed[k]) for k in ("north", "east")}
    return _fit(union, base_side_m, max_side_m, around(hand, MARGIN_M) or base)
