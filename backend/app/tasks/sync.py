"""SPYPOINT sync + backfill Celery tasks."""
from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.ingestion.sync import backfill_all, sync_all
from app.tasks.celery_app import celery

log = get_logger(__name__)


@celery.task(name="app.tasks.sync.spypoint_sync")
def spypoint_sync() -> dict:
    with SessionLocal() as db:
        result = sync_all(db)
    log.info("spypoint_sync.done", status=result.get("status"), total=result.get("total"))
    return result


@celery.task(name="app.tasks.sync.spypoint_backfill")
def spypoint_backfill(months: int = 13) -> dict:
    with SessionLocal() as db:
        result = backfill_all(db, months=months)
    log.info("spypoint_backfill.done", status=result.get("status"), total=result.get("total"))
    return result
