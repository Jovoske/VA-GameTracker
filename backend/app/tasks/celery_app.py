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
        # Exposure is the denominator under every statistic in the app, and it moves
        # as photos arrive and the classifier drains its backlog. Recompute hourly so
        # "10 of 44 nights this camera was watching" is true when it is read.
        "recompute-exposure": {
            "task": "app.tasks.exposure.recompute_exposure",
            "schedule": 3600.0,
        },
        # Record tonight's claim BEFORE the night happens. A forecast that is only
        # ever read after the fact can never be scored, which is how the old
        # confidence figure survived so long without anyone checking it.
        "persist-forecast": {
            "task": "app.tasks.scoring.persist_forecast",
            "schedule": crontab(hour=17, minute=0),
        },
        # Grade yesterday's claims once the night's photos have synced and been
        # classified. Late morning leaves room for both.
        "score-yesterday": {
            "task": "app.tasks.scoring.score_yesterday",
            "schedule": crontab(hour=11, minute=0),
        },
    },
)

# Import task modules so they register with the app.
from app.tasks import ai, exposure, scoring, sync  # noqa: E402,F401
