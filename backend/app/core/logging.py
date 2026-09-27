"""Structured JSON logging via structlog."""
import logging
import os
import re
import sys
from pathlib import Path

import structlog

# A log file is rolled over past this size, keeping this many old files beside it.
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_KEEP = 3


class _Tee:
    """stdout plus a log file: Task Scheduler throws a scheduled run's stdout away.

    Whole lines only, each in one write, so two runs appending to the same file at
    once (a scheduled one and one a button started) never splice their lines.
    """

    def __init__(self, *streams):
        self.streams = streams
        self._pending = ""

    def write(self, text: str) -> None:
        self._pending += text
        if "\n" not in self._pending:
            return
        lines, self._pending = self._pending.rsplit("\n", 1)
        for stream in self.streams:
            try:
                stream.write(lines + "\n")
                stream.flush()
            except (OSError, ValueError):
                pass  # a full disk or a closed stream must never stop the job

    def flush(self) -> None:
        pass


def _open_log(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            for n in range(LOG_KEEP - 1, 0, -1):
                older = path.with_name(f"{path.name}.{n}")
                if older.exists():
                    os.replace(older, path.with_name(f"{path.name}.{n + 1}"))
            os.replace(path, path.with_name(f"{path.name}.1"))
    except OSError:
        pass  # another run has it open (Windows): it rolls over next time
    return open(path, "a", encoding="utf-8")  # noqa: SIM115 - lives as long as the process


_TOKEN = re.compile(r"((?:^|[?&])token=)[^&\s\"]+")


class RedactTokens(logging.Filter):
    """Blank ?token= in the access log's request lines.

    uvicorn logs each request's path with its query string, and a photo's address
    carries a photo pass there (app.core.security). A pass is short-lived and opens
    only photos, but a log is read by more people than it should be, for longer than
    a pass lasts; an old app on a phone may still send its sign-in (audit D-08, H-13).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _TOKEN.sub(r"\1…", a) if isinstance(a, str) else a for a in record.args
            )
        if isinstance(record.msg, str):
            record.msg = _TOKEN.sub(r"\1…", record.msg)
        return True


def redact_access_log() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactTokens) for f in access.filters):
        access.addFilter(RedactTokens())


def configure_logging(level: str = "INFO", log_file: str | Path | None = None) -> None:
    logging.basicConfig(format="%(message)s", level=getattr(logging, level, logging.INFO))
    redact_access_log()
    out = sys.stdout
    if log_file is not None:
        try:
            out = _Tee(sys.stdout, _open_log(Path(log_file)))
        except OSError:
            pass  # no log file is no reason not to run
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level, logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(file=out),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
