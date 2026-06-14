"""Insights — multi-day outlook + plain-language correlations."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.forecasting.insights import compute_insights
from app.models import User

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("")
def insights(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return compute_insights(db)
