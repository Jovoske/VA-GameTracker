"""Camera routes (read-only in Milestone 0; populated by SPYPOINT sync in M1)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import Camera, User

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.get("")
def list_cameras(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.scalars(select(Camera).where(Camera.estate_id == user.estate_id)).all()
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "battery_pct": c.battery_pct,
            "signal_pct": c.signal_pct,
            "last_sync_at": c.last_sync_at,
            "active": c.active,
        }
        for c in rows
    ]
