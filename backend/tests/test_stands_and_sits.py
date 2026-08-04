"""Stand and claim-register tests.

The claim is the app's data-capture mechanism, so the behaviours pinned here are
the ones that decide whether the register is trustworthy: no double-booking, no
putting two hunters in each other's fire lanes, and never confusing "I saw
nothing" with "I never said".
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Estate, Sit, Stand, User

from .conftest import requires_db


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
    e = Estate(name="E", timezone="Europe/Madrid", lat=39.0, lon=-1.3)
    db_session.add(e)
    db_session.commit()
    return e


def _user(db, estate, email, role="admin"):
    from app.core.security import create_access_token, hash_password

    u = User(estate_id=estate.id, email=email, password_hash=hash_password("x" * 12), role=role)
    db.add(u)
    db.commit()
    return u, {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


@pytest.fixture
def admin(db_session, estate):
    return _user(db_session, estate, "admin@estate.local")


@pytest.fixture(autouse=True)
def _offline_weather(monkeypatch):
    """Claiming records the wind verdict; don't hit a weather API in tests."""
    import app.forecasting.model as model

    monkeypatch.setattr(
        model, "_tonight_conditions",
        lambda now: {"wind_dir_deg": 180, "wind_speed_kmh": 15.0},
    )


def _stand(client, headers, name, **kw):
    r = client.post("/api/stands", json={"name": name, **kw}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


@requires_db
def test_a_stand_records_its_geometry(client, admin):
    _, headers = admin
    s = _stand(client, headers, "Puente", shooting_dirs_deg=[90], approach_dirs_deg=[0])
    assert s["has_geometry"] is True
    assert s["approach_dirs_deg"] == [0]


@requires_db
def test_a_stand_without_arcs_is_flagged_not_assumed(client, admin):
    _, headers = admin
    s = _stand(client, headers, "Solana")
    assert s["has_geometry"] is False


@requires_db
def test_claiming_is_idempotent_for_the_same_person(client, admin):
    _, headers = admin
    s = _stand(client, headers, "Puente")
    first = client.post("/api/sits", json={"stand_id": s["id"]}, headers=headers)
    second = client.post("/api/sits", json={"stand_id": s["id"]}, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"], "re-claiming must not create a second sit"


@requires_db
def test_two_people_cannot_claim_the_same_stand(client, admin, db_session, estate):
    _, headers = admin
    _, guest_headers = _user(db_session, estate, "guest@estate.local", role="member")
    s = _stand(client, headers, "Puente")

    assert client.post("/api/sits", json={"stand_id": s["id"]}, headers=headers).status_code == 201
    clash = client.post("/api/sits", json={"stand_id": s["id"]}, headers=guest_headers)
    assert clash.status_code == 409
    assert "already claimed" in clash.json()["detail"]


@requires_db
def test_overlapping_fire_lanes_are_refused(client, admin, db_session, estate):
    """The safety interlock — two hunters must not end up shooting at each other."""
    _, headers = admin
    _, guest_headers = _user(db_session, estate, "guest2@estate.local", role="member")
    a = _stand(client, headers, "Ridge", shooting_dirs_deg=[90])
    b = _stand(client, headers, "Barranco", shooting_dirs_deg=[100])  # 10 deg apart

    assert client.post("/api/sits", json={"stand_id": a["id"]}, headers=headers).status_code == 201
    clash = client.post("/api/sits", json={"stand_id": b["id"]}, headers=guest_headers)
    assert clash.status_code == 409
    assert "shooting arc" in clash.json()["detail"]


@requires_db
def test_missing_shooting_arcs_do_not_block_a_claim(client, admin, db_session, estate):
    """Absent geometry has no information; it must not manufacture a refusal."""
    _, headers = admin
    _, guest_headers = _user(db_session, estate, "guest3@estate.local", role="member")
    a = _stand(client, headers, "Ridge")       # no arcs
    b = _stand(client, headers, "Barranco")    # no arcs

    assert client.post("/api/sits", json={"stand_id": a["id"]}, headers=headers).status_code == 201
    ok = client.post("/api/sits", json={"stand_id": b["id"]}, headers=guest_headers)
    assert ok.status_code == 201


@requires_db
def test_the_wind_verdict_is_recorded_at_claim_time(client, admin):
    """Kept verbatim so the advice can be scored later, not quietly rewritten."""
    _, headers = admin
    s = _stand(client, headers, "Puente", approach_dirs_deg=[0])
    sit = client.post("/api/sits", json={"stand_id": s["id"]}, headers=headers).json()
    # Southerly 15 km/h into a northerly approach: scent carries.
    assert sit["wind_status"] == "scent_carries"
    assert "Puente" in sit["wind_text"]


@requires_db
def test_an_unreported_sit_is_not_a_blank_sit(client, admin, db_session):
    """Conflating 'saw nothing' with 'never said' would poison the ground truth."""
    _, headers = admin
    s = _stand(client, headers, "Puente")
    sit = client.post("/api/sits", json={"stand_id": s["id"]}, headers=headers).json()
    assert sit["outcome"] == "unreported"

    row = db_session.scalar(select(Sit))
    assert row.outcome == "unreported"
    assert row.outcome != "nothing"


@requires_db
def test_reporting_an_outcome_closes_the_sit(client, admin):
    _, headers = admin
    s = _stand(client, headers, "Puente")
    sit = client.post("/api/sits", json={"stand_id": s["id"]}, headers=headers).json()

    started = client.post(f"/api/sits/{sit['id']}/start", headers=headers)
    assert started.status_code == 200 and started.json()["started_at"]

    done = client.patch(
        f"/api/sits/{sit['id']}",
        json={"outcome": "seen", "species_seen": "wild_boar"},
        headers=headers,
    )
    assert done.status_code == 200
    assert done.json()["outcome"] == "seen"
    assert done.json()["ended_at"] is not None


@requires_db
def test_you_cannot_report_on_someone_elses_sit(client, admin, db_session, estate):
    _, headers = admin
    _, guest_headers = _user(db_session, estate, "guest4@estate.local", role="member")
    s = _stand(client, headers, "Puente")
    sit = client.post("/api/sits", json={"stand_id": s["id"]}, headers=guest_headers).json()

    # A different member must not overwrite it...
    _, other_headers = _user(db_session, estate, "guest5@estate.local", role="member")
    r = client.patch(f"/api/sits/{sit['id']}", json={"outcome": "shot"}, headers=other_headers)
    assert r.status_code == 403
    # ...but an admin can, for the estate record.
    r2 = client.patch(f"/api/sits/{sit['id']}", json={"outcome": "shot"}, headers=headers)
    assert r2.status_code == 200


@requires_db
def test_a_stand_with_history_cannot_be_deleted(client, admin):
    _, headers = admin
    s = _stand(client, headers, "Puente")
    client.post("/api/sits", json={"stand_id": s["id"]}, headers=headers)

    r = client.delete(f"/api/stands/{s['id']}", headers=headers)
    assert r.status_code == 409
    assert "history" in r.json()["detail"]


@requires_db
def test_invalid_outcome_is_rejected(client, admin):
    _, headers = admin
    s = _stand(client, headers, "Puente")
    sit = client.post("/api/sits", json={"stand_id": s["id"]}, headers=headers).json()
    r = client.patch(f"/api/sits/{sit['id']}", json={"outcome": "maybe"}, headers=headers)
    assert r.status_code == 422


# ── bootstrap ───────────────────────────────────────────────────────────────


@requires_db
def test_bootstrap_creates_one_stand_per_camera_without_guessing_arcs(client, admin, db_session):
    """A guessed arc becomes confident wind advice — the exact thing wind refuses to do.

    So bootstrap copies positions, which are a fact, and leaves approach bearings
    unset, which are not.
    """
    from app.models import Camera

    e = db_session.scalar(select(Estate))
    db_session.add_all([
        Camera(estate_id=e.id, name="Ridge", lat=39.10, lon=-1.36),
        Camera(estate_id=e.id, name="Vineyard", lat=39.11, lon=-1.35),
    ])
    db_session.commit()
    _, headers = admin

    r = client.post("/api/stands/bootstrap", headers=headers)
    assert r.status_code == 200, r.text
    assert sorted(r.json()["created"]) == ["Ridge stand", "Vineyard stand"]

    stands = {s.name: s for s in db_session.scalars(select(Stand)).all()}
    assert stands["Ridge stand"].lat == 39.10
    assert stands["Ridge stand"].approach_dirs_deg is None, "arcs must never be guessed"
    assert client.get("/api/stands", headers=headers).json()[0]["has_geometry"] is False


@requires_db
def test_bootstrap_is_idempotent_and_never_touches_an_existing_stand(client, admin, db_session):
    from app.models import Camera

    e = db_session.scalar(select(Estate))
    cam = Camera(estate_id=e.id, name="Ridge", lat=39.10, lon=-1.36)
    db_session.add(cam)
    db_session.commit()
    _, headers = admin

    # A stand the user has already placed and given arcs to.
    mine = _stand(client, headers, "My hide", camera_id=str(cam.id), approach_dirs_deg=[45])

    r = client.post("/api/stands/bootstrap", headers=headers)
    assert r.json()["created"] == [], "a camera that already has a stand is skipped"
    assert db_session.query(Stand).count() == 1

    again = client.get("/api/stands", headers=headers).json()
    assert again[0]["name"] == "My hide" and again[0]["approach_dirs_deg"] == [45]
    assert again[0]["id"] == mine["id"]


@requires_db
def test_bootstrap_is_admin_only(client, db_session, estate):
    _, viewer = _user(db_session, estate, "viewer@estate.local", role="viewer")
    assert client.post("/api/stands/bootstrap", headers=viewer).status_code == 403
