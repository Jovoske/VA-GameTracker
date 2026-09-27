"""Admin — version, Git update check, and system status (deliverable 10).

The update *check* runs anywhere (GitHub API). Auto-applying an update (git pull +
migrate + restart) is deployment-specific and belongs to the host/server per
docs/08-git-update.md, so here we surface the version delta + the exact command.
"""
import os
import re
import shutil
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import jobs
from app.api.deps import get_current_admin
from app.core.db import get_db
from app.models import Camera, Detection, Image, User
from app.version import __version__

router = APIRouter(prefix="/admin", tags=["admin"])
_REPO = "Jovoske/VA-GameTracker"


@router.post("/sex-pass")
def sex_pass(_: Annotated[User, Depends(get_current_admin)]) -> dict:
    """Start the cloud-vision sex pass (stag/hind + boar sex). Needs ANTHROPIC_API_KEY.

    It runs as `pipeline.py sex` under its own lock, the one the hourly run takes, so
    a second tap (or a tap while the hourly pass runs) never bills a photo twice.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(400, "Add ANTHROPIC_API_KEY to .env first")
    if jobs.holder("sexpass") is not None:
        return {"status": "busy", "note": "Already labelling. Labels appear over a few minutes."}
    if not jobs.spawn("sex"):
        raise HTTPException(503, "Could not start it on the server. Try again in a minute.")
    return {"status": "started", "note": "Labels appear in Cameras over a few minutes."}


@router.post("/ai/retry")
def retry_failed_photos(
    _: Annotated[User, Depends(get_current_admin)], db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Photos the AI pass gave up on get another round of tries on the next fetch."""
    from app.ai.checking import retry_failed

    n = retry_failed(db)
    return {"photos": n, "note": f"{n} photo{'' if n == 1 else 's'} will be checked again "
                                 "on the next fetch." if n else "Nothing to try again."}


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
        "update_command": "Push to main. The server picks it up within 10 minutes.",
    }


def _suntek_spool() -> dict | None:
    """Suntek photos waiting to be imported and parked after failing, when there is a
    spool on this server (FTP or email camera); None when there is not."""
    from pathlib import Path

    from app.core.config import settings
    from app.ingestion.ftp_import import spool_counts

    root = settings.ftp_spool_root or str(Path(settings.models_root).parent / "ftp-spool")
    try:
        return spool_counts(root)
    except OSError:
        return None


# Below this much free space where the photos are kept, Settings says so. A UBox HD
# frame is about 0.4 MB and a busy camera sends hundreds a day, and the disk is the
# database's too: a full one stops both, with nothing on screen until it has.
LOW_DISK_BYTES = 2 * 1024**3


def _disk() -> dict | None:
    """Free space on the disk the photos are kept on; None when it can't be read."""
    from app.core.config import settings

    try:
        use = shutil.disk_usage(settings.media_root)
    except OSError:
        return None
    return {"free_gb": round(use.free / 1024**3, 1), "total_gb": round(use.total / 1024**3, 1),
            "low": use.free < LOW_DISK_BYTES}


@router.get("/status")
def status(_: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> dict:
    from app.ingestion.fetch import latest_run

    # The fetch summary (every provider together), not whichever provider wrote last.
    last = latest_run(db)
    return {
        "cameras": db.scalar(select(func.count(Camera.id))) or 0,
        "images": db.scalar(select(func.count(Image.id))) or 0,
        "detections": db.scalar(select(func.count(Detection.id))) or 0,
        "empty": db.scalar(select(func.count(Image.id)).where(Image.is_empty_frame.is_(True))) or 0,
        "last_sync": (
            {"status": last.status, "at": last.finished_at or last.started_at} if last else None
        ),
        "suntek": _suntek_spool(),
        "disk": _disk(),
        "ai": _ai_status(db),
        "sex_pass": _sex_status(db),
    }


def _ai_status(db: Session) -> dict:
    """The AI pass as the owner needs it: how many photos are waiting, how many it gave
    up on, whether it is running, and the last thing that went wrong."""
    from app.ai.checking import STATUS, failed_count, waiting_count

    note = jobs.read_note(db, STATUS)
    holder = jobs.holder("pipeline")
    # Only a run that checks photos is "checking now": the lock is also held by
    # Look for repeats, tonight's plan and the morning score.
    checking = holder is not None and holder.owner in jobs.CHECK_MODES
    return {
        "waiting": waiting_count(db),
        "failed": failed_count(db),
        "running_since": holder.started if checking else None,
        # Where the whole story is when checking stops: the owner runs the server.
        "log_file": str(jobs.log_dir() / "pipeline.log"),
        "last_run_at": note.get("last_run_at"),
        "last_ok_at": note.get("last_ok_at"),
        "stopped": note.get("stopped"),
        "last_error": note.get("last_error"),
        "last_error_at": note.get("last_error_at"),
    }


def _sex_status(db: Session) -> dict:
    from app.ai.vision_sex import STATUS, waiting

    note = jobs.read_note(db, STATUS)
    return {
        "enabled": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "running": jobs.holder("sexpass") is not None,
        "waiting": waiting(db),
        "last_run_at": note.get("last_run_at"),
        "labelled": note.get("labelled"),
        "stopped": note.get("stopped"),
        "last_error": note.get("last_error"),
        "last_error_at": note.get("last_error_at"),
    }
