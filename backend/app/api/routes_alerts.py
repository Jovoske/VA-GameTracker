"""Alerts feed — notable events."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.forecasting.alerts import compute_alerts
from app.models import User

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
def alerts(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return compute_alerts(db)
