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
from fastapi import HTTPException
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
    PushSubscription,
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
    # Checked by the AI: a frame it hasn't looked at yet is the admin's alone (R6BE-2).
    img = Image(camera_id=cam.id, captured_at=datetime.now(UTC), original_path=str(path),
                processed_at=datetime.now(UTC))
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


def _subscribe(db, user, endpoint):
    db.add(PushSubscription(user_id=user.id, endpoint=endpoint, p256dh="k", auth="a"))
    db.commit()


def _endpoints(db, user) -> set[str]:
    db.expire_all()
    return set(db.scalars(select(PushSubscription.endpoint)
                          .where(PushSubscription.user_id == user.id)).all())


@requires_db
def test_a_password_change_stops_the_lost_phones_alerts_and_keeps_this_ones(
    client, db_session, estate,
):
    """The lost phone was signed out, and still got every sighting, team note and
    the plan on its lock screen, with no end (final review SEC-1)."""
    user, headers = _user(db_session, estate, "member")
    other, _ = _user(db_session, estate, "member")
    lost, here = "https://fcm.googleapis.com/fcm/send/lost", "https://web.push.apple.com/here"
    _subscribe(db_session, user, lost)
    _subscribe(db_session, user, here)
    _subscribe(db_session, other, "https://fcm.googleapis.com/fcm/send/pedro")
    r = client.post("/api/auth/change-password", headers=headers, json={
        "current_password": PASSWORD, "new_password": "another-one-9", "keep_endpoint": here})
    assert r.status_code == 200
    assert _endpoints(db_session, user) == {here}
    assert _endpoints(db_session, other) == {"https://fcm.googleapis.com/fcm/send/pedro"}
    # A phone with no alerts of its own keeps none of the others'.
    r = client.post("/api/auth/change-password", headers=_auth(r.json()["access_token"]),
                    json={"current_password": "another-one-9", "new_password": "a-third-one-9"})
    assert r.status_code == 200 and _endpoints(db_session, user) == set()


@requires_db
def test_guessing_the_current_password_is_held_like_a_sign_in(
    client, db_session, estate, monkeypatch,
):
    """Whoever picks up an unlocked phone could guess the current password without
    end, then change it and lock the owner out (final review SEC-4)."""
    now = [1000.0]
    monkeypatch.setattr(throttle_mod.throttle, "clock", lambda: now[0])
    user, headers = _user(db_session, estate, "viewer")

    def change(current):
        return client.post("/api/auth/change-password", headers=headers,
                           json={"current_password": current, "new_password": "another-one-9"})

    for _ in range(throttle_mod.FREE_TRIES):
        assert change("guess").status_code == 400
    held = change(PASSWORD)
    assert held.status_code == 429 and held.headers["Retry-After"] == "2"
    now[0] += 2
    assert change(PASSWORD).status_code == 200


def test_one_person_checks_one_current_password_at_a_time():
    """A viewer sending thirty at once held every hashing slot sign-in shares; now
    the second waits its turn without touching them."""
    first = throttle_mod.throttle.attempt("203.0.113.9", "viewer@estate.local", known=True)
    with pytest.raises(HTTPException) as held:
        throttle_mod.throttle.attempt("203.0.113.9", "viewer@estate.local", known=True)
    assert held.value.status_code == 429
    first.failed()


@requires_db
def test_a_sign_in_from_before_token_versions_works_until_its_end_but_is_never_renewed(
    client, db_session, estate,
):
    """Those sat in photo addresses, logs and copied links: renewed, a leaked one
    would never end (final review SEC-3)."""
    user, _ = _user(db_session, estate, "member")
    then = datetime.now(UTC) - timedelta(days=20)
    legacy = jwt.encode({"sub": str(user.id), "iat": then, "exp": then + timedelta(days=30),
                         "role": "member"}, settings.jwt_secret, algorithm="HS256")
    r = client.get("/api/auth/me", headers=_auth(legacy))
    assert r.status_code == 200 and SESSION_TOKEN_HEADER not in r.headers


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

    def req(peer, **headers):
        return SimpleNamespace(client=SimpleNamespace(host=peer),
                               headers={k.replace("_", "-"): v for k, v in headers.items()})

    assert throttle_mod.client_ip(req("127.0.0.1", cf_connecting_ip="203.0.113.9")) == "203.0.113.9"
    assert throttle_mod.client_ip(
        req("127.0.0.1", x_forwarded_for="10.9.9.9, 203.0.113.9")) == "203.0.113.9"
    # From anywhere else the header is anyone's to write: the peer is what counts.
    lan = req("192.168.1.50", cf_connecting_ip="203.0.113.9")
    assert throttle_mod.client_ip(lan) == "192.168.1.50"
    assert throttle_mod.client_ip(req("127.0.0.1")) == "127.0.0.1"
    # From the internet: through the tunnel, or straight from a public address. The
    # server's own network is not.
    assert throttle_mod.from_outside(req("127.0.0.1", cf_connecting_ip="203.0.113.9"))
    assert throttle_mod.from_outside(req("8.8.8.8"))
    assert throttle_mod.from_outside(req("::ffff:8.8.8.8"))
    assert not throttle_mod.from_outside(req("127.0.0.1"))
    assert not throttle_mod.from_outside(req("192.168.1.50"))
    assert not throttle_mod.from_outside(req("testclient"))
    # Cloudflare's headers mean the internet whoever the peer is: a tunnel pointed at
    # the LAN address must not let the published admin password in (SEC-5).
    assert throttle_mod.from_outside(req("192.168.1.50", cf_connecting_ip="203.0.113.9"))
    assert throttle_mod.from_outside(req("192.168.1.50", cf_ray="8c1f-MAD"))


def test_the_tunnel_is_seen_as_the_tunnel_through_uvicorn_as_serve_py_runs_it(monkeypatch):
    """uvicorn's own X-Forwarded-For rewrite replaced the tunnel's address with the
    visitor's before the app saw it, so the CF-Connecting-IP rule never ran and every
    sign-in through the tunnel logged a false warning. serve.py turns that rewrite off;
    this goes through uvicorn's middleware stack built from serve.py's own options."""
    import asyncio
    import importlib.util

    import httpx
    import uvicorn
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    spec = importlib.util.spec_from_file_location("serve_under_test", BACKEND / "serve.py")
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    monkeypatch.setattr(settings, "trusted_proxies", ["127.0.0.1", "::1"])

    def who(request):
        return JSONResponse({"ip": throttle_mod.client_ip(request),
                             "outside": throttle_mod.from_outside(request),
                             "tunnel": request.client.host in settings.trusted_proxies})

    probe = Starlette(routes=[Route("/who", who)])

    def ask(options: dict, peer: str, headers: dict) -> dict:
        config = uvicorn.Config(probe, log_config=None, **{
            k: v for k, v in options.items() if k not in ("host", "port")})
        config.load()

        async def go():
            transport = httpx.ASGITransport(app=config.loaded_app, client=(peer, 50123))
            async with httpx.AsyncClient(transport=transport, base_url="http://db01") as c:
                return (await c.get("/who", headers=headers)).json()
        return asyncio.run(go())

    tunnel = {"CF-Connecting-IP": "198.51.100.7", "X-Forwarded-For": "198.51.100.7"}
    assert ask(serve.uvicorn_options(), "127.0.0.1", tunnel) == {
        "ip": "198.51.100.7", "outside": True, "tunnel": True}
    assert ask(serve.uvicorn_options(), "127.0.0.1", {}) == {
        "ip": "127.0.0.1", "outside": False, "tunnel": True}
    # Cloudflare's headers from an untrusted peer: its address is not believed, but
    # the request is from the internet all the same (SEC-5).
    assert ask(serve.uvicorn_options(), "192.168.1.20", tunnel) == {
        "ip": "192.168.1.20", "outside": True, "tunnel": False}
    # What uvicorn's default did: the tunnel's own address is gone before the app
    # looks, so it can't tell the request came through the tunnel at all.
    assert ask({"proxy_headers": True}, "127.0.0.1", tunnel)["tunnel"] is False
    assert serve.uvicorn_options()["proxy_headers"] is False


def test_an_ipv6_address_counts_by_its_block():
    """One home or phone is given a /64: every address in it is one place."""
    place = throttle_mod.place_of
    assert place("2001:db8:1:2:aaaa::1") == place("2001:db8:1:2:bbbb:cccc:dddd:9")
    assert place("2001:db8:1:2::1") != place("2001:db8:1:3::1")
    assert place("::ffff:203.0.113.9") == place("203.0.113.9") == "203.0.113.9"
    assert place("testclient") == "testclient"
    t = throttle_mod.LoginThrottle(clock=lambda: 1.0)
    for n in range(throttle_mod.IP_LIMIT):
        with t.attempt(f"2001:db8:1:2::{n + 1:x}", f"u{n}@x.es") as a:
            a.failed()
    with pytest.raises(HTTPException) as held:
        t.attempt("2001:db8:1:2:ffff::1", "ana@estate.local")
    assert held.value.status_code == 429 and "from here" in held.value.detail
    t.attempt("2001:db8:9:9::1", "ana@estate.local").succeeded()


def test_the_throttle_forgets_rather_than_grows_without_end(monkeypatch):
    monkeypatch.setattr(throttle_mod, "MAX_KEYS", 50)
    t = throttle_mod.LoginThrottle(clock=lambda: 1.0)
    for n in range(500):
        with t.attempt(f"10.0.{n // 250}.{n % 250}", f"u{n}@x.es") as a:
            a.failed()
        assert len(t._places) + len(t._pairs) + len(t._emails) <= 50 + 3
    # A sign-in being checked is never forgotten, however full it gets.
    busy = t.attempt("10.9.9.9", "busy@x.es")
    for n in range(200):
        with t.attempt(f"10.1.{n // 250}.{n % 250}", f"v{n}@x.es") as a:
            a.failed()
    assert t._pairs[("10.9.9.9", "busy@x.es")].checking
    busy.succeeded()


def _fake_login(monkeypatch, users: dict[str, str], delay: float = 0.0):
    """Sign-in without a database or Argon2: `users` maps emails to their passwords
    (all admins). Returns the running count of password checks and the most that
    ran at once."""
    import threading
    import time as _time

    from app.api import routes_auth

    ids = {email: uuid.uuid4() for email in users}
    seen = {"checks": 0, "now": 0, "most": 0}
    lock = threading.Lock()

    def find_user(db, email):
        email = email.strip().lower()
        if email not in users:
            return None
        return SimpleNamespace(id=ids[email], email=email, role="admin", token_version=0,
                               password_hash=f"hash:{users[email]}")

    def verify(password, hashed):
        with lock:
            seen["checks"] += 1
            seen["now"] += 1
            seen["most"] = max(seen["most"], seen["now"])
        _time.sleep(delay)
        with lock:
            seen["now"] -= 1
        return hashed == f"hash:{password}"

    monkeypatch.setattr(routes_auth, "find_user", find_user)
    monkeypatch.setattr(routes_auth, "verify_password", verify)
    monkeypatch.setattr(routes_auth, "_no_such_hash", lambda: "hash:nobody")
    return seen


@pytest.fixture
def bare_client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_sign_ins_sent_all_at_once_are_held_like_one_after_another(bare_client, monkeypatch):
    """A burst of wrong passwords in parallel used to pass the check before any of
    them was counted, so every one got a password check (R5BE-2)."""
    import threading

    monkeypatch.setattr(throttle_mod.throttle, "clock", lambda: 7000.0)  # no wait runs out
    seen = _fake_login(monkeypatch, {"admin@gamesense.local": PASSWORD}, delay=0.05)

    def burst(n, email_for):
        statuses: list[int] = []
        gate = threading.Barrier(n)

        def go(i):
            gate.wait()
            statuses.append(bare_client.post("/api/auth/login", json={
                "email": email_for(i), "password": f"guess-{i}"}).status_code)
        threads = [threading.Thread(target=go, args=(i,)) for i in range(n)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        return statuses

    one_email = burst(30, lambda i: "admin@gamesense.local")
    assert one_email.count(401) <= throttle_mod.FREE_TRIES
    assert one_email.count(429) == 30 - one_email.count(401)
    assert seen["checks"] == one_email.count(401)

    throttle_mod.throttle.reset()
    seen["checks"] = 0
    many_emails = burst(40, lambda i: f"guest{i}@estate.local")
    assert many_emails.count(401) <= throttle_mod.IP_LIMIT
    assert 2 <= seen["most"] <= throttle_mod.IP_AT_ONCE  # at once, but a few at most
    assert seen["checks"] == many_emails.count(401)
    assert set(many_emails) <= {401, 429}


def test_a_guesser_elsewhere_never_holds_the_owner_up(bare_client, monkeypatch):
    """One guess a minute at the admin's email from somewhere else used to keep the
    owner waiting for as long as the guesser liked (R5BE-3)."""
    now = [10_000.0]
    monkeypatch.setattr(throttle_mod.throttle, "clock", lambda: now[0])
    monkeypatch.setattr(settings, "trusted_proxies", ["testclient"])
    seen = _fake_login(monkeypatch, {"admin@gamesense.local": PASSWORD})

    def attempt(ip, password):
        return bare_client.post("/api/auth/login", headers={"CF-Connecting-IP": ip}, json={
            "email": "admin@gamesense.local", "password": password})

    owner_in = guesses = 0
    for second in range(0, 3 * 3600, 5):  # three hours; the guesser tries every 5 s
        now[0] = 10_000.0 + second
        r = attempt("203.0.113.9", "guess")
        assert r.status_code in (401, 429)
        guesses += r.status_code == 401
        if second % 600 == 300:  # the owner, from home, every ten minutes
            got = attempt("198.51.100.4", PASSWORD)
            assert got.status_code == 200, (second, got.json())
            owner_in += 1
    assert owner_in == 18
    # The guesser got about one password check a minute, never more.
    assert guesses <= 3 * 60 + throttle_mod.FREE_TRIES + 5
    assert seen["checks"] == guesses + owner_in


def test_a_crowd_guessing_one_email_holds_new_phones_but_not_a_known_one(
    bare_client, monkeypatch,
):
    now = [20_000.0]
    monkeypatch.setattr(throttle_mod.throttle, "clock", lambda: now[0])
    monkeypatch.setattr(settings, "trusted_proxies", ["testclient"])
    _fake_login(monkeypatch, {"owner@estate.local": PASSWORD, "guest@estate.local": PASSWORD})

    def attempt(ip, password, phone=None):
        return bare_client.post("/api/auth/login", headers={"CF-Connecting-IP": ip}, json={
            "email": "owner@estate.local", "password": password, "known_phone": phone})

    first = attempt("198.51.100.4", PASSWORD)
    assert first.status_code == 200
    mark = first.json()["known_phone"]
    assert decode_token(mark)["scope"] == "phone"

    for n in range(throttle_mod.EMAIL_LIMIT):  # a crowd, three guesses from each place
        assert attempt(f"203.0.{n // 3 // 250}.{n // 3 % 250 + 1}", "guess").status_code == 401
    held = attempt("192.0.2.77", PASSWORD)
    assert held.status_code == 429
    assert "phone that has signed in with it before" in held.json()["detail"]
    # The owner's own phone, signed in before, is not held; nor is it from anywhere.
    assert attempt("192.0.2.77", PASSWORD, phone=mark).status_code == 200
    # A mark for another email, or a made-up one, is no mark.
    guests = bare_client.post("/api/auth/login", json={
        "email": "guest@estate.local", "password": PASSWORD}).json()["known_phone"]
    assert attempt("192.0.2.78", PASSWORD, phone=guests).status_code == 429
    assert attempt("192.0.2.79", PASSWORD, phone="not-a-mark").status_code == 429
    # The crowd's hour passes.
    now[0] += throttle_mod.EMAIL_WINDOW_S
    assert attempt("192.0.2.77", PASSWORD).status_code == 200


def test_a_sign_in_the_server_was_too_busy_to_check_counts_for_nothing(
    bare_client, monkeypatch,
):
    from app.api import routes_auth

    _fake_login(monkeypatch, {"admin@gamesense.local": PASSWORD})
    monkeypatch.setattr(routes_auth, "HASH_WAIT_S", 0.01)
    taken = [throttle_mod.HASHING.acquire(timeout=1) for _ in range(4)]
    try:
        busy = bare_client.post("/api/auth/login", json={
            "email": "admin@gamesense.local", "password": PASSWORD})
        assert busy.status_code == 503 and "busy" in busy.json()["detail"]
    finally:
        for got in taken:
            if got:
                throttle_mod.HASHING.release()
    # Let go, not left "still checking", and not counted as a wrong password.
    assert bare_client.post("/api/auth/login", json={
        "email": "admin@gamesense.local", "password": PASSWORD}).status_code == 200


def test_the_known_phone_mark_opens_nothing(bare_client, monkeypatch):
    _fake_login(monkeypatch, {"admin@gamesense.local": PASSWORD})
    got = bare_client.post("/api/auth/login", json={
        "email": "admin@gamesense.local", "password": PASSWORD}).json()
    mark = got["known_phone"]
    assert decode_token(mark)["em"] == "admin@gamesense.local"
    assert bare_client.get("/api/auth/me", headers=_auth(mark)).status_code == 401
    assert bare_client.get(f"/api/images/{uuid.uuid4()}/file?token={mark}").status_code == 401


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


def _env_values(env: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in env.read_text().splitlines()
                if "=" in line and not line.startswith("#"))


@pytest.fixture
def server_secrets(monkeypatch):
    """The server's secrets, as settings and the environment hold them, put back
    afterwards whatever the code under test does to them."""
    def put(**values):
        for key in ("jwt_secret", "credentials_key", "previous_jwt_secret"):
            value = values.get(key, "")
            monkeypatch.setattr(settings, key, value)
            if value:
                monkeypatch.setenv(key.upper(), value)
            else:
                monkeypatch.delenv(key.upper(), raising=False)
    monkeypatch.setattr(settings, "app_env", "production")
    return put


def test_a_published_or_short_secret_is_replaced_as_the_server_starts(
    tmp_path, server_secrets, monkeypatch,
):
    """The server used to refuse to start on it, so the next auto-deploy could leave
    the estate's app down until someone reached Db01 (R5BE-1). It starts, on a fresh
    one, and the saved camera logins still read."""
    from app.core import crypto, startup

    env = tmp_path / ".env"
    env.write_text("# the server's settings\nADMIN_EMAIL=admin@gamesense.local\n")
    # No JWT_SECRET line: the server runs on the code's own default, a published one.
    server_secrets(jwt_secret="dev-secret-change-me")
    saved = crypto.encrypt("guest-spypoint-password")

    note = startup.replace_published_secret(env)
    assert "was the one published with GameSense" in note
    assert "Everyone signs in again once; saved camera logins keep working" in note
    values = _env_values(env)
    assert values["PREVIOUS_JWT_SECRET"] == "dev-secret-change-me"
    assert len(values["JWT_SECRET"]) >= 48 and len(values["CREDENTIALS_KEY"]) >= 48
    assert env.read_text().startswith("# the server's settings\nADMIN_EMAIL=")
    # This process runs on the new one from here on, and reads the saved login.
    assert settings.jwt_secret == values["JWT_SECRET"]
    assert crypto.decrypt(saved) == "guest-spypoint-password"
    assert startup.replace_published_secret(env) is None  # nothing left to do

    # A short one of the owner's own is replaced too.
    server_secrets(jwt_secret="short-but-not-published")
    assert "shorter than 32" in startup.replace_published_secret(env)
    # The service's environment holding a published one over a good one in the file:
    # the file's is used, and nothing is rotated again (no sign-out at every start).
    good = _env_values(env)["JWT_SECRET"]
    server_secrets(jwt_secret="dev-secret-change-me")
    assert "is used instead" in startup.replace_published_secret(env)
    assert settings.jwt_secret == good == _env_values(env)["JWT_SECRET"]
    # On a laptop nothing is touched.
    server_secrets(jwt_secret="dev-secret-change-me")
    monkeypatch.setattr(settings, "app_env", "development")
    assert startup.replace_published_secret(env) is None
    assert settings.jwt_secret == "dev-secret-change-me"


def test_a_secret_that_cant_be_written_is_said_and_the_server_starts_anyway(
    tmp_path, server_secrets,
):
    from app.core import startup

    server_secrets(jwt_secret="dev-secret-change-me")
    blocked = tmp_path / "no-such-folder" / ".env"
    note = startup.replace_published_secret(blocked)
    assert "couldn't be written" in note and "python -m app.manage new-secret" in note
    assert settings.jwt_secret == "dev-secret-change-me"


@requires_db
def test_an_admin_on_the_published_password_is_named_and_cant_sign_in_from_the_internet(
    client, db_session, estate, monkeypatch,
):
    from app.core import startup

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "admin_password", "changeme")
    # No admin yet: the seed would make one with the published password.
    [why] = startup.password_notes(db_session)
    assert "ADMIN_PASSWORD" in why and "server's own network" in why
    _user(db_session, estate, "admin", email="admin@gamesense.local", password="changeme")
    _user(db_session, estate, "member", email="m@estate.local", password="changeme")
    [why] = startup.password_notes(db_session)
    assert why.endswith("python -m app.manage set-password admin@gamesense.local")

    monkeypatch.setattr(settings, "trusted_proxies", ["testclient"])

    def sign_in(email, **headers):
        return client.post("/api/auth/login", headers=headers,
                           json={"email": email, "password": "changeme"})

    # Through the tunnel: refused, in words that say where it does work.
    far = sign_in("admin@gamesense.local", **{"CF-Connecting-IP": "203.0.113.9"})
    assert far.status_code == 403
    assert "can't sign in from the internet" in far.json()["detail"]
    assert "set-password admin@gamesense.local" in far.json()["detail"]
    # On the server's own network it signs in, so it can be changed there.
    assert sign_in("admin@gamesense.local").status_code == 200
    # Only admins; and on a laptop, anyone.
    assert sign_in("m@estate.local", **{"CF-Connecting-IP": "203.0.113.9"}).status_code == 200
    monkeypatch.setattr(settings, "app_env", "development")
    laptop = sign_in("admin@gamesense.local", **{"CF-Connecting-IP": "203.0.113.8"})
    assert laptop.status_code == 200
    assert startup.password_notes(db_session) == []

    monkeypatch.setattr(settings, "app_env", "production")
    admin = db_session.scalar(select(User).where(User.email == "admin@gamesense.local"))
    admin.password_hash = hash_password(PASSWORD)
    db_session.commit()
    assert startup.password_notes(db_session) == []


def _serve_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("serve_under_test", BACKEND / "serve.py")
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    return serve


def test_serve_py_check_changes_nothing_and_says_what_starting_will_do(tmp_path):
    """What deploy/update.ps1 asks before it deploys: the real entrypoint, as the
    Windows service would run it, beside a .env of its own."""
    (tmp_path / "serve.py").write_text((BACKEND / "serve.py").read_text())
    env_text = "JWT_SECRET=dev-secret-change-me-please\nADMIN_PASSWORD=changeme\n"
    (tmp_path / ".env").write_text(env_text)
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(BACKEND),
           "DATABASE_URL": "postgresql+psycopg://nobody@127.0.0.1:1/none"}
    run = subprocess.run([sys.executable, str(tmp_path / "serve.py"), "check"], cwd=tmp_path,
                         env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "GameSense writes a fresh one when it restarts" in run.stdout
    assert "Could not check the admin passwords" in run.stdout
    assert (tmp_path / ".env").read_text() == env_text


def test_serve_py_check_fails_when_the_app_does_not_load(monkeypatch):
    import app.main  # noqa: F401  (loaded, as by the service, before check looks)

    serve = _serve_module()
    monkeypatch.setattr(serve, "prepare", lambda dry_run: [])
    assert serve.check() == 0
    monkeypatch.setitem(sys.modules, "app.main", None)  # any import error
    assert serve.check() == 1


def test_serve_py_starts_on_a_fresh_secret_it_wrote_itself(tmp_path, server_secrets, monkeypatch):
    from app.core import crypto
    from app.core import db as core_db

    serve = _serve_module()
    env = tmp_path / ".env"
    env.write_text("JWT_SECRET=dev-secret-change-me-please\n")
    monkeypatch.setattr(serve, "ENV_FILE", env)
    server_secrets(jwt_secret="dev-secret-change-me-please")
    saved = crypto.encrypt("guest-ubox-password")

    def no_database():
        raise OSError("no database here")
    monkeypatch.setattr(core_db, "SessionLocal", no_database)
    notes = serve.prepare()
    assert "a fresh one was written" in notes[0]
    assert settings.jwt_secret == _env_values(env)["JWT_SECRET"]
    assert crypto.decrypt(saved) == "guest-ubox-password"


def test_the_update_checks_the_new_version_before_it_changes_anything():
    """deploy/update.ps1: serve.py check runs before the build, the backup, the
    migration and the restart, and a version that doesn't load is rolled back."""
    script = (BACKEND.parent / "deploy" / "update.ps1").read_text()
    check = script.index('serve.py" check')
    # The steps themselves, not the helper functions defined above them.
    for later in ("vite.js", "Find-PgTool 'pg_dump'", "alembic.exe\" upgrade",
                  "\nRestart-GameSense\n"):
        assert check < script.index(later), later
    after = script[check:script.index("vite.js")]
    assert "Fail 'check'" in after
    fail = script[script.index("function Fail("):]
    assert "git reset --hard $good" in fail[:fail.index("exit 1")]


def test_new_secret_keeps_the_saved_camera_logins_readable(tmp_path, server_secrets):
    from app import manage
    from app.core import crypto

    def restart_on(env):
        values = _env_values(env)
        server_secrets(**{k: values.get(k.upper(), "")
                          for k in ("jwt_secret", "credentials_key", "previous_jwt_secret")})

    # 1. The file names the published secret; nothing else set.
    env = tmp_path / ".env"
    env.write_text("# the server's settings\nJWT_SECRET=dev-secret-change-me-please\n"
                   "CREDENTIALS_KEY=\nADMIN_EMAIL=admin@gamesense.local\n", encoding="utf-8")
    restart_on(env)
    first = crypto.encrypt("guest-spypoint-password")
    assert "Restart the GameSense service" in manage.new_secret(env)
    values = _env_values(env)
    assert values["PREVIOUS_JWT_SECRET"] == "dev-secret-change-me-please"
    assert values["ADMIN_EMAIL"] == "admin@gamesense.local"
    restart_on(env)
    assert crypto.decrypt(first) == "guest-spypoint-password"

    # 2. No JWT_SECRET line at all: the server ran on the code's default (R5BE-4).
    bare = tmp_path / "bare.env"
    bare.write_text("ADMIN_PASSWORD=something-else\n")
    server_secrets(jwt_secret="dev-secret-change-me")
    on_default = crypto.encrypt("guest-password")
    manage.new_secret(bare)
    assert _env_values(bare)["PREVIOUS_JWT_SECRET"] == "dev-secret-change-me"
    restart_on(bare)
    assert crypto.decrypt(on_default) == "guest-password"

    # 3. CREDENTIALS_KEY already set, but a login not saved again under it yet: the
    #    old JWT_SECRET is kept too, and so is every secret kept before it.
    env.write_text(f"JWT_SECRET={'j' * 40}\nCREDENTIALS_KEY={'c' * 40}\n"
                   f"PREVIOUS_JWT_SECRET={'p' * 40}\n")
    server_secrets(jwt_secret="j" * 40, previous_jwt_secret="p" * 40)  # before the key was set
    under_jwt = crypto.encrypt("saved-before-the-key")
    server_secrets(jwt_secret="p" * 40)
    under_older = crypto.encrypt("saved-long-ago")
    restart_on(env)
    under_key = crypto.encrypt("saved-under-the-key")
    manage.new_secret(env)
    values = _env_values(env)
    assert values["CREDENTIALS_KEY"] == "c" * 40
    assert values["PREVIOUS_JWT_SECRET"] == f"{'j' * 40},{'p' * 40}"
    restart_on(env)
    for token, plain in ((under_jwt, "saved-before-the-key"), (under_older, "saved-long-ago"),
                         (under_key, "saved-under-the-key")):
        assert crypto.decrypt(token) == plain
    # And once more: the list grows, newest first, and keeps them all.
    manage.new_secret(env)
    assert _env_values(env)["PREVIOUS_JWT_SECRET"].split(",")[1:] == ["j" * 40, "p" * 40]


def test_new_secret_refuses_when_the_environment_would_win_over_the_file(
    tmp_path, monkeypatch, capsys,
):
    from app import manage

    env = tmp_path / ".env"
    env.write_text("JWT_SECRET=dev-secret-change-me-please\n")
    monkeypatch.setattr(manage, "ENV_FILE", env)
    monkeypatch.setenv("JWT_SECRET", "set-for-the-whole-machine")
    assert manage.main(["new-secret"]) == 1
    assert "wins over" in capsys.readouterr().out
    assert env.read_text() == "JWT_SECRET=dev-secret-change-me-please\n"
    monkeypatch.delenv("JWT_SECRET")
    for key in ("CREDENTIALS_KEY", "PREVIOUS_JWT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    assert manage.main(["new-secret"]) == 0
    assert _env_values(env)["PREVIOUS_JWT_SECRET"] == "dev-secret-change-me-please"


@requires_db
def test_set_password_signs_the_person_in_with_it_and_out_everywhere_else(
    client, db_session, estate, monkeypatch,
):
    from app import manage
    from app.core import db as core_db

    monkeypatch.setattr(core_db, "SessionLocal", core_db.server_sessions(db_session.get_bind()))
    user, old_h = _user(db_session, estate, "admin", email="Admin@GameSense.local",
                        password="changeme")
    with pytest.raises(SystemExit):
        manage.set_password("admin@gamesense.local", "changeme")
    with pytest.raises(SystemExit):
        manage.set_password("nobody@x.es", "a-fine-password")
    _subscribe(db_session, user, "https://fcm.googleapis.com/fcm/send/lost")
    assert "Admin@GameSense.local" in manage.set_password("admin@gamesense.local",
                                                          "a-fine-password")
    assert _endpoints(db_session, user) == set()  # the lost phone's alerts stop too
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


@requires_db
def test_a_tunnel_on_the_lan_address_is_warned_about_and_never_lets_the_published_password_in(
    client, db_session, estate, monkeypatch, capsys,
):
    """cloudflared pointed at http://db01:8090 reaches the API from the LAN: every
    visitor looked local, and the published admin password signed in from anywhere
    (final review SEC-5). Now it is refused and the log says what to change."""
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "trusted_proxies", ["127.0.0.1"])
    monkeypatch.setattr(throttle_mod, "_warned", set())
    _user(db_session, estate, "admin", email="admin@gamesense.local", password="changeme")
    lan = SimpleNamespace(host="192.168.1.10", port=50000)
    monkeypatch.setattr("starlette.requests.Request.client", property(lambda self: lan))
    r = client.post("/api/auth/login", headers={"CF-Connecting-IP": "203.0.113.9"},
                    json={"email": "admin@gamesense.local", "password": "changeme"})
    assert r.status_code == 403
    said = capsys.readouterr().out
    assert "throttle.untrusted_tunnel" in said and "TRUSTED_PROXIES" in said
