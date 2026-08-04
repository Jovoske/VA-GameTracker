"""Zones drawn on the map (bedding), and the composite the map renders for tonight."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.core.logging import get_logger
from app.forecasting import bedding
from app.models import Estate, Stand, User, Zone

router = APIRouter(tags=["zones"])
log = get_logger(__name__)

KINDS = ("bedding", "feeding", "water", "no_go")


def _zone_out(z: Zone) -> dict:
    from app import geo

    c = geo.centroid(z.polygon)
    return {
        "id": str(z.id),
        "kind": z.kind,
        "name": z.name,
        "polygon": z.polygon,
        "notes": z.notes,
        "centroid": {"lat": c[0], "lon": c[1]} if c else None,
    }


class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = "bedding"
    polygon: dict
    notes: str | None = None


class ZonePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    polygon: dict | None = None
    notes: str | None = None


def _validate_polygon(polygon: dict) -> None:
    """A polygon that is not a closed ring of at least three points is not ground."""
    from app import geo

    if (polygon or {}).get("type") != "Polygon":
        raise HTTPException(422, "polygon must be a GeoJSON Polygon")
    pts = geo.ring(polygon)
    if len(pts) < 3:
        raise HTTPException(422, "A zone needs at least three points")
    for lat, lon in pts:
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise HTTPException(422, "Coordinates out of range (expected GeoJSON lon,lat order)")


@router.get("/zones")
def list_zones(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [_zone_out(z) for z in db.scalars(select(Zone).order_by(Zone.kind, Zone.name)).all()]


@router.post("/zones", status_code=201)
def create_zone(
    body: ZoneIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if body.kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(KINDS)}")
    _validate_polygon(body.polygon)
    estate = db.scalar(select(Estate).order_by(Estate.created_at))
    if estate is None:
        raise HTTPException(400, "No estate configured yet")
    z = Zone(
        estate_id=estate.id, kind=body.kind, name=body.name.strip(),
        polygon=body.polygon, notes=body.notes, created_by=user.id,
    )
    db.add(z)
    db.commit()
    log.info("zone.created", kind=z.kind, name=z.name)
    return _zone_out(z)


@router.patch("/zones/{zone_id}")
def update_zone(
    zone_id: uuid.UUID, body: ZonePatch,
    _: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    z = db.get(Zone, zone_id)
    if z is None:
        raise HTTPException(404, "Zone not found")
    data = body.model_dump(exclude_unset=True)
    if "polygon" in data and data["polygon"] is not None:
        _validate_polygon(data["polygon"])
    for k, v in data.items():
        setattr(z, k, v)
    db.commit()
    return _zone_out(z)


@router.delete("/zones/{zone_id}", status_code=204, response_model=None)
def delete_zone(
    zone_id: uuid.UUID, _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    z = db.get(Zone, zone_id)
    if z is None:
        raise HTTPException(404, "Zone not found")
    db.delete(z)
    db.commit()


@router.get("/map/tonight")
def map_tonight(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Everything the map draws for tonight, in one call.

    One endpoint rather than five because these are one picture: the same wind has
    to reach the zones, the stands and the shaded ground, and fetching them
    separately invites a map that disagrees with itself mid-render.
    """
    from app.forecasting.model import _tonight_conditions

    try:
        cond = _tonight_conditions(datetime.now(timezone.utc))
    except Exception as e:
        log.warning("map.conditions_failed", error=str(e))
        cond = {}
    wdir, wspd = cond.get("wind_dir_deg"), cond.get("wind_speed_kmh")

    zones = [_zone_out(z) for z in db.scalars(select(Zone).order_by(Zone.name)).all()]

    stands = []
    for s in db.scalars(select(Stand).order_by(Stand.name)).all():
        report = bedding.stand_wind_report(
            db, stand_name=s.name, lat=s.lat, lon=s.lon,
            wind_dir_deg=wdir, wind_speed_kmh=wspd,
        )
        stands.append({
            "id": str(s.id),
            "name": s.name,
            "lat": s.lat,
            "lon": s.lon,
            "wind": report,
            # Derived from the drawn bedding, so it is available even when nobody
            # has entered arcs by hand.
            "approaches": bedding.approach_bearings(db, s.lat, s.lon),
        })

    return {
        "conditions": {
            "wind_dir_deg": wdir,
            "wind_speed_kmh": wspd,
            "moon_illum": cond.get("moon_illum"),
        },
        "zones": zones,
        "stands": stands,
        "safe_ground": bedding.safe_ground(db, wind_dir_deg=wdir, wind_speed_kmh=wspd),
        "routes": bedding.routes(db),
        "scent_range_m": bedding.SCENT_RANGE_M,
    }
