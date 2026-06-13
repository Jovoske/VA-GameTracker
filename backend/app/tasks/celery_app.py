"""Celery application + beat schedule."""
from celery import Celery

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
    },
)

# Import task modules so they register with the app.
from app.tasks import sync  # noqa: E402,F401
