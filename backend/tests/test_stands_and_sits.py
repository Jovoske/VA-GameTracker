"""Stand and claim-register tests.

The claim is the app's data-capture mechanism, so the behaviours pinned here are
the ones that decide whether the register is trustworthy: no double-booking, no
putting two hunters in each other's fire lanes, and never confusing "I saw
nothing" with "I never said".
"""
from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import Estate, Sit, Stand, User

from .conftest import requires_db


def _ago(**kw) -> str:
    """A tap time, `kw` before now, as the phone sends it."""
    return (datetime.now(UTC) - timedelta(**kw)).isoformat()


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
def test_reporting_does_not_end_the_sit_end_sit_does(client, admin):
    """Seeing animals at 20:15 does not end the sit (audit A-06, J-03): the hunter
    must still be able to get back in and report the shot at 21:30."""
    _, headers = admin
    s = _stand(client, headers, "Puente")
    sit = client.post("/api/sits", json={"stand_id": s["id"]}, headers=headers).json()

    started = client.post(f"/api/sits/{sit['id']}/start", headers=headers)
    assert started.status_code == 200 and started.json()["started_at"]

    seen = client.patch(
        f"/api/sits/{sit['id']}",
        json={"outcome": "seen", "species_seen": "wild_boar"},
        headers=headers,
    )
    assert seen.status_code == 200
    assert seen.json()["outcome"] == "seen"
    assert seen.json()["ended_at"] is None, "a report is not END SIT"

    at = _ago(minutes=5)
    ended = client.post(f"/api/sits/{sit['id']}/end", json={"at": at}, headers=headers)
    assert ended.status_code == 200
    assert ended.json()["ended_at"] is not None
    assert ended.json()["outcome"] == "seen", "ending leaves the report alone"

    # Idempotent: a replayed END SIT keeps the first end.
    again = client.post(f"/api/sits/{sit['id']}/end", headers=headers)
    assert again.json()["ended_at"] == ended.json()["ended_at"]


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


# ── sit reports that are never lost or overwritten (plan item 2) ───────────


def _started_sit(client, headers, name="Puente"):
    s = _stand(client, headers, name)
    sit = client.post("/api/sits", json={"stand_id": s["id"]}, headers=headers).json()
    assert client.post(f"/api/sits/{sit['id']}/start", headers=headers).status_code == 200
    return sit


def _report(client, headers, sit_id, outcome, **kw):
    r = client.patch(f"/api/sits/{sit_id}", json={"outcome": outcome, **kw}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


@requires_db
def test_a_later_lower_tap_never_lowers_a_report(client, admin):
    """The whole screen is SAW ANIMALS: a glove brushing it after SHOT must not
    turn the shot into a sighting (audit A-01, J-02)."""
    _, headers = admin
    sit = _started_sit(client, headers)
    assert _report(client, headers, sit["id"], "seen")["outcome"] == "seen"
    assert _report(client, headers, sit["id"], "shot")["outcome"] == "shot"
    assert _report(client, headers, sit["id"], "seen")["outcome"] == "shot"
    assert _report(client, headers, sit["id"], "nothing")["outcome"] == "shot"
    # Clearing a report is a correction too, never a stray tap.
    assert _report(client, headers, sit["id"], "unreported")["outcome"] == "shot"


@requires_db
def test_an_older_queued_tap_arriving_late_is_ignored(client, admin, db_session):
    """20:10 SAW ANIMALS with no signal, 20:40 SHOT with one bar, then the 20:10 tap
    replays at END SIT: the shot stays, and so does its time (audit I-02)."""
    _, headers = admin
    sit = _started_sit(client, headers)
    shot_at = _ago(minutes=30)
    _report(client, headers, sit["id"], "shot", at=shot_at)
    late = _report(client, headers, sit["id"], "seen", at=_ago(minutes=60))
    assert late["outcome"] == "shot"
    row = db_session.get(Sit, sit["id"])
    db_session.refresh(row)
    assert row.reported_at == datetime.fromisoformat(shot_at)


@requires_db
def test_an_older_higher_tap_still_counts_after_a_lower_one(client, admin):
    """Only a report that counted moves the clock: an ignored lower tap must not make
    the queued, older SHOT look stale when it finally arrives."""
    _, headers = admin
    sit = _started_sit(client, headers)
    _report(client, headers, sit["id"], "seen", at=_ago(minutes=50))
    _report(client, headers, sit["id"], "nothing", at=_ago(minutes=10))  # lower: ignored
    assert _report(client, headers, sit["id"], "shot", at=_ago(minutes=30))["outcome"] == "shot"


@requires_db
def test_a_correction_lowers_it_and_an_older_tap_cannot_undo_it(client, admin):
    _, headers = admin
    sit = _started_sit(client, headers)
    _report(client, headers, sit["id"], "shot", at=_ago(minutes=90))
    fixed = _report(client, headers, sit["id"], "seen", at=_ago(minutes=20), correct=True)
    assert fixed["outcome"] == "seen", "the hunter's own answer on Stands may lower it"
    # The 90-minute-old SHOT, stuck on the phone, arrives now: older than the correction.
    assert _report(client, headers, sit["id"], "shot", at=_ago(minutes=90))["outcome"] == "seen"
    # A new tap after the correction still goes up.
    assert _report(client, headers, sit["id"], "shot", at=_ago(minutes=5))["outcome"] == "shot"


@requires_db
def test_a_phone_clock_running_fast_cannot_lock_out_later_reports(client, admin, db_session):
    _, headers = admin
    sit = _started_sit(client, headers)
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    _report(client, headers, sit["id"], "seen", at=future)
    row = db_session.get(Sit, sit["id"])
    db_session.refresh(row)
    assert row.reported_at <= datetime.now(UTC)
    fixed = _report(client, headers, sit["id"], "nothing", correct=True)
    assert fixed["outcome"] == "nothing"


@requires_db
def test_end_sit_on_an_unreported_sit_keeps_it_unreported(client, admin):
    """A blank sit is never assumed: the phone asks what happened instead."""
    _, headers = admin
    sit = _started_sit(client, headers)
    ended = client.post(f"/api/sits/{sit['id']}/end", headers=headers).json()
    assert ended["outcome"] == "unreported" and ended["ended_at"]
    # The report still goes in after the end (the next-morning card).
    assert _report(client, headers, sit["id"], "nothing", correct=True)["outcome"] == "nothing"


@requires_db
def test_ending_a_sit_that_never_started_or_was_cancelled_is_refused(client, admin):
    _, headers = admin
    s = _stand(client, headers, "Puente")
    sit = client.post("/api/sits", json={"stand_id": s["id"]}, headers=headers).json()
    assert client.post(f"/api/sits/{sit['id']}/end", headers=headers).status_code == 409
    _report(client, headers, sit["id"], "cancelled")
    assert client.post(f"/api/sits/{sit['id']}/end", headers=headers).status_code == 409


@requires_db
def test_a_cancelled_reservation_stays_cancelled(client, admin, db_session, estate):
    """A late write must not bring a cancelled reservation back next to somebody
    else's on the same stand (audit A-23)."""
    _, headers = admin
    _, bob = _user(db_session, estate, "bob@estate.local", role="member")
    s = _stand(client, headers, "Puente")
    sit = client.post("/api/sits", json={"stand_id": s["id"]}, headers=headers).json()
    _report(client, headers, sit["id"], "cancelled")
    assert client.post("/api/sits", json={"stand_id": s["id"]}, headers=bob).status_code == 201

    late = client.patch(f"/api/sits/{sit['id']}", json={"outcome": "seen"}, headers=headers)
    assert late.status_code == 409
    assert client.post(f"/api/sits/{sit['id']}/start", headers=headers).status_code == 409
    assert _report(client, headers, sit["id"], "cancelled")["outcome"] == "cancelled"
    live = db_session.scalars(select(Sit).where(Sit.outcome != "cancelled")).all()
    assert len(live) == 1


@requires_db
def test_a_reported_sit_cannot_be_cancelled(client, admin):
    _, headers = admin
    sit = _started_sit(client, headers)
    _report(client, headers, sit["id"], "seen")
    r = client.patch(f"/api/sits/{sit['id']}", json={"outcome": "cancelled"}, headers=headers)
    assert r.status_code == 409


@requires_db
def test_only_the_hunter_or_an_admin_writes_to_a_sit(client, admin, db_session, estate):
    _, admin_headers = admin
    _, alice = _user(db_session, estate, "alice@estate.local", role="member")
    _, bob = _user(db_session, estate, "bob2@estate.local", role="member")
    _, viewer = _user(db_session, estate, "viewer2@estate.local", role="viewer")
    s = _stand(client, admin_headers, "Puente")
    other = _stand(client, admin_headers, "Solana")
    sit = client.post("/api/sits", json={"stand_id": s["id"]}, headers=alice).json()

    for who in (bob, viewer):
        assert client.post(f"/api/sits/{sit['id']}/start", headers=who).status_code == 403
        assert client.post(f"/api/sits/{sit['id']}/end", headers=who).status_code == 403
        r = client.patch(f"/api/sits/{sit['id']}", json={"outcome": "seen"}, headers=who)
        assert r.status_code == 403
    r = client.post("/api/sits", json={"stand_id": other["id"]}, headers=viewer)
    assert r.status_code == 403, "viewers never write"

    assert client.post(f"/api/sits/{sit['id']}/start", headers=alice).status_code == 200
    assert client.post(f"/api/sits/{sit['id']}/end", headers=admin_headers).status_code == 200


@requires_db
def test_start_keeps_the_first_start_and_takes_the_phone_time(client, admin):
    _, headers = admin
    s = _stand(client, headers, "Puente")
    sit = client.post("/api/sits", json={"stand_id": s["id"]}, headers=headers).json()
    start = f"/api/sits/{sit['id']}/start"
    first = client.post(start, json={"at": _ago(seconds=1)}, headers=headers)
    again = client.post(start, headers=headers)
    assert first.json()["started_at"] == again.json()["started_at"]
    # Never before the reservation, however slow the phone's clock.
    assert first.json()["started_at"] >= sit["claimed_at"]


def _sit_row(db, stand, user, night, **kw):
    row = Sit(stand_id=stand.id, user_id=user.id, night=night, **{"outcome": "unreported", **kw})
    db.add(row)
    db.commit()
    return row


@requires_db
def test_a_sit_still_on_after_six_stays_on_stands(client, admin, db_session, estate):
    """A dawn sit reserved at 05:30 counts toward the evening before; at 06:00 it
    must not vanish, nor its stand show free while the hunter is in it (A-20)."""
    from app.api.routes_stands import tonight

    user, headers = admin
    stand = Stand(estate_id=estate.id, name="Alba")
    gone = Stand(estate_id=estate.id, name="Olvido")
    db_session.add_all([stand, gone])
    db_session.commit()
    last = tonight() - timedelta(days=1)
    now = datetime.now(UTC)
    on = _sit_row(db_session, stand, user, last, started_at=now - timedelta(hours=2))
    # A phone that died mid-sit two nights ago must not hold its stand for good.
    _sit_row(db_session, gone, user, last, started_at=now - timedelta(hours=13))

    sits = client.get("/api/sits", headers=headers).json()
    assert [x["id"] for x in sits] == [str(on.id)]
    stands = {x["name"]: x for x in client.get("/api/stands", headers=headers).json()}
    assert stands["Alba"]["claimed_tonight"] is True
    assert stands["Olvido"]["claimed_tonight"] is False
    # An asked-for night is that night only.
    assert client.get(f"/api/sits?night={tonight().isoformat()}", headers=headers).json() == []


@requires_db
def test_my_sits_asks_about_unreported_sits_and_knows_the_one_on(
    client, admin, db_session, estate
):
    """Unreported sits used to drop off at 06:00 and could never be reported (J-22)."""
    from app.api.routes_stands import tonight

    user, headers = admin
    bob, _ = _user(db_session, estate, "bob3@estate.local", role="member")
    stands = [Stand(estate_id=estate.id, name=f"S{i}") for i in range(8)]
    db_session.add_all(stands)
    db_session.commit()
    night, now = tonight(), datetime.now(UTC)
    last = night - timedelta(days=1)
    unstarted = _sit_row(db_session, stands[0], user, last)
    blank = _sit_row(
        db_session, stands[1], user, last,
        started_at=now - timedelta(hours=14), ended_at=now - timedelta(hours=11),
    )
    _sit_row(db_session, stands[2], user, last, outcome="seen")
    _sit_row(db_session, stands[3], user, last, outcome="cancelled")
    _sit_row(db_session, stands[4], user, night - timedelta(days=5))
    _sit_row(db_session, stands[5], bob, last)
    live = _sit_row(db_session, stands[6], user, night, started_at=now - timedelta(hours=1))
    ended = _sit_row(
        db_session, stands[7], user, night,
        started_at=now - timedelta(hours=1), ended_at=now - timedelta(minutes=5),
    )

    got = client.get("/api/sits/mine", headers=headers).json()
    assert [x["id"] for x in got["live"]] == [str(live.id)]
    assert {x["id"] for x in got["to_report"]} == {str(unstarted.id), str(blank.id), str(ended.id)}
    assert got["to_report"][0]["stand"] and got["to_report"][0]["night"]


# ── two hunters reserving at the same moment ────────────────────────────────


@pytest.fixture
def threaded_client(db_session, fresh_db):
    """A client whose every request gets its own session, as in production, so two
    requests can really run at once."""
    from app.core.db import get_db
    from app.main import app

    eng = create_engine(fresh_db)
    make = sessionmaker(bind=eng)

    def own_session():
        s = make()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = own_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    eng.dispose()


def _at_once(monkeypatch, client, calls):
    """Run `calls` (headers, stand id) together, all held at the weather call until
    every one has reached it: the moment the old code checked, then waited, then wrote."""
    import app.forecasting.model as model

    gate = threading.Barrier(len(calls), timeout=10)

    def weather(now):
        gate.wait()
        return {"wind_dir_deg": 180, "wind_speed_kmh": 15.0}

    monkeypatch.setattr(model, "_tonight_conditions", weather)
    out: list = [None] * len(calls)

    def go(i, headers, stand_id):
        out[i] = client.post("/api/sits", json={"stand_id": stand_id}, headers=headers)

    threads = [threading.Thread(target=go, args=(i, *c)) for i, c in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    return sorted(r.status_code for r in out), out


@requires_db
def test_two_hunters_reserving_one_stand_at_once_get_one_answer_each(
    threaded_client, monkeypatch, admin, db_session, estate
):
    """Both used to be told the stand was theirs (audit A-07, I-03, J-11)."""
    _, alice = admin
    _, bob = _user(db_session, estate, "bob4@estate.local", role="member")
    s = _stand(threaded_client, alice, "Puente")

    codes, out = _at_once(monkeypatch, threaded_client, [(alice, s["id"]), (bob, s["id"])])
    assert codes == [201, 409], [r.text for r in out]
    db_session.expire_all()
    assert len(db_session.scalars(select(Sit)).all()) == 1


@requires_db
def test_two_hunters_reserving_crossing_fire_lanes_at_once_get_one_answer_each(
    threaded_client, monkeypatch, admin, db_session, estate
):
    """The same window used to let the fire-lane interlock pass twice."""
    _, alice = admin
    _, bob = _user(db_session, estate, "bob5@estate.local", role="member")
    a = _stand(threaded_client, alice, "Ridge", shooting_dirs_deg=[90])
    b = _stand(threaded_client, alice, "Barranco", shooting_dirs_deg=[100])

    codes, out = _at_once(monkeypatch, threaded_client, [(alice, a["id"]), (bob, b["id"])])
    assert codes == [201, 409], [r.text for r in out]
    assert "shooting arc" in next(r for r in out if r.status_code == 409).json()["detail"]


@requires_db
def test_the_unique_index_backs_up_the_lock(
    threaded_client, monkeypatch, admin, db_session, estate
):
    """Were the lock ever skipped, the database still keeps one live reservation per
    stand and night, and the loser is told so rather than shown a 500."""
    import app.api.routes_stands as routes

    _, alice = admin
    _, bob = _user(db_session, estate, "bob6@estate.local", role="member")
    s = _stand(threaded_client, alice, "Puente")
    monkeypatch.setattr(routes, "_lock_night", lambda db, night: None)
    monkeypatch.setattr(routes, "_refusal", lambda db, stand, user, night: None)

    codes, out = _at_once(monkeypatch, threaded_client, [(alice, s["id"]), (bob, s["id"])])
    assert codes == [201, 409], [r.text for r in out]
    db_session.expire_all()
    assert len(db_session.scalars(select(Sit)).all()) == 1

    # And straight into the table, past the API.
    row = db_session.scalars(select(Sit)).one()
    db_session.add(Sit(stand_id=row.stand_id, night=row.night, outcome="unreported"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    db_session.add(Sit(stand_id=row.stand_id, night=row.night, outcome="cancelled"))
    db_session.commit()  # a cancelled one is history, not a reservation
