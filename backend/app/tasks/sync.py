"""SPYPOINT sync Celery task — pulls photos, downloads them, enriches each."""
from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.ingestion.sync import sync_all
from app.tasks.celery_app import celery

log = get_logger(__name__)


@celery.task(name="app.tasks.sync.spypoint_sync")
def spypoint_sync() -> dict:
    with SessionLocal() as db:
        result = sync_all(db)
    log.info("spypoint_sync.done", status=result.get("status"), downloaded=result.get("downloaded"))
    return result
