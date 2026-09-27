"""One photo fetch across every provider, as the Check button and the scheduled run do it.

SPYPOINT and UBox each run even when the other fails, and the run leaves one summary
row in sync_log (provider "pipeline") that says what came of it: how many photos came
in, and which logins need attention, in the words Settings uses. That row is what the
Check button and the admin status read, so a failing SPYPOINT login is no longer hidden
behind the UBox row written after it.

The row is written as soon as the photos are in, with stage "identifying" while the
detector looks at them, and finished once the AI pass and the night recount are done.
So the Check button can say "7 new photos came in" without waiting for the detector,
and a run killed during the AI pass still leaves a true count behind.

With less than app.ops.FULL_DISK_BYTES free where the photos are kept, nothing is
downloaded and the run says why (audit H-18): that disk is the database's too, and a
full one stops Postgres and every import at once. The photos wait on the cameras'
clouds and come in on the first fetch after room is made.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import SyncLog

log = get_logger(__name__)

PROVIDERS = {"spypoint": "SPYPOINT", "ubox": "UBox"}
# Not a provider: the run stood down because the server's disk is nearly full.
DISK = "disk"
LABELS = {**PROVIDERS, DISK: "Server disk"}


def summarize(results: dict) -> dict:
    """The run's status, photo count and problems from each provider's result.

    status: ok (everything worked), partial (photos came in or a provider worked, but
    something failed), error (nothing worked), skipped (no camera logins at all).
    problems: [{"label", "error"}], one per login (or provider) that needs a look.
    """
    downloaded = sum(r.get("total", 0) or 0 for r in results.values())
    problems: list[dict] = []
    statuses = []
    for provider, result in results.items():
        status = result.get("status") or "error"
        statuses.append(status)
        accounts = result.get("accounts") or []
        for account in accounts:
            if account.get("error"):
                problems.append({"label": account.get("label") or LABELS[provider],
                                 "error": account["error"]})
        if status == "error" and not any(a.get("error") for a in accounts):
            problems.append({"label": LABELS[provider],
                             "error": result.get("reason") or result.get("error")
                             or "The fetch failed. It tries again on the next one."})
    if statuses and all(s == "skipped" for s in statuses):
        status = "skipped"
    elif all(s in ("ok", "skipped") for s in statuses):
        status = "ok"
    elif downloaded > 0 or any(s in ("ok", "partial") for s in statuses):
        status = "partial"
    else:
        status = "error"
    return {"status": status, "downloaded": downloaded, "problems": problems}


def fetch_photos(db: Session) -> tuple[SyncLog, dict]:
    """Fetch from every provider; returns the summary row (stage "identifying")."""
    from app import jobs, ops
    from app.ingestion.sync import sync_all
    from app.ingestion.ubox_sync import sync_ubox_all

    started = datetime.now(UTC)
    results: dict = {}
    free = ops.disk_free()
    if free is not None and free < ops.FULL_DISK_BYTES:
        log.error("fetch.disk_full", free_gb=round(free / 1024**3, 1))
        results[DISK] = {
            "status": "error", "total": 0,
            "reason": f"Nearly full ({free / 1024**3:.1f} GB free). The photos wait on the "
                      "cameras and come in once there is room.",
        }
    runs = () if DISK in results else (("spypoint", sync_all), ("ubox", sync_ubox_all))
    for provider, run in runs:
        if jobs.lock_lost():
            break  # another run took the lock over and fetches now
        try:
            results[provider] = run(db)
        except Exception as exc:  # one provider's crash must not stop the other
            db.rollback()
            log.error("fetch.provider_failed", provider=provider, error=str(exc))
            results[provider] = {
                "status": "error", "total": 0,
                "reason": f"The {PROVIDERS[provider]} fetch failed ({type(exc).__name__}). "
                          "It tries again on the next one.",
            }
    summary = summarize(results)
    row = SyncLog(
        status=summary["status"], started_at=started, images_downloaded=summary["downloaded"],
        error="; ".join(f"{p['label']}: {p['error']}" for p in summary["problems"]) or None,
        details={"provider": "pipeline", "stage": "identifying",
                 "problems": summary["problems"], "results": results},
    )
    db.add(row)
    db.commit()
    return row, results


def finish(db: Session, row: SyncLog, error: str | None = None) -> None:
    """The AI pass is done (or failed): close the run's summary row."""
    details = dict(row.details or {})
    details["stage"] = "done"
    if error:
        details["ai_error"] = error
    row.details = details
    row.finished_at = datetime.now(UTC)
    db.commit()


def check_and_recount(db: Session) -> tuple[dict, str | None]:
    """The AI pass over what came in, then the night recount; (results, what went
    wrong in words or None). Shared by the routine fetch and the one-off imports.
    Last, weather that Open-Meteo could not give when the photos came in is filled
    in (enrich.refill_unavailable)."""
    from app import jobs
    from app.ai.checking import check_photos
    from app.enrichment.enrich import refill_unavailable
    from app.forecasting.exposure import recompute_camera_nights

    results: dict = {}
    error = None
    try:
        results["ai"] = check_photos(db)
        if results["ai"].get("status") == "stopped":
            error = results["ai"].get("reason")
    except Exception as exc:
        db.rollback()
        log.error("fetch.ai_failed", error=str(exc))
        error = f"Looking for animals failed ({type(exc).__name__})"
    if jobs.lock_lost():
        return results, error  # the run that took the lock over recounts
    try:
        # Exposure is the denominator under every statistic in the app, and it only
        # becomes knowable once the frames are checked: an unchecked night is not an
        # observation yet. So it runs here, after the AI pass.
        results["exposure"] = recompute_camera_nights(db)
    except Exception as exc:
        db.rollback()
        log.error("fetch.exposure_failed", error=str(exc))
    try:
        results["weather_refilled"] = refill_unavailable(db)
    except Exception as exc:  # never a reason to fail the run
        db.rollback()
        log.warning("fetch.weather_refill_failed", error=str(exc))
    return results, error


def run_fetch(db: Session) -> dict:
    """The whole routine run: fetch, look for animals, recount the nights."""
    row, results = fetch_photos(db)
    checked, error = check_and_recount(db)
    results.update(checked)
    row = db.get(SyncLog, row.id)
    if row is not None:
        finish(db, row, error)
    return results


def latest_run(db: Session) -> SyncLog | None:
    """The newest fetch summary, or the newest provider row before any summary exists."""
    return db.scalar(
        select(SyncLog).where(SyncLog.details["provider"].astext == "pipeline")
        .order_by(SyncLog.started_at.desc()).limit(1)
    ) or db.scalar(select(SyncLog).order_by(SyncLog.started_at.desc()).limit(1))
