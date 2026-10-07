"""Bring configured Suntek inboxes through the existing durable photo importer."""

from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from sqlalchemy import select

from app import jobs
from app.core.config import settings
from app.core.db import server_sessions
from app.ingestion import logins
from app.ingestion.ftp_import import requeue, run_once, spool_counts
from app.ingestion.inbox import PROVIDERS, InboxConfig, connect, poll_ftp, poll_mail, stage
from app.models import Camera, CameraAccount


def sync_inbox_all(db, account_id=None):
    query = select(CameraAccount).where(
        CameraAccount.provider.in_(PROVIDERS), CameraAccount.active.is_(True)
    )
    if account_id is not None:
        query = query.where(CameraAccount.id == account_id)
    accounts = db.scalars(query).all()
    result = {"status": "skipped" if not accounts else "ok", "total": 0, "accounts": []}
    for account in accounts:
        if jobs.lock_lost():
            result["status"] = "partial"
            break
        row = {
            "account_id": str(account.id),
            "label": account.label or account.username,
            "status": "ok",
            "total": 0,
        }
        result["accounts"].append(row)
        lock = jobs.acquire("inbox-" + str(account.id), "camera inbox")
        if lock is None:
            row["status"] = "skipped"
            continue
        try:
            camera = db.scalar(
                select(Camera).where(
                    Camera.account_id == account.id, Camera.estate_id == account.estate_id
                )
            )
            if camera is None:
                raise ValueError("Camera inbox has no linked camera")
            config = InboxConfig.model_validate(account.connection_config).for_provider(
                account.provider
            )
            spool = Path(settings.models_root).parent / "camera-inboxes" / str(account.id)
            # This account lock excludes every scheduled/manual inbox worker. A package
            # claimed by a crashed predecessor can safely return to the durable queue.
            requeue(spool, "processing", workers_stopped=True)
            password = logins.read_password(db, account)
            db.commit()
            error = None

            def checkpoint(cursor, account=account, lock=lock):
                if jobs.lock_lost() or not lock.check():
                    raise RuntimeError(
                        "The import was interrupted; it will continue on the next check"
                    )
                account.input_cursor = cursor
                db.commit()

            try:
                with connect(config, account.username, password) as client:
                    poll = poll_mail if account.provider == "suntek_email" else poll_ftp
                    poll(
                        client,
                        config,
                        account.input_cursor or {},
                        partial(stage, spool),
                        checkpoint,
                    )
            except Exception as exc:
                db.rollback()
                error = logins.login_error(exc, account.provider)
            if not jobs.lock_lost() and lock.check():
                imported = run_once(
                    spool,
                    camera.id,
                    timezone_name=config.timezone,
                    session_factory=server_sessions(db.get_bind()),
                )
                row["total"] = imported["imported"]
                result["total"] += row["total"]
                counts = spool_counts(spool) or {}
                if imported["deferred"] or counts.get("failed"):
                    error = (
                        error
                        or "Some camera photos are waiting for server attention. Check the "
                        "camera inbox import log."
                    )
            else:
                error = error or "Import interrupted. Photos will be retried on the next check."
            db.refresh(camera)
            camera.fetch_error = error
            logins.record(db, account, error=error, cameras=1)
            if error is None:
                account.last_sync_at = datetime.now(UTC)
            else:
                row.update(status="error", error=error)
            db.commit()
        except Exception as exc:
            db.rollback()
            error = logins.login_error(exc, account.provider)
            row.update(status="error", error=error)
            logins.record(db, account, error=error)
            db.commit()
        finally:
            lock.release()
    if any(r["status"] == "error" for r in result["accounts"]):
        result["status"] = (
            "partial"
            if result["total"] or any(r["status"] == "ok" for r in result["accounts"])
            else "error"
        )
    return result
