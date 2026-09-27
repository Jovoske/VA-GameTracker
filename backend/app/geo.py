"""Plain-lat/lon geometry. No PostGIS — the native build runs on vanilla Postgres,
and at estate scale (a few km across, a handful of polygons) doing this in Python is
both fast enough and far easier to reason about than SQL spatial types.

Everything here is deliberately simple and testable: bearings, distances, centroids
and point-in-polygon. Nothing pretends to be a projection-correct GIS.
"""
from __future__ import annotations

import math

EARTH_R_M = 6_371_000.0


def plausible_position(lat: object, lon: object) -> bool:
    """A real place: two finite numbers in range, and not (0, 0).

    (0, 0) is what a camera with no GPS lock reports, and it is in the Gulf of
    Guinea, not on anybody's estate.
    """
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)):
        return False
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return not (abs(lat) < 1e-6 and abs(lon) < 1e-6)


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


# ── outlines drawn on the map ────────────────────────────────────────────────


class ShapeError(ValueError):
    """An outline that isn't a piece of ground, in words a hunter can act on."""


# Closer than this to the corner before is the same corner tapped twice.
SAME_CORNER_M = 0.5
# Smaller than a 10 m square is a mis-tap, not cover animals lie up in.
MIN_AREA_M2 = 100.0
MAX_CORNERS = 500
# Wider than this is not one piece of cover on an estate.
MAX_SPAN_M = 20_000.0


def _number(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _flat(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """(lon, lat) corners as metres on a flat sheet laid over the outline."""
    lat0 = math.radians(sum(p[1] for p in points) / len(points))
    k = math.pi / 180 * EARTH_R_M
    return [(lon * k * math.cos(lat0), lat * k) for lon, lat in points]


def _area_m2(xy: list[tuple[float, float]]) -> float:
    twice = sum(xy[i][0] * xy[(i + 1) % len(xy)][1] - xy[(i + 1) % len(xy)][0] * xy[i][1]
                for i in range(len(xy)))
    return abs(twice) / 2


def _crosses_itself(xy: list[tuple[float, float]]) -> bool:
    """Whether two edges of the closed outline cross or touch, or one doubles back
    along the one before it (a spike): a bow-tie or a needle, not an area."""
    n = len(xy)

    def side(a, b, c) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on(a, b, c) -> bool:  # c on segment ab, given the three are in a line
        return (min(a[0], b[0]) <= c[0] <= max(a[0], b[0])
                and min(a[1], b[1]) <= c[1] <= max(a[1], b[1]))

    eps = 1e-6
    for i in range(n):
        a, b, c = xy[i - 1], xy[i], xy[(i + 1) % n]
        # Straight back the way it came: the corner is the tip of a spike.
        back = (a[0] - b[0]) * (c[0] - b[0]) + (a[1] - b[1]) * (c[1] - b[1]) > 0
        if abs(side(a, b, c)) < eps and back:
            return True
    for i in range(n):
        a, b = xy[i], xy[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue  # edges that share a corner
            c, d = xy[j], xy[(j + 1) % n]
            s1, s2, s3, s4 = side(a, b, c), side(a, b, d), side(c, d, a), side(c, d, b)
            if ((s1 > eps and s2 < -eps) or (s1 < -eps and s2 > eps)) and \
                    ((s3 > eps and s4 < -eps) or (s3 < -eps and s4 > eps)):
                return True
            if (abs(s1) <= eps and on(a, b, c)) or (abs(s2) <= eps and on(a, b, d)) or \
                    (abs(s3) <= eps and on(c, d, a)) or (abs(s4) <= eps and on(c, d, b)):
                return True
    return False


def clean_polygon(polygon: object) -> dict:
    """A drawn outline as a closed GeoJSON Polygon, or ShapeError saying what is wrong.

    Corners are GeoJSON [longitude, latitude] pairs. A corner repeating the one before
    (a double tap) is dropped, as is the closing corner, which is added back. What is
    left must be at least three corners around some ground, not crossing itself: the
    wind calls test whether a point is inside it, and a bow-tie leaves the crossed
    part "outside" (audit B-10). Only the outer ring is kept.
    """
    if not isinstance(polygon, dict) or polygon.get("type") != "Polygon":
        raise ShapeError("The outline must be a GeoJSON Polygon.")
    rings = polygon.get("coordinates")
    if not isinstance(rings, list) or not rings or not isinstance(rings[0], list):
        raise ShapeError("The outline has no corners.")
    if len(rings[0]) > MAX_CORNERS + 1:
        raise ShapeError(f"That outline has {len(rings[0])} corners. Keep it under {MAX_CORNERS}.")
    points: list[tuple[float, float]] = []
    for pt in rings[0]:
        if not isinstance(pt, (list, tuple)) or len(pt) not in (2, 3):
            raise ShapeError("Each corner must be two numbers: longitude, then latitude.")
        lon, lat = _number(pt[0]), _number(pt[1])
        if lon is None or lat is None:
            raise ShapeError("Each corner must be two numbers: longitude, then latitude.")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ShapeError("A corner is off the map. Corners go longitude first, then latitude.")
        if points and distance_m(lat, lon, points[-1][1], points[-1][0]) < SAME_CORNER_M:
            continue
        points.append((lon, lat))
    first, last = points[0] if points else None, points[-1] if points else None
    if len(points) > 1 and distance_m(first[1], first[0], last[1], last[0]) < SAME_CORNER_M:
        points.pop()
    if len(points) < 3:
        raise ShapeError("Tap at least three corners around the area.")
    lats, lons = [p[1] for p in points], [p[0] for p in points]
    if distance_m(min(lats), min(lons), max(lats), max(lons)) > MAX_SPAN_M:
        raise ShapeError(
            "That outline is over 20 km across. Draw just the cover the animals lie up in."
        )
    xy = _flat(points)
    if _crosses_itself(xy):
        raise ShapeError("The outline crosses itself. Put the corners in order around the edge.")
    if _area_m2(xy) < MIN_AREA_M2:
        raise ShapeError("That outline has almost no area. Spread the corners around the cover.")
    closed = [[lon, lat] for lon, lat in points] + [[points[0][0], points[0][1]]]
    return {"type": "Polygon", "coordinates": [closed]}
