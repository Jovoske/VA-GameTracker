"""One feed of every animal photo across every camera.

The camera gallery answers "what did PL19 see", the species gallery "where were the
boar". Most evenings the question is just "what came through last night", so this
lists everything newest first, filtered by any mix of animals and cameras, and
leaves out empty frames and hidden species.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.visibility import VISIBLE_ANIMAL
from app.core.db import get_db
from app.forecasting.model import class_label
from app.models import Camera, Detection, Image, Species, User

router = APIRouter(prefix="/photos", tags=["photos"])


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


@router.get("/filters")
def filters(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """The chips: every animal that is not hidden and every camera, with photo counts."""
    sp_rows = db.execute(
        select(Species.id, Species.common_name, func.count(func.distinct(Detection.image_id)))
        .outerjoin(Detection, Detection.species_id == Species.id)
        .where(Species.hidden.is_(False))
        .group_by(Species.id, Species.common_name)
        .order_by(func.count(func.distinct(Detection.image_id)).desc(), Species.common_name)
    ).all()
    cam_rows = db.execute(
        select(Camera.id, Camera.name, func.count(Image.id))
        .outerjoin(Image, (Image.camera_id == Camera.id) & VISIBLE_ANIMAL)
        .where(Camera.active.is_(True))
        .group_by(Camera.id, Camera.name)
        .order_by(Camera.name)
    ).all()
    return {
        "species": [
            {"id": sid, "common_name": name, "count": int(n)} for sid, name, n in sp_rows if n
        ],
        "cameras": [{"id": str(cid), "name": name, "count": int(n)} for cid, name, n in cam_rows],
    }


@router.get("")
def feed(
    species: str | None = Query(None, description="Comma-separated species ids; omit for all"),
    cameras: str | None = Query(None, description="Comma-separated camera ids; omit for all"),
    before: datetime | None = Query(None, description="Only photos taken before this instant"),
    limit: int = Query(60, ge=1, le=200),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Newest first. `next_before` pages on; it is null on the last page."""
    species_ids = _csv(species)
    camera_ids = []
    for c in _csv(cameras):
        try:
            camera_ids.append(uuid.UUID(c))
        except ValueError:
            continue

    q = (
        select(Image.id, Image.captured_at, Image.camera_id, Camera.name)
        .join(Camera, Camera.id == Image.camera_id)
        .where(Image.original_path.isnot(None), VISIBLE_ANIMAL)
    )
    if species_ids:
        q = q.where(
            select(Detection.id)
            .where(Detection.image_id == Image.id, Detection.species_id.in_(species_ids))
            .exists()
        )
    if camera_ids:
        q = q.where(Image.camera_id.in_(camera_ids))
    if before is not None:
        q = q.where(Image.captured_at < before)
    rows = db.execute(q.order_by(Image.captured_at.desc(), Image.id.desc()).limit(limit + 1)).all()
    more = len(rows) > limit
    rows = rows[:limit]

    labels: dict[uuid.UUID, tuple[str, str | None, int | None]] = {}
    if rows:
        drows = db.execute(
            select(
                Detection.image_id, Detection.species_id, Species.common_name, Species.hidden,
                Detection.sex, Detection.group_type, Detection.group_size, Detection.species_conf,
            )
            .join(Species, Species.id == Detection.species_id)
            .where(Detection.image_id.in_([r.id for r in rows]))
            .order_by(Detection.species_conf.desc().nullslast())
        ).all()
        for d in drows:
            if d.hidden or d.image_id in labels:
                continue  # first row per image is the surest sighting
            labels[d.image_id] = (
                class_label(d.species_id, d.common_name, d.sex, d.group_type),
                d.species_id,
                d.group_size,
            )

    items = []
    for r in rows:
        label, sid, size = labels.get(r.id, ("Animal", None, None))
        items.append({
            "image_id": str(r.id),
            "file_url": f"/api/images/{r.id}/file",
            "captured_at": r.captured_at,
            "camera": r.name,
            "camera_id": str(r.camera_id),
            "label": label,
            "species_id": sid,
            "group_size": size,
        })
    return {
        "items": items,
        "next_before": rows[-1].captured_at if more and rows else None,
    }
