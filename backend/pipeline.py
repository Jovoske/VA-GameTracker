"""Native (no-Celery) pipeline runner.

Docker ran these as Celery beat tasks; the native build drives them from Windows Task
Scheduler instead, and the app's buttons start the same script (app.jobs.spawn), so
the AI models never load into the web server. Modes:

    python pipeline.py sync       # SPYPOINT + UBox fetch + local AI (free) — every 15 min
    python pipeline.py sync queued  # the Check button while another job runs: waits for it
    python pipeline.py backfill [months]  # SPYPOINT history pull + local AI — one-off
    python pipeline.py scan       # the local AI pass over waiting photos only
    python pipeline.py login <id> # first import of a camera login just added + local AI
    python pipeline.py sex        # cloud stag/hind + boar/sow pass (costs API credit) — hourly
    python pipeline.py plan       # record tonight's claims before the night — daily, ~17:00
    python pipeline.py score      # grade the claims of finished nights — daily, ~11:00
    python pipeline.py reid       # "Look for repeats": embed new sightings, regroup them
    python pipeline.py busy       # exit 3 while a run is working (deploy/update.ps1)

Every mode but `sex` shares the "pipeline" lock (app.jobs): they load the CPU models
or rebuild the exposure table, so they must never run on top of each other. `sync`
and the one-offs give way when it is held (the next fetch is 15 minutes off); `plan`,
`score`, `reid` and a queued `sync` wait for it, and `plan`/`score` exit 1 if it never
frees, so Task Scheduler shows a failure instead of a silent success. The lock is
taken before the heavy AI imports, so a run that finds it held costs a couple of
seconds.

Everything a run logs also goes to pipeline.log (app.jobs.log_dir): Task Scheduler
throws a scheduled run's output away.
"""
import os
import sys
import uuid
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# --- load .env into the process environment (same rationale as serve.py) ---
_env = Path(__file__).with_name(".env")
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from app import jobs  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402

log = get_logger("pipeline")

MODES = ("sync", "backfill", "scan", "login", "sex", "plan", "score", "reid", "busy")
# plan and score wait this long for a running job (inside the tasks' 1 h limit).
WAIT_SECONDS = int(os.environ.get("PIPELINE_WAIT_SECONDS", str(40 * 60)))
POLL_SECONDS = 30
# A Check press queued behind another job looks for the lock this often, so the
# photos come in as soon as that job ends.
QUEUE_POLL_SECONDS = 5
# Tonight's claim is written by the 17:00 plan run (GameSense-Plan). If that run never
# did (it crashed, or timed out waiting), any fetch or photo check from then on writes
# it, until sunset and never after dark: a claim made after dark is not a forecast
# (scoring._claims_for). At Alatoz the sun sets before 17:45 from late November to
# Christmas, so the window opens at 17:00, or an hour before sunset if that is earlier.
PLAN_AT = time(17, 0)
PLAN_LEAD = timedelta(hours=1)
BUSY_EXIT = 3
# Jobs a button queues behind a running one: the marker lock that says one is on its
# way, so a second tap is told so instead of queueing another.
QUEUES = {("reid", ()): "reid", ("sync", ("queued",)): "fetchqueue"}


def _claimed(db, day) -> bool:
    """Whether a claim for `day` has been written already."""
    from sqlalchemy import select

    from app.models import ModelRun

    return db.scalar(select(ModelRun.id).where(
        ModelRun.kind == "forecast",
        ModelRun.metrics["target_date"].astext == day.isoformat(),
    ).limit(1)) is not None


def plan_catch_up(db, now: datetime | None = None) -> dict | None:
    """Tonight's claim, if nothing has claimed tonight yet and it is still daylight."""
    from app.enrichment.astro import solar

    now = now or datetime.now(UTC)
    zone = ZoneInfo(settings.estate_timezone)
    local = now.astimezone(zone)
    sunset = solar(settings.estate_lat, settings.estate_lon, local.date()).get("sunset")
    if sunset is None or now >= sunset:
        return None
    opens = min(datetime.combine(local.date(), PLAN_AT, tzinfo=zone), sunset - PLAN_LEAD)
    if now < opens or _claimed(db, local.date()):
        return None
    from app.forecasting.model import forecast_tonight
    from app.forecasting.scoring import persist_tonight

    run = persist_tonight(db, forecast_tonight(db), target=local.date())
    log.warning("pipeline.plan_caught_up", model_run=str(run.id), **(run.metrics or {}))
    return run.metrics


def _checked(db) -> None:
    from app.ingestion.fetch import check_and_recount

    results, error = check_and_recount(db)
    log.info("pipeline.ai", result=results.get("ai"), error=error)


def _catch_up(db) -> None:
    """After a fetch or a photo check: tonight's claim, if the plan run never wrote it."""
    if jobs.lock_lost():
        return  # another run has the lock now; it writes the claim if it is due
    plan_catch_up(db)


def _run(mode: str, args: list[str], db) -> int:
    if mode == "sync":
        # Both providers (one failing never stops the other), the AI pass and the
        # night recount, leaving the summary row the Check button and Settings read.
        from app.ingestion.fetch import latest_run, run_fetch

        if args[:1] == ["queued"]:
            # A Check press that waited for another job: if a fetch has run since
            # it was pressed (the scheduled one got the lock first), that was it.
            asked = jobs.read_note(db, "fetch_request").get("at")
            row = latest_run(db)
            if asked and row is not None and row.started_at >= datetime.fromisoformat(asked):
                log.info("pipeline.sync_already_done", asked=asked)
                return 0
        log.info("pipeline.sync", result=run_fetch(db))
        _catch_up(db)
    elif mode == "backfill":
        from app.ingestion.sync import backfill_all

        months = int(args[0]) if args else int(os.environ.get("BACKFILL_MONTHS", "1"))
        log.info("pipeline.backfill", result=backfill_all(db, months=months))
        _checked(db)
        _catch_up(db)
    elif mode == "scan":
        _checked(db)
        _catch_up(db)
    elif mode == "login":
        if not args:
            log.error("pipeline.login_needs_id")
            return 2
        from app.models import CameraAccount

        account = db.get(CameraAccount, uuid.UUID(args[0]))
        if account is None:
            log.warning("pipeline.login_gone", account=args[0])
            return 0
        if account.provider == "ubox":
            from app.ingestion.ubox_sync import backfill_ubox_account

            log.info("pipeline.login", result=backfill_ubox_account(db, args[0]))
        else:
            from app.ingestion.sync import backfill_account

            log.info("pipeline.login", result=backfill_account(db, args[0]))
        _checked(db)
        _catch_up(db)
    elif mode == "plan":
        # Record what the app is claiming BEFORE the night happens. A forecast
        # only ever read after the fact can never be scored, which is how the
        # old confidence figure survived so long without anyone checking it.
        from app.forecasting.model import forecast_tonight
        from app.forecasting.scoring import local_today, persist_tonight

        if _claimed(db, local_today()):
            # A fetch wrote it while this run waited for the lock: one claim a night.
            log.info("pipeline.plan_already_claimed", night=local_today().isoformat())
            return 0
        run = persist_tonight(db, forecast_tonight(db), target=local_today())
        log.info("pipeline.plan", model_run=str(run.id), **(run.metrics or {}))
    elif mode == "score":
        # Exposure first: a night the camera cannot vouch for must be excluded,
        # not counted as a miss, and that decision reads the exposure table. Then
        # every unscored night of the last two weeks, not only yesterday.
        from app.forecasting.exposure import recompute_camera_nights
        from app.forecasting.scoring import evaluate_pending

        recompute_camera_nights(db)
        log.info("pipeline.score", result=evaluate_pending(db))
    elif mode == "reid":
        from app.ai.reid import recompute

        started = datetime.now(UTC)
        jobs.note(db, "reid_status", state="running", started_at=started)
        try:
            result = recompute(db)
        except Exception as e:
            db.rollback()
            from app.ai.reid import ModelUnavailable

            words = str(e) if isinstance(e, ModelUnavailable) else (
                f"Something went wrong ({type(e).__name__}).")
            jobs.note(db, "reid_status", state="failed", finished_at=datetime.now(UTC),
                      error=words)
            if isinstance(e, ModelUnavailable):
                log.error("pipeline.reid_stopped", reason=words)
                return 1
            raise
        if result.get("stopped"):
            jobs.note(db, "reid_status", state="failed", finished_at=datetime.now(UTC),
                      error="It stopped partway: the server was held up too long. "
                            "Tap it again to finish.")
            log.warning("pipeline.reid_lost_lock", result=result)
            return 0
        jobs.note(db, "reid_status", state="done", finished_at=datetime.now(UTC), result=result)
        log.info("pipeline.reid", result=result)
    return 0


def _sex(db) -> int:
    from app.ai import vision_sex

    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("pipeline.sex.skipped_no_key")
        return 0
    limit = int(os.environ.get("SEX_LIMIT_PER_RUN", "150"))
    log.info("pipeline.sex", result=vision_sex.sex_pass(db, limit=limit))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    mode = argv[0] if argv else "sync"
    if mode not in MODES:
        print(f"unknown mode: {mode!r} (use {'|'.join(MODES)})")
        return 2
    if mode == "busy":
        # The deploy stands down while either lock is held, as it did when the cloud
        # stag/hind pass shared the pipeline lock: a migration or a code swap must not
        # land under a running pass.
        for name in ("pipeline", "sexpass"):
            h = jobs.holder(name)
            if h is not None:
                print(f"busy: {h.owner} (pid {h.pid} on {h.host}) since {h.started.isoformat()}")
                return BUSY_EXIT
        print("free")
        return 0

    configure_logging(log_file=jobs.log_dir() / "pipeline.log")
    name = "sexpass" if mode == "sex" else "pipeline"
    marker = QUEUES.get((mode, tuple(argv[1:])))
    queued = None
    if marker:
        # Marks a "Look for repeats" or a Check press as on its way, so a second tap
        # is told so instead of queueing another.
        queued = jobs.try_acquire(marker, mode)
        if queued is None:
            log.info("pipeline.skip_queued", mode=mode)
            return 0
    wait = WAIT_SECONDS if mode in ("plan", "score") or queued is not None else 0
    lock = jobs.acquire(name, mode, wait=wait,
                        poll=QUEUE_POLL_SECONDS if mode == "sync" else POLL_SECONDS)
    if lock is None:
        if queued is not None:
            queued.release()
        holder = jobs.holder(name)
        if mode in ("plan", "score"):
            log.error("pipeline.lock_timeout", mode=mode, waited_s=wait,
                      held_by=holder.owner if holder else None)
            return 1
        log.info("pipeline.skip_locked", mode=mode, held_by=holder.owner if holder else None)
        return 0
    jobs.run_under(lock)
    try:
        with SessionLocal() as db:
            return _sex(db) if mode == "sex" else _run(mode, argv[1:], db)
    except Exception:
        log.exception("pipeline.crashed", mode=mode)
        return 1
    finally:
        jobs.run_under(None)
        lock.release()
        if queued is not None:
            queued.release()
        if lock.lost:
            log.error("pipeline.lock_lost", mode=mode)


if __name__ == "__main__":
    sys.exit(main())
