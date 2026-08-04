"""Scheduled forecast persistence and verification."""
from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.forecasting.model import forecast_tonight
from app.forecasting.scoring import evaluate_night, persist_tonight
from app.tasks.celery_app import celery

log = get_logger(__name__)


@celery.task(name="app.tasks.scoring.persist_forecast")
def persist_forecast() -> dict:
    """Record what the app is claiming tonight, before the night happens."""
    with SessionLocal() as db:
        run = persist_tonight(db, forecast_tonight(db))
        return {"model_run_id": str(run.id), **(run.metrics or {})}


@celery.task(name="app.tasks.scoring.score_yesterday")
def score_yesterday() -> dict:
    """Grade yesterday's claims against what the cameras actually recorded."""
    with SessionLocal() as db:
        return evaluate_night(db)
