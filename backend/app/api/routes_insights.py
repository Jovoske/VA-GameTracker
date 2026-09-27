"""Insights — multi-day outlook, correlations, and class → photos drill-down."""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.visibility import VISIBLE_SIGHTING
from app.core.db import get_db
from app.forecasting.insights import compute_insights
from app.forecasting.model import class_label_sql, sentence_case_sql
from app.forecasting.patterns import compute_patterns
from app.models import Camera, Detection, Image, Species, User

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("")
def insights(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return compute_insights(db)


@router.get("/patterns")
def patterns(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Behaviour drivers — activity vs weather & moon, estate-wide and per species."""
    return compute_patterns(db)


def _in_class(label: str):
    """SQL on a Detection joined to its Species: it is of this class (Stag, Sow +
    piglets, Roe deer). The same split as model.class_label, so the photos are the
    ones labelled with the class the Insights makeup names (a visit it counted as
    "Sow + piglets" may have plain "Wild boar" frames too; those list under that)."""
    split = class_label_sql(Detection.species_id, Detection.sex, Detection.group_type,
                            Species.common_name)
    return or_(split == label,
               and_(split.is_(None), sentence_case_sql(Species.common_name) == label))


@router.get("/class")
def class_images(
    label: str,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    before: Annotated[datetime | None, Query(
        description="Only photos taken before this instant")] = None,
    before_id: Annotated[uuid.UUID | None, Query(
        description="With `before`: the last photo of the page before, for photos "
                    "taken in the same second")] = None,
    limit: Annotated[int, Query(ge=1, le=300)] = 120,
) -> dict:
    """Photos of this class, newest first, a page at a time: `next_before` and
    `next_before_id` ask for the next page, and are null on the last.

    Only photos anybody can see: not a hidden species, not a photo marked "nothing
    in it", not a retired camera (which the makeup leaves out too).
    """
    of_class = (
        select(Detection.image_id)
        .join(Species, Species.id == Detection.species_id)
        .join(Image, Image.id == Detection.image_id)
        .where(_in_class(label), VISIBLE_SIGHTING)
    )
    group = (
        select(func.max(Detection.group_size))
        .join(Species, Species.id == Detection.species_id)
        .where(Detection.image_id == Image.id, _in_class(label))
        .scalar_subquery()
    )
    q = (
        select(Image.id, Image.captured_at, Camera.name, group.label("group_size"))
        .join(Camera, Camera.id == Image.camera_id)
        .where(Image.id.in_(of_class), Image.original_path.isnot(None),
               Camera.retired_at.is_(None))
    )
    if before is not None:
        q = q.where(
            tuple_(Image.captured_at, Image.id) < tuple_(before, before_id)
            if before_id is not None else Image.captured_at < before
        )
    rows = db.execute(
        q.order_by(Image.captured_at.desc(), Image.id.desc()).limit(limit + 1)
    ).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            {
                "image_id": str(r.id),
                "file_url": f"/api/images/{r.id}/file",
                "captured_at": r.captured_at,
                "camera": r.name,
                "group_size": r.group_size,
            }
            for r in rows
        ],
        "next_before": rows[-1].captured_at if more else None,
        "next_before_id": str(rows[-1].id) if more else None,
    }
