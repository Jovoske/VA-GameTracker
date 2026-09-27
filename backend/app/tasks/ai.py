"""AI Celery tasks (the Docker build) — the photo check, re-ID and the sex pass.

They take the same locks as pipeline.py (app.jobs), so beat, a button and a manual
`pipeline.py` run never overlap, and a busy lock skips the run: the next beat tick
picks up where it left off.
"""
from app import jobs
from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.tasks.celery_app import celery

log = get_logger(__name__)


def _check() -> dict:
    lock = jobs.try_acquire("pipeline", "celery:check")
    if lock is None:
        return {"status": "busy"}
    with lock, SessionLocal() as db:
        from app.ingestion.fetch import check_and_recount

        result, error = check_and_recount(db)
    log.info("check_photos.done", error=error, **(result.get("ai") or {}))
    return result


@celery.task(name="app.tasks.ai.scan_empty")
def scan_empty(limit: int = 5000) -> dict:
    return _check()


@celery.task(name="app.tasks.ai.classify_species")
def classify_species(limit: int = 2000) -> dict:
    return _check()


@celery.task(name="app.tasks.ai.reid")
def reid() -> dict:
    """On-demand re-ID: embed new detections + regenerate candidate individuals.

    Not scheduled on beat — re-clustering should only run when the user asks, so it
    never disturbs manual curation between sessions.
    """
    from app.ai.reid import recompute as reid_recompute

    lock = jobs.acquire("pipeline", "celery:reid", wait=40 * 60)
    if lock is None:
        return {"status": "busy"}
    with lock, SessionLocal() as db:
        result = reid_recompute(db)
    log.info("reid.done", **result)
    return result


@celery.task(name="app.tasks.ai.sex_pass")
def sex_pass() -> dict:
    """On-demand cloud-vision sex pass: stag/hind + boar sex (costs API credit per call)."""
    from app.ai.vision_sex import sex_pass as run

    lock = jobs.try_acquire("sexpass", "celery:sex")
    if lock is None:
        return {"status": "busy"}
    with lock, SessionLocal() as db:
        out = run(db)
    log.info("sex_pass.done", stopped=out.get("stopped"))
    return out
