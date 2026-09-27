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
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.estate_area import side_m, terrain_box
from app.models import TerrainGrid

log = get_logger(__name__)

ELEVATION_API = "https://api.open-meteo.com/v1/elevation"
MAX_POINTS_PER_CALL = 100  # Open-Meteo's documented limit

# ~250 m posts over a 5 km box, in 4 requests. Finer than this buys nothing: the
# underlying DEM is ~90 m, a hand-placed stand is not located to better than that,
# and drainage is a hillside-scale phenomenon rather than a per-boulder one.
GRID_STEPS = 20
BOX_KM = 5.0
# The box grows to take in every stand, camera and bedding outline (plus a margin):
# a stand 3 km out of a fixed 5 km box was told its ground was flat (audit B-20).
# Posts stay about POST_M apart, up to MAX_STEPS a side (16 requests).
MAX_BOX_KM = 12.0
POST_M = 250.0
MAX_STEPS = 40

# Open-Meteo is free and unauthenticated, so it is rate limited and we should be
# polite: pace the chunks and back off rather than hammering it.
CHUNK_PAUSE_S = 1.5
MAX_RETRIES = 4


def _get_elevations(lats: list[float], lons: list[float]) -> list[float]:
    """One elevation request, retrying politely through rate limits."""
    params = {
        "latitude": ",".join(f"{v:.5f}" for v in lats),
        "longitude": ",".join(f"{v:.5f}" for v in lons),
    }
    delay = 3.0
    for attempt in range(MAX_RETRIES):
        r = httpx.get(ELEVATION_API, params=params, timeout=45)
        if r.status_code == 429:
            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(
                    "Elevation service is rate limiting us. It is free and shared — "
                    "wait a few minutes and load the terrain again."
                )
            log.info("terrain.rate_limited", attempt=attempt + 1, sleeping=delay)
            time.sleep(delay)
            delay *= 2
            continue
        r.raise_for_status()
        return [float(v) for v in r.json().get("elevation", [])]
    return []


def fetch_grid(
    db: Session, centre_lat: float, centre_lon: float, *, force: bool = False
) -> TerrainGrid:
    """Download and store the elevation grid over the estate: the square round its
    centre, grown to take in every stand, camera and bedding outline. Idempotent."""
    existing = db.scalar(select(TerrainGrid).order_by(TerrainGrid.created_at.desc()))
    if existing is not None and not force:
        return existing

    box = terrain_box(db, centre_lat, centre_lon, BOX_KM * 1000, MAX_BOX_KM * 1000)
    min_lat, max_lat, min_lon, max_lon = box["south"], box["north"], box["west"], box["east"]
    steps = min(MAX_STEPS, max(GRID_STEPS, math.ceil(max(side_m(box)) / POST_M) + 1))

    lats: list[float] = []
    lons: list[float] = []
    for i in range(steps):
        for j in range(steps):
            lats.append(min_lat + (max_lat - min_lat) * i / (steps - 1))
            lons.append(min_lon + (max_lon - min_lon) * j / (steps - 1))

    elevations: list[float] = []
    for start in range(0, len(lats), MAX_POINTS_PER_CALL):
        if start:
            time.sleep(CHUNK_PAUSE_S)
        elevations.extend(
            _get_elevations(
                lats[start:start + MAX_POINTS_PER_CALL],
                lons[start:start + MAX_POINTS_PER_CALL],
            )
        )

    if len(elevations) != len(lats):
        raise RuntimeError(f"elevation API returned {len(elevations)} of {len(lats)} points")

    if existing is not None:
        existing.min_lat, existing.min_lon = min_lat, min_lon
        existing.max_lat, existing.max_lon = max_lat, max_lon
        existing.steps = steps
        existing.elevations = elevations
        db.commit()
        log.info("terrain.refreshed", points=len(elevations))
        return existing

    grid = TerrainGrid(
        min_lat=min_lat, min_lon=min_lon, max_lat=max_lat, max_lon=max_lon,
        steps=steps, elevations=elevations,
    )
    db.add(grid)
    db.commit()
    log.info("terrain.fetched", points=len(elevations),
             relief_m=round(max(elevations) - min(elevations)))
    return grid


def get_grid(db: Session) -> TerrainGrid | None:
    return db.scalar(select(TerrainGrid).order_by(TerrainGrid.created_at.desc()))


def covers(grid: TerrainGrid, lat: float, lon: float) -> bool:
    """Whether the hill shape reaches this spot."""
    return _indices(grid, lat, lon) is not None


# ── loading it from the map ─────────────────────────────────────────────────
# The download takes 5 to 30 s when the service is kind and minutes when it rate
# limits us, so the map's button starts it and asks how it went (audit B-18) instead
# of holding a request (and the hunter) for all of it. Where it is lives in
# app_settings, so every worker process of the server reads the same answer.

STATUS_KEY = "terrain_status"
# A download "loading" for longer than this died with its process: start another.
LOADING_STALE_S = 10 * 60
FAILED_WORDS = {
    "busy": "The elevation service is busy. Try again in a few minutes.",
    "down": "The elevation service didn’t answer. Try again later.",
}


def load_status(db: Session) -> dict:
    """{"state": "none" | "loading" | "loaded" | "failed", "error": words or None, ...}."""
    from app.models import AppSetting

    row = db.get(AppSetting, STATUS_KEY)
    value = dict(row.value) if row else {}
    grid = get_grid(db)
    if value.get("state") == "loading" and _age_s(value.get("started_at")) > LOADING_STALE_S:
        value = {**value, "state": "failed", "error": FAILED_WORDS["down"]}
    if value.get("state") not in ("loading", "failed"):
        value = {"state": "loaded" if grid is not None else "none",
                 "finished_at": value.get("finished_at")}
    value.setdefault("error", None)
    # A reload updates the grid's row in place, so its created_at is the first load.
    loaded = value.get("finished_at") if value["state"] == "loaded" else None
    value["loaded_at"] = loaded or (grid.created_at if grid is not None else None)
    return value


def _age_s(iso: str | None) -> float:
    from datetime import UTC, datetime

    try:
        return (datetime.now(UTC) - datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


def _set_status(db: Session, value: dict) -> None:
    from app.models import AppSetting

    row = db.get(AppSetting, STATUS_KEY, with_for_update=True)
    if row is None:
        db.add(AppSetting(key=STATUS_KEY, value=value))
    else:
        row.value = value
    db.commit()


def start_load(db: Session) -> tuple[dict, bool]:
    """Mark a download as started, unless one already is. (status, started)."""
    from datetime import UTC, datetime

    from app.models import AppSetting

    row = db.get(AppSetting, STATUS_KEY, with_for_update=True)
    now = row.value if row else {}
    if now.get("state") == "loading" and _age_s(now.get("started_at")) <= LOADING_STALE_S:
        db.rollback()
        return load_status(db), False
    _set_status(db, {"state": "loading", "started_at": datetime.now(UTC).isoformat()})
    return load_status(db), True


def load_in_background(centre_lat: float, centre_lon: float) -> None:
    """fetch_grid on its own session, after the button's answer has gone back. What
    went wrong is logged in full; the map gets a short line it can show."""
    from datetime import UTC, datetime

    from app.core import db as core_db

    with core_db.SessionLocal() as db:
        try:
            fetch_grid(db, centre_lat, centre_lon, force=True)
            _set_status(db, {"state": "loaded", "finished_at": datetime.now(UTC).isoformat()})
        except Exception as e:
            db.rollback()
            log.warning("terrain.load_failed", error=f"{type(e).__name__}: {e}"[:500])
            busy = isinstance(e, RuntimeError) and "rate limit" in str(e).lower() or (
                isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429)
            _set_status(db, {"state": "failed", "finished_at": datetime.now(UTC).isoformat(),
                             "error": FAILED_WORDS["busy" if busy else "down"]})


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

    # i increases north, j increases east. At the grid's edge there is no post beyond,
    # so the difference is one-sided over one cell rather than a central one over two
    # cells with one of them clamped, which halved the slope there (audit B-20).
    i0, i1 = max(i - 1, 0), min(i + 1, n - 1)
    j0, j1 = max(j - 1, 0), min(j + 1, n - 1)
    dz_north = (_at(grid, i1, j) - _at(grid, i0, j)) / ((i1 - i0) * cell_lat_m)
    dz_east = (_at(grid, i, j1) - _at(grid, i, j0)) / ((j1 - j0) * cell_lon_m)

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
