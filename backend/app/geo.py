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


def distance_to_polygon_m(polygon: dict, lat: float, lon: float) -> float:
    """Metres to the nearest vertex, or 0 inside.

    Nearest *vertex* rather than nearest edge: for hand-drawn bedding outlines with
    vertices every few tens of metres the difference is well inside the error of the
    drawing itself, and it keeps this dependency-free.
    """
    if contains(polygon, lat, lon):
        return 0.0
    pts = ring(polygon)
    if not pts:
        return float("inf")
    return min(distance_m(lat, lon, p[0], p[1]) for p in pts)


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
