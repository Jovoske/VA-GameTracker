"""What the server's own upkeep last did, for Settings -> App version and System.

deploy/update.ps1 (every 10 minutes), deploy/backup.ps1 (nightly) and
deploy/restore-check.ps1 (weekly) run as scheduled tasks on the server, outside the
app. Each leaves a small JSON file beside the job locks (app.jobs.data_dir():
C:\\GameSense\\data on Db01) saying what it last did, and this reads them. A missing
file means the task has never run on this server, and an old one means it stopped:
both are what the owner needs to see, because a backup nobody checks is not a backup
(audit H-10), and "Up to date" from a check that never ran is not an answer (D-22).

Also the free space where the photos are kept (H-18): the same disk holds the
database and the nightly dumps, and a full one stops all three.
"""
from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta

from app import jobs
from app.core.config import settings
from app.i18n import localize, t

DEPLOY_FILE = "deploy-status.json"
BACKUP_FILE = "backup-status.json"
RESTORE_FILE = "restore-check.json"

# The update task runs every 10 minutes: three missed runs is a stopped task.
DEPLOY_LATE = timedelta(minutes=30)
# The backup runs nightly: a day and a half without one is a night missed.
BACKUP_LATE = timedelta(hours=36)
# The restore check runs weekly.
RESTORE_LATE = timedelta(days=8)

# Free space where the photos are kept. Below LOW_DISK Settings says so in amber;
# below FULL_DISK in red, and the photo fetch stops downloading (app.ingestion.fetch)
# so the database, which shares the disk, keeps room to work.
LOW_DISK_BYTES = 20 * 1024**3
FULL_DISK_BYTES = 5 * 1024**3


def read_status(name: str) -> dict | None:
    """A task's status file, None when there is none, {"unreadable": True} when it
    can't be read as one (half-written, or edited by hand)."""
    try:
        # utf-8-sig: Windows PowerShell 5.1 may start a file with a byte-order mark.
        raw = (jobs.data_dir() / name).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError:
        return {"unreadable": True}
    try:
        value = json.loads(raw)
    except ValueError:
        return {"unreadable": True}
    return value if isinstance(value, dict) else {"unreadable": True}


def _when(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value, limit: int = 300) -> str | None:
    return value.strip()[:limit] or None if isinstance(value, str) else None


def deploy(now: datetime | None = None) -> dict | None:
    """The self-update as update.ps1 last left it; None when it never ran here."""
    s = read_status(DEPLOY_FILE)
    if s is None:
        return None
    now = now or datetime.now(UTC)
    checked = _when(s.get("checked_at"))
    failed = s.get("failed") if isinstance(s.get("failed"), dict) else None
    return {
        "checked_at": checked,
        "late": checked is None or now - checked > DEPLOY_LATE,
        # "deploy": only commits that passed the tests; "main": every push (no CI yet).
        "source": s.get("source") if s.get("source") in ("deploy", "main") else None,
        "running": _text(s.get("running"), 40),
        "running_subject": _text(s.get("running_subject"), 120),
        "running_since": _when(s.get("running_since")),
        "waiting_for_tests": _int(s.get("waiting_for_tests")),
        "offline": s.get("state") == "offline",
        "failed": failed and {
            "commit": _text(failed.get("commit"), 40),
            "subject": _text(failed.get("subject"), 120),
            "step": _text(failed.get("step"), 40),
            "reason": _text(failed.get("reason")),
            "at": _when(failed.get("at")),
            "attempts": _int(failed.get("attempts")),
            "gave_up": bool(failed.get("gave_up")),
            "rolled_back": bool(failed.get("rolled_back")),
        },
    }


def backup(now: datetime | None = None) -> dict | None:
    """The nightly backup as backup.ps1 last left it; None when it never ran here."""
    s = read_status(BACKUP_FILE)
    if s is None:
        return None
    now = now or datetime.now(UTC)
    at = _when(s.get("finished_at"))
    ok = s.get("ok") is True
    # The last one that worked, so a failed night still says how old the good copy is.
    last_ok = at if ok else _when(s.get("last_ok_at"))
    return {
        "at": at, "ok": ok, "last_ok_at": last_ok,
        "late": last_ok is None or now - last_ok > BACKUP_LATE,
        "target": _text(s.get("target"), 200),
        "dump_mb": s.get("dump_mb") if isinstance(s.get("dump_mb"), (int, float)) else None,
        # Photos in the media folder and in its copy: the copy never has fewer.
        "photos_on_server": _int(s.get("photos_on_server")),
        "photos_in_backup": _int(s.get("photos_in_backup")),
        "target_free_gb": (s.get("target_free_gb")
                           if isinstance(s.get("target_free_gb"), (int, float)) else None),
        "error": localize(_text(s.get("error"))) or (t("ops.unreadable")
                                                     if s.get("unreadable") else None),
    }


def restore_check(now: datetime | None = None) -> dict | None:
    """The weekly restore rehearsal; None when it never ran here."""
    s = read_status(RESTORE_FILE)
    if s is None:
        return None
    now = now or datetime.now(UTC)
    at = _when(s.get("finished_at"))
    return {
        "at": at, "ok": s.get("ok") is True,
        "late": at is None or now - at > RESTORE_LATE,
        "dump": _text(s.get("dump"), 200),
        "photos_checked": _int(s.get("photos_checked")),
        "photos_found": _int(s.get("photos_found")),
        "error": _problems(s) or (t("ops.unreadable") if s.get("unreadable") else None),
    }


def _problems(s: dict) -> str | None:
    """What the restore rehearsal found wrong, in the reader's language (kept in
    English, each on its own, by app.backup_check)."""
    problems = s.get("problems")
    if isinstance(problems, list) and problems and all(isinstance(p, str) for p in problems):
        return " ".join(localize(p) for p in problems)[:300]
    return localize(_text(s.get("error")))


def disk_free(path: str | None = None) -> int | None:
    """Free bytes on the disk that holds `path` (the photos by default), or None."""
    try:
        return shutil.disk_usage(path or settings.media_root).free
    except OSError:
        return None


def disk() -> dict | None:
    """Free space where the photos are kept; None when it can't be read."""
    try:
        use = shutil.disk_usage(settings.media_root)
    except OSError:
        return None
    return {"free_gb": round(use.free / 1024**3, 1), "total_gb": round(use.total / 1024**3, 1),
            "low": use.free < LOW_DISK_BYTES, "full": use.free < FULL_DISK_BYTES}
