"""Nordic accounts use the existing login, health and fetch flows in isolation."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api import routes_camera_accounts as accounts
from app.core.crypto import decrypt
from app.health import camera_health
from app.i18n import localize, stored
from app.ingestion import fetch, logins
from app.ingestion.nordic import NordicAuthError, NordicError
from app.models import Camera, CameraAccount, Estate, Image, User

from .conftest import requires_db


@pytest.mark.parametrize(("failure", "status"), [
    (NordicAuthError("Rejected", 401), 400),
    (NordicError("Bad response", 400), 400),
    (NordicError("Busy", 429), 503),
    (NordicError("Unavailable", 503), 503),
    (httpx.ConnectError("connection unavailable"), 503),
])
def test_failed_nordic_verification_never_stores_login(monkeypatch, failure, status):
    client = Mock()
    client.login.side_effect = failure
    manager = Mock()
    manager.__enter__ = Mock(return_value=client)
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(accounts, "NordicClient", Mock(return_value=manager))
    db = Mock()
    db.scalar.return_value = None
    user = User(id=uuid.uuid4(), estate_id=uuid.uuid4(), role="member")
    with pytest.raises(HTTPException) as exc:
        accounts.add_account(accounts.AddAccountBody(
            provider="nordic", username="owner@example.test", password="private-password",
        ), user, db)
    assert exc.value.status_code == status
    assert "Nordic Gamekeeper" in exc.value.detail
    assert "private-password" not in exc.value.detail
    db.add.assert_not_called()
    db.commit.assert_not_called()
    manager.__exit__.assert_called_once()


@pytest.mark.parametrize(("error", "key", "password_problem"), [
    (NordicAuthError("Rejected", 401), "login.provider_refused", True),
    (NordicError("Busy", 429), "login.provider_throttled", False),
    (NordicError("Unavailable", 503), "login.provider_down", False),
    (NordicError("Forbidden", 403), "login.provider_refused_request", False),
    (httpx.ConnectError("offline"), "login.unreachable", False),
])
def test_nordic_errors_name_the_provider_and_only_auth_requests_a_password(
    error, key, password_problem,
):
    message = logins.login_error(error, "nordic")
    assert message == stored(key, provider="Nordic Gamekeeper")
    assert logins.asks_for_password(message) is password_problem
    assert localize(message, "fi") != message


def test_nordic_login_failure_is_visible_on_its_camera(monkeypatch):
    monkeypatch.setattr(logins, "primary_configured", lambda: False)
    now = datetime.now(UTC)
    account = CameraAccount(id=uuid.uuid4(), provider="nordic", username="owner@example.test",
                            active=True, last_attempt_at=now, last_ok_at=now,
                            last_error=logins.NORDIC_REFUSED)
    camera = Camera(id=uuid.uuid4(), nordic_id="nordic-1", account_id=account.id,
                    name="North feeder", active=True, last_report_at=now)
    db = Mock()
    db.scalars.return_value = [account]
    status = logins.camera_logins(db, [camera], now)[camera.id]
    assert status["provider"] == "nordic" and status["state"] == "failing"
    assert camera_health(camera, now, status)["status"] == "not_syncing"
    camera.last_report_at = now - timedelta(hours=40)
    assert camera_health(camera, now)["status"] == "offline"


def test_nordic_orphaned_account_is_not_mislabeled_as_spypoint(monkeypatch):
    monkeypatch.setattr(logins, "primary_configured", lambda: False)
    camera = Camera(id=uuid.uuid4(), nordic_id="nordic-1", account_id=uuid.uuid4())
    db = Mock()
    db.scalars.return_value = []
    status = logins.camera_logins(db, [camera])[camera.id]
    assert status["provider"] == "nordic" and status["state"] == "off"


@pytest.mark.parametrize("broken", ["spypoint", "ubox", "nordic", "suntek"])
def test_fetch_runs_all_providers_even_when_one_crashes(monkeypatch, broken):
    from app.ingestion import inbox_sync, nordic_sync, sync, ubox_sync

    called = []

    def run(provider):
        def work(db):
            called.append(provider)
            if provider == broken:
                raise RuntimeError("synthetic provider outage")
            return {"status": "ok", "total": 2}
        return work

    monkeypatch.setattr(sync, "sync_all", run("spypoint"))
    monkeypatch.setattr(ubox_sync, "sync_ubox_all", run("ubox"))
    monkeypatch.setattr(nordic_sync, "sync_nordic_all", run("nordic"))
    monkeypatch.setattr(inbox_sync, "sync_inbox_all", run("suntek"))
    monkeypatch.setattr(fetch, "disk_full", lambda: None)
    monkeypatch.setattr(fetch, "_summary", lambda db, started, results: fetch.summarize(results))
    summary, results = fetch.fetch_photos(Mock())
    assert called == ["spypoint", "ubox", "nordic", "suntek"]
    assert results[broken]["status"] == "error"
    assert summary["status"] == "partial" and summary["downloaded"] == 6
    assert summary["problems"][0]["label"] == fetch.PROVIDERS[broken]


def test_new_nordic_login_imports_via_its_own_pipeline_handler(monkeypatch):
    import pipeline
    from app.ingestion import nordic_sync, sync, ubox_sync

    db = Mock()
    account_id = uuid.uuid4()
    db.get.return_value = CameraAccount(id=account_id, provider="nordic")
    backfill = Mock(return_value={"status": "ok", "total": 1})
    monkeypatch.setattr(nordic_sync, "backfill_nordic_account", backfill)
    monkeypatch.setattr(sync, "backfill_account", Mock(side_effect=AssertionError("SPYPOINT")))
    monkeypatch.setattr(ubox_sync, "backfill_ubox_account",
                        Mock(side_effect=AssertionError("UBox")))
    monkeypatch.setattr(fetch, "room_to_fetch", lambda db: True)
    monkeypatch.setattr(pipeline, "_checked", lambda db: None)
    monkeypatch.setattr(pipeline, "_catch_up", lambda db: None)
    pipeline._run("login", [str(account_id)], db)
    backfill.assert_called_once_with(db, str(account_id))


@pytest.mark.parametrize("field", ["spypoint_id", "ubox_uid", "nordic_id"])
def test_ftp_import_cannot_bind_a_cloud_camera(field, tmp_path):
    from app.ingestion.ftp_import import _persist_photo

    camera = Camera(id=uuid.uuid4(), name="Cloud camera", **{field: "device-1"})
    db = Mock()
    db.get_bind.return_value.dialect.name = "postgresql"
    db.get.return_value = camera
    with pytest.raises(ValueError, match="dedicated FTP camera"):
        _persist_photo(db, camera.id, None, tmp_path, enrich=False)
    db.execute.assert_not_called()


@requires_db
def test_nordic_connect_encrypts_then_disconnect_preserves_history(db_session, monkeypatch):
    estate = Estate(name="Nordic estate", timezone="Europe/Helsinki")
    db_session.add(estate)
    db_session.flush()
    user = User(estate_id=estate.id, email="owner@example.test", password_hash="hash",
                role="member")
    db_session.add(user)
    db_session.commit()
    client = Mock()
    client.list_cameras.return_value = [object()]
    manager = Mock()
    manager.__enter__ = Mock(return_value=client)
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(accounts, "NordicClient", Mock(return_value=manager))
    monkeypatch.setattr("app.api.routes_cameras._pipeline_busy", lambda: True)
    result = accounts.add_account(accounts.AddAccountBody(
        provider="nordic", username="owner@example.test", password="private-password",
    ), user, db_session)
    account = db_session.get(CameraAccount, uuid.UUID(result["id"]))
    assert decrypt(account.password_enc) == "private-password"
    assert account.password_enc != "private-password"
    client.login.assert_called_once()
    client.list_cameras.assert_called_once()
    camera = Camera(estate_id=estate.id, account_id=account.id, nordic_id="nordic-1", name="Apex")
    db_session.add(camera)
    db_session.flush()
    image = Image(camera_id=camera.id, nordic_photo_id="nordic-1:photo-1",
                  captured_at=datetime.now(UTC), original_path="preserved.jpg")
    db_session.add(image)
    db_session.commit()
    listing = accounts.list_accounts(user, db_session)
    row = next(a for a in listing if a["id"] == str(account.id))
    assert row["provider"] == "nordic" and row["cameras"] == 1
    assert "private-password" not in str(row) and "session_enc" not in str(row)
    accounts.remove_account(account.id, user, db_session)
    assert camera.account_id is None and camera.active is False
    assert db_session.get(Image, image.id).original_path == "preserved.jpg"


@requires_db
@pytest.mark.parametrize("other_field", ["ubox_uid", "spypoint_id"])
def test_nordic_device_cannot_also_belong_to_another_provider(db_session, other_field):
    estate = Estate(name="Test estate")
    db_session.add(estate)
    db_session.commit()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(Camera(estate_id=estate.id, name="Invalid", nordic_id="nordic-1",
                              **{other_field: "other-device"}))
        db_session.flush()


@requires_db
def test_unlisted_nordic_cameras_disconnect_without_affecting_ubox(db_session):
    estate = Estate(name="Test estate")
    db_session.add(estate)
    db_session.flush()
    account = CameraAccount(estate_id=estate.id, provider="nordic", username="owner@example.test",
                            password_enc="test-only")
    db_session.add(account)
    db_session.flush()
    kept = Camera(estate_id=estate.id, account_id=account.id, nordic_id="kept", name="Kept")
    missing = Camera(estate_id=estate.id, account_id=account.id, nordic_id="gone", name="Gone")
    ubox = Camera(estate_id=estate.id, ubox_uid="ubox-1", name="UBox")
    db_session.add_all([kept, missing, ubox])
    db_session.commit()
    assert logins.disconnect_unlisted(db_session, estate.id, "nordic", {"kept"},
                                      answered={account.id}, tried={account.id}) == 1
    assert not missing.active and kept.active and ubox.active
    assert len(list(db_session.scalars(select(Camera)))) == 3
