"""Terrain: a cached elevation grid, and the slope direction at any point.

Needed because on a calm evening the synoptic forecast is not the wind the hunter
is standing in. Cold air drains downhill after sunset, and which way "downhill"
points is a property of the ground, not the weather — so it is fetched once and
kept.

Source is Open-Meteo's elevation API (Copernicus DEM, ~90 m posts): free, no key,
and already the provider behind the weather in this app. 90 m sees a barranco. It
does not see the small gully you are actually sitting in, which is why everything
downstream of this reports a tendency rather than a certainty.
"""
from __future__ import annotations

import math

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import TerrainGrid

log = get_logger(__name__)

ELEVATION_API = "https://api.open-meteo.com/v1/elevation"
MAX_POINTS_PER_CALL = 100  # Open-Meteo's documented limit

# ~200 m posts over a 5 km box. Finer than this buys nothing: the underlying DEM is
# ~90 m, and a hand-placed stand is not located to better than that anyway.
GRID_STEPS = 25
BOX_KM = 5.0


def _deg_per_km(lat: float) -> tuple[float, float]:
    return (1.0 / 111.32, 1.0 / (111.32 * max(0.1, math.cos(math.radians(lat)))))


def fetch_grid(db: Session, centre_lat: float, centre_lon: float, *, force: bool = False) -> TerrainGrid:
    """Download and store the elevation grid around the estate. Idempotent."""
    existing = db.scalar(select(TerrainGrid).order_by(TerrainGrid.created_at.desc()))
    if existing is not None and not force:
        return existing

    dlat, dlon = _deg_per_km(centre_lat)
    half_lat = (BOX_KM / 2) * dlat
    half_lon = (BOX_KM / 2) * dlon
    min_lat, max_lat = centre_lat - half_lat, centre_lat + half_lat
    min_lon, max_lon = centre_lon - half_lon, centre_lon + half_lon

    lats: list[float] = []
    lons: list[float] = []
    for i in range(GRID_STEPS):
        for j in range(GRID_STEPS):
            lats.append(min_lat + (max_lat - min_lat) * i / (GRID_STEPS - 1))
            lons.append(min_lon + (max_lon - min_lon) * j / (GRID_STEPS - 1))

    elevations: list[float] = []
    for start in range(0, len(lats), MAX_POINTS_PER_CALL):
        chunk_lat = lats[start:start + MAX_POINTS_PER_CALL]
        chunk_lon = lons[start:start + MAX_POINTS_PER_CALL]
        r = httpx.get(
            ELEVATION_API,
            params={
                "latitude": ",".join(f"{v:.5f}" for v in chunk_lat),
                "longitude": ",".join(f"{v:.5f}" for v in chunk_lon),
            },
            timeout=45,
        )
        r.raise_for_status()
        elevations.extend(float(v) for v in r.json().get("elevation", []))

    if len(elevations) != len(lats):
        raise RuntimeError(f"elevation API returned {len(elevations)} of {len(lats)} points")

    if existing is not None:
        existing.min_lat, existing.min_lon = min_lat, min_lon
        existing.max_lat, existing.max_lon = max_lat, max_lon
        existing.steps = GRID_STEPS
        existing.elevations = elevations
        db.commit()
        log.info("terrain.refreshed", points=len(elevations))
        return existing

    grid = TerrainGrid(
        min_lat=min_lat, min_lon=min_lon, max_lat=max_lat, max_lon=max_lon,
        steps=GRID_STEPS, elevations=elevations,
    )
    db.add(grid)
    db.commit()
    log.info("terrain.fetched", points=len(elevations),
             relief_m=round(max(elevations) - min(elevations)))
    return grid


def get_grid(db: Session) -> TerrainGrid | None:
    return db.scalar(select(TerrainGrid).order_by(TerrainGrid.created_at.desc()))


def _at(grid: TerrainGrid, i: int, j: int) -> float:
    n = grid.steps
    i = min(max(i, 0), n - 1)
    j = min(max(j, 0), n - 1)
    return float(grid.elevations[i * n + j])


def _indices(grid: TerrainGrid, lat: float, lon: float) -> tuple[float, float] | None:
    if not (grid.min_lat <= lat <= grid.max_lat and grid.min_lon <= lon <= grid.max_lon):
        return None
    fi = (lat - grid.min_lat) / (grid.max_lat - grid.min_lat) * (grid.steps - 1)
    fj = (lon - grid.min_lon) / (grid.max_lon - grid.min_lon) * (grid.steps - 1)
    return (fi, fj)


def elevation_at(grid: TerrainGrid, lat: float, lon: float) -> float | None:
    idx = _indices(grid, lat, lon)
    if idx is None:
        return None
    fi, fj = idx
    i, j = int(fi), int(fj)
    di, dj = fi - i, fj - j
    return (
        _at(grid, i, j) * (1 - di) * (1 - dj)
        + _at(grid, i + 1, j) * di * (1 - dj)
        + _at(grid, i, j + 1) * (1 - di) * dj
        + _at(grid, i + 1, j + 1) * di * dj
    )


def slope_at(grid: TerrainGrid, lat: float, lon: float) -> dict | None:
    """Downhill direction and steepness at a point.

    Returns `downhill_deg` (compass bearing air drains toward), `slope_pct`, and the
    elevation. Central differences over one grid cell, which at ~200 m posts gives
    the *hillside's* fall line rather than a local hummock — the right scale for
    where a body of cold air goes.
    """
    idx = _indices(grid, lat, lon)
    if idx is None:
        return None
    fi, fj = idx
    i, j = int(round(fi)), int(round(fj))

    n = grid.steps
    cell_lat_m = (grid.max_lat - grid.min_lat) / (n - 1) * 111_320.0
    cell_lon_m = (grid.max_lon - grid.min_lon) / (n - 1) * 111_320.0 * math.cos(math.radians(lat))

    # i increases north, j increases east.
    dz_north = (_at(grid, i + 1, j) - _at(grid, i - 1, j)) / (2 * cell_lat_m)
    dz_east = (_at(grid, i, j + 1) - _at(grid, i, j - 1)) / (2 * cell_lon_m)

    slope = math.hypot(dz_north, dz_east)
    if slope < 1e-6:
        return {"downhill_deg": None, "slope_pct": 0.0,
                "elevation_m": round(elevation_at(grid, lat, lon) or 0)}

    # Steepest descent points opposite the gradient (which points uphill).
    downhill = (math.degrees(math.atan2(-dz_east, -dz_north)) + 360.0) % 360.0
    return {
        "downhill_deg": round(downhill),
        "slope_pct": round(slope * 100, 1),
        "elevation_m": round(elevation_at(grid, lat, lon) or 0),
    }
