"""Plain-lat/lon geometry. No PostGIS — the native build runs on vanilla Postgres,
and at estate scale (a few km across, a handful of polygons) doing this in Python is
both fast enough and far easier to reason about than SQL spatial types.

Everything here is deliberately simple and testable: bearings, distances, centroids
and point-in-polygon. Nothing pretends to be a projection-correct GIS.
"""
from __future__ import annotations

import math

EARTH_R_M = 6_371_000.0


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_M * math.asin(math.sqrt(a))


def destination(lat: float, lon: float, bearing_deg: float, dist_m: float) -> tuple[float, float]:
    """The point dist_m away along a bearing — used to draw scent cones on the map."""
    br = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    ad = dist_m / EARTH_R_M
    p2 = math.asin(math.sin(p1) * math.cos(ad) + math.cos(p1) * math.sin(ad) * math.cos(br))
    l2 = l1 + math.atan2(
        math.sin(br) * math.sin(ad) * math.cos(p1),
        math.cos(ad) - math.sin(p1) * math.sin(p2),
    )
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def ring(polygon: dict) -> list[tuple[float, float]]:
    """The outer ring of a GeoJSON Polygon as [(lat, lon), ...].

    Stored coordinates are GeoJSON order (lon, lat); everything else in this app
    speaks lat/lon, and mixing the two silently mirrors the estate about a
    diagonal, so the swap happens here once.
    """
    coords = (polygon or {}).get("coordinates") or []
    if not coords:
        return []
    return [(float(pt[1]), float(pt[0])) for pt in coords[0] if len(pt) >= 2]


def centroid(polygon: dict) -> tuple[float, float] | None:
    """Area centroid of the outer ring (falls back to vertex mean if degenerate)."""
    pts = ring(polygon)
    if not pts:
        return None
    if len(pts) < 3:
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    a = cx = cy = 0.0
    for i in range(len(pts)):
        y1, x1 = pts[i]
        y2, x2 = pts[(i + 1) % len(pts)]
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-12:
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    a *= 0.5
    return (cy / (6 * a), cx / (6 * a))


def contains(polygon: dict, lat: float, lon: float) -> bool:
    """Ray-casting point-in-polygon on the outer ring."""
    pts = ring(polygon)
    if len(pts) < 3:
        return False
    inside = False
    for i in range(len(pts)):
        y1, x1 = pts[i]
        y2, x2 = pts[(i + 1) % len(pts)]
        if (y1 > lat) != (y2 > lat):
            xint = x1 + (lat - y1) * (x2 - x1) / ((y2 - y1) or 1e-12)
            if lon < xint:
                inside = not inside
    return inside


def _local(lat0: float, lon0: float, lat: float, lon: float) -> tuple[float, float]:
    """(east, north) metres from (lat0, lon0), on a flat patch of ground around it.

    Plenty at estate scale: over a few km the error is centimetres, well inside
    how well a hand-drawn outline or a placed stand is known.
    """
    north = math.radians(lat - lat0) * EARTH_R_M
    east = math.radians(lon - lon0) * EARTH_R_M * math.cos(math.radians(lat0))
    return east, north


def _edges(polygon: dict, lat: float, lon: float) -> list[tuple[tuple, tuple]]:
    """The outline's edges in local metres around (lat, lon), closing the ring."""
    pts = [_local(lat, lon, p[0], p[1]) for p in ring(polygon)]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) == 1:
        return [(pts[0], pts[0])]
    return [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]


def _nearest_on_segment(a: tuple, b: tuple) -> tuple[float, float]:
    """The point of segment ab nearest the origin."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, -(a[0] * dx + a[1] * dy) / length2))
    return a[0] + t * dx, a[1] + t * dy


def distance_to_polygon_m(polygon: dict, lat: float, lon: float) -> float:
    """Metres to the nearest point of the outline (any edge, not just a corner), or
    0 inside.

    It used to be the nearest corner: bedding drawn with a handful of taps has long
    edges, and a stand 200 m off the middle of one read as 632 m away (audit B-03).
    """
    if contains(polygon, lat, lon):
        return 0.0
    edges = _edges(polygon, lat, lon)
    if not edges:
        return float("inf")
    return min(math.hypot(*_nearest_on_segment(a, b)) for a, b in edges)


def _bearing_of(p: tuple) -> float:
    return (math.degrees(math.atan2(p[0], p[1])) + 360.0) % 360.0


def _in_cone(p: tuple, bearing_deg: float, half_deg: float, range_m: float) -> bool:
    d = math.hypot(*p)
    if d > range_m + 1e-6:
        return False
    return d < 1e-9 or angular_distance(_bearing_of(p), bearing_deg) <= half_deg + 1e-9


def _cross_ray(a: tuple, b: tuple, bearing_deg: float, range_m: float) -> tuple | None:
    """Where segment ab crosses the ray from the origin along a bearing, within range."""
    ux, uy = math.sin(math.radians(bearing_deg)), math.cos(math.radians(bearing_deg))
    dx, dy = b[0] - a[0], b[1] - a[1]
    det = dx * uy - dy * ux
    if abs(det) < 1e-12:
        return None  # parallel: its ends are tested on their own
    # a + s*d = t*u  ->  solve for s (along the edge) and t (along the ray)
    s = (a[1] * ux - a[0] * uy) / det
    t = (dx * a[1] - dy * a[0]) / det
    if 0.0 <= s <= 1.0 and 0.0 <= t <= range_m:
        return a[0] + s * dx, a[1] + s * dy
    return None


def _cross_arc(a: tuple, b: tuple, range_m: float) -> list[tuple]:
    """Where segment ab crosses the circle of radius range_m round the origin."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    qa = dx * dx + dy * dy
    if qa == 0:
        return []
    qb = 2 * (a[0] * dx + a[1] * dy)
    qc = a[0] * a[0] + a[1] * a[1] - range_m * range_m
    disc = qb * qb - 4 * qa * qc
    if disc < 0:
        return []
    root = math.sqrt(disc)
    return [(a[0] + s * dx, a[1] + s * dy)
            for s in ((-qb - root) / (2 * qa), (-qb + root) / (2 * qa)) if 0.0 <= s <= 1.0]


def cone_reaches_polygon(
    polygon: dict, lat: float, lon: float, bearing_deg: float, half_deg: float, range_m: float,
) -> float | None:
    """Metres to the nearest part of the outline inside a cone from (lat, lon), or
    None when the cone misses it. 0 when the point is inside.

    The cone is a sector: `range_m` long, `half_deg` either side of `bearing_deg`.
    Tested against the outline itself, not its middle: aiming at the centroid said
    "clean" for scent blowing straight into the near end of a long strip of bedding
    (audit B-03). Exact for any outline: the part of an edge inside the sector starts
    and ends at the edge's own ends, where it crosses the sector's sides, or on its
    arc, and the nearest point of it is one of those or the foot of the
    perpendicular from the stand.
    """
    if contains(polygon, lat, lon):
        return 0.0
    half_deg = min(half_deg, 90.0)
    best: float | None = None
    for a, b in _edges(polygon, lat, lon):
        found = [p for p in (a, b, _nearest_on_segment(a, b))
                 if _in_cone(p, bearing_deg, half_deg, range_m)]
        for side in (bearing_deg - half_deg, bearing_deg + half_deg):
            hit = _cross_ray(a, b, side, range_m)
            if hit is not None:
                found.append(hit)
        found += [p for p in _cross_arc(a, b, range_m)
                  if _in_cone(p, bearing_deg, half_deg, range_m)]
        for p in found:
            d = math.hypot(*p)
            if best is None or d < best:
                best = d
    return best


def bounds(polygons: list[dict]) -> tuple[float, float, float, float] | None:
    """(min_lat, min_lon, max_lat, max_lon) over every ring given."""
    pts = [p for poly in polygons for p in ring(poly)]
    if not pts:
        return None
    return (
        min(p[0] for p in pts), min(p[1] for p in pts),
        max(p[0] for p in pts), max(p[1] for p in pts),
    )


def angular_distance(a: float, b: float) -> float:
    """Smallest angle between two bearings, 0-180."""
    d = abs((a % 360.0) - (b % 360.0)) % 360.0
    return 360.0 - d if d > 180.0 else d
