"""Liveness and readiness probes that tell the truth.

/api/health answers 200 only when the app can reach its database, with the version
and the commit this process runs; 503 when it can't. deploy/update.ps1 asks it after
every restart and rolls the deploy back when it doesn't come good, so a constant
"ok" here would let a broken deploy stand (audit H-07).

/api/ready says, on top, whether the database's schema is at the code's migration
head, and whether Redis answers where a Celery broker is in use (the Docker stack).
The native server runs no Celery and has no Redis, so there it is not asked about:
asking would make the server read "degraded" for ever. Anything not ready is a 503.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.logging import get_logger
from app.version import COMMIT, __version__

router = APIRouter(tags=["system"])
log = get_logger(__name__)

BACKEND = Path(__file__).resolve().parents[2]


def _database(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception as e:
        log.warning("health.database_unreachable", error=type(e).__name__)
        return False


@lru_cache
def code_head() -> str | None:
    """The newest migration this code carries, or None when it can't be told (two
    heads, or no scripts on disk)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    try:
        cfg = Config()
        cfg.set_main_option("script_location", str(BACKEND / "alembic"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:
        return None


def _schema(db: Session) -> str | None:
    try:
        return db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        db.rollback()
        return None


def _broker_in_use() -> bool:
    """A Celery broker is configured (REDIS_URL set, as the Docker stack does)."""
    return "redis_url" in settings.model_fields_set


def _redis() -> bool:
    import redis

    try:
        return bool(redis.from_url(settings.redis_url, socket_timeout=2).ping())
    except Exception:
        return False


@router.get("/health")
def health(db: Annotated[Session, Depends(get_db)]) -> JSONResponse:
    ok = _database(db)
    return JSONResponse(
        {"status": "ok" if ok else "down", "app": "GameSense", "version": __version__,
         "commit": COMMIT, "database": ok},
        status_code=200 if ok else 503,
    )


@router.get("/ready")
def ready(db: Annotated[Session, Depends(get_db)]) -> JSONResponse:
    database = _database(db)
    at, head = (_schema(db) if database else None), code_head()
    checks = {"database": database, "schema": database and at is not None and at == head}
    if _broker_in_use():
        checks["redis"] = _redis()
    ok = all(checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "degraded", "checks": checks, "schema": at,
         "code_schema": head, "version": __version__, "commit": COMMIT},
        status_code=200 if ok else 503,
    )
