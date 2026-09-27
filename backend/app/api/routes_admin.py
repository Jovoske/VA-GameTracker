"""Admin — the version and how the server's self-update is doing, and system status.

The server updates itself (deploy/update.ps1, every 10 minutes, only commits that
passed the tests once CI is live), so "App version" says what that last did: which
commit runs, since when, what waits for its tests, and an update that didn't go in
and why. It used to ask GitHub for release tags, which stopped at v0.17.0 while the
app moved on by pushes, so it said "Up to date" whatever the server ran, and also
when GitHub refused to answer (audit D-22). System also says how the nightly backup
and the weekly restore rehearsal went, and how much room is left for photos (H-10,
H-18). All of it comes from files the server's own tasks write (app.ops).
"""
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import jobs, ops
from app.api.deps import get_current_admin
from app.core.db import get_db
from app.models import Camera, Detection, Image, User
from app.version import COMMIT, __version__

router = APIRouter(prefix="/admin", tags=["admin"])

# A deploy holds every job's lock while it swaps the code (pipeline.py hold).
DEPLOYING = "The server is installing an update. Try again in a few minutes."


def _deploying(name: str) -> bool:
    h = jobs.holder(name)
    return h is not None and h.owner == "deploy"


@router.post("/sex-pass")
def sex_pass(_: Annotated[User, Depends(get_current_admin)]) -> dict:
    """Start the cloud-vision sex pass (stag/hind + boar sex). Needs ANTHROPIC_API_KEY.

    It runs as `pipeline.py sex` under its own lock, the one the hourly run takes, so
    a second tap (or a tap while the hourly pass runs) never bills a photo twice.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(400, "Add ANTHROPIC_API_KEY to .env first")
    if _deploying("sexpass"):
        return {"status": "busy", "note": DEPLOYING}
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
    """The version, the commit this process runs, and the self-update's last word
    (None where no self-update runs, as on a laptop)."""
    return {"version": __version__, "commit": COMMIT, "deploy": ops.deploy()}


@router.get("/version/check")
def version_check(_: User = Depends(get_current_admin)) -> dict:
    """What an app copy from before the self-update status asks; it shows `error`."""
    return {"current": f"v{__version__}", "latest": None, "update_available": False,
            "error": "Reload the app: updates now show under App version by themselves."}


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
        "disk": ops.disk(),
        "backup": ops.backup(),
        "restore_check": ops.restore_check(),
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
        "running": jobs.holder("sexpass") is not None and not _deploying("sexpass"),
        "waiting": waiting(db),
        "last_run_at": note.get("last_run_at"),
        "labelled": note.get("labelled"),
        "stopped": note.get("stopped"),
        "last_error": note.get("last_error"),
        "last_error_at": note.get("last_error_at"),
    }
