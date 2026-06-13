"""SPYPOINT sync task. Milestone 0 = heartbeat; M1 implements the real pull."""
from app.core.logging import get_logger
from app.tasks.celery_app import celery

log = get_logger(__name__)


@celery.task(name="app.tasks.sync.spypoint_sync")
def spypoint_sync() -> dict:
    log.info("spypoint_sync.placeholder", note="real SPYPOINT pull arrives in Milestone 1")
    return {"status": "noop", "milestone": 0}
