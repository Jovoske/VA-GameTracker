"""Scheduled exposure recompute — keeps the denominator current."""
from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.forecasting.exposure import recompute_camera_nights
from app.tasks.celery_app import celery

log = get_logger(__name__)


@celery.task(name="app.tasks.exposure.recompute_exposure")
def recompute_exposure() -> dict:
    with SessionLocal() as db:
        totals = recompute_camera_nights(db)
    log.info("exposure.task_done", **totals)
    return totals
