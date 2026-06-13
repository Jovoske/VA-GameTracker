"""AI Celery tasks — empty-frame scanning and species classification."""
from app.ai.empty_filter import scan_unprocessed
from app.ai.species import classify_unclassified
from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.tasks.celery_app import celery

log = get_logger(__name__)


@celery.task(name="app.tasks.ai.scan_empty")
def scan_empty(limit: int = 5000) -> dict:
    with SessionLocal() as db:
        result = scan_unprocessed(db, limit=limit)
    log.info("scan_empty.done", **result)
    return result


@celery.task(name="app.tasks.ai.classify_species")
def classify_species(limit: int = 2000) -> dict:
    with SessionLocal() as db:
        result = classify_unclassified(db, limit=limit)
    log.info("classify_species.done", classified=result.get("classified"))
    return result
