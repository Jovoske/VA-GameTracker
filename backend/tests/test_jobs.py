"""Background jobs run reliably (plan item 5): the lock, the pipeline runner, the catch-up.

The pipeline lock used to be a file judged by its age: a crash blocked syncing for
3 hours, a long run let a second one in on top of it, any run deleted it whether it
had written it or not, and the 17:00 plan and 11:00 score runs silently skipped when
a sync held it, so a missed night was never scored.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, date, datetime, timedelta

import pytest

from app import jobs
from app.models import (
    Camera,
    CameraNight,
    Estate,
    Forecast,
    ForecastOutcome,
    ModelRun,
)

from .conftest import requires_db


def _write_lock(name="pipeline", *, owner="sync", pid=None, host=None, started=None,
                beat_age: timedelta | None = None, token="theirs"):
    path = jobs.lock_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "owner": owner, "pid": pid, "host": host,
        "started": (started or datetime.now(UTC)).timestamp(), "token": token,
    }))
    if beat_age is not None:
        at = (datetime.now(UTC) - beat_age).timestamp()
        os.utime(path, (at, at))
    return path


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


# ── the lock ───────────────────────────────────────────────────────────────────


def test_only_one_run_can_hold_the_lock_and_it_names_its_owner():
    first = jobs.try_acquire("pipeline", "sync")
    assert first is not None
    assert jobs.try_acquire("pipeline", "plan") is None
    holder = jobs.holder("pipeline")
    assert (holder.owner, holder.pid, holder.host) == ("sync", os.getpid(), socket.gethostname())
    first.release()
    assert jobs.holder("pipeline") is None and not jobs.lock_path("pipeline").exists()
    again = jobs.try_acquire("pipeline", "plan")
    assert again is not None
    again.release()


def test_two_runs_starting_in_the_same_instant_never_both_get_it():
    barrier = threading.Barrier(8)
    won: list = []

    def start():
        barrier.wait()
        lock = jobs.try_acquire("pipeline", "sync")
        if lock is not None:
            won.append(lock)

    threads = [threading.Thread(target=start) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(won) == 1
    won[0].release()


def test_a_run_never_removes_a_lock_it_does_not_own():
    mine = jobs.try_acquire("pipeline", "api:sync")
    # Its heartbeat stalled and another run took over: the file is theirs now.
    _write_lock(token="someone-else")
    mine.release()
    assert jobs.lock_path("pipeline").exists()
    assert json.loads(jobs.lock_path("pipeline").read_text())["token"] == "someone-else"


def test_a_lock_left_by_a_dead_process_is_taken_over_at_once():
    _write_lock(pid=_dead_pid(), host=socket.gethostname())
    assert jobs.holder("pipeline") is None  # not 3 hours: at once
    lock = jobs.try_acquire("pipeline", "sync")
    assert lock is not None and jobs.holder("pipeline").owner == "sync"
    lock.release()


def test_a_lock_is_abandoned_only_when_its_heartbeat_stops():
    # Another machine's run (its process can't be checked from here): the heartbeat
    # decides. A long run keeps beating and is never taken for dead...
    _write_lock(pid=12345, host="elsewhere", started=datetime.now(UTC) - timedelta(hours=5),
                beat_age=timedelta(minutes=1))
    assert jobs.holder("pipeline") is not None
    assert jobs.try_acquire("pipeline", "sync") is None
    # ...and one whose heartbeat stopped 15 minutes ago was left by a crash.
    _write_lock(pid=12345, host="elsewhere", beat_age=timedelta(minutes=15))
    assert jobs.holder("pipeline") is None
    lock = jobs.try_acquire("pipeline", "sync")
    assert lock is not None
    lock.release()


def test_an_old_style_lock_is_judged_by_its_age():
    path = jobs.lock_path("pipeline")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("sync 1727000000")
    assert jobs.holder("pipeline").owner == "sync"
    old = time.time() - 20 * 60
    os.utime(path, (old, old))
    assert jobs.holder("pipeline") is None


def test_many_runs_taking_over_one_dead_lock_leave_exactly_one_owner():
    _write_lock(pid=_dead_pid(), host=socket.gethostname())
    barrier = threading.Barrier(6)
    won: list = []

    def start():
        barrier.wait()
        lock = jobs.try_acquire("pipeline", "sync")
        if lock is not None:
            won.append(lock)

    threads = [threading.Thread(target=start) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(won) == 1
    assert json.loads(jobs.lock_path("pipeline").read_text())["token"] == won[0].token
    won[0].release()


def test_the_heartbeat_keeps_a_long_run_fresh_and_stops_when_taken_over(monkeypatch):
    monkeypatch.setattr(jobs, "HEARTBEAT_SECONDS", 0.05)
    lock = jobs.try_acquire("pipeline", "backfill")
    old = time.time() - 9 * 60
    os.utime(lock.path, (old, old))
    time.sleep(0.3)
    assert time.time() - lock.path.stat().st_mtime < 5
    _write_lock(token="usurper")
    time.sleep(0.3)
    assert lock.lost
    lock.release()
    assert jobs.lock_path("pipeline").exists()  # the usurper's, left alone


def test_waiting_for_the_lock_gets_it_once_the_running_job_ends():
    running = jobs.try_acquire("pipeline", "sync")
    threading.Timer(0.3, running.release).start()
    began = time.monotonic()
    lock = jobs.acquire("pipeline", "plan", wait=5, poll=0.05)
    assert lock is not None and time.monotonic() - began >= 0.25
    lock.release()
    held = jobs.try_acquire("pipeline", "sync")
    assert jobs.acquire("pipeline", "plan", wait=0.2, poll=0.05) is None
    held.release()


# ── the pipeline runner ────────────────────────────────────────────────────────


@pytest.fixture
def runner(monkeypatch):
    import pipeline

    ran: list = []
    monkeypatch.setattr(pipeline, "configure_logging", lambda **kw: ran.append(("log", kw)))
    monkeypatch.setattr(pipeline, "_run", lambda mode, args, db: ran.append((mode, args)) or 0)
    monkeypatch.setattr(pipeline, "POLL_SECONDS", 0.05)
    monkeypatch.setattr(pipeline, "WAIT_SECONDS", 3)
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _NullSession())
    return pipeline, ran


class _NullSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_plan_waits_for_a_running_sync_instead_of_skipping(runner):
    pipeline, ran = runner
    sync = jobs.try_acquire("pipeline", "sync")
    threading.Timer(0.3, sync.release).start()
    assert pipeline.main(["plan"]) == 0
    assert ("plan", []) in ran
    assert jobs.holder("pipeline") is None  # released after


def test_plan_and_score_fail_loudly_when_the_lock_never_frees(runner, monkeypatch):
    pipeline, ran = runner
    monkeypatch.setattr(pipeline, "WAIT_SECONDS", 0.3)
    held = jobs.try_acquire("pipeline", "sync")
    assert pipeline.main(["score"]) == 1  # Task Scheduler shows a failure
    assert pipeline.main(["plan"]) == 1
    # A sync finding it held just gives way: the next one is 15 minutes off.
    assert pipeline.main(["sync"]) == 0
    assert [r for r in ran if r[0] != "log"] == []
    held.release()


def test_every_run_writes_its_log_to_a_file(runner):
    pipeline, ran = runner
    assert pipeline.main(["sync"]) == 0
    assert ran[0] == ("log", {"log_file": jobs.log_dir() / "pipeline.log"})


def test_the_sex_pass_has_a_lock_of_its_own_and_never_blocks_a_sync(runner):
    pipeline, ran = runner
    sex = jobs.try_acquire("sexpass", "sex")
    assert pipeline.main(["sync"]) == 0 and ("sync", []) in ran
    assert pipeline.main(["sex"]) == 0 and not any(r[0] == "sex" for r in ran)
    sex.release()


def test_busy_answers_the_deploy_script(runner, capsys):
    pipeline, _ = runner
    assert pipeline.main(["busy"]) == 0
    held = jobs.try_acquire("pipeline", "sync")
    assert pipeline.main(["busy"]) == pipeline.BUSY_EXIT
    assert "busy: sync" in capsys.readouterr().out
    held.release()


def test_a_crash_is_logged_and_the_lock_released(runner, monkeypatch):
    pipeline, _ = runner

    def boom(mode, args, db):
        raise RuntimeError("disk full")

    monkeypatch.setattr(pipeline, "_run", boom)
    assert pipeline.main(["scan"]) == 1
    assert jobs.holder("pipeline") is None


def test_log_file_gets_the_run_output(tmp_path):
    import structlog

    from app.core.logging import configure_logging

    path = tmp_path / "logs" / "pipeline.log"
    try:
        configure_logging(log_file=path)
        structlog.get_logger("fresh").info("pipeline.skip_locked", mode="plan")
        assert '"pipeline.skip_locked"' in path.read_text()
    finally:
        configure_logging()


# ── score catches up, plan is caught up before dark ────────────────────────────


@pytest.fixture
def camera(db_session):
    estate = Estate(name="E", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db_session.add(estate)
    db_session.flush()
    cam = Camera(estate_id=estate.id, name="Puente", active=True)
    db_session.add(cam)
    db_session.commit()
    return cam


def _claim(db, cam, night: date, *, scored=False, state="CONFIRMED"):
    fc = Forecast(camera_id=cam.id, target_date=night, probability=0.4)
    db.add(fc)
    db.flush()
    if scored:
        db.add(ForecastOutcome(forecast_id=fc.id, occurred=False,
                               evaluated_at=datetime.now(UTC)))
    if state and db.query(CameraNight).filter_by(camera_id=cam.id, night=night).first() is None:
        db.add(CameraNight(camera_id=cam.id, night=night, exposure_state=state))
    db.commit()
    return fc


@requires_db
def test_score_catches_up_every_unscored_night_of_the_last_two_weeks(db_session, camera):
    from app.forecasting.scoring import evaluate_pending

    today = date(2026, 10, 20)
    missed = _claim(db_session, camera, today - timedelta(days=3))  # the 11:00 run skipped
    done = _claim(db_session, camera, today - timedelta(days=2), scored=True)
    blind = _claim(db_session, camera, today - timedelta(days=1), state="UNPROCESSED")
    too_old = _claim(db_session, camera, today - timedelta(days=20))
    tonight = _claim(db_session, camera, today)

    result = evaluate_pending(db_session, today=today)
    assert result["nights"] == [str(today - timedelta(days=3)), str(today - timedelta(days=1))]
    assert db_session.get(ForecastOutcome, missed.id) is not None
    assert db_session.get(ForecastOutcome, done.id) is not None
    # Photos still being checked: not a miss, and tried again tomorrow.
    assert db_session.get(ForecastOutcome, blind.id) is None
    assert result["skipped_unverifiable"] == 1
    assert db_session.get(ForecastOutcome, too_old.id) is None
    assert db_session.get(ForecastOutcome, tonight.id) is None


@requires_db
def test_a_missed_plan_is_written_by_the_fetch_before_dark_and_never_after(
    db_session, camera, monkeypatch,
):
    import pipeline
    from app.forecasting import model

    monkeypatch.setattr(model, "forecast_tonight", lambda db: {"where": [
        {"camera": "Puente", "species_id": None, "probability": 0.3,
         "best_window": {"start_hour": 19, "end_hour": 22}},
    ]})
    madrid = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)  # sunset ~17:25 UTC (19:25 CEST)
    early = madrid.replace(hour=14)  # 16:00 in Madrid: the 17:00 plan run is still to come
    assert pipeline.plan_catch_up(db_session, early) is None
    dark = madrid.replace(hour=18)  # 20:00 in Madrid: after sunset, not a forecast
    assert pipeline.plan_catch_up(db_session, dark) is None
    assert db_session.query(ModelRun).count() == 0

    dusk = madrid.replace(hour=16)  # 18:00 in Madrid, before sunset, nothing claimed
    assert pipeline.plan_catch_up(db_session, dusk)["target_date"] == "2026-10-05"
    assert db_session.query(Forecast).filter_by(target_date=date(2026, 10, 5)).count() == 1
    # Claimed now: the next fetch leaves it alone.
    assert pipeline.plan_catch_up(db_session, dusk + timedelta(minutes=15)) is None
    assert db_session.query(ModelRun).count() == 1
