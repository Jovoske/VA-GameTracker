"""The forecast counts nights and ranks cameras correctly (plan item 9).

Each test pins one way the plan used to mislead: nights counted by calendar date,
a camera too new to judge taking the headline, a camera in a drawer topping Tonight
on its old history, nights the AI hadn't checked counted as empty, photos counted
as visits, and the Changed line reading the night still under way.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.forecasting import alerts as alerts_mod
from app.forecasting import model
from app.forecasting.changes import whats_changed
from app.forecasting.exposure import current_night, recompute_camera_nights
from app.forecasting.model import forecast_tonight
from app.models import Camera, CameraNight, Detection, Estate, Image, Species, User

from .conftest import requires_db

MADRID = ZoneInfo("Europe/Madrid")
TONIGHT = current_night()


def at(night: date, hour: int, minute: int = 0) -> datetime:
    """A moment of the night keyed `night`, by the local clock (after midnight is
    the next calendar day)."""
    day = night if hour >= 6 else night + timedelta(days=1)
    return datetime.combine(day, time(hour, minute), tzinfo=MADRID).astimezone(UTC)


def ago(n: int) -> date:
    return TONIGHT - timedelta(days=n)


def empty(db, cam, night: date, hour: int = 20) -> Image:
    img = Image(camera_id=cam.id, captured_at=at(night, hour), is_empty_frame=True,
                processed_at=at(night, hour), reviewed=False)
    db.add(img)
    db.flush()
    return img


def seen(db, cam, night: date, hour: int = 22, minute: int = 0, *, species="wild_boar",
         sex=None, group=None, checked=True) -> Image:
    img = Image(camera_id=cam.id, captured_at=at(night, hour, minute),
                is_empty_frame=False if checked else None,
                processed_at=at(night, hour, minute) if checked else None, reviewed=False)
    db.add(img)
    db.flush()
    if checked:
        db.add(Detection(image_id=img.id, species_id=species, sex=sex, group_type=group,
                         group_size=1))
    return img


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(model, "_tonight_conditions", lambda now: {"moon_phase": "New Moon"})


@pytest.fixture
def estate(db_session):
    e = Estate(name="Piedras Lisas", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db_session.add(e)
    db_session.add_all([
        Species(id="wild_boar", common_name="Wild Boar", huntable=True, is_priority=True),
        Species(id="red_deer", common_name="Red Deer", huntable=True, is_priority=True),
        Species(id="roe_deer", common_name="Roe Deer", huntable=True, is_priority=True),
        Species(id="fox", common_name="Fox", huntable=True, is_priority=True),
    ])
    db_session.flush()
    return e


def camera(db, estate, name: str) -> Camera:
    # Sends photos only, and the last came in just now (health: sending).
    c = Camera(estate_id=estate.id, name=name, active=True, last_report_at=datetime.now(UTC))
    db.add(c)
    db.flush()
    return c


def watched(db, cam, first: int, last: int = 1) -> None:
    """An empty frame on every night from `first` nights ago to `last`: watching."""
    for n in range(last, first + 1):
        empty(db, cam, ago(n))


# ── G-01 / A-13: nights, not calendar dates ─────────────────────────────────


@requires_db
def test_a_visit_either_side_of_midnight_is_one_night(db_session, estate):
    """Boar at 23:40 and again at 00:20 is one night. Keyed by calendar date it was
    two, which gave "Wild boar seen 8 of the last 7 nights" and 16 of 21."""
    cam = camera(db_session, estate, "Puente")
    watched(db_session, cam, 20)
    for n in range(1, 9):  # the last eight nights
        seen(db_session, cam, ago(n), 23, 40)
        seen(db_session, cam, ago(n), 0, 20)
    db_session.commit()
    recompute_camera_nights(db_session)

    out = forecast_tonight(db_session)
    rec = out["recommended"]
    assert (rec["nights_present"], rec["active_nights"]) == (8, 20)
    assert rec["reason"] == "Wild boar seen 8 of 20 nights at this camera."
    assert out["factors"][0]["text"] == "Wild boar seen 7 of the last 7 nights here"
    assert out["nights_of_data"] == 20
    # Two arrivals a night, 40 minutes apart: 16 visits, 16 photos.
    assert (rec["visits"], rec["photos"]) == (16, 16)


@requires_db
def test_the_night_under_way_counts_neither_way(db_session, estate):
    """A boar this evening (or this morning) is tonight's news, not a finished night:
    it is not in "seen X of Y" and not in the last seven."""
    cam = camera(db_session, estate, "Puente")
    watched(db_session, cam, 20)
    seen(db_session, cam, ago(3))
    now = datetime.now(UTC) - timedelta(minutes=1)
    if current_night(now) == TONIGHT:
        img = Image(camera_id=cam.id, captured_at=now, is_empty_frame=False,
                    processed_at=now, reviewed=False)
        db_session.add(img)
        db_session.flush()
        db_session.add(Detection(image_id=img.id, species_id="wild_boar", group_size=1))
    db_session.commit()
    recompute_camera_nights(db_session)

    rec = forecast_tonight(db_session)["recommended"]
    assert (rec["nights_present"], rec["active_nights"]) == (1, 20)
    assert not db_session.query(CameraNight).filter_by(night=TONIGHT,
                                                       exposure_state="PRESUMED_UP").count()


# ── A-03 / G-03: a camera that can be judged leads ──────────────────────────


@requires_db
def test_a_camera_too_new_to_judge_does_not_take_the_headline(db_session, estate):
    old = camera(db_session, estate, "Old ridge")
    new = camera(db_session, estate, "New feeder")
    watched(db_session, old, 40)
    for n in range(1, 41):
        if n % 5 < 3:  # 24 of 40
            seen(db_session, old, ago(n))
    for n in range(1, 4):  # three nights, boar on all three
        seen(db_session, new, ago(n))
    db_session.commit()
    recompute_camera_nights(db_session)

    out = forecast_tonight(db_session)
    assert out["verdict"] == "BEST_ODDS"
    assert out["recommended"]["camera"] == "Old ridge"
    assert out["alternates"][0]["camera"] == "New feeder"
    assert out["alternates"][0]["verdict"] == "NO_DATA"
    assert [w["camera"] for w in out["where"]] == ["Old ridge", "New feeder"]


@requires_db
def test_with_no_camera_to_judge_the_headline_says_so(db_session, estate):
    new = camera(db_session, estate, "New feeder")
    for n in range(1, 4):
        seen(db_session, new, ago(n))
    db_session.commit()
    recompute_camera_nights(db_session)
    assert forecast_tonight(db_session)["verdict"] == "NO_DATA"


# ── K-01: a camera silent for over a week, and the Retire switch ────────────


@requires_db
def test_a_camera_silent_for_over_a_week_is_not_ranked_on_its_history(db_session, estate):
    """PL07 saw boar on 24 of 30 nights, then went in a drawer 20 days ago. It used to
    stay Best odds on Tonight for good; PL19, live, was pushed to Other places."""
    drawer = camera(db_session, estate, "PL07")
    drawer.spypoint_id = "sp-7"
    drawer.last_report_at = datetime.now(UTC) - timedelta(days=20)
    live = camera(db_session, estate, "PL19")
    live.spypoint_id, live.last_report_at = "sp-19", datetime.now(UTC)
    watched(db_session, drawer, 50, 21)
    for n in range(21, 51):
        if n % 5:
            seen(db_session, drawer, ago(n))
    watched(db_session, live, 20)
    for n in (1, 3, 5, 9, 12, 15):
        seen(db_session, live, ago(n))
    db_session.commit()
    recompute_camera_nights(db_session)

    out = forecast_tonight(db_session)
    assert out["recommended"]["camera"] == "PL19"
    assert [w["camera"] for w in out["where"]] == ["PL19"]
    [gone] = out["alerts"]
    assert gone["camera"] == "PL07" and gone["ranked"] is False
    # Its last photo was at 22:00 on the night 21 nights ago: 20 whole days until then,
    # 21 after (the day count must not depend on the hour the tests run at).
    days = (datetime.now(UTC) - at(ago(21), 22)).days
    assert gone["detail"].endswith(
        f"No photos for {days} days, so it is left out of tonight's ranking")


@requires_db
def test_retiring_a_camera_takes_it_out_of_the_plan_alerts_and_numbers(db_session, estate):
    from app.core.db import get_db
    from app.forecasting.insights import compute_insights
    from app.main import app

    admin = User(estate_id=estate.id, email="owner@x.local", password_hash="x", role="admin")
    member = User(estate_id=estate.id, email="pedro@x.local", password_hash="x", role="member")
    db_session.add_all([admin, member])
    drawer = camera(db_session, estate, "PL07")
    live = camera(db_session, estate, "PL19")
    for cam, every in ((drawer, 1), (live, 3)):
        watched(db_session, cam, 30)
        for n in range(1, 31):
            if n % every == 0:
                seen(db_session, cam, ago(n))
    db_session.commit()
    recompute_camera_nights(db_session)
    assert forecast_tonight(db_session)["recommended"]["camera"] == "PL07"

    def auth(user):
        return {"Authorization": f"Bearer {create_access_token(str(user.id), {'role': user.role})}"}

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            url = f"/api/cameras/{drawer.id}/retired"
            refused = client.patch(url, json={"retired": True}, headers=auth(member))
            assert refused.status_code == 403
            got = client.patch(url, json={"retired": True}, headers=auth(admin))
            assert got.status_code == 200 and got.json()["retired_at"]
            listed = {c["name"]: c for c in client.get("/api/cameras", headers=auth(member)).json()}
            assert listed["PL07"]["health"]["status"] == "retired"
            assert listed["PL07"]["retired_at"]
            overview = client.get("/api/analytics/overview", headers=auth(member)).json()
            assert [c["name"] for c in overview["by_camera"]] == ["PL19"]
            # Its photos stay in Photos.
            chips = client.get("/api/photos/filters", headers=auth(member)).json()["cameras"]
            assert "PL07" in {c["name"] for c in chips}
    finally:
        app.dependency_overrides.clear()

    out = forecast_tonight(db_session)
    assert out["recommended"]["camera"] == "PL19"
    assert [w["camera"] for w in out["where"]] == ["PL19"]
    assert out["alerts"] == []
    assert all("PL07" not in a["title"] for a in alerts_mod.compute_alerts(db_session))
    insights = compute_insights(db_session)
    assert {c["top_camera"] for c in insights["composition"]} == {"PL19"}
    # The routine exposure rebuild leaves it alone.
    db_session.query(CameraNight).filter_by(camera_id=drawer.id).delete()
    db_session.commit()
    recompute_camera_nights(db_session)
    assert db_session.query(CameraNight).filter_by(camera_id=drawer.id).count() == 0

    # Back from the drawer: in the plan again.
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            got = client.patch(f"/api/cameras/{drawer.id}/retired", json={"retired": False},
                               headers=auth(admin))
            assert got.status_code == 200 and got.json()["retired_at"] is None
    finally:
        app.dependency_overrides.clear()
    assert db_session.query(CameraNight).filter_by(camera_id=drawer.id).count() == 30
    assert forecast_tonight(db_session)["recommended"]["camera"] == "PL07"


# ── A-14 / G-02: nights the AI hasn't checked are left out, not empty ───────


@requires_db
def test_nights_the_ai_has_not_checked_are_left_out_not_counted_empty(db_session, estate):
    """Classified: Best odds, seen 7 of the last 7. Unclassified, the same photos read
    as "No Wild boar here in the last 7 nights" and Worth a look. Now the week that
    can't be read is left out, said so, and costs nothing."""
    cam = camera(db_session, estate, "Cerro")
    watched(db_session, cam, 30, 8)
    for n in range(8, 31):
        if n % 2 == 0:
            seen(db_session, cam, ago(n))
    for n in range(1, 8):  # the last week: photos in, not checked yet
        seen(db_session, cam, ago(n), checked=False)
    db_session.commit()
    recompute_camera_nights(db_session)

    out = forecast_tonight(db_session)
    rec = out["recommended"]
    assert (rec["nights_present"], rec["active_nights"]) == (12, 23)
    assert rec["probability"] == pytest.approx(0.52)  # no penalty for an unread week
    assert out["verdict"] == "BEST_ODDS"
    assert out["factors"][0]["text"] == (
        "Photos from 7 of the last 7 nights are still being checked. Going on its history.")
    assert out["exposure"] == {
        "excluded_nights": 7, "note": "7 nights at Cerro left out: photos not checked yet."}
    changed = whats_changed(db_session)
    assert changed["kind"] == "checking"
    assert changed["text"] == "Last night's photos from Cerro are still being checked."


@requires_db
def test_a_quiet_week_that_was_watched_still_counts_against(db_session, estate):
    cam = camera(db_session, estate, "Cerro")
    watched(db_session, cam, 30)
    for n in range(8, 31):
        if n % 2 == 0:
            seen(db_session, cam, ago(n))
    db_session.commit()
    recompute_camera_nights(db_session)

    out = forecast_tonight(db_session)
    assert out["factors"][0] == {"text": "No wild boar here in the last 7 nights", "impact": "--"}
    assert out["recommended"]["probability"] == pytest.approx(round(12 / 30 - 0.15, 2))


# ── A-24: no photos says so ─────────────────────────────────────────────────


@requires_db
def test_with_no_photos_it_is_zero_nights_not_one(db_session, estate):
    camera(db_session, estate, "Puente")
    db_session.commit()
    out = forecast_tonight(db_session)
    assert out["verdict"] == "NO_DATA"
    assert out["nights_of_data"] == 0


# ── J-24 / I-20: visits, and the animal the card names ──────────────────────


@requires_db
def test_counts_are_visits_and_the_top_card_lists_the_animal_it_names(db_session, estate):
    """A sow and piglets loitering for twelve frames is one visit, not "×12"; and a
    card that says boar lists boar, with the roe deer in the fold."""
    cam = camera(db_session, estate, "Charca")
    watched(db_session, cam, 20)
    for n in range(1, 21):
        if n % 2:
            for minute in range(0, 24, 2):  # one family, twelve frames, one visit
                seen(db_session, cam, ago(n), 22, minute, group="sow_with_piglets")
        for hour in (19, 21, 23):  # roe deer three times a night, never the target
            seen(db_session, cam, ago(n), hour, species="roe_deer")
    db_session.commit()
    recompute_camera_nights(db_session)

    out = forecast_tonight(db_session, species_ids=["wild_boar"])
    rec = out["recommended"]
    assert rec["species"] == "Wild boar"
    assert rec["classes"] == [{"label": "Sow + piglets", "visits": 10, "photos": 120}]
    assert rec["expect"] == "Sow + piglets"

    anything = forecast_tonight(db_session)
    rec = anything["recommended"]
    # Ranked by the nights an animal came, then visits: roe deer came every night.
    assert rec["species"] == "Roe deer"
    assert [c["label"] for c in rec["classes"]] == ["Roe deer"]
    fold = anything["where"][0]["classes"]
    assert {c["label"]: (c["visits"], c["photos"]) for c in fold} == {
        "Roe deer": (60, 60), "Sow + piglets": (10, 120)}


@requires_db
def test_the_classes_of_an_animal_add_up_to_its_visits(db_session, estate):
    """The sex and group pass looks at only some frames, so one arrival's frames carry
    two labels. Counted per label, each such arrival was a visit of both, and the top
    card listed about twice the visits the forecast, the map and Insights counted.
    Each visit is now of one class: the most telling label, then the most frames."""
    cam = camera(db_session, estate, "PL19 Charca")
    watched(db_session, cam, 26)
    for n in range(1, 11):  # a sow with piglets; only the first frame was sexed
        seen(db_session, cam, ago(n), 22, 0, group="sow_with_piglets")
        seen(db_session, cam, ago(n), 22, 2)
        seen(db_session, cam, ago(n), 22, 4)
    for n in range(11, 21):  # a boar frame and two sow frames: most frames say sow
        seen(db_session, cam, ago(n), 21, 0, sex="male")
        seen(db_session, cam, ago(n), 21, 2, sex="female")
        seen(db_session, cam, ago(n), 21, 4, sex="female")
    for n in range(21, 26):  # nobody sexed these
        seen(db_session, cam, ago(n), 23, 0)
        seen(db_session, cam, ago(n), 23, 10)
    # A night whose photos are not all checked yet is not counted, class or visit.
    seen(db_session, cam, ago(26), 22, 0, sex="male")
    seen(db_session, cam, ago(26), 23, 0, checked=False)
    db_session.commit()
    recompute_camera_nights(db_session)

    out = forecast_tonight(db_session)
    rec = out["recommended"]
    assert (rec["visits"], rec["photos"]) == (25, 70)
    assert rec["classes"] == [
        {"label": "Sow", "visits": 10, "photos": 30},
        {"label": "Sow + piglets", "visits": 10, "photos": 30},
        {"label": "Wild boar", "visits": 5, "photos": 10},
    ]
    assert sum(c["visits"] for c in rec["classes"]) == rec["visits"]
    assert sum(c["photos"] for c in rec["classes"]) == rec["photos"]
    fold = out["where"][0]["classes"]
    assert sum(c["visits"] for c in fold) == out["where"][0]["visits"]

    # Insights' makeup counts the same visits (the unchecked night's boar too: the
    # makeup is every visit of the season, as its summaries are).
    from app.forecasting.insights import compute_insights

    makeup = {c["label"]: c["visits"] for c in compute_insights(db_session)["composition"]}
    assert makeup == {"Sow + piglets": 10, "Sow": 10, "Wild boar": 5, "Boar": 1}


@requires_db
def test_a_renamed_animal_keeps_its_name_in_the_classes_and_their_photos(db_session, estate):
    """An admin's name for an animal (Settings) is what its tiles call a boar nobody
    sexed, capitals as typed. Tonight's classes, Insights' makeup and the photos
    behind each makeup line must use it too, or tapping "Jabalí" finds nothing."""
    from app.core.db import get_db
    from app.forecasting.insights import compute_insights
    from app.main import app

    db_session.get(Species, "wild_boar").common_name = "Jabalí"
    db_session.get(Species, "red_deer").common_name = "Ciervo Ibérico"
    admin = User(estate_id=estate.id, email="owner@x.local", password_hash="x", role="admin")
    db_session.add(admin)
    cam = camera(db_session, estate, "PL19 Charca")
    watched(db_session, cam, 20)
    shots = [seen(db_session, cam, ago(n), 22) for n in range(1, 6)]
    shots += [seen(db_session, cam, ago(n), 22, sex="male") for n in range(6, 9)]
    shots += [seen(db_session, cam, ago(n), 23, species="red_deer", group="herd")
              for n in range(1, 5)]
    for img in shots:
        img.original_path = f"/photos/{img.id}.jpg"
    db_session.commit()
    recompute_camera_nights(db_session)

    rec = forecast_tonight(db_session)["recommended"]
    assert [(c["label"], c["visits"]) for c in rec["classes"]] == [("Jabalí", 5), ("Boar", 3)]
    makeup = {c["label"]: c["visits"] for c in compute_insights(db_session)["composition"]}
    assert makeup == {"Jabalí": 5, "Boar": 3, "Ciervo Ibérico (herd)": 4}

    headers = {"Authorization": f"Bearer {create_access_token(str(admin.id), {'role': 'admin'})}"}
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            for label, visits in makeup.items():
                got = client.get("/api/insights/class", params={"label": label}, headers=headers)
                assert len(got.json()["items"]) == visits, label
    finally:
        app.dependency_overrides.clear()


# ── A-12 / G-18 / J-12: alerts don't work the plan out again ────────────────


@requires_db
def test_alerts_never_compute_the_forecast_or_repeat_its_camera_card(
    db_session, estate, monkeypatch,
):
    cam = camera(db_session, estate, "PL19")
    cam.spypoint_id, cam.last_report_at = "sp-19", datetime.now(UTC) - timedelta(hours=48)
    watched(db_session, cam, 10)
    seen(db_session, cam, ago(1))
    db_session.commit()
    recompute_camera_nights(db_session)

    def boom(*a, **k):
        raise AssertionError("the alerts must not work the plan out again")

    monkeypatch.setattr(model, "forecast_tonight", boom)
    feed = alerts_mod.compute_alerts(db_session)
    # Offline is on the plan's own "Cameras not sending" card; not repeated here.
    assert not any("offline" in a["title"] for a in feed)
    assert not hasattr(alerts_mod, "forecast_tonight")


@requires_db
def test_sighting_alerts_count_visits_of_the_animals_marked_as_mattering(db_session, estate):
    cam = camera(db_session, estate, "PL19")
    watched(db_session, cam, 3)
    for minute in range(0, 20, 2):  # ten frames, one visit
        seen(db_session, cam, ago(1), 22, minute)
    seen(db_session, cam, ago(1), 2)  # and back after 02:00
    db_session.get(Species, "red_deer").is_priority = False
    seen(db_session, cam, ago(1), 21, species="red_deer")
    db_session.commit()

    feed = [a for a in alerts_mod.compute_alerts(db_session) if a["type"] == "sighting"]
    assert [(a["title"], a["text"].split(",")[0]) for a in feed] == [
        ("Wild boar", "Seen 2 times in the last 2 days")]


# ── I-26: one name, one camera ──────────────────────────────────────────────


@requires_db
def test_a_second_camera_cannot_take_a_name_already_in_use(db_session, estate):
    from app.core.db import get_db
    from app.main import app

    admin = User(estate_id=estate.id, email="owner@x.local", password_hash="x", role="admin")
    db_session.add(admin)
    a = camera(db_session, estate, "Pinar Alto")
    camera(db_session, estate, "PL19 Charca")
    db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(admin.id), {'role': 'admin'})}"}
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            got = client.patch(f"/api/cameras/{a.id}/name", json={"name": "pl19 charca"},
                               headers=headers)
            assert got.status_code == 409
            assert got.json()["detail"] == (
                "Another camera is already called pl19 charca. Pick another name.")
            ok = client.patch(f"/api/cameras/{a.id}/name", json={"name": "Pinar Bajo"},
                              headers=headers)
            assert ok.status_code == 200
            # "Use camera's name" too: the vendor's default is often the same for all.
            a.provider_name = "SPYPOINT"
            camera(db_session, estate, "SPYPOINT")
            db_session.commit()
            back = client.patch(f"/api/cameras/{a.id}/name", json={"name": None},
                                headers=headers)
            assert back.status_code == 409
            assert back.json()["detail"] == (
                "Another camera is already called SPYPOINT, so this one keeps its own name.")
            db_session.refresh(a)
            assert (a.name, a.name_is_custom) == ("Pinar Bajo", True)
    finally:
        app.dependency_overrides.clear()


@requires_db
def test_two_cameras_that_share_a_name_are_two_cameras_in_insights(db_session, estate):
    """Two cameras left on the vendor's name merged into one busiest camera."""
    from app.forecasting.insights import compute_insights

    for name, visits in (("SPYPOINT", 10), ("SPYPOINT", 10), ("Loma", 15)):
        cam = camera(db_session, estate, name)
        for n in range(1, visits + 1):
            seen(db_session, cam, ago(n), 22)
    db_session.commit()
    places = [c["statement"] for c in compute_insights(db_session)["correlations"]
              if c["kind"] == "location"]
    assert places == ["Loma and SPYPOINT are your busiest cameras."]


# ── G-16 / J-10 / G-17: the Changed line ────────────────────────────────────


@requires_db
def test_after_midnight_last_night_is_the_night_before_the_one_under_way(db_session, estate):
    """At 01:00 on 1 Nov the night under way is 31 Oct's: "last night" is 30 Oct's.
    The server's calendar date said 31 Oct, and half a night read as a quiet one."""
    cam = camera(db_session, estate, "Puente")
    night = date(2025, 10, 31)
    for d in range(1, 15):
        for hour in (21, 23, 2, 4):
            seen(db_session, cam, night - timedelta(days=d), hour)
    for hour in (21, 23):  # the night under way, so far
        seen(db_session, cam, night, hour)
    db_session.commit()
    recompute_camera_nights(db_session)

    one_am = datetime(2025, 11, 1, 1, 0, tzinfo=MADRID)
    got = whats_changed(db_session, tonight=current_night(one_am))
    assert current_night(one_am) == night
    assert got["kind"] == "none", got


@requires_db
def test_one_more_boar_than_half_a_usual_one_is_not_news(db_session, estate):
    cam = camera(db_session, estate, "Puente")
    last = ago(1)
    for d in range(1, 11):
        empty(db_session, cam, last - timedelta(days=d))
        if d % 2:
            seen(db_session, cam, last - timedelta(days=d))
    seen(db_session, cam, last)
    db_session.commit()
    recompute_camera_nights(db_session)
    assert whats_changed(db_session)["kind"] == "none"


@requires_db
def test_a_real_shift_reads_in_plain_words(db_session, estate):
    cam = camera(db_session, estate, "Puente")
    last = ago(1)
    for d in range(1, 11):
        empty(db_session, cam, last - timedelta(days=d))
        for hour in (21, 23) if d % 2 else (21,):  # a usual of 1.5 visits
            seen(db_session, cam, last - timedelta(days=d), hour)
    for hour in (19, 21, 23, 1, 3):
        seen(db_session, cam, last, hour)
    db_session.commit()
    recompute_camera_nights(db_session)
    assert whats_changed(db_session)["text"] == (
        "Puente was busier than usual last night: 5 visits against a usual about 1.5.")


@requires_db
def test_tonight_never_says_nothing_changed_beside_a_quiet_camera(db_session, estate):
    """G-23: the quiet alert went by a month's total, the Changed line by the usual
    night, so a camera whose visits all came in one spell read "Nothing changed" on
    one line and "Puente quiet ... usually sees more" under Alerts. One rule now."""
    cam = camera(db_session, estate, "Puente")
    watched(db_session, cam, 29)
    for d in (10, 11, 12, 13):  # 16 visits, all in one spell
        for hour in (19, 21, 23, 2):
            seen(db_session, cam, ago(d), hour)
    db_session.commit()
    recompute_camera_nights(db_session)
    assert whats_changed(db_session)["kind"] == "none"
    assert not [a for a in alerts_mod.compute_alerts(db_session) if a["type"] == "quiet"]

    # A camera that usually sees two a night and has had none for five: both say
    # so, with the same numbers.
    busy = camera(db_session, estate, "Charca")
    watched(db_session, busy, 20)
    for d in range(6, 21):
        for hour in (21, 23):
            seen(db_session, busy, ago(d), hour)
    db_session.commit()
    recompute_camera_nights(db_session)
    assert whats_changed(db_session) == {
        "kind": "gone_quiet", "camera": "Charca",
        "text": "Charca has been quiet for 5 nights. It usually sees about 2 a night."}
    quiet, = [a for a in alerts_mod.compute_alerts(db_session) if a["type"] == "quiet"]
    assert quiet["camera"] == "Charca"
    assert quiet["text"] == (
        f"Nothing on its last 5 watched nights, since the night of {ago(6).day} "
        f"{ago(6):%b}. It usually sees about 2 a night.")


@requires_db
def test_gone_quiet_counts_only_nights_the_camera_was_watching(db_session, estate):
    """Three unchecked nights and one watched empty one used to be "quiet for 4
    nights". Only the watched ones count, and the run is the real length."""
    cam = camera(db_session, estate, "Puente")
    last = ago(1)
    for d in range(5, 20):
        for hour in (21, 23):
            seen(db_session, cam, last - timedelta(days=d), hour)
    unchecked = [seen(db_session, cam, last - timedelta(days=d), checked=False)
                 for d in (2, 3, 4)]
    empty(db_session, cam, last - timedelta(days=1))
    empty(db_session, cam, last)
    db_session.commit()
    recompute_camera_nights(db_session)
    got = whats_changed(db_session)
    assert got["kind"] == "none", "two watched empty nights are not yet a quiet spell"

    # The AI gets to them: nothing in any of them. Now it is five watched nights.
    for img in unchecked:
        img.is_empty_frame, img.processed_at = True, img.captured_at
    db_session.commit()
    recompute_camera_nights(db_session)
    assert whats_changed(db_session)["text"] == (
        "Puente has been quiet for 5 nights. It usually sees about 2 a night.")
