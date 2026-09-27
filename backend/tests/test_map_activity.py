"""The activity map and the replay of a night: visits, where they happen, and in what order.

What these pin down is what a hunter reads off the map: a visit is an arrival, not a
frame; a camera that wasn't working is left out of its own average rather than
dragging it down; the parts of the night run across midnight and dawn belongs to the
night before it; and a line between two cameras is only drawn when the same species
could really have walked from one to the other.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.api.routes_map import last_completed_night
from app.core.security import create_access_token
from app.forecasting.activity import activity, likely_paths, replay, replay_nights, still_running
from app.forecasting.exposure import visits_by_night
from app.forecasting.visits import list_visits, map_night_window
from app.models import Camera, CameraNight, Detection, Estate, Image, Species, User

from .conftest import requires_db

pytestmark = requires_db

TZ = ZoneInfo("Europe/Madrid")
NIGHT = date(2026, 9, 20)  # a fixed evening for everything that doesn't go through the clock


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
    db_session.add_all([
        Species(id="wild_boar", common_name="Wild Boar", is_priority=True),
        Species(id="red_deer", common_name="Red Deer", is_priority=True),
        Species(id="fox", common_name="Fox"),
        # Stored as the classifier names them: title-cased.
        Species(id="roe_deer", common_name="Roe Deer"),
        Species(id="badger", common_name="Badger"),
        Species(id="lagomorph", common_name="Rabbit", hidden=True),
    ])
    db_session.commit()
    return e


def _user(db, estate, role="admin"):
    u = User(estate_id=estate.id, email=f"{role}-{uuid.uuid4().hex[:6]}@estate.local",
             password_hash="x", role=role)
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


# Two cameras about 420 m apart, and one 12 km away (another valley, same account).
CHARCA, ENCINAR, FAR = (39.0951, -1.3622), (39.0921, -1.3651), (39.2030, -1.3622)


def _camera(db, estate, name="Charca", at=CHARCA):
    c = Camera(estate_id=estate.id, name=name, lat=at[0], lon=at[1])
    db.add(c)
    db.commit()
    return c


def _at(night: date, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    """Local time on the night of `night`: 18-23 h that evening, 0-17 h the next day."""
    day = night if hh >= 18 else night + timedelta(days=1)
    return datetime(day.year, day.month, day.day, hh, mm, ss, tzinfo=TZ)


def _photo(db, cam, at, species=("wild_boar",), *, empty=False, group=None):
    """One frame. `species` are the detections in it; () is an animal nobody named.
    `empty`: False kept, True "nothing in it", None not checked yet."""
    img = Image(camera_id=cam.id, captured_at=at, original_path="p.jpg", is_empty_frame=empty)
    db.add(img)
    db.flush()
    for sid in species:
        db.add(Detection(image_id=img.id, species_id=sid, species_conf=0.9, group_size=group))
    db.commit()
    return img


def _watched(db, cam, nights, state="CONFIRMED"):
    db.add_all([CameraNight(camera_id=cam.id, night=n, exposure_state=state) for n in nights])
    db.commit()


def _week(last=NIGHT):
    return [last - timedelta(days=i) for i in range(6, -1, -1)]


def _visits(db, night=NIGHT, **kw):
    start, end = map_night_window(night)
    return list_visits(db, start=start, end=end, **kw)


def _cam(result, cam):
    return next(c for c in result["cameras"] if c["camera_id"] == str(cam.id))


# ── the visits helper ───────────────────────────────────────────────────────


def test_a_burst_is_one_visit_with_its_first_frame_and_largest_group(db_session, estate):
    cam = _camera(db_session, estate)
    t = _at(NIGHT, 21, 40)
    burst = [_photo(db_session, cam, t, group=g) for g in (2, 4, 3)]
    _photo(db_session, cam, t + timedelta(minutes=10))  # still the same visit

    (v,) = _visits(db_session)
    assert (v["species_id"], v["label"], v["frames"], v["max_group"]) == (
        "wild_boar", "Wild boar", 4, 4,
    )
    assert v["first_at"] == t and v["last_at"] == t + timedelta(minutes=10)
    assert v["image_id"] in {b.id for b in burst}
    assert v["night"] == NIGHT


def test_the_same_animals_back_more_than_30_minutes_later_are_a_new_visit(db_session, estate):
    cam = _camera(db_session, estate)
    t = _at(NIGHT, 22)
    _photo(db_session, cam, t)
    _photo(db_session, cam, t + timedelta(minutes=30))  # exactly the gap: the same visit
    _photo(db_session, cam, t + timedelta(minutes=60, seconds=1))  # 30 min 1 s after: new

    visits = _visits(db_session)
    assert [(v["first_at"], v["frames"]) for v in visits] == [
        (t, 2), (t + timedelta(minutes=60, seconds=1), 1),
    ]


def test_each_species_is_its_own_visit(db_session, estate):
    cam = _camera(db_session, estate)
    t = _at(NIGHT, 21)
    _photo(db_session, cam, t)
    _photo(db_session, cam, t + timedelta(minutes=10), ("red_deer",))
    # The boar again: the deer in between doesn't split its visit.
    _photo(db_session, cam, t + timedelta(minutes=20))

    assert sorted((v["species_id"], v["frames"]) for v in _visits(db_session)) == [
        ("red_deer", 1), ("wild_boar", 2),
    ]


def test_hidden_species_and_frames_that_are_not_animals_are_never_visits(db_session, estate):
    cam = _camera(db_session, estate)
    _photo(db_session, cam, _at(NIGHT, 19), ("lagomorph",))  # hidden
    _photo(db_session, cam, _at(NIGHT, 20), empty=True)  # "nothing in it"
    _photo(db_session, cam, _at(NIGHT, 21), empty=None)  # the detector hasn't checked it
    both = _photo(db_session, cam, _at(NIGHT, 22), ("lagomorph", "wild_boar"))
    unnamed = _photo(db_session, cam, _at(NIGHT, 23), ())

    visits = _visits(db_session)
    assert [(v["species_id"], v["label"], v["image_id"]) for v in visits] == [
        ("wild_boar", "Wild boar", both.id),
        (None, "Animal", unnamed.id),
    ]
    # The nightly statistics count with the same rule.
    by_night = visits_by_night(db_session, camera_id=cam.id)
    assert {k[2]: row["visits"] for k, row in by_night.items()} == {"wild_boar": 1, None: 1}


def test_the_camera_sheet_and_the_activity_map_agree_on_last_night(client, db_session, estate):
    headers = _user(db_session, estate, "viewer")
    cam = _camera(db_session, estate)
    night = last_completed_night()
    _watched(db_session, cam, [night])
    for hh, mm, sid in [(19, 5, "wild_boar"), (19, 20, "wild_boar"), (22, 0, "wild_boar"),
                        (23, 30, "red_deer"), (2, 10, "wild_boar"), (5, 0, "fox")]:
        for s in range(3):  # bursts of three
            _photo(db_session, cam, _at(night, hh, mm, s), (sid,))

    sheet = client.get("/api/map/cameras", headers=headers).json()[0]["last_night"]
    act = client.get("/api/map/activity?nights=1", headers=headers).json()["cameras"][0]
    assert {v["species_id"]: v["visits"] for v in sheet} == {
        "wild_boar": 3, "red_deer": 1, "fox": 1,
    }
    assert {v["species_id"]: v["visits"] for v in act["by_species"]} == {
        "wild_boar": 3, "red_deer": 1, "fox": 1,
    }
    assert act["read"].startswith("5 animal visits last night")


def test_a_visit_under_way_at_dusk_or_eight_is_the_same_visit_on_every_view(
    db_session, estate,
):
    """The day between two nights ends a visit, whichever range is asked for."""
    cam = _camera(db_session, estate)
    week = _week()
    _watched(db_session, cam, week)
    mid, late = week[3], week[5]
    # A badger from 17:40 to 18:25 that evening: on the map, a visit at 18:05.
    for at in (_at(mid, 18) - timedelta(minutes=20), _at(mid, 18, 5), _at(mid, 18, 25)):
        _photo(db_session, cam, at, ("badger",))
    # A fox from 07:50 into the day: a visit at 07:50 of one frame.
    _photo(db_session, cam, _at(late, 7, 50), ("fox",))
    _photo(db_session, cam, _at(late, 8, 10), ("fox",))

    def act(last, nights, species):
        got = activity(db_session, cameras=[cam], last_night=last, nights=nights, part="all",
                       species=species)["cameras"][0]
        return got["visits"], got["read"]

    assert act(mid, 1, "badger") == (1, "1 badger visit last night, at 18:05")
    assert act(NIGHT, 7, "badger") == (1, "Badger on 1 of 7 nights, at 18:05")
    assert act(late, 1, "fox") == (1, "1 fox visit last night, at 07:50")
    assert act(NIGHT, 7, "fox") == (1, "Fox on 1 of 7 nights, at 07:50")
    played = {
        n: [(v["label"], v["at"], v["last_at"], v["frames"])
            for v in replay(db_session, cameras=[cam], night=n)["visits"]]
        for n in (mid, late)
    }
    assert played == {
        mid: [("Badger", _at(mid, 18, 5), _at(mid, 18, 25), 2)],
        late: [("Fox", _at(late, 7, 50), _at(late, 7, 50), 1)],
    }
    listed = {n["night"]: n["visits"] for n in replay_nights(
        db_session, cameras=[cam], last_night=NIGHT, limit=7)}
    assert (listed[mid.isoformat()], listed[late.isoformat()]) == (1, 1)
    assert sum(listed.values()) == 2


def test_species_read_mid_sentence_in_lower_case(db_session, estate):
    cam = _camera(db_session, estate)
    _watched(db_session, cam, [NIGHT])

    def read(**kw):
        got = activity(db_session, cameras=[cam], last_night=NIGHT, nights=1, part="all", **kw)
        return got["cameras"][0]["read"]

    # With the label the endpoint passes, and with the one the visits carry.
    assert read(species="roe_deer", species_label="Roe Deer") == "No roe deer last night."
    _photo(db_session, cam, _at(NIGHT, 21), ("roe_deer",))
    assert read(species="roe_deer") == "1 roe deer visit last night, at 21:00"


def test_last_night_is_marked_so_far_until_eight(db_session, estate):
    """From 06:00 the app calls it last night, but the map's night runs to 08:00."""
    cam = _camera(db_session, estate)
    _watched(db_session, cam, [NIGHT])
    _photo(db_session, cam, _at(NIGHT, 21))
    seven, eight = _at(NIGHT, 7), _at(NIGHT, 8)
    assert last_completed_night(seven) == NIGHT
    assert still_running(NIGHT, seven) and not still_running(NIGHT, eight)

    def act(now):
        return activity(db_session, cameras=[cam], last_night=NIGHT, nights=1, part="all",
                        now=now)

    early = act(seven)
    assert early["so_far"] is True
    assert early["cameras"][0]["read"] == "1 animal visit last night so far, at 21:00"
    later = act(eight)
    assert later["so_far"] is False
    assert later["cameras"][0]["read"] == "1 animal visit last night, at 21:00"
    got = activity(db_session, cameras=[cam], last_night=NIGHT, nights=1, part="all",
                   species="red_deer", species_label="Red deer", now=seven)
    assert got["cameras"][0]["read"] == "No red deer last night so far."

    listed = replay_nights(db_session, cameras=[cam], last_night=NIGHT, limit=3, now=seven)
    assert [(n["visits"], n["so_far"]) for n in listed] == [(1, True), (0, False), (0, False)]
    assert not replay_nights(db_session, cameras=[cam], last_night=NIGHT, limit=1,
                             now=eight)[0]["so_far"]


# ── the activity map ────────────────────────────────────────────────────────


def test_nights_a_camera_was_down_are_left_out_not_counted_as_quiet(db_session, estate):
    week = _week()
    patchy = _camera(db_session, estate, "Charca")
    dead = _camera(db_session, estate, "Pinar", at=ENCINAR)
    quiet = _camera(db_session, estate, "Barranco", at=FAR)
    # Working on five nights, down on the first two.
    _watched(db_session, patchy, week[2:])
    _watched(db_session, patchy, week[:2], "UNKNOWN")
    _watched(db_session, dead, week, "UNKNOWN")
    _watched(db_session, quiet, week, "PRESUMED_UP")
    for n in (week[2], week[4], week[6]):
        _photo(db_session, patchy, _at(n, 21, 30))
    _photo(db_session, patchy, _at(week[6], 23, 50))
    # A boar on a night it can't vouch for (out of credits): not in the rate.
    _photo(db_session, patchy, _at(week[0], 21, 30))
    _photo(db_session, dead, _at(week[3], 21, 30))

    got = activity(db_session, cameras=[patchy, dead, quiet], last_night=NIGHT, nights=7,
                   part="all")
    p, d, q = _cam(got, patchy), _cam(got, dead), _cam(got, quiet)
    numbers = ("visits", "watched_nights", "blind_nights", "nights_with", "per_night")
    assert [p[k] for k in numbers] == [4, 5, 2, 3, 0.8]
    assert p["peak"] == "21–23"
    assert p["read"] == "Animals on 3 of 5 nights it was working, mostly 21–23 h"
    assert (d["visits"], d["watched_nights"], d["per_night"]) == (0, 0, None)
    assert d["read"] == "Not counted: the camera wasn’t working on these nights."
    assert (q["visits"], q["watched_nights"], q["per_night"]) == (0, 7, 0.0)
    assert q["read"] == "No animals on the 7 nights."


def test_nights_the_ai_gave_up_on_are_left_out_not_counted_as_quiet(db_session, estate):
    """A night whose frames the AI could not check is not "watched, nothing came", even
    where the hourly rebuild of camera_nights called it watched before the AI gave up."""
    week = _week()
    cam = _camera(db_session, estate)
    _watched(db_session, cam, week)
    for n in (week[1], week[5]):
        _photo(db_session, cam, _at(n, 21, 30))
    for n in (week[2], week[3]):
        img = _photo(db_session, cam, _at(n, 22, 0), (), empty=None)
        img.ai_attempts, img.ai_failed_at = 3, datetime.now(UTC)
    db_session.commit()

    got = _cam(activity(db_session, cameras=[cam], last_night=NIGHT, nights=7, part="all"), cam)
    numbers = ("visits", "watched_nights", "unreadable_nights", "blind_nights", "per_night")
    assert [got[k] for k in numbers] == [2, 5, 2, 0, 0.4]
    assert got["read"] == "Animals on 2 of 5 nights that could be checked, at 21:30 and 21:30"


def test_the_parts_of_the_night_run_past_midnight_and_dawn_belongs_to_the_night_before(
    db_session, estate,
):
    cam = _camera(db_session, estate)
    nights = [NIGHT, NIGHT + timedelta(days=1)]
    _watched(db_session, cam, nights)
    for hh, mm in [(19, 0), (23, 30), (1, 30), (3, 10), (7, 30)]:
        _photo(db_session, cam, _at(NIGHT, hh, mm))
    # Daytime is no part of any night: the morning after, and the afternoon before.
    _photo(db_session, cam, _at(NIGHT, 8, 30))
    _photo(db_session, cam, _at(NIGHT, 17, 0) - timedelta(days=1))

    def count(part, last=NIGHT):
        got = activity(db_session, cameras=[cam], last_night=last, nights=1, part=part)
        return got["cameras"][0]["visits"]

    assert {p: count(p) for p in ("dusk", "night", "dawn", "all")} == {
        "dusk": 1, "night": 2, "dawn": 2, "all": 5,
    }
    # 07:30 is dawn after NIGHT, not a visit on the next night.
    assert count("all", NIGHT + timedelta(days=1)) == 0


def test_the_read_names_the_busiest_two_hours_only_when_there_is_one(db_session, estate):
    cam = _camera(db_session, estate)
    week = _week()
    _watched(db_session, cam, week)
    for n, hh, mm in [(week[0], 21, 10), (week[1], 21, 50), (week[3], 22, 40), (week[5], 2, 0)]:
        _photo(db_session, cam, _at(n, hh, mm))
    got = _cam(activity(db_session, cameras=[cam], last_night=NIGHT, nights=7, part="all",
                        species="wild_boar", species_label="Wild boar"), cam)
    assert got["read"] == "Wild boar on 4 of 7 nights, mostly 21–23 h"

    # One visit: its time, not a window. Spread out: no set time.
    other = _camera(db_session, estate, "Encinar", at=ENCINAR)
    _watched(db_session, other, week)
    _photo(db_session, other, _at(week[2], 20, 15))
    got = activity(db_session, cameras=[other], last_night=NIGHT, nights=7, part="all")
    assert got["cameras"][0]["read"] == "Animals on 1 of 7 nights, at 20:15"
    for n, hh in [(week[3], 18), (week[4], 22), (week[5], 2), (week[6], 6)]:
        _photo(db_session, other, _at(n, hh, 5))
    got = activity(db_session, cameras=[other], last_night=NIGHT, nights=7, part="all")
    assert (got["cameras"][0]["peak"], got["cameras"][0]["read"]) == (
        None, "Animals on 5 of 7 nights, at no set time",
    )


def test_a_few_visits_are_read_by_their_times_in_the_order_of_the_night(db_session, estate):
    cam = _camera(db_session, estate)
    week = _week()
    _watched(db_session, cam, week)
    for n, hh, mm in [(week[1], 2, 15), (week[3], 23, 10), (week[5], 19, 40)]:
        _photo(db_session, cam, _at(n, hh, mm))
    got = activity(db_session, cameras=[cam], last_night=NIGHT, nights=7, part="all")
    assert got["cameras"][0]["read"] == "Animals on 3 of 7 nights, at 19:40, 23:10 and 02:15"

    # More than three, a third of them in two hours: the busiest time, not "mostly".
    for n, hh in [(week[0], 21), (week[2], 21), (week[4], 22), (week[6], 6)]:
        _photo(db_session, cam, _at(n, hh, 20))
    got = activity(db_session, cameras=[cam], last_night=NIGHT, nights=7, part="all")["cameras"][0]
    assert (got["peak"], got["read"]) == ("21–23", "Animals on 7 of 7 nights, busiest 21–23 h")


def test_frames_decide_while_camera_nights_has_not_caught_up(db_session, estate):
    """At 06:30 the hourly rebuild may not have a row for last night yet."""
    checked = _camera(db_session, estate, "Charca")
    waiting = _camera(db_session, estate, "Encinar", at=ENCINAR)
    silent = _camera(db_session, estate, "Barranco", at=FAR)
    _photo(db_session, checked, _at(NIGHT, 22), (), empty=True)  # proof it was awake
    _photo(db_session, checked, _at(NIGHT, 23))
    _photo(db_session, waiting, _at(NIGHT, 21))
    _photo(db_session, waiting, _at(NIGHT, 4), (), empty=None)

    got = activity(db_session, cameras=[checked, waiting, silent], last_night=NIGHT, nights=1,
                   part="all")
    c, w, s = _cam(got, checked), _cam(got, waiting), _cam(got, silent)
    assert (c["watched_nights"], c["visits"]) == (1, 1)
    assert c["read"] == "1 animal visit last night, at 23:00"
    assert (w["watched_nights"], w["checking_nights"], w["read"]) == (
        0, 1, "Still checking last night’s photos.",
    )
    assert s["read"] == "Not counted: the camera may not have been working last night."


def test_species_filter_and_the_species_present(db_session, estate):
    cam = _camera(db_session, estate)
    _watched(db_session, cam, [NIGHT])
    for hh in (19, 21, 23):
        _photo(db_session, cam, _at(NIGHT, hh))
    _photo(db_session, cam, _at(NIGHT, 22), ("fox",))
    _photo(db_session, cam, _at(NIGHT, 2), ())  # unnamed: counts in "all", no chip of its own
    _photo(db_session, cam, _at(NIGHT, 3), ("lagomorph",))  # hidden: nowhere

    everything = activity(db_session, cameras=[cam], last_night=NIGHT, nights=1, part="all")
    assert everything["species_options"] == [
        {"species_id": "wild_boar", "label": "Wild boar", "visits": 3},
        {"species_id": "fox", "label": "Fox", "visits": 1},
    ]
    assert everything["cameras"][0]["visits"] == 5
    # Busiest first; the unnamed animal after the named ones.
    by_species = everything["cameras"][0]["by_species"]
    assert [s["species_id"] for s in by_species] == ["wild_boar", "fox", None]

    boar = activity(db_session, cameras=[cam], last_night=NIGHT, nights=1, part="dusk",
                    species="wild_boar", species_label="Wild boar")
    assert boar["cameras"][0]["read"] == "2 wild boar visits at dusk last night, at 19:00 and 21:00"
    deer = activity(db_session, cameras=[cam], last_night=NIGHT, nights=1, part="all",
                    species="red_deer", species_label="Red deer")
    assert deer["species_label"] == "Red deer"
    assert deer["cameras"][0]["visits"] == 0
    assert deer["cameras"][0]["read"] == "No red deer last night."
    # The chips still offer what was there.
    assert [o["species_id"] for o in deer["species_options"]] == ["wild_boar", "fox"]


def test_activity_endpoint_is_for_everyone_and_checks_its_filters(client, db_session, estate):
    headers = _user(db_session, estate, "viewer")
    cam = _camera(db_session, estate)
    _camera(db_session, estate, "Unplaced", at=(None, None))
    night = last_completed_night()
    _watched(db_session, cam, [night - timedelta(days=i) for i in range(30)])
    _photo(db_session, cam, _at(night, 21))

    r = client.get("/api/map/activity?species=wild_boar&part=dusk&nights=30", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["nights"], body["part"], body["species"]) == (30, "dusk", "wild_boar")
    assert body["hours"] == [18, 22]
    assert body["last_night"] == night.isoformat()
    assert body["first_night"] == (night - timedelta(days=29)).isoformat()
    assert isinstance(body["so_far"], bool)
    charca = next(c for c in body["cameras"] if c["name"] == "Charca")
    assert (charca["lat"], charca["visits"], charca["watched_nights"], charca["per_night"]) == (
        CHARCA[0], 1, 30, 0.03,
    )
    assert {c["name"] for c in body["cameras"]} == {"Charca", "Unplaced"}

    assert client.get("/api/map/activity?nights=3", headers=headers).status_code == 422
    assert client.get("/api/map/activity?part=noon", headers=headers).status_code == 422
    assert client.get("/api/map/activity?species=lagomorph", headers=headers).status_code == 404
    assert client.get("/api/map/activity?species=unicorn", headers=headers).status_code == 404
    assert client.get("/api/map/activity").status_code in (401, 403)  # signed out


# ── replaying a night ───────────────────────────────────────────────────────


def test_replay_is_in_order_and_links_the_same_species_at_the_next_camera(db_session, estate):
    charca = _camera(db_session, estate, "Charca", CHARCA)
    encinar = _camera(db_session, estate, "Encinar", ENCINAR)
    far = _camera(db_session, estate, "Lejos", FAR)
    for s in range(3):
        _photo(db_session, encinar, _at(NIGHT, 20, 50, s), group=3)
    _photo(db_session, encinar, _at(NIGHT, 20, 52))
    _photo(db_session, charca, _at(NIGHT, 21, 40), group=4)  # 48 min after it left Encinar: linked
    _photo(db_session, charca, _at(NIGHT, 23, 10))  # the same camera: no line, the chain moves on
    _photo(db_session, far, _at(NIGHT, 23, 20))  # 12 km in 10 minutes: two sounders, no line
    _photo(db_session, charca, _at(NIGHT, 2, 15), ("red_deer",))
    _photo(db_session, encinar, _at(NIGHT, 4, 0), ("red_deer",))  # 1 h 45 later: linked

    got = replay(db_session, cameras=[charca, encinar, far], night=NIGHT)
    assert got["start"] == _at(NIGHT, 18) and got["end"] == _at(NIGHT, 8)
    assert [(v["label"], str(v["camera_id"]), v["at"]) for v in got["visits"]] == [
        ("Wild boar", str(encinar.id), _at(NIGHT, 20, 50)),
        ("Wild boar", str(charca.id), _at(NIGHT, 21, 40)),
        ("Wild boar", str(charca.id), _at(NIGHT, 23, 10)),
        ("Wild boar", str(far.id), _at(NIGHT, 23, 20)),
        ("Red deer", str(charca.id), _at(NIGHT, 2, 15)),
        ("Red deer", str(encinar.id), _at(NIGHT, 4, 0)),
    ]
    first = got["visits"][0]
    assert (first["group_size"], first["frames"], first["last_at"]) == (3, 4, _at(NIGHT, 20, 52))
    keys = ("species_id", "from_camera_id", "to_camera_id", "from_at", "to_at")
    assert [tuple(link[k] for k in keys) for link in got["links"]] == [
        ("wild_boar", str(encinar.id), str(charca.id), _at(NIGHT, 20, 52), _at(NIGHT, 21, 40)),
        ("red_deer", str(charca.id), str(encinar.id), _at(NIGHT, 2, 15), _at(NIGHT, 4, 0)),
    ]


def test_a_link_needs_another_camera_within_three_hours_after_the_first_left(db_session, estate):
    a = _camera(db_session, estate, "A", CHARCA)
    b = _camera(db_session, estate, "B", ENCINAR)
    unplaced = _camera(db_session, estate, "Unplaced", (None, None))
    cams = {c.id: c for c in (a, b, unplaced)}

    def visit(cam, start, end=None, species="wild_boar"):
        return {"camera_id": cam.id, "species_id": species, "label": "x",
                "first_at": start, "last_at": end or start}

    t = _at(NIGHT, 20)
    three = timedelta(hours=3)
    assert len(likely_paths([visit(a, t), visit(b, t + three)], cams)) == 1  # exactly 3 h
    assert likely_paths([visit(a, t), visit(b, t + three + timedelta(minutes=1))], cams) == []
    # Overlapping visits at two cameras are two groups, not one that moved.
    overlap = [visit(a, t, t + timedelta(minutes=20)), visit(b, t + timedelta(minutes=10))]
    assert likely_paths(overlap, cams) == []
    # Another species in between doesn't join or break anything.
    mixed = [visit(a, t), visit(b, t + timedelta(minutes=30), species="red_deer"),
             visit(b, t + timedelta(minutes=50))]
    assert [(link["species_id"], link["to_at"]) for link in likely_paths(mixed, cams)] == [
        ("wild_boar", t + timedelta(minutes=50)),
    ]
    # Unnamed animals and cameras that aren't on the map are never joined.
    unnamed = [visit(a, t, species=None), visit(b, t + timedelta(hours=1), species=None)]
    assert likely_paths(unnamed, cams) == []
    assert likely_paths([visit(a, t), visit(unplaced, t + timedelta(hours=1))], cams) == []


def test_replay_endpoints(client, db_session, estate):
    headers = _user(db_session, estate, "viewer")
    cam = _camera(db_session, estate)
    night = last_completed_night()
    img = _photo(db_session, cam, _at(night, 21, 40), group=4)
    _photo(db_session, cam, _at(night - timedelta(days=2), 22))
    _photo(db_session, cam, _at(night - timedelta(days=2), 23, 30), ("red_deer",))
    _photo(db_session, cam, _at(night - timedelta(days=5), 22))  # outside the three nights asked

    r = client.get("/api/map/replay/nights?limit=3", headers=headers)
    assert r.status_code == 200, r.text
    assert [n.pop("so_far") for n in r.json()][1:] == [False, False]
    assert [{k: v for k, v in n.items() if k != "so_far"} for n in r.json()] == [
        {"night": night.isoformat(), "visits": 1},
        {"night": (night - timedelta(days=1)).isoformat(), "visits": 0},
        {"night": (night - timedelta(days=2)).isoformat(), "visits": 2},
    ]
    assert len(client.get("/api/map/replay/nights", headers=headers).json()) == 14

    r = client.get(f"/api/map/replay?night={night.isoformat()}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["night"] == night.isoformat()
    assert datetime.fromisoformat(body["start"]) == _at(night, 18)
    assert datetime.fromisoformat(body["end"]) == _at(night, 8)
    (v,) = body["visits"]
    assert (v["camera_id"], v["species_id"], v["label"], v["group_size"], v["image_id"]) == (
        str(cam.id), "wild_boar", "Wild boar", 4, str(img.id),
    )
    assert datetime.fromisoformat(v["at"]) == _at(night, 21, 40)
    assert body["links"] == []

    # A night with nothing on it is an empty replay, not an error.
    before = (night - timedelta(days=1)).isoformat()
    quiet = client.get(f"/api/map/replay?night={before}", headers=headers)
    assert quiet.status_code == 200 and (quiet.json()["visits"], quiet.json()["links"]) == ([], [])
    assert client.get("/api/map/replay?night=yesterday", headers=headers).status_code == 422
    assert client.get("/api/map/replay/nights?limit=0", headers=headers).status_code == 422


def test_replay_times_are_the_estates_evening_whatever_the_server_clock(db_session, estate):
    cam = _camera(db_session, estate)
    got = replay(db_session, cameras=[cam], night=NIGHT)
    assert got["start"].astimezone(UTC) == datetime(2026, 9, 20, 16, 0, tzinfo=UTC)
    assert got["end"].astimezone(UTC) == datetime(2026, 9, 21, 6, 0, tzinfo=UTC)
    assert (got["visits"], got["links"]) == ([], [])
