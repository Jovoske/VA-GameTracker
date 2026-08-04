"""Species — list them, toggle hunting-advice visibility, and browse what was spotted."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.db import get_db
from app.forecasting.model import class_label
from app.models import Camera, Detection, Image, Species, User

router = APIRouter(prefix="/species", tags=["species"])


@router.get("")
def list_species(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    """Every species with its detection count and whether it shows in hunting advice."""
    counts = dict(
        db.execute(
            select(Detection.species_id, func.count(Detection.id)).group_by(Detection.species_id)
        ).all()
    )
    rows = db.scalars(select(Species)).all()
    out = [
        {
            "id": s.id,
            "common_name": s.common_name,
            "huntable": s.huntable,
            "is_priority": s.is_priority,
            "detections": int(counts.get(s.id, 0)),
        }
        for s in rows
    ]
    # most-seen first, so the species that actually matter sit at the top of the list
    out.sort(key=lambda r: (-r["detections"], r["common_name"]))
    return out


@router.get("/spotted")
def spotted(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    """Every species seen on the estate, with its class breakdown (Stag/Hind, Boar/Sow…).

    This is the tracking view — it always includes every species, regardless of the
    huntable (advice) toggle.
    """
    rows = db.execute(
        select(
            Detection.species_id, Species.common_name, Detection.sex, Detection.group_type,
            func.count(Detection.id), func.max(Image.captured_at),
        )
        .join(Image, Image.id == Detection.image_id)
        .join(Species, Species.id == Detection.species_id)
        .where(Image.original_path.isnot(None))
        .group_by(Detection.species_id, Species.common_name, Detection.sex, Detection.group_type)
    ).all()

    agg: dict[str, dict] = {}
    for sid, cn, sex, gt, cnt, last in rows:
        s = agg.setdefault(sid, {"id": sid, "name": cn, "count": 0, "last_seen": None, "classes": {}})
        s["count"] += int(cnt)
        lbl = class_label(sid, cn, sex, gt)
        s["classes"][lbl] = s["classes"].get(lbl, 0) + int(cnt)
        if last is not None and (s["last_seen"] is None or last > s["last_seen"]):
            s["last_seen"] = last

    out = []
    for sid, s in agg.items():
        thumb = db.scalar(
            select(Image.id)
            .join(Detection, Detection.image_id == Image.id)
            .where(Detection.species_id == sid, Image.original_path.isnot(None))
            .order_by(Image.captured_at.desc())
            .limit(1)
        )
        out.append({
            "id": sid,
            "name": s["name"],
            "count": s["count"],
            "last_seen": s["last_seen"],
            "thumb_image_id": str(thumb) if thumb else None,
            "classes": [
                {"label": lbl, "count": c}
                for lbl, c in sorted(s["classes"].items(), key=lambda kv: -kv[1])
            ],
        })
    out.sort(key=lambda r: -r["count"])
    return out


@router.get("/{species_id}/images")
def species_images(
    species_id: str,
    label: str | None = Query(None, description="Optional class label filter (e.g. 'Stag')"),
    limit: int = Query(300, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """All photos of a species, newest first — optionally only one class (Stag, Sow + piglets…)."""
    rows = db.execute(
        select(
            Detection.sex, Detection.group_type, Detection.group_size,
            Image.id, Image.captured_at, Camera.name, Species.common_name,
        )
        .join(Image, Image.id == Detection.image_id)
        .join(Species, Species.id == Detection.species_id)
        .join(Camera, Camera.id == Image.camera_id)
        .where(Detection.species_id == species_id, Image.original_path.isnot(None))
        .order_by(Image.captured_at.desc())
    ).all()
    out = []
    for sex, gt, gsize, img_id, cap, cam, cn in rows:
        lbl = class_label(species_id, cn, sex, gt)
        if label and lbl != label:
            continue
        out.append({
            "image_id": str(img_id),
            "file_url": f"/api/images/{img_id}/file",
            "captured_at": cap,
            "camera": cam,
            "label": lbl,
            "group_size": gsize,
        })
        if len(out) >= limit:
            break
    return out


class HuntableBody(BaseModel):
    huntable: bool


@router.patch("/{species_id}")
def set_huntable(
    species_id: str,
    body: HuntableBody,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Turn a species on/off for hunting advice (admin). Does not affect stats or tracking."""
    sp = db.get(Species, species_id)
    if sp is None:
        raise HTTPException(404, "Species not found")
    sp.huntable = body.huntable
    db.commit()
    return {"id": sp.id, "common_name": sp.common_name, "huntable": sp.huntable}
