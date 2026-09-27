"""Background jobs on a server with no queue: one lock each, a heartbeat, and a way to start them.

Production has no Celery: Windows Task Scheduler runs `pipeline.py <mode>`, and the
app's buttons start the same script as a process of its own (spawn), so the AI models
never load into the web server and a button press obeys the same lock as the timer.

The lock used to be a file judged by its age: a crash blocked every sync for 3 hours,
a run longer than 3 hours let a second one in on top of it, and any run deleted the
file whether it had written it or not. Now a lock is a file created atomically
(O_CREAT|O_EXCL, so two runs can never both take it) that names its owner: the job,
the process id, the host, when it began, and a token. A thread touches it every
minute while the job runs (the heartbeat). A lock is abandoned, and may be taken
over, when its heartbeat is older than LOCK_STALE or its process is gone from this
host, so a crash frees it within minutes and a long run never looks stale. A job
only ever removes a lock that carries its own token.

Two locks exist: "pipeline" (fetching, the AI pass, the night recount, the plan and
the score: anything that loads the local models or rebuilds camera_nights) and
"sexpass" (the cloud stag/hind pass, which needs no local model and must not hold
the photo fetch up for an hour). "reid" only marks a queued "Look for repeats", so
a second tap is told it is already on its way.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# A lock whose heartbeat is older than this was left by a run that died.
LOCK_STALE = timedelta(minutes=10)
HEARTBEAT_SECONDS = 60
# A takeover in progress that is older than this was left by a process that died
# in the middle of it (it takes milliseconds).
_TAKEOVER_STALE = 60

BACKEND = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Where the locks live: beside the media/models data, known-writable by the service."""
    return Path(settings.models_root).parent


def lock_path(name: str = "pipeline") -> Path:
    return data_dir() / f"{name}.lock"


def log_dir() -> Path:
    """Where pipeline.log goes: LOG_DIR, else the server's logs folder beside the data
    (C:\\GameSense\\logs on Db01, where update.ps1 writes too), else <data>/logs."""
    if settings.log_dir:
        return Path(settings.log_dir)
    beside = data_dir().parent / "logs"
    return beside if beside.is_dir() else data_dir() / "logs"


@dataclass
class Holder:
    """Who holds a lock, as its file says."""

    owner: str
    pid: int | None
    host: str | None
    started: datetime
    beat: datetime
    token: str | None


def _read(path: Path) -> Holder | None:
    try:
        raw = path.read_text(encoding="utf-8")
        beat = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        return None
    try:
        data = json.loads(raw)
        return Holder(
            owner=str(data.get("owner") or "?"), pid=data.get("pid"), host=data.get("host"),
            started=datetime.fromtimestamp(float(data["started"]), UTC),
            beat=beat, token=data.get("token"),
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        # Written by an older build ("sync 1727000000"), or caught between being
        # created and written: an owner we can only judge by its age.
        return Holder(owner=(raw.split() or ["?"])[0], pid=None, host=None,
                      started=beat, beat=beat, token=None)


def _alive(pid: int) -> bool:
    """Whether a process with this id is running on this machine."""
    if pid == os.getpid():
        return True
    if os.name == "nt":
        # os.kill(pid, 0) would *terminate* the process on Windows: ask the kernel.
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _abandoned(h: Holder, now: datetime) -> bool:
    if now - h.beat > LOCK_STALE:
        return True
    return bool(h.pid) and h.host == socket.gethostname() and not _alive(int(h.pid))


def holder(name: str = "pipeline", now: datetime | None = None) -> Holder | None:
    """The live holder of a lock, or None when it is free or was abandoned."""
    h = _read(lock_path(name))
    if h is None or _abandoned(h, now or datetime.now(UTC)):
        return None
    return h


def busy_since(name: str = "pipeline") -> datetime | None:
    h = holder(name)
    return h.started if h else None


class JobLock:
    """A held lock. Use acquire() to get one; release() (or `with`) gives it back."""

    def __init__(self, name: str, owner: str, token: str, path: Path):
        self.name, self.owner, self.token, self.path = name, owner, token, path
        self.lost = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, name=f"{name}-heartbeat", daemon=True)
        self._thread.start()

    def _mine(self) -> bool:
        h = _read(self.path)
        return h is not None and h.token == self.token

    def _beat(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            if not self._mine():
                # Taken over (this process stalled past LOCK_STALE) or removed by hand:
                # never touch someone else's lock.
                self.lost = True
                log.warning("joblock.lost", lock=self.name, owner=self.owner)
                return
            try:
                os.utime(self.path)
            except OSError as e:
                log.warning("joblock.heartbeat_failed", lock=self.name, error=str(e))

    def release(self) -> None:
        self._stop.set()
        if self._mine():
            for _ in range(3):
                try:
                    self.path.unlink()
                    break
                except FileNotFoundError:
                    break
                except PermissionError:  # Windows: a reader has it open for a moment
                    time.sleep(0.2)

    def __enter__(self) -> JobLock:
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def _create(path: Path, owner: str, token: str) -> bool:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"owner": owner, "pid": os.getpid(), "host": socket.gethostname(),
                   "started": time.time(), "token": token}, f)
    return True


def _take_over(path: Path, now: datetime) -> None:
    """Remove an abandoned lock, one process at a time.

    Without the guard, two runs could both judge the same dead lock, one remove it
    and take the lock, and the other then remove the fresh one. Inside the guard the
    lock is read again and removed only if it is still the abandoned one.
    """
    guard = path.with_name(path.name + ".takeover")
    try:
        fd = os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        try:
            if time.time() - guard.stat().st_mtime > _TAKEOVER_STALE:
                guard.unlink()
        except OSError:
            pass
        return
    os.close(fd)
    try:
        h = _read(path)
        if h is not None and _abandoned(h, now):
            log.warning("joblock.taking_over", lock=path.name, owner=h.owner, pid=h.pid,
                        host=h.host, beat=h.beat.isoformat())
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    finally:
        try:
            guard.unlink()
        except OSError:
            pass


def try_acquire(name: str, owner: str) -> JobLock | None:
    """Take the lock now, or None when a live run holds it."""
    path = lock_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    if _create(path, owner, token):
        return JobLock(name, owner, token, path)
    h = _read(path)
    if h is None or _abandoned(h, datetime.now(UTC)):
        _take_over(path, datetime.now(UTC))
        if _create(path, owner, token):
            return JobLock(name, owner, token, path)
    return None


def acquire(name: str, owner: str, *, wait: float = 0, poll: float = 30) -> JobLock | None:
    """Take the lock, waiting up to `wait` seconds for a running job to finish."""
    deadline = time.monotonic() + wait
    said = False
    while True:
        lock = try_acquire(name, owner)
        if lock is not None or time.monotonic() >= deadline:
            return lock
        if not said:
            h = _read(lock_path(name))
            log.info("joblock.waiting", lock=name, owner=owner, held_by=h.owner if h else None)
            said = True
        time.sleep(min(poll, max(0.0, deadline - time.monotonic())))


def note(db, key: str, **fields) -> dict:
    """Merge `fields` into a job's status document (app_settings) and commit it.

    What the AI pass or the stag/hind pass last did, and why it stopped, kept where
    the admin status can read it: a log file on the server is not somewhere anyone
    looks when the photos stop being labelled.
    """
    from sqlalchemy.orm.attributes import flag_modified

    from app.models import AppSetting

    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value={})
        db.add(row)
    value = dict(row.value or {})
    value.update({k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in fields.items()})
    row.value = value
    flag_modified(row, "value")
    db.commit()
    return value


def read_note(db, key: str) -> dict:
    from app.models import AppSetting

    row = db.get(AppSetting, key)
    return dict(row.value or {}) if row is not None else {}


def spawn(mode: str, *args: str) -> bool:
    """Start `pipeline.py <mode> [args]` as a process of its own and return at once.

    The job takes its own lock, so the caller only checks the lock to answer "busy"
    first. It logs to pipeline.log like a scheduled run. On Windows it is started
    without a console and outside the web service's process group, so restarting the
    service does not have to stop it.
    """
    cmd = [sys.executable, str(BACKEND / "pipeline.py"), mode, *args]
    folder = log_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        out = open(folder / "pipeline.log", "ab")  # noqa: SIM115 - handed to the child
    except OSError:
        out = subprocess.DEVNULL
    # Its log lines go to pipeline.log themselves (app.core.logging); only what it
    # writes before logging starts (an import that fails) comes through stderr.
    kwargs: dict = {"cwd": str(BACKEND), "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL, "stderr": out, "close_fds": True}
    try:
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            try:
                subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB,
                                 **kwargs)
            except OSError:  # the service's job does not allow breaking away
                subprocess.Popen(cmd, creationflags=flags, **kwargs)
        else:
            subprocess.Popen(cmd, start_new_session=True, **kwargs)
    except OSError as e:
        log.error("jobs.spawn_failed", mode=mode, error=str(e))
        return False
    finally:
        if out is not subprocess.DEVNULL:
            out.close()
    log.info("jobs.spawned", mode=mode, args=list(args))
    return True
