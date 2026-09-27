"""Zones drawn on the map (bedding), and the composite the map renders for tonight."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import geo
from app.api.deps import get_current_admin, get_current_user
from app.core.db import get_db
from app.core.logging import get_logger
from app.forecasting import bedding
from app.i18n import t
from app.models import Estate, Stand, User, Zone
from app.terrain import covers, get_grid, load_in_background, load_status, start_load

router = APIRouter(tags=["zones"])
log = get_logger(__name__)

KINDS = ("bedding", "feeding", "water", "no_go")
# Drawing, redrawing and removing areas, and loading the hill shape, are admin work,
# as on the map: every wind call leans on them (audit B-08).
Admin = Annotated[User, Depends(get_current_admin)]
DB = Annotated[Session, Depends(get_db)]


def _zone_out(z: Zone) -> dict:
    c = geo.centroid(z.polygon)
    return {
        "id": str(z.id),
        "kind": z.kind,
        "name": z.name,
        "polygon": z.polygon,
        "notes": z.notes,
        "centroid": {"lat": c[0], "lon": c[1]} if c else None,
    }


def _clean_name(value: object) -> object:
    """Names are trimmed; one of only spaces is no name."""
    if isinstance(value, str):
        value = value.strip()
        if not value:
            raise ValueError(t("zones.name_needed"))
    return value


class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = "bedding"
    polygon: dict
    notes: str | None = None

    _name = field_validator("name", mode="before")(_clean_name)


class ZonePatch(BaseModel):
    """Only what is sent changes. A name or outline can be changed, not taken away:
    null for either is refused in words (it was a 500, audit B-10)."""
    name: str | None = Field(default=None, min_length=1, max_length=80)
    polygon: dict | None = None
    notes: str | None = None

    _name = field_validator("name", mode="before")(_clean_name)

    @field_validator("name", "polygon")
    @classmethod
    def _not_null(cls, value: object, info) -> object:
        if value is None:
            raise ValueError(t("zones.name_not_empty" if info.field_name == "name"
                               else "zones.outline_not_empty"))
        return value


def _validate_polygon(polygon: dict) -> dict:
    """The outline as it is kept (closed, no repeated corners), or a 422 in words:
    too few corners, no area, crossing itself, or not numbers (audit B-10)."""
    try:
        return geo.clean_polygon(polygon)
    except geo.ShapeError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/zones")
def list_zones(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [_zone_out(z) for z in db.scalars(select(Zone).order_by(Zone.kind, Zone.name)).all()]


@router.post("/zones", status_code=201)
def create_zone(body: ZoneIn, user: Admin, db: DB) -> dict:
    """Draw an area (admins, as on the map). Every wind call leans on the bedding."""
    if body.kind not in KINDS:
        raise HTTPException(422, t("zones.bad_kind", kinds=", ".join(KINDS)))
    polygon = _validate_polygon(body.polygon)
    estate = db.scalar(select(Estate).order_by(Estate.created_at))
    if estate is None:
        raise HTTPException(400, t("stands.no_estate"))
    z = Zone(
        estate_id=estate.id, kind=body.kind, name=body.name,
        polygon=polygon, notes=body.notes, created_by=user.id,
    )
    db.add(z)
    db.commit()
    log.info("zone.created", kind=z.kind, name=z.name)
    return _zone_out(z)


@router.patch("/zones/{zone_id}")
def update_zone(zone_id: uuid.UUID, body: ZonePatch, _: Admin, db: DB) -> dict:
    """Rename an area or redraw its outline (admins): it keeps its place in every
    wind call rather than being removed and drawn again (audit B-22)."""
    z = db.get(Zone, zone_id)
    if z is None:
        raise HTTPException(404, t("zones.gone"))
    data = body.model_dump(exclude_unset=True)
    if "polygon" in data:
        data["polygon"] = _validate_polygon(data["polygon"])
    for k, v in data.items():
        setattr(z, k, v)
    db.commit()
    return _zone_out(z)


@router.delete("/zones/{zone_id}", status_code=204, response_model=None)
def delete_zone(zone_id: uuid.UUID, _: Admin, db: DB) -> None:
    z = db.get(Zone, zone_id)
    if z is None:
        raise HTTPException(404, t("zones.gone"))
    db.delete(z)
    db.commit()


@router.get("/map/tonight")
def map_tonight(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Everything the map draws for tonight, in one call.

    One endpoint rather than five because these are one picture: the same wind has
    to reach the zones, the stands and the shaded ground, and fetching them
    separately invites a map that disagrees with itself mid-render.
    """
    from app.forecasting.conditions import release, sit_time, wind_verdict
    from app.forecasting.model import _tonight_conditions

    now = datetime.now(timezone.utc)
    # The forecast with no database connection held while Open-Meteo answers (K-04).
    release(db)
    try:
        cond = _tonight_conditions(now)
    except Exception as e:
        log.warning("map.conditions_failed", error=str(e))
        cond = {}
    wdir, wspd = cond.get("wind_dir_deg"), cond.get("wind_speed_kmh")
    cloud = cond.get("cloud_cover_pct")
    # Everything on the map is judged for the sit: 45 minutes after tonight's
    # sunset, or now once that has passed, until 06:00. At lunch the map used to
    # show the midday upslope air under the evening's forecast, the opposite of the
    # sit (B-04); from 06:00 to sunrise, the dawn air (R4BE-1).
    try:
        at, at_now = datetime.fromisoformat(cond["wind_at"]), bool(cond.get("wind_now"))
    except (KeyError, TypeError, ValueError):
        at, at_now = sit_time(now)

    zones = [_zone_out(z) for z in db.scalars(select(Zone).order_by(Zone.name)).all()]

    stands = []
    for s in db.scalars(select(Stand).order_by(Stand.name)).all():
        stands.append({
            "id": str(s.id),
            "name": s.name,
            "lat": s.lat,
            "lon": s.lon,
            # The same verdict Tonight, a reservation and Sit mode give this stand.
            "wind": wind_verdict(db, s, cond, now=now),
            # Derived from the drawn bedding, so it is available even when nobody
            # has entered arcs by hand.
            "approaches": bedding.approach_bearings(db, s.lat, s.lon),
        })

    # What the air is actually doing at the estate centre — the headline the map
    # shows, so a calm evening reads "drainage NW" rather than a useless "calm".
    from app.core.config import settings as _s
    from app.forecasting import thermal

    reg = thermal.regime(
        db, lat=_s.estate_lat, lon=_s.estate_lon, when=at,
        wind_dir_deg=wdir, wind_speed_kmh=wspd, cloud_pct=cloud,
    )
    return {
        "conditions": {
            "wind_dir_deg": wdir,
            "wind_speed_kmh": wspd,
            "cloud_cover_pct": cloud,
            "moon_illum": cond.get("moon_illum"),
            "sunset_local": cond.get("sunset_local"),
            # The instant, so the page says "sunset was" only once it has been.
            "sunset": cond.get("sunset"),
            # The moment the wind bar, the stands and the shading are for.
            "wind_at": at.isoformat(),
            "wind_at_local": at.astimezone(ZoneInfo(_s.estate_timezone)).strftime("%H:%M"),
            "wind_now": at_now,
            "forecast_fetched_at": cond.get("forecast_fetched_at"),
            "forecast_stale": bool(cond.get("forecast_stale")),
        },
        "airflow": {
            "source": reg["source"],
            "wind_dir_deg": reg.get("wind_dir_deg"),
            "wind_speed_kmh": reg.get("wind_speed_kmh"),
            "confidence": reg.get("confidence"),
            "slope": reg.get("slope"),
            "text": reg.get("text"),
        },
        "zones": zones,
        "stands": stands,
        "safe_ground": bedding.safe_ground(
            db, wind_dir_deg=wdir, wind_speed_kmh=wspd, cloud_pct=cloud, when=at
        ),
        # Straight lines from bedding to every camera near it said nothing about how
        # animals move (audit G-25): the map's "Likely paths" come from /map/paths.
        # Kept empty for an app from before that.
        "routes": [],
        "scent_range_m": bedding.SCENT_RANGE_M,
        **_terrain(db, stands),
    }


def _terrain(db: Session, stands: list[dict]) -> dict:
    """Whether the hill shape is loaded, and the placed stands it doesn't reach
    (loading it again covers them: the box grows to take them in, audit B-20)."""
    grid = get_grid(db)
    outside = [s["name"] for s in stands if grid is not None
               and geo.plausible_position(s["lat"], s["lon"])
               and not covers(grid, s["lat"], s["lon"])]
    return {"terrain_loaded": grid is not None, "terrain_outside": outside}


@router.post("/terrain/refresh", status_code=202)
def refresh_terrain(background: BackgroundTasks, _: Admin, db: DB) -> dict:
    """Start downloading the hill shape (admins) and answer at once; GET
    /terrain/status says how it went. The download used to hold this request for 20 s
    or more, and a failure answered with kilobytes of the elevation service's URL
    (audit B-18). A second press while it runs starts nothing new."""
    from app.core.config import settings as _s

    status, started = start_load(db)
    if started:
        background.add_task(load_in_background, _s.estate_lat, _s.estate_lon)
    return status


@router.get("/terrain/status")
def terrain_status(_: Annotated[User, Depends(get_current_user)], db: DB) -> dict:
    """{"state": "none" | "loading" | "loaded" | "failed", "error": a short line or null,
    "loaded_at"}. Any role."""
    return load_status(db)
