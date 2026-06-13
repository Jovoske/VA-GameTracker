"""Tonight forecast — the GO/MARGINAL/SKIP recommendation."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.forecasting.model import forecast_tonight
from app.models import User

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/tonight")
def tonight(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return forecast_tonight(db)
