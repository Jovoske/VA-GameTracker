"""Provider verification, import controls and preservation of estate photo history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.api import routes_camera_accounts as accounts
from app.core.crypto import decrypt
from app.models import Camera, CameraAccount, Estate, Image, SyncLog, User

from .conftest import requires_db


def _user(estate_id=None, role="member"):
    return User(
        id=uuid.uuid4(),
        estate_id=estate_id or uuid.uuid4(),
        role=role,
        email=f"{uuid.uuid4()}@example.test",
        password_hash="test-hash",
    )


def _seed(db):
    estate = Estate(name="Test estate", timezone="Europe/Madrid")
    db.add(estate)
    db.flush()
    user = _user(estate.id)
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def provider_clients(monkeypatch):
    calls = []

    class Ubox:
        def __init__(self, email, password):
            calls.append(("credentials", email, password))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append(("closed",))

        def login(self):
            calls.append(("login",))

        def list_devices(self):
            calls.append(("devices",))
            return [object(), object()]

    class Spypoint(Ubox):
        def list_cameras(self):
            calls.append(("spypoint_cameras",))
            return [object()]

        def close(self):
            calls.append(("closed",))

    monkeypatch.setattr(accounts, "UboxClient", Ubox)
    monkeypatch.setattr(accounts, "SpypointClient", Spypoint)
    monkeypatch.setattr("app.api.routes_cameras._pipeline_busy", lambda: True)
    return calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("ubox_min_interval_seconds", 9),
        ("ubox_min_interval_seconds", 3601),
        ("ubox_min_interval_seconds", 10.5),
        ("ubox_min_interval_seconds", True),
        ("ubox_max_images_per_day", 0),
        ("ubox_max_images_per_day", 5001),
    ],
)
def test_import_controls_reject_unsafe_values(field, value):
    body = {"ubox_min_interval_seconds": 60, "ubox_max_images_per_day": 500, field: value}
    with pytest.raises(ValidationError):
        accounts.ImportSettingsBody(**body)
    with pytest.raises(ValidationError):
        accounts.AddAccountBody(username="cam@example.test", password="secret", **body)


def test_provider_default_preserves_existing_spypoint_clients():
    body = accounts.AddAccountBody(username="cam@example.test", password="secret")
    assert body.provider == "spypoint"
    with pytest.raises(ValidationError):
        accounts.AddAccountBody(username="cam@example.test", password="secret", provider="other")


@pytest.mark.parametrize("failure_step", ["login", "list_devices"])
def test_failed_ubox_verification_never_saves_credentials(
    monkeypatch, provider_clients, failure_step
):
    def fail(_):
        raise accounts.UboxError("Provider unavailable")

    monkeypatch.setattr(accounts.UboxClient, failure_step, fail)
    db = Mock()
    db.scalar.return_value = None
    with pytest.raises(HTTPException) as exc:
        accounts.add_account(
            accounts.AddAccountBody(
                username="cam@example.test", password="secret", provider="ubox"
            ),
            BackgroundTasks(),
            _user(),
            db,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "Could not connect to UBox Pro: Provider unavailable"
    assert provider_clients[-1] == ("closed",)
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize(
    "provider,backfill_name",
    [
        ("ubox", "backfill_ubox_account"),
        ("spypoint", "backfill_account"),
    ],
)
def test_connection_queues_matching_backfill_and_ai_under_pipeline_lock(
    monkeypatch,
    provider_clients,
    provider,
    backfill_name,
):
    from app.api import routes_cameras

    monkeypatch.setattr(routes_cameras, "_pipeline_busy", lambda: False)
    calls = []
    for module, name in [
        ("app.ai.empty_filter", "scan_unprocessed"),
        ("app.ai.species", "classify_unclassified"),
        ("app.forecasting.exposure", "recompute_camera_nights"),
        ("app.ingestion.ubox_sync" if provider == "ubox" else "app.ingestion.sync", backfill_name),
    ]:

        def record(*args, _name=name):
            calls.append((_name, args))

        monkeypatch.setitem(__import__("sys").modules, module, SimpleNamespace(**{name: record}))
    db = Mock()
    db.scalar.return_value = None
    account_id = uuid.uuid4()
    db.add.side_effect = lambda account: setattr(account, "id", account_id)
    background = BackgroundTasks()
    result = accounts.add_account(
        accounts.AddAccountBody(username="cam@example.test", password="secret", provider=provider),
        background,
        _user(),
        db,
    )
    assert result["import_started"]
    provider_label = "UBox Pro" if provider == "ubox" else "SPYPOINT"
    assert result["note"].startswith(f"Connected — {provider_label} reports ")
    assert len(background.tasks) == 1
    queued = background.tasks[0]
    assert queued.func is routes_cameras._run_locked
    session = object()
    queued.args[0](session)
    assert calls == [
        (backfill_name, (session, str(account_id))),
        ("scan_unprocessed", (session,)),
        ("classify_unclassified", (session,)),
        ("recompute_camera_nights", (session,)),
    ]


@requires_db
def test_verified_account_encrypts_password_and_keeps_limits(db_session, provider_clients):
    user = _seed(db_session)
    background = BackgroundTasks()
    result = accounts.add_account(
        accounts.AddAccountBody(
            username=" camera@example.test ",
            password="secret",
            provider="ubox",
            ubox_min_interval_seconds=120,
            ubox_max_images_per_day=250,
        ),
        background,
        user,
        db_session,
    )
    stored = db_session.get(CameraAccount, uuid.UUID(result["id"]))
    assert stored.provider == "ubox"
    assert stored.username == "camera@example.test"
    assert stored.password_enc != "secret"
    assert decrypt(stored.password_enc) == "secret"
    assert stored.ubox_min_interval_seconds == 120
    assert stored.ubox_max_images_per_day == 250
    assert provider_clients == [
        ("credentials", "camera@example.test", "secret"),
        ("login",),
        ("devices",),
        ("closed",),
    ]
    assert result["cameras"] == 2
    assert not result["import_started"]
    assert background.tasks == []


@requires_db
def test_same_email_is_allowed_for_different_providers(db_session, provider_clients):
    user = _seed(db_session)
    for provider in ("spypoint", "ubox"):
        result = accounts.add_account(
            accounts.AddAccountBody(
                username="same@example.test", password="secret", provider=provider
            ),
            BackgroundTasks(),
            user,
            db_session,
        )
        assert result["provider"] == provider
    assert len(db_session.scalars(select(CameraAccount)).all()) == 2
    with pytest.raises(HTTPException, match="") as exc:
        accounts.add_account(
            accounts.AddAccountBody(
                username="same@example.test", password="secret", provider="ubox"
            ),
            BackgroundTasks(),
            user,
            db_session,
        )
    assert exc.value.status_code == 400


@requires_db
def test_list_is_estate_scoped_and_reports_skips_without_credentials(db_session, provider_clients):
    owner = _seed(db_session)
    result = accounts.add_account(
        accounts.AddAccountBody(username="cam@example.test", password="secret", provider="ubox"),
        BackgroundTasks(),
        owner,
        db_session,
    )
    now = datetime.now(UTC)
    db_session.add(
        SyncLog(
            started_at=now,
            status="ok",
            details={
                "provider": "ubox",
                "accounts": [{"account_id": result["id"], "status": "ok", "error": None}],
                "cameras": [
                    {
                        "account_id": result["id"],
                        "downloaded": 3,
                        "interval_skipped": 5,
                        "daily_limit_skipped": 7,
                    },
                    {"account_id": result["id"], "downloaded": 1, "interval_skipped": 2},
                    {"account_id": str(uuid.uuid4()), "downloaded": 100, "interval_skipped": 100},
                ],
            },
        )
    )
    db_session.commit()
    other_estate_user = _seed(db_session)
    assert accounts.list_accounts(other_estate_user, db_session) == []
    (listed,) = accounts.list_accounts(owner, db_session)
    assert listed["provider"] == "ubox"
    assert listed["can_edit"]
    assert "password_enc" not in listed and "password" not in listed
    assert listed["last_import"] == {
        "at": now,
        "downloaded": 4,
        "interval_skipped": 7,
        "daily_limit_skipped": 7,
        "no_image": 0,
        "failed": 0,
        "status": "ok",
        "error": None,
    }
    db_session.add(
        SyncLog(
            started_at=now + timedelta(minutes=15),
            status="error",
            details={
                "provider": "ubox",
                "cameras": [],
                "accounts": [
                    {
                        "account_id": result["id"],
                        "status": "error",
                        "error": "Account connection failed (UboxError)",
                    }
                ],
            },
        )
    )
    db_session.commit()
    (listed,) = accounts.list_accounts(owner, db_session)
    assert listed["last_import"]["status"] == "error"
    assert listed["last_import"]["error"] == "Account connection failed (UboxError)"
    assert listed["last_import"]["downloaded"] == 0


@requires_db
def test_import_settings_require_owner_or_estate_admin(db_session, provider_clients):
    owner = _seed(db_session)
    result = accounts.add_account(
        accounts.AddAccountBody(username="cam@example.test", password="secret", provider="ubox"),
        BackgroundTasks(),
        owner,
        db_session,
    )
    account_id = uuid.UUID(result["id"])
    body = accounts.ImportSettingsBody(ubox_min_interval_seconds=300, ubox_max_images_per_day=100)
    for denied_user, status in [(_user(owner.estate_id), 403), (_user(role="admin"), 404)]:
        with pytest.raises(HTTPException) as exc:
            accounts.update_import_settings(account_id, body, denied_user, db_session)
        assert exc.value.status_code == status
    accounts.update_import_settings(account_id, body, owner, db_session)
    saved = db_session.get(CameraAccount, account_id)
    assert saved.ubox_min_interval_seconds == 300
    assert saved.ubox_max_images_per_day == 100
    admin_body = accounts.ImportSettingsBody(
        ubox_min_interval_seconds=60, ubox_max_images_per_day=500
    )
    accounts.update_import_settings(
        account_id, admin_body, _user(owner.estate_id, "admin"), db_session
    )
    assert saved.ubox_min_interval_seconds == 60


@requires_db
def test_disconnect_keeps_cameras_and_photos(db_session, provider_clients):
    owner = _seed(db_session)
    result = accounts.add_account(
        accounts.AddAccountBody(username="cam@example.test", password="secret", provider="ubox"),
        BackgroundTasks(),
        owner,
        db_session,
    )
    account_id = uuid.UUID(result["id"])
    camera = Camera(
        estate_id=owner.estate_id, account_id=account_id, ubox_uid="test-device", name="UBox"
    )
    db_session.add(camera)
    db_session.flush()
    photo = Image(
        camera_id=camera.id,
        captured_at=datetime.now(UTC),
        original_path="existing/photo.jpg",
        ubox_event_id="test-device:event1",
    )
    db_session.add(photo)
    db_session.commit()
    with pytest.raises(HTTPException) as exc:
        accounts.remove_account(account_id, _user(role="admin"), db_session)
    assert exc.value.status_code == 404
    accounts.remove_account(account_id, owner, db_session)
    db_session.refresh(camera)
    assert camera.account_id is None
    assert db_session.get(Image, photo.id).original_path == "existing/photo.jpg"
    assert db_session.get(CameraAccount, account_id) is None
