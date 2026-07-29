"""User management and multi-SPYPOINT-account tests.

The behaviours worth pinning are the ones whose failure is expensive: locking
every admin out of the estate, leaking a stored third-party password, deleting an
account that still owns cameras (and with them, a season of images), and — the
promise made when this work started — not disturbing credentials or logins that
already exist.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import decrypt_secret, encrypt_secret
from app.models import Camera, Estate, SpypointAccount, User

from .conftest import requires_db


@pytest.fixture
def client(db_session, monkeypatch):
    """An app wired to the throwaway test database."""
    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def estate(db_session):
    e = Estate(name="Piedras Lisas", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture
def admin_token(db_session, estate):
    from app.core.security import create_access_token, hash_password

    u = User(
        estate_id=estate.id, email="admin@estate.local",
        password_hash=hash_password("x" * 12), role="admin",
    )
    db_session.add(u)
    db_session.commit()
    return u, {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


# ── secret handling ─────────────────────────────────────────────────────────


def test_secret_round_trips():
    assert decrypt_secret(encrypt_secret("hunter2-spypoint")) == "hunter2-spypoint"


def test_unreadable_secret_returns_none_rather_than_raising():
    """A rotated JWT_SECRET must degrade visibly, not crash the sync."""
    assert decrypt_secret("not-a-fernet-token") is None
    assert decrypt_secret(None) is None


def test_encryption_does_not_store_plaintext():
    blob = encrypt_secret("hunter2-spypoint")
    assert "hunter2-spypoint" not in blob


# ── users ───────────────────────────────────────────────────────────────────


@requires_db
def test_admin_cannot_delete_themselves(client, admin_token):
    me, headers = admin_token
    r = client.delete(f"/api/users/{me.id}", headers=headers)
    assert r.status_code == 409


@requires_db
def test_last_admin_cannot_be_demoted(client, admin_token, db_session):
    me, headers = admin_token
    other = client.post(
        "/api/users",
        json={"email": "guest@estate.local", "password": "a" * 12, "role": "member"},
        headers=headers,
    )
    assert other.status_code == 201

    # Only one admin exists, so demoting them must be refused.
    r = client.patch(f"/api/users/{me.id}", json={"role": "member"}, headers=headers)
    assert r.status_code == 409

    # Promote the second user, and the demotion becomes allowed.
    client.patch(f"/api/users/{other.json()['id']}", json={"role": "admin"}, headers=headers)
    r = client.patch(f"/api/users/{me.id}", json={"role": "member"}, headers=headers)
    assert r.status_code == 200


@requires_db
def test_non_admin_cannot_manage_users(client, admin_token, db_session):
    from app.core.security import create_access_token

    _, headers = admin_token
    created = client.post(
        "/api/users",
        json={"email": "viewer@estate.local", "password": "a" * 12, "role": "viewer"},
        headers=headers,
    ).json()
    viewer_headers = {"Authorization": f"Bearer {create_access_token(created['id'])}"}

    assert client.get("/api/users", headers=viewer_headers).status_code == 403
    # ...but they can still identify themselves.
    me = client.get("/api/users/me", headers=viewer_headers)
    assert me.status_code == 200 and me.json()["role"] == "viewer"


@requires_db
def test_duplicate_email_is_rejected(client, admin_token):
    _, headers = admin_token
    body = {"email": "dup@estate.local", "password": "a" * 12, "role": "member"}
    assert client.post("/api/users", json=body, headers=headers).status_code == 201
    assert client.post("/api/users", json=body, headers=headers).status_code == 409


@requires_db
def test_bad_token_subject_is_401_not_500(client):
    from app.core.security import create_access_token

    headers = {"Authorization": f"Bearer {create_access_token('not-a-uuid')}"}
    assert client.get("/api/users/me", headers=headers).status_code == 401


# ── SPYPOINT accounts ───────────────────────────────────────────────────────


@requires_db
def test_account_password_is_never_returned(client, admin_token):
    _, headers = admin_token
    r = client.post(
        "/api/spypoint/accounts",
        json={"label": "North", "username": "north@x.com", "password": "s3cret-pw"},
        headers=headers,
    )
    assert r.status_code == 201
    assert "s3cret-pw" not in r.text
    assert r.json()["password_set"] is True
    assert r.json()["password_readable"] is True

    listing = client.get("/api/spypoint/accounts", headers=headers)
    assert "s3cret-pw" not in listing.text


@requires_db
def test_account_with_cameras_cannot_be_deleted(client, admin_token, db_session, estate):
    _, headers = admin_token
    acc = client.post(
        "/api/spypoint/accounts",
        json={"label": "North", "username": "north@x.com", "password": "s3cret-pw"},
        headers=headers,
    ).json()

    db_session.add(
        Camera(
            estate_id=estate.id,
            spypoint_account_id=uuid.UUID(acc["id"]),
            spypoint_id="CAM-1",
            name="Puente",
            active=True,
        )
    )
    db_session.commit()

    r = client.delete(f"/api/spypoint/accounts/{acc['id']}", headers=headers)
    assert r.status_code == 409
    assert "orphan" in r.json()["detail"]

    # Deactivating is the supported way to stop syncing it.
    off = client.patch(f"/api/spypoint/accounts/{acc['id']}", json={"active": False}, headers=headers)
    assert off.status_code == 200 and off.json()["active"] is False


@requires_db
def test_two_accounts_may_hold_the_same_upstream_camera_id(db_session, estate):
    """The old schema made spypoint_id globally unique, which multi-account breaks."""
    a = SpypointAccount(estate_id=estate.id, label="A", username="a@x.com", active=True)
    b = SpypointAccount(estate_id=estate.id, label="B", username="b@x.com", active=True)
    db_session.add_all([a, b])
    db_session.flush()

    db_session.add_all(
        [
            Camera(estate_id=estate.id, spypoint_account_id=a.id, spypoint_id="DUP", name="A-cam", active=True),
            Camera(estate_id=estate.id, spypoint_account_id=b.id, spypoint_id="DUP", name="B-cam", active=True),
        ]
    )
    db_session.commit()  # must not raise

    assert db_session.scalar(select(Camera).where(Camera.spypoint_account_id == a.id)).name == "A-cam"


@requires_db
def test_env_credentials_are_adopted_as_the_first_account(db_session, estate, monkeypatch):
    """The compatibility promise: an existing .env keeps working untouched."""
    from app.core.config import settings
    from app.ingestion.sync import resolve_accounts

    monkeypatch.setattr(settings, "spypoint_username", "legacy@estate.com")
    monkeypatch.setattr(settings, "spypoint_password", "legacy-pw")

    accounts = resolve_accounts(db_session, estate)
    assert len(accounts) == 1
    assert accounts[0].username == "legacy@estate.com"
    assert decrypt_secret(accounts[0].password_enc) == "legacy-pw"

    # Idempotent: a second call must not create a duplicate.
    assert len(resolve_accounts(db_session, estate)) == 1


@requires_db
def test_api_created_account_is_not_overwritten_by_stale_env(db_session, estate, monkeypatch):
    """A password changed through the API must survive a stale value in .env."""
    from app.core.config import settings
    from app.seed import _seed_spypoint_account

    db_session.add(
        SpypointAccount(
            estate_id=estate.id, label="Main account", username="legacy@estate.com",
            password_enc=encrypt_secret("new-password-set-in-ui"), active=True,
        )
    )
    db_session.commit()

    monkeypatch.setattr(settings, "spypoint_username", "legacy@estate.com")
    monkeypatch.setattr(settings, "spypoint_password", "old-password-in-env")
    _seed_spypoint_account(db_session, estate)
    db_session.commit()

    stored = db_session.scalar(
        select(SpypointAccount).where(SpypointAccount.username == "legacy@estate.com")
    )
    assert decrypt_secret(stored.password_enc) == "new-password-set-in-ui"
