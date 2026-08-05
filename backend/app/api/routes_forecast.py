"""Tonight forecast — what the ground has been doing, and where to sit."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.forecasting.model import forecast_tonight
from app.models import User

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/tonight")
def tonight(
    species: str | None = Query(
        None,
        description="Comma-separated species ids to rank by (e.g. wild_boar,red_deer). "
                    "Omit for every huntable species.",
    ),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ids = [s.strip() for s in species.split(",") if s.strip()] if species else None
    return forecast_tonight(db, species_ids=ids)
