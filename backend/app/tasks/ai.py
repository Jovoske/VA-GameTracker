"""AI Celery tasks — empty-frame scanning, species classification, re-ID."""
from app.ai.empty_filter import scan_unprocessed
from app.ai.reid import recompute as reid_recompute
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


@celery.task(name="app.tasks.ai.reid")
def reid() -> dict:
    """On-demand re-ID: embed new detections + regenerate candidate individuals.

    Not scheduled on beat — re-clustering should only run when the user asks, so it
    never disturbs manual curation between sessions.
    """
    with SessionLocal() as db:
        result = reid_recompute(db)
    log.info("reid.done", **result)
    return result


@celery.task(name="app.tasks.ai.sex_pass")
def sex_pass() -> dict:
    """On-demand cloud-vision sex pass: stag/hind + boar sex (costs API credit per call)."""
    from app.ai.vision_sex import sex_unclassified

    out: dict = {}
    with SessionLocal() as db:
        for sp in ("red_deer", "wild_boar"):
            out[sp] = sex_unclassified(db, sp)
    log.info("sex_pass.done", **{k: v.get("processed") for k, v in out.items()})
    return out
