"""Liveness and readiness probes."""
import redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "app": "GameSense", "version": "0.1.0"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    checks = {"database": False, "redis": False}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass
    try:
        checks["redis"] = bool(redis.from_url(settings.redis_url).ping())
    except Exception:
        pass
    return {"status": "ok" if all(checks.values()) else "degraded", "checks": checks}
