"""The app never goes blank without anyone knowing, and never gets the shell for an API call.

Two halves of plan item 1 live on the server. A phone that crashes posts what broke
to /api/client-errors: it always reaches the server log, a signed-in phone's report
is kept (the newest few hundred) for an admin to read in Settings, and a phone
stuck in a crash loop is cut off after a handful. And the built app is served so an
installed phone cannot end up holding an index.html whose bundle a deploy deleted:
the shell is always re-checked, hashed assets are kept for good, and an unknown
/api path is a JSON 404 instead of the app's HTML.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_client_errors
from app.core.security import create_access_token
from app.frontend import FOREVER, FRESH, mount_frontend
from app.models import Camera, ClientError, Detection, Estate, Image, Species, User

from .conftest import requires_db

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15"


@pytest.fixture(autouse=True)
def _fresh_limits():
    routes_client_errors._reset_limits()
    yield
    routes_client_errors._reset_limits()


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
    e = Estate(name="Piedras Lisas", timezone="Europe/Madrid")
    db_session.add(e)
    db_session.flush()
    out = {}
    for role, email in (("admin", "owner@estate.local"), ("member", "pedro.garcia@estate.local"),
                        ("viewer", "ana@estate.local")):
        u = User(estate_id=e.id, email=email, password_hash="x", role=role)
        db_session.add(u)
        db_session.flush()
        out[role] = u
    db_session.commit()
    return out


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), {'role': user.role})}"}


def _report(**over) -> dict:
    return {"kind": "chunk", "message": "Failed to fetch dynamically imported module",
            "stack": "TypeError: Failed to fetch\n    at Map", "route": "/map", "build": "b1",
            **over}


# ── reporting ───────────────────────────────────────────────────────────────


@requires_db
def test_a_signed_in_phone_report_is_logged_kept_and_listed_for_admins(client, people, capsys):
    r = client.post("/api/client-errors", json=_report(),
                    headers={**_auth(people["member"]), "User-Agent": IPHONE})
    assert r.status_code == 202 and r.json() == {"status": "saved"}

    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines()
              if '"client_error"' in line]
    assert logged and logged[-1]["route"] == "/map" and logged[-1]["device"] == "iPhone"
    assert logged[-1]["user"] == str(people["member"].id)

    listed = client.get("/api/client-errors", headers=_auth(people["admin"])).json()
    assert len(listed) == 1
    row = listed[0]
    assert row["who"] == "Pedro" and row["device"] == "iPhone" and row["kind"] == "chunk"
    assert row["route"] == "/map" and row["build"] == "b1" and row["stack"].startswith("TypeError")
    assert row["message"] == "Failed to fetch dynamically imported module"


@requires_db
def test_viewers_report_too_but_only_admins_read_the_list(client, people):
    assert client.post("/api/client-errors", json=_report(),
                       headers=_auth(people["viewer"])).status_code == 202
    assert client.get("/api/client-errors", headers=_auth(people["member"])).status_code == 403
    assert client.get("/api/client-errors", headers=_auth(people["viewer"])).status_code == 403
    assert client.get("/api/client-errors").status_code in (401, 403)


@requires_db
def test_a_report_without_a_good_token_is_logged_but_not_kept(client, people, db_session, capsys):
    """The login screen can break too. And a phone with an expired token is not told
    to sign in by its own crash report."""
    for headers in ({}, {"Authorization": "Bearer not-a-token"}):
        r = client.post("/api/client-errors", json=_report(route="/login"), headers=headers)
        assert r.status_code == 202 and r.json() == {"status": "logged"}
    assert capsys.readouterr().out.count('"client_error"') == 2
    assert db_session.query(ClientError).count() == 0


@requires_db
def test_long_fields_are_cut_to_fit_and_an_unknown_kind_is_an_error(client, people, db_session):
    r = client.post("/api/client-errors", headers=_auth(people["member"]), json=_report(
        kind="<script>", message="m" * 900, stack="s" * 9000, route="/" + "r" * 400,
        build="b" * 90))
    assert r.status_code == 202
    e = db_session.query(ClientError).one()
    assert e.kind == "error"
    assert len(e.message) == 500 and len(e.stack) == 4000
    assert len(e.route) == 200 and len(e.build) == 64


@requires_db
def test_an_oversized_body_is_refused_before_it_is_read_whole(client, people, db_session):
    body = json.dumps(_report(stack="x" * 20_000))
    r = client.post("/api/client-errors", content=body,
                    headers={**_auth(people["member"]), "Content-Type": "application/json"})
    assert r.status_code == 413

    # No length to go by: a chunked upload is cut off as it streams in.
    streamed = []

    def chunks():
        for _ in range(64):
            streamed.append(1)
            yield b"x" * 1024

    r = client.post("/api/client-errors", content=chunks(),
                    headers={**_auth(people["member"]), "Content-Type": "application/json"})
    assert r.status_code == 413
    assert db_session.query(ClientError).count() == 0


@requires_db
def test_a_body_that_is_not_a_report_is_refused_in_words(client, people):
    for body in (b"not json", b'{"kind": "error"}', b"[]"):
        r = client.post("/api/client-errors", content=body,
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 422 and r.json()["detail"] == "That isn't a crash report."


@requires_db
def test_a_crash_loop_is_cut_off_per_person_and_strangers_share_a_limit(client, people, db_session):
    member, viewer = _auth(people["member"]), _auth(people["viewer"])
    codes = [client.post("/api/client-errors", json=_report(), headers=member).status_code
             for _ in range(routes_client_errors.PER_PERSON + 2)]
    assert codes.count(202) == routes_client_errors.PER_PERSON and codes[-1] == 429
    # Somebody else's phone is not cut off by Pedro's.
    assert client.post("/api/client-errors", json=_report(), headers=viewer).status_code == 202
    anon = [client.post("/api/client-errors", json=_report()).status_code
            for _ in range(routes_client_errors.ANONYMOUS + 1)]
    assert anon[-1] == 429 and anon.count(202) == routes_client_errors.ANONYMOUS
    assert db_session.query(ClientError).count() == routes_client_errors.PER_PERSON + 1


def test_the_window_slides():
    allow = routes_client_errors._allow
    assert all(allow("k", 2, now=t) for t in (0.0, 1.0))
    assert not allow("k", 2, now=2.0)
    assert allow("k", 2, now=routes_client_errors.WINDOW_S + 1.5)


@requires_db
def test_only_the_newest_reports_are_kept(client, people, db_session, monkeypatch):
    monkeypatch.setattr(routes_client_errors, "KEEP", 3)
    for i in range(5):
        client.post("/api/client-errors", json=_report(message=f"crash {i}"),
                    headers=_auth(people["member"] if i % 2 else people["admin"]))
    kept = [r["message"] for r in client.get("/api/client-errors",
                                              headers=_auth(people["admin"])).json()]
    assert kept == ["crash 4", "crash 3", "crash 2"]


@requires_db
def test_a_removed_persons_reports_stay_without_a_name(client, people, db_session):
    client.post("/api/client-errors", json=_report(), headers=_auth(people["member"]))
    db_session.delete(db_session.get(User, people["member"].id))
    db_session.commit()
    rows = client.get("/api/client-errors", headers=_auth(people["admin"])).json()
    assert [r["who"] for r in rows] == ["Removed person"]


@requires_db
def test_a_report_that_waited_for_signal_says_when_it_happened(client, people):
    """A crash in the valley is posted hours later, when the phone finds signal. The
    list says when it happened (and sorts by that), not when it arrived; a phone
    whose clock is far out, or that sends nonsense, keeps the arrival time."""
    now = datetime.now(UTC)
    member = _auth(people["member"])
    waited = (now - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    for over in ({"message": "in the valley", "at": waited},
                 {"message": "just now"},
                 {"message": "clock in 2001", "at": "2001-01-01T00:00:00Z"},
                 {"message": "clock a day ahead", "at": (now + timedelta(days=1)).isoformat()},
                 {"message": "no zone", "at": "2026-09-27T21:40:00"},
                 {"message": "nonsense", "at": "yesterday"}):
        r = client.post("/api/client-errors", json=_report(**over), headers=member)
        assert r.status_code == 202
    rows = client.get("/api/client-errors", headers=_auth(people["admin"])).json()
    assert rows[-1]["message"] == "in the valley"
    by = {r["message"]: r for r in rows}
    valley = by["in the valley"]
    happened = datetime.fromisoformat(valley["at"])
    assert abs(happened - (now - timedelta(hours=3))) < timedelta(seconds=1)
    assert datetime.fromisoformat(valley["reported_at"]) >= now - timedelta(minutes=1)
    for m in ("just now", "clock in 2001", "clock a day ahead", "no zone", "nonsense"):
        assert by[m]["at"] == by[m]["reported_at"], m


def test_the_phones_time_is_believed_only_when_it_is_believable():
    now = datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    happened_at = routes_client_errors.happened_at
    assert happened_at(now - timedelta(days=2), now) == now - timedelta(days=2)
    assert happened_at(now + timedelta(minutes=5), now) == now  # a few minutes fast
    assert happened_at(now + timedelta(hours=1), now) is None
    assert happened_at(now - timedelta(days=31), now) is None
    assert happened_at(None, now) is None


def test_device_names():
    assert routes_client_errors.device_of(IPHONE) == "iPhone"
    assert routes_client_errors.device_of("Mozilla/5.0 (Linux; Android 14; Pixel 8)") == "Android"
    assert routes_client_errors.device_of(None) == "Unknown device"


# ── serving the built app ───────────────────────────────────────────────────


@pytest.fixture
def shell(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "sw.js").write_text("// worker")
    (dist / "manifest.webmanifest").write_text("{}")
    (dist / "icon-192.png").write_bytes(b"\x89PNG")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("PRIVATE")
    app = FastAPI()

    @app.get("/api/real")
    def real():
        return {"ok": True}

    mount_frontend(app, str(dist))
    return TestClient(app)


def test_an_unknown_api_path_is_a_json_404_not_the_app(shell):
    """An old screen calling an endpoint that moved gets "not found", not
    "Unexpected token '<'" (audit D-18, H-05)."""
    for path in ("/api/forecast/tonite", "/api/stands/x/extra/x", "/api"):
        r = shell.get(path)
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/json")
        assert r.json() == {"detail": "Not Found"}
    assert shell.get("/api/real").json() == {"ok": True}


def test_the_shell_is_always_rechecked_and_hashed_assets_kept_for_good(shell):
    for path in ("/", "/stands", "/photos?image=abc", "/index.html", "/sw.js",
                 "/manifest.webmanifest"):
        r = shell.get(path)
        assert r.status_code == 200, path
        assert r.headers["cache-control"] == FRESH, path
    assert "root" in shell.get("/map").text
    js = shell.get("/assets/index-abc123.js")
    assert js.status_code == 200 and js.headers["cache-control"] == FOREVER
    # A chunk a deploy deleted is a plain 404, never the shell and never cached.
    gone = shell.get("/assets/Map-old999.js")
    assert gone.status_code == 404 and "cache-control" not in gone.headers
    assert "cache-control" not in shell.get("/icon-192.png").headers


def test_the_shell_never_walks_out_of_the_dist_folder(shell):
    for path in ("/..%2fsecret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt"):
        r = shell.get(path)
        assert "PRIVATE" not in r.text, path


def test_no_dist_means_no_shell():
    app = FastAPI()
    mount_frontend(app, "")
    mount_frontend(app, "/does/not/exist")
    assert TestClient(app).get("/").status_code == 404


# ── Tonight's numbers in one pass ───────────────────────────────────────────


@requires_db
def test_overview_counts_every_visible_photo_once_by_hour_and_camera(client, people, db_session):
    """The overview now reads the animal photos once and sums them (audit G-19); the
    totals must still agree with each other and leave out hidden species and empties."""
    estate_id = people["admin"].estate_id
    db_session.add_all([
        Species(id="wild_boar", common_name="Wild Boar"),
        Species(id="lagomorph", common_name="Rabbit", hidden=True),
    ])
    a = Camera(estate_id=estate_id, name="Charca")
    b = Camera(estate_id=estate_id, name="Solana")
    db_session.add_all([a, b])
    db_session.flush()
    base = datetime(2026, 9, 20, 20, 0, tzinfo=UTC)  # 22:00 in Madrid

    def photo(cam, hours, species=None, empty=False):
        im = Image(id=uuid.uuid4(), camera_id=cam.id, captured_at=base + timedelta(hours=hours),
                   is_empty_frame=empty)
        db_session.add(im)
        db_session.flush()
        if species:
            db_session.add(Detection(image_id=im.id, species_id=species))

    photo(a, 0, "wild_boar")
    photo(a, 0, "wild_boar")
    photo(a, 2, "wild_boar")
    photo(b, 0, "wild_boar")
    photo(b, 1, "lagomorph")  # hidden: never counted
    photo(b, 1, empty=True)  # nothing in it
    db_session.commit()

    d = client.get("/api/analytics/overview", headers=_auth(people["member"])).json()
    assert d["totals"]["sightings"] == 4
    assert d["totals"]["empty"] == 1
    assert sum(h["count"] for h in d["by_hour"]) == 4
    assert {h["hour"]: h["count"] for h in d["by_hour"] if h["count"]} == {22: 3, 0: 1}
    assert [{k: c[k] for k in ("name", "sightings")} for c in d["by_camera"]] == [
        {"name": "Charca", "sightings": 3}, {"name": "Solana", "sightings": 1},
    ]
    assert d["totals"]["cameras"] == 2
