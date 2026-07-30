"""Celery application + beat schedule."""
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery = Celery("gamesense", broker=settings.redis_url, backend=settings.redis_url)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.estate_timezone,
    enable_utc=True,
    beat_schedule={
        "spypoint-sync": {
            "task": "app.tasks.sync.spypoint_sync",
            "schedule": float(settings.sync_interval_minutes * 60),
        },
        "scan-empty": {
            "task": "app.tasks.ai.scan_empty",
            "schedule": 1200.0,  # every 20 min — flag empties on newly synced photos
        },
        "classify-species": {
            "task": "app.tasks.ai.classify_species",
            "schedule": 1500.0,  # every 25 min — classify newly-kept animal frames
        },
        "persist-forecast": {
            # Record the claim before the night it is about, so it cannot be
            # rewritten after the fact.
            "task": "app.tasks.scoring.persist_forecast",
            "schedule": crontab(hour=16, minute=0),
        },
        "score-yesterday": {
            # Grade it the next morning, once the night's frames have synced.
            "task": "app.tasks.scoring.score_yesterday",
            "schedule": crontab(hour=9, minute=0),
        },
        "recompute-exposure": {
            # The denominator. Runs after the classifier has had a chance at the
            # night's frames, so nights settle from UNPROCESSED to CONFIRMED rather
            # than being counted as empty.
            "task": "app.tasks.exposure.recompute_exposure",
            "schedule": 3600.0,
        },
    },
)

# Import task modules so they register with the app.
from app.tasks import ai, exposure, scoring, sync  # noqa: E402,F401
