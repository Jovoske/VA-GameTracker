"""Insights — multi-day outlook, correlations, and class → photos drill-down."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.forecasting.insights import compute_insights
from app.forecasting.model import class_label
from app.models import Camera, Detection, Image, Species, User

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("")
def insights(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return compute_insights(db)


@router.get("/class")
def class_images(
    label: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    """Every photo whose detection falls in this class (Stag, Sow + piglets, …).

    Filters with the same class_label() the Insights makeup is built from, so the
    photos always match the count shown.
    """
    rows = db.execute(
        select(
            Detection.species_id, Detection.sex, Detection.group_type, Detection.group_size,
            Image.id, Image.captured_at, Image.original_path, Camera.name, Species.common_name,
        )
        .join(Image, Image.id == Detection.image_id)
        .join(Species, Species.id == Detection.species_id)
        .join(Camera, Camera.id == Image.camera_id)
        .order_by(Image.captured_at.desc())
    ).all()
    out = []
    for sp, sex, gt, gsize, img_id, cap, path, cam, cn in rows:
        if path and class_label(sp, cn, sex, gt) == label:
            out.append({
                "image_id": str(img_id),
                "file_url": f"/api/images/{img_id}/file",
                "captured_at": cap,
                "camera": cam,
                "group_size": gsize,
            })
    return out
