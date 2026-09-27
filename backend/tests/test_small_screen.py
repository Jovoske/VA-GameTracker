"""Glove-sized and small-screen polish, the server's part (plan item 16).

A double tap on a slow link must not turn a person that was added into an error
(audit D-24), and a refusal reads in the hunter's words, not "Admin privileges
required" (C-26).
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import false, func, select

from app.api import routes_users
from app.api import throttle as throttle_mod
from app.core.security import create_access_token
from app.models import Estate, User

from .conftest import requires_db


@pytest.fixture(autouse=True)
def _fresh_throttle():
    throttle_mod.throttle.reset()
    yield
    throttle_mod.throttle.reset()


@pytest.fixture
def client(db_session):
    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def people(db_session):
    e = Estate(name="Piedras Lisas", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db_session.add(e)
    db_session.flush()
    admin = User(estate_id=e.id, email="admin@estate.local", password_hash="x", role="admin")
    member = User(estate_id=e.id, email="member@estate.local", password_hash="x", role="member")
    db_session.add_all([admin, member])
    db_session.commit()

    def auth(u):
        return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}

    return {"admin": auth(admin), "member": auth(member)}


@requires_db
def test_a_second_add_that_races_the_first_says_the_person_is_there(
    client, db_session, people, monkeypatch
):
    """Two taps on Add person: the second got past the check while the first was
    being saved, and the unique email answered with a server error."""
    body = {"email": "pedro@estate.local", "password": "long-enough-1", "role": "member"}
    assert client.post("/api/users", headers=people["admin"], json=body).status_code == 200
    real = routes_users.select

    def racing(*cols):
        q = real(*cols)
        # The check for an existing email finds nothing, as it did for the second tap.
        return q.where(false()) if cols and cols[0] is User.id else q

    monkeypatch.setattr(routes_users, "select", racing)
    again = client.post("/api/users", headers=people["admin"], json=body)
    assert again.status_code == 400
    assert again.json()["detail"] == "Someone with that email already has a login"
    monkeypatch.setattr(routes_users, "select", real)
    assert db_session.scalar(
        select(func.count()).select_from(User).where(User.email == body["email"])) == 1


@requires_db
def test_an_admin_only_refusal_is_in_plain_words(client, people):
    r = client.get("/api/users", headers=people["member"])
    assert r.status_code == 403
    assert r.json()["detail"] == "Only the estate admin can do that."
    assert client.delete(f"/api/users/{uuid.uuid4()}", headers=people["member"]).status_code == 403
