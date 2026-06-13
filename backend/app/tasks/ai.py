"""AI Celery tasks — empty-frame scanning."""
from app.ai.empty_filter import scan_unprocessed
from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.tasks.celery_app import celery

log = get_logger(__name__)


@celery.task(name="app.tasks.ai.scan_empty")
def scan_empty(limit: int = 2000) -> dict:
    with SessionLocal() as db:
        result = scan_unprocessed(db, limit=limit)
    log.info("scan_empty.done", **result)
    return result
