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
    python pipeline.py notify     # alerts that waited for a sit or quiet hours, and
                                  # tonight's plan ~2 h before sunset — every 15 min
    python pipeline.py busy       # exit 3 while a run is working (deploy/update.ps1)
    python pipeline.py hold       # deploy/update.ps1: every job's lock, held until the
                                  # deploy closes this process's input (it is done)

Every mode but `sex` and `notify` shares the "pipeline" lock (app.jobs): they load
the CPU models or rebuild the exposure table, so they must never run on top of each
other. `notify` loads no model and takes a few seconds, so it never waits behind an
hour of photo checking: it has a lock of its own, only so two runs of it don't
overlap (and a second is not needed: every send is also guarded in the database).
`sync`
and the one-offs give way when it is held (the next fetch is 15 minutes off); `plan`,
`score`, `reid` and a queued `sync` wait for it, and `plan`/`score` exit 1 if it never
frees, so Task Scheduler shows a failure instead of a silent success. The lock is
taken before the heavy AI imports, so a run that finds it held costs a couple of
seconds.

Everything a run logs also goes to pipeline.log (app.jobs.log_dir): Task Scheduler
throws a scheduled run's output away.

A deploy holds every one of those locks (`hold`) from before it swaps the code until
the new version answers, so no job runs new code on the old schema, or has its rows
moved by a data migration halfway through (audit H-09). A run that waited for a lock
(plan, score, a queued Check) and finds the code changed under it meanwhile starts
again on the new code rather than finish on a mix of the two.
"""
import os
import sys
import threading
import uuid
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# --- load .env into the process environment (same rationale and rules as serve.py) ---
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).with_name(".env"), override=False, encoding="utf-8")

from app import jobs  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.version import read_commit  # noqa: E402

log = get_logger("pipeline")

MODES = ("sync", "backfill", "scan", "login", "sex", "plan", "score", "reid", "notify", "busy",
         "hold")
# The modes that don't take the "pipeline" lock, and the lock each takes instead.
OWN_LOCK = {"sex": "sexpass", "notify": "notify"}
# What a deploy holds while the code and the schema change: every job's lock.
DEPLOY_LOCKS = ("pipeline", *OWN_LOCK.values())
# A deploy that never says it is done lets go after this long: a hung migration must
# not stop the photos for good.
HOLD_MAX_SECONDS = int(os.environ.get("DEPLOY_HOLD_MAX_SECONDS", str(90 * 60)))
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
        from app.ingestion.fetch import room_to_fetch
        from app.ingestion.sync import backfill_all

        months = int(args[0]) if args else int(os.environ.get("BACKFILL_MONTHS", "1"))
        if room_to_fetch(db):
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
        from app.ingestion.fetch import room_to_fetch
        from app.models import CameraAccount

        account = db.get(CameraAccount, uuid.UUID(args[0]))
        if account is None:
            log.warning("pipeline.login_gone", account=args[0])
            return 0
        if not room_to_fetch(db):
            # Its history waits: the routine fetch imports a login never imported yet,
            # once there is room.
            log.warning("pipeline.login_waits_for_room", account=args[0])
        elif account.provider == "ubox":
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


def _notify(db) -> int:
    """What waited for a sit or quiet hours, then tonight's plan if it is due. One
    failing never stops the other."""
    from app.notifications.hold import deliver_held
    from app.notifications.plan import send_daily_plan

    failed = 0
    for name, step in (("held", deliver_held), ("plan", send_daily_plan)):
        try:
            log.info("pipeline.notify", step=name, result=step(db))
        except Exception:
            db.rollback()
            log.exception("pipeline.notify_failed", step=name)
            failed = 1
    return failed


def _sex(db) -> int:
    from app.ai import vision_sex

    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("pipeline.sex.skipped_no_key")
        return 0
    limit = int(os.environ.get("SEX_LIMIT_PER_RUN", "150"))
    log.info("pipeline.sex", result=vision_sex.sex_pass(db, limit=limit))
    return 0


def _busy_line(h: jobs.Holder) -> str:
    return f"busy: {h.owner} (pid {h.pid} on {h.host}) since {h.started.isoformat()}"


def hold(stream=None) -> int:
    """`pipeline.py hold`, for deploy/update.ps1: take every job's lock, print "held",
    and keep them until the deploy closes this process's input (it is done, or it
    died, which closes it too), or HOLD_MAX_SECONDS pass. A job holding one: "busy:
    ..." and exit 3, holding nothing."""
    stream = sys.stdin if stream is None else stream
    held: list[jobs.JobLock] = []
    for name in DEPLOY_LOCKS:
        lock = jobs.try_acquire(name, "deploy")
        if lock is None:
            for mine in held:
                mine.release()
            h = jobs.holder(name)
            print(_busy_line(h) if h else f"busy: {name}", flush=True)
            return BUSY_EXIT
        held.append(lock)
    print("held", flush=True)
    done = threading.Event()

    def until_closed() -> None:
        try:
            while stream.read(1024):
                pass
        except (OSError, ValueError):
            pass
        done.set()

    threading.Thread(target=until_closed, name="deploy-hold", daemon=True).start()
    if not done.wait(HOLD_MAX_SECONDS):
        log.warning("pipeline.hold_timed_out", seconds=HOLD_MAX_SECONDS)
    for lock in held:
        lock.release()
    print("released", flush=True)
    return 0


def again(argv: list[str]) -> int:
    """Start this run over on the code now on disk (the process is replaced)."""
    os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *argv])
    return 0  # not reached


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    mode = argv[0] if argv else "sync"
    if mode not in MODES:
        print(f"unknown mode: {mode!r} (use {'|'.join(MODES)})")
        return 2
    if mode == "busy":
        # The deploy stands down while any of the locks is held, as it did when the
        # cloud stag/hind pass shared the pipeline lock: a migration or a code swap
        # must not land under a running pass (or a notify run, a few seconds long).
        for name in DEPLOY_LOCKS:
            h = jobs.holder(name)
            if h is not None:
                print(_busy_line(h))
                return BUSY_EXIT
        print("free")
        return 0
    if mode == "hold":
        return hold()

    configure_logging(log_file=jobs.log_dir() / "pipeline.log")
    started_on = read_commit()
    name = OWN_LOCK.get(mode, "pipeline")
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
    if wait and read_commit() != started_on:
        # A deploy swapped the code while this run waited for it: the modules not
        # imported yet would come from the new code, the rest from the old.
        log.info("pipeline.code_changed_while_waiting", mode=mode, was=started_on)
        lock.release()
        if queued is not None:
            queued.release()
        return again(argv)
    jobs.run_under(lock)
    try:
        with SessionLocal() as db:
            if mode in OWN_LOCK:
                return _sex(db) if mode == "sex" else _notify(db)
            return _run(mode, argv[1:], db)
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
