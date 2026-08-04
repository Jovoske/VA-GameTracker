"""Native (no-Celery) pipeline runner.

Docker ran these as Celery beat tasks; the native build drives them from Windows Task
Scheduler instead. Three modes:

    python pipeline.py sync       # SPYPOINT incremental sync + local AI (free) — every 15 min
    python pipeline.py backfill   # initial SPYPOINT pull (BACKFILL_MONTHS) + local AI — one-off
    python pipeline.py sex        # cloud vision stag/hind + boar/sow pass (costs API credit) — hourly
    python pipeline.py plan       # record tonight's claims before the night — daily, ~17:00
    python pipeline.py score      # grade last night's claims against the cameras — daily, ~11:00

A lock file serialises every mode: the long initial backfill, the 15-min sync and the
hourly sex pass share one database and load the CPU models into memory, so they must never
run on top of each other. The lock is checked before the heavy AI imports, so a run that
finds the lock held exits in a couple of seconds.
"""
import os
import sys
import time
from pathlib import Path

# --- load .env into the process environment (same rationale as serve.py) ---
_env = Path(__file__).with_name(".env")
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from app.core.db import SessionLocal  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402

configure_logging()
log = get_logger("pipeline")

# Lock lives beside the media/models data (known-writable by the service account).
_DATA = Path(os.environ.get("MODELS_ROOT", str(Path(__file__).parent))).parent
LOCK = _DATA / "pipeline.lock"
LOCK_STALE_SECONDS = 3 * 3600  # a crashed run stops blocking after 3h


def _locked() -> bool:
    if LOCK.exists() and (time.time() - LOCK.stat().st_mtime) < LOCK_STALE_SECONDS:
        return True
    return False


def _run(mode: str) -> None:
    with SessionLocal() as db:
        if mode == "backfill":
            from app.ingestion.sync import backfill_all
            months = int(os.environ.get("BACKFILL_MONTHS", "1"))
            log.info("pipeline.backfill", result=backfill_all(db, months=months))
        elif mode == "sync":
            from app.ingestion.sync import sync_all
            log.info("pipeline.sync", result=sync_all(db))

        if mode in ("sync", "backfill"):
            from app.ai.empty_filter import scan_unprocessed
            from app.ai.species import classify_unclassified
            log.info("pipeline.scan", result=scan_unprocessed(db))
            log.info("pipeline.species", result=classify_unclassified(db))
            # Exposure is the denominator under every statistic in the app, and it
            # only becomes knowable once the frames are classified — an unprocessed
            # night is not an observation yet. So it runs here, after the AI pass,
            # rather than on its own timer.
            from app.forecasting.exposure import recompute_camera_nights
            log.info("pipeline.exposure", result=recompute_camera_nights(db))

        if mode == "plan":
            # Record what the app is claiming BEFORE the night happens. A forecast
            # only ever read after the fact can never be scored, which is how the
            # old confidence figure survived so long without anyone checking it.
            from app.forecasting.model import forecast_tonight
            from app.forecasting.scoring import persist_tonight
            run = persist_tonight(db, forecast_tonight(db))
            log.info("pipeline.plan", model_run=str(run.id), **(run.metrics or {}))

        if mode == "score":
            # Exposure first: a night the camera cannot vouch for must be excluded,
            # not counted as a miss, and that decision reads the exposure table.
            from app.forecasting.exposure import recompute_camera_nights
            from app.forecasting.scoring import evaluate_night
            recompute_camera_nights(db)
            log.info("pipeline.score", result=evaluate_night(db))

        if mode == "sex":
            if not os.environ.get("ANTHROPIC_API_KEY"):
                log.warning("pipeline.sex.skipped_no_key")
                return
            from app.ai.vision_sex import sex_unclassified
            limit = int(os.environ.get("SEX_LIMIT_PER_RUN", "150"))
            for sp in ("red_deer", "wild_boar"):
                log.info("pipeline.sex", species=sp, result=sex_unclassified(db, sp, limit=limit))


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "sync"
    if mode not in ("sync", "backfill", "sex", "plan", "score"):
        print(f"unknown mode: {mode!r} (use sync|backfill|sex|plan|score)")
        sys.exit(2)
    if _locked():
        log.info("pipeline.skip_locked", mode=mode)
        return
    LOCK.write_text(f"{mode} {int(time.time())}")
    try:
        _run(mode)
    finally:
        try:
            LOCK.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
