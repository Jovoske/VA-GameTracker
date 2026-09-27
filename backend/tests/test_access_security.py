"""Access and security (plan item 12): who can do what, and what ends a sign-in.

Each rule here is one a hunter or the owner would notice: removing a person works
and keeps what they recorded, their camera logins keep fetching; a password change
signs the lost phone out; photo addresses carry a photo pass, not the sign-in; the
public sign-in slows a guesser down without ever locking the owner out; the server
won't start on the secrets published in this repository.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api import throttle as throttle_mod
from app.api.deps import IMAGE_TOKEN_HEADER, SESSION_TOKEN_HEADER
from app.api.routes_stands import tonight
from app.core.config import settings
from app.core.security import (
    PASS_WINDOW,
    create_access_token,
    decode_token,
    hash_password,
    image_token,
    pass_expiry,
)
from app.models import (
    Camera,
    CameraAccount,
    Estate,
    Image,
    PhotoNote,
    Sit,
    Stand,
    User,
    Zone,
)

from .conftest import requires_db

BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "a-good-long-password"


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
def estate(db_session):
    e = Estate(name="Piedras Lisas", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db_session.add(e)
    db_session.commit()
    return e


_HASH = None


def _user(db, estate, role="member", email=None, password=None):
    global _HASH
    if password is None:
        _HASH = _HASH or hash_password(PASSWORD)
        hashed = _HASH
    else:
        hashed = hash_password(password)
    u = User(estate_id=estate.id, email=email or f"{role}-{uuid.uuid4().hex[:6]}@estate.local",
             password_hash=hashed, role=role)
    db.add(u)
    db.commit()
    return u, _auth(create_access_token(str(u.id)))


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _photo(db, estate, tmp_path):
    cam = Camera(estate_id=estate.id, name="Charca", lat=39.095, lon=-1.362)
    db.add(cam)
    db.flush()
    path = tmp_path / f"{uuid.uuid4().hex}.jpg"
    path.write_bytes(b"\xff\xd8\xff\xd9")
    img = Image(camera_id=cam.id, captured_at=datetime.now(UTC), original_path=str(path))
    db.add(img)
    db.commit()
    return cam, img


# ── removing a person ───────────────────────────────────────────────────────


@requires_db
def test_removing_a_person_keeps_what_they_recorded_and_their_logins_keep_fetching(
    client, db_session, estate, tmp_path,
):
    """It used to be a 500 for anyone who had ever reserved a stand, drawn an area or
    added a camera login (audit D-05, H-01, I-12), so a guest could never be removed."""
    admin, admin_h = _user(db_session, estate, "admin")
    guest, guest_h = _user(db_session, estate, "member", email="pedro.garcia@gmail.com")
    stand = Stand(estate_id=estate.id, name="Ridge stand", lat=39.09, lon=-1.36)
    db_session.add(stand)
    db_session.flush()
    last_week = Sit(stand_id=stand.id, user_id=guest.id, night=tonight() - timedelta(days=7),
                    outcome="seen", species_seen="wild_boar")
    reserved = Sit(stand_id=stand.id, user_id=guest.id, night=tonight(), outcome="unreported")
    zone = Zone(estate_id=estate.id, kind="bedding", name="Pinar", created_by=guest.id,
                polygon={"type": "Polygon", "coordinates": [
                    [[-1.36, 39.09], [-1.35, 39.09], [-1.35, 39.1], [-1.36, 39.09]]]})
    login = CameraAccount(estate_id=estate.id, owner_user_id=guest.id, username="pedro@spy.es",
                          provider="spypoint", password_enc="x", active=True)
    _, img = _photo(db_session, estate, tmp_path)
    note = PhotoNote(image_id=img.id, user_id=guest.id, text="Big one")
    db_session.add_all([last_week, reserved, zone, login, note])
    db_session.commit()
    guest_id, img_pass = guest.id, image_token(guest)

    r = client.delete(f"/api/users/{guest_id}", headers=admin_h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["camera_logins_moved"] == 1
    assert "1 camera login they added keeps fetching photos" in body["note"]

    db_session.expire_all()
    assert db_session.get(User, guest_id) is None
    # Their sits and what they reported stay; tonight's stand is free again.
    kept = db_session.get(Sit, last_week.id)
    assert (kept.user_id, kept.outcome, kept.species_seen) == (None, "seen", "wild_boar")
    assert db_session.get(Sit, reserved.id).outcome == "cancelled"
    assert db_session.get(Zone, zone.id).created_by is None
    assert db_session.get(PhotoNote, note.id).text == "Big one"
    # The login keeps fetching, owned by the admin, and says who added it.
    acct = db_session.get(CameraAccount, login.id)
    assert (acct.active, acct.owner_user_id, acct.former_owner) == (
        True, admin.id, "pedro.garcia@gmail.com")
    row = next(a for a in client.get("/api/camera-accounts", headers=admin_h).json()
               if a["id"] == str(login.id))
    assert row["added_by_removed"] == "pedro.garcia@gmail.com"
    assert row["can_remove"] and row["can_edit"]
    # And the removed person is out everywhere at once, photos included.
    assert client.get("/api/auth/me", headers=guest_h).status_code == 401
    assert client.get(f"/api/images/{img.id}/file?token={img_pass}").status_code == 401
    # The admin can still remove the login when they decide to.
    assert client.delete(f"/api/camera-accounts/{login.id}", headers=admin_h).status_code == 200


@requires_db
def test_removing_someone_on_a_sit_ends_it_and_a_second_removal_keeps_the_first_name(
    client, db_session, estate,
):
    admin, admin_h = _user(db_session, estate, "admin")
    other_admin, _ = _user(db_session, estate, "admin", email="luis@estate.local")
    guest, _ = _user(db_session, estate, "member", email="marco@finca.es")
    stand = Stand(estate_id=estate.id, name="Ridge stand")
    db_session.add(stand)
    db_session.flush()
    on_now = Sit(stand_id=stand.id, user_id=guest.id, night=tonight(), outcome="unreported",
                 started_at=datetime.now(UTC) - timedelta(minutes=30))
    login = CameraAccount(estate_id=estate.id, owner_user_id=guest.id, username="m@ubox.es",
                          provider="ubox", password_enc="x")
    db_session.add_all([on_now, login])
    db_session.commit()

    assert client.delete(f"/api/users/{guest.id}", headers=admin_h).status_code == 200
    db_session.expire_all()
    sit = db_session.get(Sit, on_now.id)
    assert sit.ended_at is not None and sit.outcome == "unreported"

    # The login passed to the admin; if that admin goes too, it says who added it.
    db_session.get(CameraAccount, login.id).owner_user_id = other_admin.id
    db_session.commit()
    assert client.delete(f"/api/users/{other_admin.id}", headers=admin_h).status_code == 200
    db_session.expire_all()
    acct = db_session.get(CameraAccount, login.id)
    assert (acct.owner_user_id, acct.former_owner) == (admin.id, "marco@finca.es")


@requires_db
def test_a_removal_that_still_fails_says_so_in_words(client, db_session, estate, monkeypatch):
    _, admin_h = _user(db_session, estate, "admin")
    guest, _ = _user(db_session, estate, "member", email="ana@estate.local")
    real = db_session.commit

    def refuse():
        raise IntegrityError("DELETE FROM users", {}, Exception("fk_something"))

    monkeypatch.setattr(db_session, "commit", refuse)
    r = client.delete(f"/api/users/{guest.id}", headers=admin_h)
    monkeypatch.setattr(db_session, "commit", real)
    assert r.status_code == 409
    assert r.json()["detail"].startswith("Couldn't remove ana@estate.local")
    assert db_session.get(User, guest.id) is not None


@requires_db
def test_only_an_admin_removes_and_never_the_last_admin(client, db_session, estate):
    admin, admin_h = _user(db_session, estate, "admin")
    member, member_h = _user(db_session, estate, "member")
    assert client.delete(f"/api/users/{admin.id}", headers=member_h).status_code == 403
    assert client.delete(f"/api/users/{admin.id}", headers=admin_h).status_code == 400
    assert client.delete(f"/api/users/{uuid.uuid4()}", headers=admin_h).status_code == 404


# ── sessions: the token version, renewal, the photo pass ────────────────────


@requires_db
def test_a_password_change_signs_every_other_phone_out(client, db_session, estate, tmp_path):
    user, old_h = _user(db_session, estate, "member")
    _, img = _photo(db_session, estate, tmp_path)
    old_pass = image_token(user)
    assert client.get(f"/api/images/{img.id}/file?token={old_pass}").status_code == 200

    wrong = client.post("/api/auth/change-password", headers=old_h,
                        json={"current_password": "nope", "new_password": "another-one-9"})
    assert wrong.status_code == 400
    r = client.post("/api/auth/change-password", headers=old_h,
                    json={"current_password": PASSWORD, "new_password": "another-one-9"})
    assert r.status_code == 200
    body = r.json()
    assert r.headers[IMAGE_TOKEN_HEADER] == body["image_token"]

    # The lost phone's sign-in and photo pass stop working; this phone's new ones work.
    assert client.get("/api/auth/me", headers=old_h).status_code == 401
    assert client.get(f"/api/images/{img.id}/file?token={old_pass}").status_code == 401
    assert client.get("/api/auth/me", headers=_auth(body["access_token"])).status_code == 200
    assert client.get(f"/api/images/{img.id}/file?token={body['image_token']}").status_code == 200
    login = client.post("/api/auth/login", json={"email": user.email, "password": "another-one-9"})
    assert login.status_code == 200


@requires_db
def test_sign_ins_from_before_the_token_version_still_work(client, db_session, estate):
    """Tokens made before this change carry no version: they read as 0, so nobody is
    signed out by the upgrade itself."""
    user, _ = _user(db_session, estate, "member")
    now = datetime.now(UTC)
    legacy = jwt.encode({"sub": str(user.id), "iat": now, "exp": now + timedelta(days=30),
                         "role": "member"}, settings.jwt_secret, algorithm="HS256")
    assert client.get("/api/auth/me", headers=_auth(legacy)).status_code == 200
    user.token_version = 1
    db_session.commit()
    assert client.get("/api/auth/me", headers=_auth(legacy)).status_code == 401


@requires_db
def test_a_photo_pass_opens_photos_and_nothing_else(client, db_session, estate, tmp_path):
    user, headers = _user(db_session, estate, "member")
    _, img = _photo(db_session, estate, tmp_path)
    img_pass = image_token(user)
    assert client.get("/api/auth/me", headers=_auth(img_pass)).status_code == 401
    assert client.get(f"/api/images/{img.id}/file", headers=_auth(img_pass)).status_code == 401
    assert client.get(f"/api/images/{img.id}/file?token={img_pass}").status_code == 200
    # The sign-in in an address is an old link: refused in words, not a 500.
    signin = headers["Authorization"].split()[1]
    old = client.get(f"/api/images/{img.id}/file?token={signin}")
    assert old.status_code == 401 and "Open the photo in the app" in old.json()["detail"]


@requires_db
def test_every_answer_carries_the_photo_pass_and_it_holds_still_all_window(
    client, db_session, estate,
):
    user, headers = _user(db_session, estate, "viewer")
    first = client.get("/api/auth/me", headers=headers).headers[IMAGE_TOKEN_HEADER]
    again = client.get("/api/cameras", headers=headers).headers[IMAGE_TOKEN_HEADER]
    assert first == again  # the same text, so photo addresses don't change
    claims = decode_token(first)
    assert (claims["scope"], claims["sub"], claims["tv"]) == ("img", str(user.id), 0)
    left = datetime.fromtimestamp(claims["exp"], UTC) - datetime.now(UTC)
    assert PASS_WINDOW - timedelta(seconds=5) <= left <= 2 * PASS_WINDOW
    r = client.get("/api/auth/image-token", headers=headers).json()
    assert r["image_token"] == first
    # A fresh sign-in isn't renewed; one over a week old is, under the same version.
    assert SESSION_TOKEN_HEADER not in client.get("/api/auth/me", headers=headers).headers


def test_a_pass_lasts_between_one_and_two_windows():
    at = datetime(2026, 10, 3, 17, 59, tzinfo=UTC)
    assert pass_expiry(at) == datetime(2026, 10, 4, 0, 0, tzinfo=UTC)
    assert pass_expiry(datetime(2026, 10, 3, 18, 0, tzinfo=UTC)) == datetime(
        2026, 10, 4, 6, 0, tzinfo=UTC)
    who = SimpleNamespace(id=uuid.uuid4(), token_version=3)
    assert image_token(who, at) == image_token(who, at - timedelta(hours=5))
    assert image_token(who, at) != image_token(who, at + timedelta(minutes=1))


@requires_db
def test_a_week_old_sign_in_is_renewed_so_a_daily_hunter_is_never_thrown_out(
    client, db_session, estate,
):
    user, _ = _user(db_session, estate, "member")
    then = datetime.now(UTC) - timedelta(days=8)
    old = jwt.encode({"sub": str(user.id), "iat": then, "exp": then + timedelta(days=30),
                      "tv": 0}, settings.jwt_secret, algorithm="HS256")
    r = client.get("/api/auth/me", headers=_auth(old))
    assert r.status_code == 200
    fresh = r.headers[SESSION_TOKEN_HEADER]
    claims = decode_token(fresh)
    assert claims["sub"] == str(user.id) and claims.get("scope") is None
    assert datetime.fromtimestamp(claims["exp"], UTC) > then + timedelta(days=30)
    assert client.get("/api/auth/me", headers=_auth(fresh)).status_code == 200


# ── signing in ──────────────────────────────────────────────────────────────


@requires_db
def test_sign_in_ignores_the_case_and_spaces_of_the_email(client, db_session, estate):
    """The admin types "Marco@Finca.es", it is kept lowercase, and Marco types it the
    way he was given it (audit D-23)."""
    _, admin_h = _user(db_session, estate, "admin")
    made = client.post("/api/users", headers=admin_h,
                       json={"email": "Marco@Finca.es", "password": PASSWORD, "role": "member"})
    assert made.status_code == 200 and made.json()["email"] == "marco@finca.es"
    r = client.post("/api/auth/login", json={"email": " Marco@Finca.es ", "password": PASSWORD})
    assert r.status_code == 200
    assert decode_token(r.json()["image_token"])["scope"] == "img"
    # A login stored with capitals before this still signs in, and can't be made twice.
    _user(db_session, estate, "member", email="Old.Guest@Estate.local")
    ok = client.post("/api/auth/login", json={"email": "old.guest@estate.local",
                                             "password": PASSWORD})
    assert ok.status_code == 200
    dup = client.post("/api/users", headers=admin_h, json={
        "email": "OLD.GUEST@estate.local", "password": PASSWORD, "role": "member"})
    assert dup.status_code == 400


@requires_db
def test_wrong_passwords_slow_an_email_down_but_never_lock_the_owner_out(
    client, db_session, estate, monkeypatch,
):
    now = [1000.0]
    monkeypatch.setattr(throttle_mod.throttle, "clock", lambda: now[0])
    user, _ = _user(db_session, estate, "admin", email="admin@gamesense.local")

    def attempt(password, email="admin@gamesense.local"):
        return client.post("/api/auth/login", json={"email": email, "password": password})

    for _ in range(throttle_mod.FREE_TRIES):
        assert attempt("guess").status_code == 401
    # Now a wait: even the right password is asked to wait, and told how long.
    held = attempt(PASSWORD)
    assert held.status_code == 429
    assert held.headers["Retry-After"] == "2"
    assert "Try again in 2 seconds" in held.json()["detail"]
    now[0] += 2
    assert attempt(PASSWORD).status_code == 200  # the wait passed: no lockout
    # A success starts afresh; the waits grow with each wrong one, to a minute at most.
    assert [throttle_mod.wait_for(n) for n in (2, 3, 4, 5, 8, 20)] == [0, 2, 4, 8, 60, 60]
    # Another email is not held up by this one's wrong guesses.
    for _ in range(throttle_mod.FREE_TRIES):
        attempt("guess")
    assert attempt("guess", email="someone@else.es").status_code == 401


@requires_db
def test_one_place_guessing_many_emails_is_held_up_and_nobody_else_is(
    client, db_session, estate, monkeypatch,
):
    now = [5000.0]
    monkeypatch.setattr(throttle_mod.throttle, "clock", lambda: now[0])
    monkeypatch.setattr(settings, "trusted_proxies", ["testclient"])
    _user(db_session, estate, "member", email="ana@estate.local")

    def attempt(ip, email, password="guess"):
        return client.post("/api/auth/login", json={"email": email, "password": password},
                           headers={"CF-Connecting-IP": ip})

    for n in range(throttle_mod.IP_LIMIT):
        assert attempt("203.0.113.9", f"user{n}@x.es").status_code == 401
    held = attempt("203.0.113.9", "ana@estate.local", PASSWORD)
    assert held.status_code == 429 and "from here" in held.json()["detail"]
    assert int(held.headers["Retry-After"]) > 60
    # Someone else behind the same tunnel signs in as usual.
    assert attempt("198.51.100.4", "ana@estate.local", PASSWORD).status_code == 200
    now[0] += throttle_mod.IP_WINDOW_S
    assert attempt("203.0.113.9", "ana@estate.local", PASSWORD).status_code == 200


def test_the_visitors_address_is_believed_only_from_the_tunnel(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", ["127.0.0.1", "::1"])

    def req(peer, header=None):
        return SimpleNamespace(client=SimpleNamespace(host=peer),
                               headers={"cf-connecting-ip": header} if header else {})

    assert throttle_mod.client_ip(req("127.0.0.1", "203.0.113.9")) == "203.0.113.9"
    # From anywhere else the header is anyone's to write: the peer is what counts.
    assert throttle_mod.client_ip(req("192.168.1.50", "203.0.113.9")) == "192.168.1.50"
    assert throttle_mod.client_ip(req("127.0.0.1")) == "127.0.0.1"


def test_the_throttle_forgets_rather_than_grows_without_end(monkeypatch):
    monkeypatch.setattr(throttle_mod, "MAX_KEYS", 50)
    t = throttle_mod.LoginThrottle(clock=lambda: 1.0)
    for n in range(500):
        t.failed(f"10.0.{n // 250}.{n % 250}", f"u{n}@x.es")
    assert len(t._ips) + len(t._emails) <= 50


# ── who may change what ─────────────────────────────────────────────────────


@requires_db
def test_viewers_look_and_members_do_hunter_things_but_not_admin_ones(
    client, db_session, estate, tmp_path,
):
    """Every write that changes the estate for everyone checks the role (audit B-08,
    C-09, C-28, E-09): viewers never write; bedding, camera places and the hill
    shape are admin work, as on the map; members may start a photo check."""
    _, admin_h = _user(db_session, estate, "admin")
    _, member_h = _user(db_session, estate, "member")
    _, viewer_h = _user(db_session, estate, "viewer")
    cam, img = _photo(db_session, estate, tmp_path)
    zone = Zone(estate_id=estate.id, kind="bedding", name="Pinar", polygon={
        "type": "Polygon", "coordinates": [[[-1.36, 39.09], [-1.35, 39.09], [-1.35, 39.1],
                                            [-1.36, 39.09]]]})
    db_session.add(zone)
    db_session.commit()
    square = {"type": "Polygon", "coordinates": [[[-1.37, 39.08], [-1.36, 39.08],
                                                  [-1.36, 39.09], [-1.37, 39.09],
                                                  [-1.37, 39.08]]]}
    writes = [
        ("post", "/api/zones", {"name": "Loma", "polygon": square}),
        ("patch", f"/api/zones/{zone.id}", {"name": "Pinar alto"}),
        ("delete", f"/api/zones/{zone.id}", None),
        ("put", f"/api/cameras/{cam.id}/location", {"lat": 39.1, "lng": -1.35}),
        ("post", "/api/stands", {"name": "Loma stand", "lat": 39.1, "lon": -1.35}),
    ]
    for method, url, body in writes:
        for who in (member_h, viewer_h):
            r = client.request(method, url, headers=who, json=body)
            assert r.status_code == 403, (method, url, r.status_code)
    assert client.post("/api/terrain/refresh", headers=member_h).status_code == 403
    assert client.post(f"/api/images/{img.id}/flag", headers=viewer_h,
                       json={"is_empty": True}).status_code == 403
    assert client.post(f"/api/images/{img.id}/flag", headers=viewer_h,
                       json={"is_empty": False}).status_code == 403  # Keep, too
    assert client.post("/api/camera-accounts", headers=viewer_h, json={
        "username": "v@spy.es", "password": "x"}).status_code == 403
    assert client.patch("/api/species/wild_boar", headers=member_h,
                        json={"huntable": False}).status_code == 403
    assert client.post("/api/animals/recompute", headers=member_h).status_code == 403
    # The Check button: members yes, viewers told photos come by themselves.
    refused = client.post("/api/cameras/sync", headers=viewer_h)
    assert refused.status_code == 403 and "every 15 minutes" in refused.json()["detail"]
    assert client.post("/api/cameras/sync", headers=member_h).json()["status"] == "started"
    # And the admin can do the admin work.
    assert client.patch(f"/api/zones/{zone.id}", headers=admin_h,
                        json={"name": "Pinar alto"}).status_code == 200
    assert client.post(f"/api/images/{img.id}/flag", headers=member_h,
                       json={"is_empty": True}).status_code == 200


@requires_db
def test_a_stand_or_camera_off_the_planet_is_refused(client, db_session, estate, tmp_path):
    _, admin_h = _user(db_session, estate, "admin")
    cam, _ = _photo(db_session, estate, tmp_path)
    for lat, lon in ((1000, -1.3), (39.1, 400)):
        assert client.post("/api/stands", headers=admin_h,
                           json={"name": "Bad", "lat": lat, "lon": lon}).status_code == 422
        assert client.put(f"/api/cameras/{cam.id}/location", headers=admin_h,
                          json={"lat": lat, "lng": lon}).status_code == 422


# ── the API docs and the published secrets ──────────────────────────────────


def test_the_api_docs_are_off_unless_asked_for(monkeypatch):
    import importlib

    import app.main as main

    plain = TestClient(main.app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert plain.get(path).status_code == 404
    monkeypatch.setattr(settings, "enable_api_docs", True)
    try:
        opened = TestClient(importlib.reload(main).app)
        assert opened.get("/openapi.json").status_code == 200
        assert opened.get("/docs").status_code == 200
    finally:
        monkeypatch.setattr(settings, "enable_api_docs", False)
        importlib.reload(main)


def test_the_server_refuses_the_published_secret(monkeypatch):
    from app.core import startup

    monkeypatch.setattr(settings, "app_env", "production")
    for published in ("dev-secret-change-me", "dev-secret-change-me-please"):
        monkeypatch.setattr(settings, "jwt_secret", published)
        [why] = startup.refusals()
        assert "python -m app.manage new-secret" in why
    monkeypatch.setattr(settings, "jwt_secret", "short-but-not-published")
    assert "shorter than 32" in startup.refusals()[0]
    monkeypatch.setattr(settings, "jwt_secret", "x" * 48)
    assert startup.refusals() == []
    # On a laptop it starts anyway.
    monkeypatch.setattr(settings, "jwt_secret", "dev-secret-change-me")
    monkeypatch.setattr(settings, "app_env", "development")
    assert startup.refusals() == []


@requires_db
def test_the_server_refuses_an_admin_on_the_published_password(db_session, estate, monkeypatch):
    from app.core import startup

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "y" * 48)
    monkeypatch.setattr(settings, "admin_password", "changeme")
    # No admin yet: the seed would make one with the published password.
    assert "ADMIN_PASSWORD" in startup.refusals(db_session)[0]
    _user(db_session, estate, "admin", email="admin@gamesense.local", password="changeme")
    _user(db_session, estate, "member", email="m@estate.local", password="changeme")
    [why] = startup.refusals(db_session)
    assert why.endswith("python -m app.manage set-password admin@gamesense.local")
    admin = db_session.scalar(select(User).where(User.email == "admin@gamesense.local"))
    admin.password_hash = hash_password(PASSWORD)
    db_session.commit()
    assert startup.refusals(db_session) == []


def test_serve_py_stops_with_the_fix_in_words(tmp_path):
    """The real entrypoint, as the Windows service runs it: it exits before uvicorn
    and prints what to do (the service log keeps it)."""
    env = {"PATH": "/usr/bin:/bin", "JWT_SECRET": "dev-secret-change-me",
           "DATABASE_URL": "postgresql+psycopg://nobody@127.0.0.1:1/none",
           "PYTHONPATH": str(BACKEND)}
    run = subprocess.run([sys.executable, str(BACKEND / "serve.py")], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 2
    assert "GameSense will not start" in run.stderr
    assert "python -m app.manage new-secret" in run.stderr


def test_new_secret_keeps_the_saved_camera_logins_readable(tmp_path, monkeypatch):
    from app import manage
    from app.core import crypto

    env = tmp_path / ".env"
    env.write_text("# the server's settings\nJWT_SECRET=dev-secret-change-me-please\n"
                   "CREDENTIALS_KEY=\nADMIN_EMAIL=admin@gamesense.local\n", encoding="utf-8")
    monkeypatch.setattr(settings, "jwt_secret", "dev-secret-change-me-please")
    monkeypatch.setattr(settings, "credentials_key", "")
    monkeypatch.setattr(settings, "previous_jwt_secret", "")
    saved = crypto.encrypt("guest-spypoint-password")

    assert "Restart the GameSense service" in manage.new_secret(env)
    values = dict(line.split("=", 1) for line in env.read_text().splitlines()
                  if "=" in line and not line.startswith("#"))
    assert len(values["JWT_SECRET"]) >= 48 and values["JWT_SECRET"] != "dev-secret-change-me-please"
    assert values["PREVIOUS_JWT_SECRET"] == "dev-secret-change-me-please"
    assert len(values["CREDENTIALS_KEY"]) >= 48
    assert values["ADMIN_EMAIL"] == "admin@gamesense.local"
    assert env.read_text().startswith("# the server's settings\n")
    # The server as it restarts with the new file still reads the saved password.
    for key in ("jwt_secret", "credentials_key", "previous_jwt_secret"):
        monkeypatch.setattr(settings, key, values[key.upper()])
    assert crypto.decrypt(saved) == "guest-spypoint-password"


@requires_db
def test_set_password_signs_the_person_in_with_it_and_out_everywhere_else(
    client, db_session, estate, monkeypatch,
):
    from sqlalchemy.orm import sessionmaker

    from app import manage
    from app.core import db as core_db

    monkeypatch.setattr(core_db, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    user, old_h = _user(db_session, estate, "admin", email="Admin@GameSense.local",
                        password="changeme")
    with pytest.raises(SystemExit):
        manage.set_password("admin@gamesense.local", "changeme")
    with pytest.raises(SystemExit):
        manage.set_password("nobody@x.es", "a-fine-password")
    assert "Admin@GameSense.local" in manage.set_password("admin@gamesense.local",
                                                          "a-fine-password")
    db_session.expire_all()
    assert client.get("/api/auth/me", headers=old_h).status_code == 401
    assert client.post("/api/auth/login", json={
        "email": "admin@gamesense.local", "password": "a-fine-password"}).status_code == 200


def test_the_access_log_never_keeps_a_token():
    import app.main  # noqa: F401  (the app sets the filter up as it loads)
    from app.core.logging import RedactTokens

    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", "/api/images/abc/file?token=eyJhbGci.x.y&download=1", "1.1", 200),
        None)
    assert RedactTokens().filter(record)
    line = record.getMessage()
    assert "eyJ" not in line and "token=…&download=1" in line
    assert any(isinstance(f, RedactTokens) for f in logging.getLogger("uvicorn.access").filters)
