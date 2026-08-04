"""Admin — version, Git update check, and system status (deliverable 10).

The update *check* runs anywhere (GitHub API). Auto-applying an update (git pull +
migrate + restart) is deployment-specific and belongs to the host/server per
docs/08-git-update.md, so here we surface the version delta + the exact command.
"""
import os
import re

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.db import get_db
from app.models import Camera, Detection, Image, SyncLog, User
from app.version import __version__

router = APIRouter(prefix="/admin", tags=["admin"])
_REPO = "Jovoske/VA-GameTracker"


def _run_sex_pass() -> None:
    # Runs in the api process, which has reliable network — the Celery worker's DNS
    # can drop intermittently (same flakiness that breaks SPYPOINT sync).
    from app.ai.vision_sex import sex_unclassified
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        for sp in ("red_deer", "wild_boar"):
            sex_unclassified(db, sp)


@router.post("/sex-pass")
def sex_pass(
    background: BackgroundTasks, _: User = Depends(get_current_admin)
) -> dict:
    """Kick off the cloud-vision sex pass (stag/hind + boar sex). Needs ANTHROPIC_API_KEY."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(400, "Set ANTHROPIC_API_KEY in .env to enable sex identification")
    background.add_task(_run_sex_pass)
    return {"status": "started", "note": "Labels appear in Cameras over a few minutes."}


@router.get("/version")
def version(_: User = Depends(get_current_admin)) -> dict:
    return {"version": __version__}


@router.get("/version/check")
def version_check(_: User = Depends(get_current_admin)) -> dict:
    current = f"v{__version__}"
    try:
        tags = httpx.get(f"https://api.github.com/repos/{_REPO}/tags", timeout=15).json()
        names = [t["name"] for t in tags if isinstance(t, dict) and "name" in t]
        semver = [n for n in names if re.match(r"^v\d+\.\d+\.\d+$", n)]  # excludes v1-legacy
        latest = max(semver, key=lambda v: tuple(int(x) for x in v[1:].split("."))) if semver else None
    except Exception as e:
        return {"current": current, "latest": None, "error": str(e)}
    cur_t = tuple(int(x) for x in __version__.split("."))
    lat_t = (
        tuple(int(x) for x in latest[1:].split("."))
        if latest and re.match(r"^v\d+\.\d+\.\d+$", latest)
        else None
    )
    return {
        "current": current,
        "latest": latest,
        "update_available": bool(lat_t and lat_t > cur_t),
        # The server pulls from GitHub itself (deploy/update.ps1, every 10 min), so an
        # update needs nothing on the host — it only has to be pushed.
        "update_command": "Push to main — the server pulls and applies it within 10 minutes.",
    }


@router.get("/status")
def status(_: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> dict:
    last = db.scalar(select(SyncLog).order_by(SyncLog.started_at.desc()).limit(1))
    return {
        "cameras": db.scalar(select(func.count(Camera.id))) or 0,
        "images": db.scalar(select(func.count(Image.id))) or 0,
        "detections": db.scalar(select(func.count(Detection.id))) or 0,
        "empty": db.scalar(select(func.count(Image.id)).where(Image.is_empty_frame.is_(True))) or 0,
        "last_sync": (
            {"status": last.status, "at": last.finished_at} if last else None
        ),
    }
