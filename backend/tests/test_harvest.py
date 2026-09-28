"""The harvest book (feature 23): logged the morning after a SHOT, changed later, and
exported for the season.

What these pin down: the morning card asks only about your own SHOTs, only once the
night is over, and stops once the animal is logged or you said there was nothing to
log; a line is the hunter's to change (and any admin's); a retry after a weak signal
is the same line; the season runs 1 April to 31 March on the estate's clock; the
export is the admin's, and opens right in a spreadsheet; and removing a person keeps
their lines and the name on them.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.api.routes_harvests import season_bounds, season_of, shot_time
from app.api.routes_stands import tonight
from app.forecasting.conditions import sunset_of
from app.forecasting.thermal import SETTLING
from app.models import Estate, Harvest, Sit, Stand, User

from .conftest import requires_db

MADRID = ZoneInfo("Europe/Madrid")


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


def _user(db, estate, email, role):
    from app.core.security import create_access_token, hash_password

    u = User(estate_id=estate.id, email=email, password_hash=hash_password("x" * 12), role=role)
    db.add(u)
    db.commit()
    return u, {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


@pytest.fixture
def people(db_session, estate):
    return {
        "admin": _user(db_session, estate, "owner@estate.local", "admin"),
        "pedro": _user(db_session, estate, "pedro.garcia@estate.local", "member"),
        "ana": _user(db_session, estate, "ana@estate.local", "member"),
        "viewer": _user(db_session, estate, "guest@estate.local", "viewer"),
    }


@pytest.fixture
def stand(db_session, estate):
    s = Stand(estate_id=estate.id, name="Puente", lat=39.09, lon=-1.36)
    db_session.add(s)
    db_session.commit()
    return s


def _sit(db, stand, user, *, nights_ago=1, outcome="shot"):
    night = tonight() - timedelta(days=nights_ago)
    shot = datetime.combine(night, datetime.min.time(), tzinfo=MADRID).replace(hour=21, minute=40)
    s = Sit(stand_id=stand.id, user_id=user.id, night=night, outcome=outcome,
            started_at=shot - timedelta(hours=2), reported_at=shot)
    db.add(s)
    db.commit()
    return s


BOAR = {"species_id": "wild_boar", "sex": "male", "age_class": "mature_adult"}


# ── the morning card ────────────────────────────────────────────────────────


@requires_db
def test_the_morning_after_a_shot_asks_to_log_it_and_stops_once_it_is(
    client, db_session, people, stand,
):
    pedro, h = people["pedro"]
    last_night = _sit(db_session, stand, pedro)
    _sit(db_session, stand, pedro, nights_ago=0)  # tonight's: not until the morning
    _sit(db_session, stand, pedro, nights_ago=2, outcome="seen")  # no shot, nothing to log
    _sit(db_session, stand, pedro, nights_ago=9)  # long ago: let be
    solana = Stand(estate_id=stand.estate_id, name="Solana")
    db_session.add(solana)
    db_session.commit()
    other = _sit(db_session, solana, people["ana"][0])

    asks = client.get("/api/harvests/asks", headers=h).json()
    assert [a["sit_id"] for a in asks] == [str(last_night.id)]
    assert asks[0]["stand"] == "Puente"
    assert datetime.fromisoformat(asks[0]["shot_at"]) == last_night.reported_at
    # Ana's shot is Ana's card.
    assert [a["sit_id"] for a in client.get("/api/harvests/asks", headers=people["ana"][1]).json()
            ] == [str(other.id)]
    assert client.get("/api/harvests/asks", headers=people["viewer"][1]).json() == []

    r = client.post("/api/harvests", json={**BOAR, "sit_id": str(last_night.id),
                                           "seal": " CU-2026 0412 ", "weight_kg": 78.5},
                    headers=h)
    assert r.status_code == 201, r.text
    line = r.json()
    assert (line["stand"], line["hunter"], line["seal"], line["weight_kg"]) == (
        "Puente", "Pedro", "CU-2026 0412", 78.5)
    # When SHOT was tapped, unless the form says otherwise.
    assert datetime.fromisoformat(line["taken_at"]) == last_night.reported_at
    assert line["yours"] and line["can_edit"]
    assert client.get("/api/harvests/asks", headers=h).json() == []


def _local(night, hour, minute=0, days=0):
    return datetime.combine(night + timedelta(days=days), datetime.min.time(),
                            tzinfo=MADRID).replace(hour=hour, minute=minute)


@requires_db
def test_a_shot_answered_the_next_morning_is_logged_on_the_night_of_the_sit(
    client, db_session, people, stand,
):
    """ "What happened last night?" answered at 08:30: the report's time is the
    morning's, and the harvest used to be dated to it, a day late in the book and the
    return (R6BE-1). The shot was during the sit."""
    pedro, h = people["pedro"]
    night = tonight() - timedelta(days=1)
    sit = Sit(stand_id=stand.id, user_id=pedro.id, night=night, outcome="shot",
              started_at=_local(night, 20), ended_at=_local(night, 22, 30),
              reported_at=_local(night, 8, 30, days=1))
    db_session.add(sit)
    db_session.commit()
    ask = client.get("/api/harvests/asks", headers=h).json()[0]
    assert datetime.fromisoformat(ask["shot_at"]) == sit.ended_at
    line = client.post("/api/harvests", json={**BOAR, "sit_id": str(sit.id)}, headers=h).json()
    assert datetime.fromisoformat(line["taken_at"]) == sit.ended_at
    csv_rows = list(csv.reader(io.StringIO(client.get(
        f"/api/harvests/export.csv?season={season_of(sit.ended_at)}",
        headers=people["admin"][1]).content.decode()[1:]), delimiter=";"))
    assert csv_rows[1][:3] == [night.isoformat(), "22:30", "Wild boar"]


def test_the_shot_time_is_always_on_the_night_of_the_sit():
    night = tonight() - timedelta(days=3)

    def sit(**kw):
        return Sit(night=night, outcome="shot", **kw)

    # Tapped during the sit: that is when.
    assert shot_time(sit(started_at=_local(night, 20), ended_at=_local(night, 23),
                         reported_at=_local(night, 21, 40))) == _local(night, 21, 40)
    # Tapped on the walk back, after END SIT: no later than the end.
    assert shot_time(sit(started_at=_local(night, 20), ended_at=_local(night, 22, 30),
                         reported_at=_local(night, 23, 10))) == _local(night, 22, 30)
    # A dawn sit's SHOT at 04:50 is still that night.
    assert shot_time(sit(reported_at=_local(night, 4, 50, days=1))) == _local(night, 4, 50, days=1)
    # Answered the next morning, sit mode ended the next morning too: its start.
    assert shot_time(sit(started_at=_local(night, 20, 15), ended_at=_local(night, 7, 55, days=1),
                         reported_at=_local(night, 8, 30, days=1))) == _local(night, 20, 15)
    # Never in sit mode, answered days later: the sit time that evening.
    at = shot_time(sit(reported_at=_local(night, 9, 0, days=2)))
    assert at == sunset_of(night) + SETTLING
    assert tonight(at) == night


@requires_db
def test_nothing_to_log_stops_the_card_and_undo_brings_it_back(client, db_session, people, stand):
    pedro, h = people["pedro"]
    sit = _sit(db_session, stand, pedro)
    r = client.post(f"/api/sits/{sit.id}/no-harvest", json={"nothing": True}, headers=h)
    assert r.json() == {"sit_id": str(sit.id), "nothing_to_log": True}
    assert client.get("/api/harvests/asks", headers=h).json() == []
    db_session.refresh(sit)
    assert sit.outcome == "shot"  # the report stays what it was
    client.post(f"/api/sits/{sit.id}/no-harvest", json={"nothing": False}, headers=h)
    assert len(client.get("/api/harvests/asks", headers=h).json()) == 1
    # Someone else's sit is theirs to say.
    r = client.post(f"/api/sits/{sit.id}/no-harvest", headers=people["ana"][1])
    assert r.status_code == 403
    # Only a SHOT has nothing to log, as only a SHOT has a line to log (R6BE-6).
    seen = _sit(db_session, stand, pedro, nights_ago=2, outcome="seen")
    r = client.post(f"/api/sits/{seen.id}/no-harvest", json={"nothing": True}, headers=h)
    assert r.status_code == 409 and "shot" in r.json()["detail"]
    db_session.refresh(seen)
    assert seen.no_harvest_at is None
    # Undo still works whatever the sit says now.
    assert client.post(f"/api/sits/{seen.id}/no-harvest", json={"nothing": False},
                       headers=h).json()["nothing_to_log"] is False


@requires_db
def test_a_harvest_hangs_off_a_shot_you_made(client, db_session, people, stand):
    pedro, h = people["pedro"]
    seen = _sit(db_session, stand, pedro, outcome="seen")
    r = client.post("/api/harvests", json={**BOAR, "sit_id": str(seen.id)}, headers=h)
    assert r.status_code == 409 and "shot" in r.json()["detail"]
    shot = _sit(db_session, stand, pedro, nights_ago=2)
    assert client.post("/api/harvests", json={**BOAR, "sit_id": str(shot.id)},
                       headers=people["ana"][1]).status_code == 403
    assert client.post("/api/harvests", json=BOAR, headers=people["viewer"][1]).status_code == 403
    # An admin logs it for the hunter: the line is Pedro's, and says so.
    r = client.post("/api/harvests", json={**BOAR, "sit_id": str(shot.id)},
                    headers=people["admin"][1])
    assert r.status_code == 201
    assert r.json()["hunter"] == "Pedro"
    line = db_session.get(Harvest, uuid.UUID(r.json()["id"]))
    assert (line.user_id, line.created_by) == (pedro.id, people["admin"][0].id)


@requires_db
def test_saving_again_after_no_answer_is_the_same_line(client, db_session, people, stand):
    pedro, h = people["pedro"]
    sit = _sit(db_session, stand, pedro)
    body = {**BOAR, "id": str(uuid.uuid4()), "sit_id": str(sit.id)}
    first = client.post("/api/harvests", json=body, headers=h)
    again = client.post("/api/harvests", json=body, headers=h)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    assert db_session.query(Harvest).count() == 1
    # Another hunter can't take over the line by sending its id.
    assert client.post("/api/harvests", json=body, headers=people["ana"][1]).status_code == 409


@requires_db
def test_a_retry_with_changed_answers_keeps_what_was_sent_last(client, db_session, people, stand):
    """A save lost its answer, and the hunter put the animal right before trying again
    with the same line: the book says what they sent last, not the first try (R6BE-5)."""
    pedro, h = people["pedro"]
    sit = _sit(db_session, stand, pedro)
    line_id = str(uuid.uuid4())
    first = client.post("/api/harvests", json={
        **BOAR, "id": line_id, "sit_id": str(sit.id), "seal": "CU-1", "weight_kg": 70}, headers=h)
    assert first.status_code == 201
    again = client.post("/api/harvests", json={
        "id": line_id, "sit_id": str(sit.id), "species_id": "red_deer", "sex": "female",
        "age_class": "unknown", "seal": "CU-9", "weight_kg": None,
        "taken_at": "2026-09-20T21:15:00+02:00",
    }, headers=h)
    assert again.status_code == 200, again.text
    line = again.json()
    assert (line["id"], line["species_id"], line["sex"], line["seal"], line["weight_kg"]) == (
        line_id, "red_deer", "female", "CU-9", None)
    assert datetime.fromisoformat(line["taken_at"]) == datetime(2026, 9, 20, 19, 15, tzinfo=UTC)
    assert line["stand"] == "Puente" and line["hunter"] == "Pedro"
    assert db_session.query(Harvest).count() == 1
    # The same answers again change nothing, and a member's retry can't rename it.
    same = client.post("/api/harvests", json={
        "id": line_id, "species_id": "red_deer", "sex": "female", "seal": "CU-9",
        "hunter": "Somebody"}, headers=h).json()
    assert (same["species_id"], same["hunter"], same["seal"]) == ("red_deer", "Pedro", "CU-9")


@requires_db
@pytest.mark.parametrize("change,words", [
    ({"species_id": "unicorn"}, "animals on the list"),
    ({"sex": "stag"}, "male, female"),
    ({"age_class": "ancient"}, "age"),
    ({"weight_kg": 0}, "greater than 0"),
    ({"weight_kg": 2000}, "less than 1000"),
    ({"seal": "x" * 41}, "at most 40"),
    ({"notes": "a‮b"}, "hidden characters"),
    ({"taken_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()}, "still to come"),
    ({"taken_at": "1990-10-10T21:00:00+02:00"}, "too long ago"),
])
def test_a_line_that_cant_be_right_is_refused_in_words(client, people, change, words):
    r = client.post("/api/harvests", json={**BOAR, **change}, headers=people["pedro"][1])
    assert r.status_code == 422
    assert words in str(r.json()["detail"])


# ── changing and listing ────────────────────────────────────────────────────


@requires_db
def test_a_line_is_the_hunters_to_change_and_any_admins(client, db_session, people):
    _, h = people["pedro"]
    line = client.post("/api/harvests", json={**BOAR, "seal": "CU-1"}, headers=h).json()
    assert line["hunter"] == "Pedro" and line["stand"] is None
    url = f"/api/harvests/{line['id']}"
    r = client.patch(url, json={"sex": "female", "seal": "", "weight_kg": 61}, headers=h)
    assert (r.json()["sex"], r.json()["seal"], r.json()["weight_kg"]) == ("female", None, 61)
    assert r.json()["age_class"] == "mature_adult"  # what wasn't sent stays
    assert client.patch(url, json={"sex": "male"}, headers=people["ana"][1]).status_code == 403
    assert client.delete(url, headers=people["ana"][1]).status_code == 403
    assert client.patch(url, json={"hunter": "Pedro García"}, headers=h).status_code == 403
    r = client.patch(url, json={"hunter": "Pedro  García "}, headers=people["admin"][1])
    assert r.json()["hunter"] == "Pedro García"
    assert client.delete(url, headers=h).json()["status"] == "deleted"
    assert db_session.query(Harvest).count() == 0


@requires_db
def test_members_see_their_own_lines_and_the_admin_sees_the_book(client, people):
    client.post("/api/harvests", json=BOAR, headers=people["pedro"][1])
    client.post("/api/harvests", json={**BOAR, "species_id": "red_deer"}, headers=people["ana"][1])
    guest = client.post("/api/harvests", json={**BOAR, "hunter": "Luis (guest)"},
                        headers=people["admin"][1]).json()
    assert guest["hunter"] == "Luis (guest)"
    mine = client.get("/api/harvests", headers=people["pedro"][1]).json()
    assert [i["species_id"] for i in mine["items"]] == ["wild_boar"]
    assert not mine["can_export"]
    book = client.get("/api/harvests", headers=people["admin"][1]).json()
    assert len(book["items"]) == 3 and book["can_export"]
    assert {i["species"] for i in book["items"]} == {"Wild boar", "Red deer"}
    season = season_of(datetime.now(UTC))
    assert book["season"] == season and book["seasons"][0]["season"] == season
    assert client.get("/api/harvests", headers=people["viewer"][1]).json()["items"] == []
    # A member's own name is theirs: a hunter can't log in someone else's name.
    r = client.post("/api/harvests", json={**BOAR, "hunter": "Somebody"}, headers=people["ana"][1])
    assert r.json()["hunter"] == "Ana"


def test_the_season_runs_april_to_march_on_the_estates_clock():
    # 31 March 23:30 in Madrid is still the season that began the April before.
    assert season_of(datetime(2027, 3, 31, 21, 30, tzinfo=UTC)) == 2026
    # 1 April 00:30 in Madrid (22:30 UTC the day before) is the new one.
    assert season_of(datetime(2027, 3, 31, 22, 30, tzinfo=UTC)) == 2027
    start, end = season_bounds(2026)
    assert (start.isoformat(), end.isoformat()) == (
        "2026-04-01T00:00:00+02:00", "2027-04-01T00:00:00+02:00")


# ── the export ──────────────────────────────────────────────────────────────


@requires_db
def test_the_season_export_is_the_admins_and_opens_right_in_a_spreadsheet(
    client, db_session, people, stand,
):
    pedro, h = people["pedro"]
    sit = _sit(db_session, stand, pedro)
    client.post("/api/harvests", json={
        **BOAR, "sit_id": str(sit.id), "seal": "CU-0412", "weight_kg": 78.5,
        "notes": "=HYPERLINK(\"http://x\")", "taken_at": "2026-09-10T21:40:00+02:00",
    }, headers=h)
    client.post("/api/harvests", json={
        "species_id": "red_deer", "sex": "female", "taken_at": "2026-09-02T20:05:00+02:00",
        "hunter": "Luis Martín",
    }, headers=people["admin"][1])
    # Last season's line is not in this one.
    client.post("/api/harvests", json={**BOAR, "taken_at": "2026-03-30T21:00:00+02:00"},
                headers=h)

    assert client.get("/api/harvests/export.csv?season=2026", headers=h).status_code == 403
    r = client.get("/api/harvests/export.csv?season=2026", headers=people["admin"][1])
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="harvest-2026-27.csv"' in r.headers["content-disposition"]
    text = r.content.decode("utf-8")
    assert text.startswith("﻿")
    # Excel set to Spanish (the estate's PC) splits on ';' and reads "78,5" as a number
    # (R6BE-7); no "sep=" line, which would make it drop the byte-order mark.
    assert text[1:].startswith("Date;Time;Species;")
    rows = list(csv.reader(io.StringIO(text[1:]), delimiter=";"))
    assert rows[0] == ["Date", "Time", "Species", "Sex", "Age", "Seal number", "Weight (kg)",
                       "Hunter", "Stand", "Notes"]
    assert rows[1] == ["2026-09-02", "20:05", "Red deer", "Female", "Not sure", "", "",
                       "Luis Martín", "", ""]
    assert rows[2] == ["2026-09-10", "21:40", "Wild boar", "Male", "Adult", "CU-0412", "78,5",
                       "Pedro", "Puente", "'=HYPERLINK(\"http://x\")"]
    assert len(rows) == 3
    old = client.get("/api/harvests/export.csv?season=2025", headers=people["admin"][1])
    assert len(list(csv.reader(io.StringIO(old.content.decode()[1:]), delimiter=";"))) == 2


@requires_db
def test_removing_a_person_keeps_their_lines_and_the_name_on_them(client, db_session, people):
    pedro, h = people["pedro"]
    line = client.post("/api/harvests", json=BOAR, headers=h).json()
    r = client.delete(f"/api/users/{pedro.id}", headers=people["admin"][1])
    assert r.status_code == 200, r.text
    db_session.expire_all()
    kept = db_session.get(Harvest, uuid.UUID(line["id"]))
    assert (kept.user_id, kept.created_by, kept.hunter) == (None, None, "Pedro")
    book = client.get("/api/harvests", headers=people["admin"][1]).json()["items"]
    assert [i["hunter"] for i in book] == ["Pedro"]
