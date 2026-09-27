"""People and vehicles on camera (feature 25, audit F-25).

MegaDetector's person and vehicle classes used to be dropped, so a walker or a truck
at a stand was filed as an empty frame. Now the detector's surest person and vehicle
are kept with the photo, and such a frame is an admin's alone: out of the team's
feed, galleries, notes and pushes, out of every count, and listed apart under
"People & vehicles" in Photos. An admin can say nobody is in one the detector
misread (a feeder taken for a vehicle), and older photos are looked at again for
people in daylight. The heavy models are stand-ins here.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PImage
from sqlalchemy import select

from app.ai import checking, species
from app.api.visibility import PERSON_MIN, VEHICLE_MIN, is_people
from app.core.security import create_access_token, hash_password, image_token
from app.models import Camera, Detection, Estate, Image, Notification, Species, User

from .conftest import requires_db

NIGHT = datetime(2026, 9, 20, 20, 0, tzinfo=UTC)
BOAR = {"confidence": 0.93, "bbox": [100.0, 100.0, 400.0, 300.0]}
PERSON = {"category": 1, "confidence": 0.81, "bbox": [500.0, 80.0, 560.0, 300.0]}
TRUCK = {"category": 2, "confidence": 0.77, "bbox": [0.0, 200.0, 300.0, 400.0]}


@pytest.fixture
def client(db_session):
    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def cam(db_session):
    estate = Estate(name="Piedras Lisas", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db_session.add(estate)
    db_session.flush()
    c = Camera(estate_id=estate.id, name="Puente", active=True)
    db_session.add(c)
    db_session.add(Species(id="wild_boar", common_name="Wild boar", is_priority=True))
    db_session.commit()
    return c


def _user(db, cam, role):
    u = User(estate_id=cam.estate_id, email=f"{role}@estate.local",
             password_hash=hash_password("x" * 12), role=role)
    db.add(u)
    db.commit()
    return u, {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


@pytest.fixture
def admin(db_session, cam):
    return _user(db_session, cam, "admin")


@pytest.fixture
def member(db_session, cam):
    return _user(db_session, cam, "member")


@pytest.fixture
def models(monkeypatch):
    """The detector answers `boxes[path]` (default: a boar); the species model says boar."""
    state = {"boxes": {}, "raises": {}}

    def detect(path):
        if path in state["raises"]:
            raise state["raises"][path]
        return state["boxes"].get(path, [BOAR])

    monkeypatch.setattr(checking, "load_models", lambda: None)
    monkeypatch.setattr(checking, "detect", detect)
    monkeypatch.setattr(species, "detect_animals", lambda path: [BOAR])
    monkeypatch.setattr(species, "classify_crop",
                        lambda path, bbox: ("wild_boar", "Wild boar", 0.9))
    monkeypatch.setattr(checking, "models_work", lambda: None)
    monkeypatch.setattr("app.notifications.dispatch.dispatch_new_sightings", lambda db: None)
    return state


def _frame(db, cam, at, path, **kw):
    img = Image(camera_id=cam.id, captured_at=at, original_path=path, **kw)
    db.add(img)
    db.commit()
    return img


def _seen(db, cam, at, path, **kw):
    """A photo the AI checked and kept as a boar."""
    img = _frame(db, cam, at, path, is_empty_frame=False, processed_at=at, animal_conf=0.9, **kw)
    db.add(Detection(image_id=img.id, species_id="wild_boar", species_conf=0.9))
    db.commit()
    return img


def _ids(items) -> list[str]:
    return [i["image_id"] for i in items]


# ── the detector keeps them, the team never sees them ───────────────────────────


@requires_db
def test_the_detector_keeps_people_and_vehicles_and_the_team_never_sees_those_frames(
    client, db_session, cam, admin, member, models,
):
    walker = _frame(db_session, cam, NIGHT, "walker.jpg")
    truck = _frame(db_session, cam, NIGHT + timedelta(minutes=5), "truck.jpg")
    dog_walk = _frame(db_session, cam, NIGHT + timedelta(minutes=10), "dogwalk.jpg")
    boar = _frame(db_session, cam, NIGHT + timedelta(minutes=30), "boar.jpg")
    models["boxes"] = {"walker.jpg": [PERSON], "truck.jpg": [TRUCK],
                       "dogwalk.jpg": [BOAR, PERSON], "boar.jpg": [BOAR]}
    checking.check_photos(db_session)
    for img in (walker, truck, dog_walk, boar):
        db_session.refresh(img)
    # A person alone is still "no animal" to the detector, but it is not lost now.
    assert (walker.is_empty_frame, walker.person_conf, walker.vehicle_conf) == (True, 0.81, 0.0)
    assert (truck.is_empty_frame, truck.person_conf, truck.vehicle_conf) == (True, 0.0, 0.77)
    assert (dog_walk.is_empty_frame, dog_walk.person_conf) == (False, 0.81)
    assert (boar.person_conf, boar.vehicle_conf) == (0.0, 0.0)
    assert [is_people(i) for i in (walker, truck, dog_walk, boar)] == [True, True, True, False]

    feed = client.get("/api/photos", headers=member[1]).json()["items"]
    assert _ids(feed) == [str(boar.id)]
    assert _ids(client.get("/api/photos", headers=admin[1]).json()["items"]) == [str(boar.id)]
    chips = client.get("/api/photos/filters", headers=member[1]).json()
    assert chips["people"] is None
    assert chips["species"] == [{"id": "wild_boar", "common_name": "Wild boar", "count": 1}]
    assert client.get("/api/photos/filters", headers=admin[1]).json()["people"] == 3

    # Cameras: not among the empties either, and not counted as one.
    listed = client.get(f"/api/cameras/{cam.id}/images?include_empty=true",
                        headers=member[1]).json()
    assert [i["id"] for i in listed] == [str(boar.id)]
    card = next(c for c in client.get("/api/cameras", headers=member[1]).json()
                if c["id"] == str(cam.id))
    assert (card["animal_count"], card["empty_count"]) == (1, 0)
    # The map's newest photo is the boar's, not the walk.
    pin = client.get("/api/map/cameras", headers=member[1]).json()[0]
    assert pin["latest"]["image_id"] == str(boar.id)


@requires_db
def test_people_and_vehicles_are_listed_apart_for_an_admin_only(
    client, db_session, cam, admin, member,
):
    walker = _frame(db_session, cam, NIGHT, "walker.jpg", is_empty_frame=True,
                    processed_at=NIGHT, person_conf=0.6, vehicle_conf=0.0)
    both = _frame(db_session, cam, NIGHT + timedelta(minutes=2), "both.jpg", is_empty_frame=True,
                  processed_at=NIGHT, person_conf=0.5, vehicle_conf=0.9)
    dog_walk = _seen(db_session, cam, NIGHT + timedelta(minutes=4), "dog.jpg", person_conf=0.7)
    _seen(db_session, cam, NIGHT + timedelta(minutes=6), "boar.jpg", person_conf=0.0)

    assert client.get("/api/photos?people=true", headers=member[1]).status_code == 403
    page = client.get("/api/photos?people=true", headers=admin[1]).json()
    assert _ids(page["items"]) == [str(dog_walk.id), str(both.id), str(walker.id)]
    assert [(i["label"], i["has_person"], i["has_vehicle"]) for i in page["items"]] == [
        ("Person · Wild boar", True, False),
        ("Person and vehicle", True, True),
        ("Person", True, False),
    ]
    # The camera chips still narrow it.
    other = Camera(estate_id=cam.estate_id, name="Solana", active=True)
    db_session.add(other)
    db_session.commit()
    assert client.get(f"/api/photos?people=true&cameras={other.id}",
                      headers=admin[1]).json()["items"] == []


@requires_db
@pytest.mark.parametrize("person,vehicle,people", [
    (PERSON_MIN - 0.01, 0.0, False),
    (PERSON_MIN, 0.0, True),
    (0.0, VEHICLE_MIN - 0.01, False),  # a feeder half-read as a vehicle is not enough
    (0.0, VEHICLE_MIN, True),
    (None, None, False),  # not looked at for people yet
])
def test_the_bar_for_a_person_is_lower_than_for_a_vehicle(
    client, db_session, cam, member, person, vehicle, people,
):
    img = _seen(db_session, cam, NIGHT, "a.jpg", person_conf=person, vehicle_conf=vehicle)
    assert is_people(img) is people
    shown = _ids(client.get("/api/photos", headers=member[1]).json()["items"])
    assert shown == ([] if people else [str(img.id)])


@requires_db
def test_the_team_cant_open_notes_on_or_fix_a_frame_of_people(
    client, db_session, cam, admin, member, tmp_path,
):
    img = _seen(db_session, cam, NIGHT, str(tmp_path / "walk.jpg"), person_conf=0.9)
    PImage.new("RGB", (64, 48), (90, 120, 60)).save(img.original_path, "JPEG")
    for who, want in ((member, 404), (admin, 200)):
        token = image_token(who[0])
        assert client.get(f"/api/images/{img.id}/file?token={token}").status_code == want
        assert client.get(f"/api/images/{img.id}/thumb?token={token}").status_code == want
        assert client.get(f"/api/images/{img.id}/notes", headers=who[1]).status_code == want
    assert client.post(f"/api/images/{img.id}/flag", json={"is_empty": True},
                       headers=member[1]).status_code == 404
    assert client.get(f"/api/photos/{img.id}", headers=member[1]).status_code == 404
    # Not even an admin sends the team to it: a note is for the team to see.
    r = client.post(f"/api/images/{img.id}/notes", json={"text": "Who is this?", "tell_team": True},
                    headers=admin[1])
    assert r.status_code == 409 and "person or a vehicle" in r.json()["detail"]


@requires_db
def test_a_frame_of_people_is_never_counted_or_pushed(db_session, cam, monkeypatch):
    from app.models import NotificationPref
    from app.notifications import dispatch
    from app.notifications.dispatch import dispatch_new_sightings

    sent = []
    monkeypatch.setattr(dispatch.push, "send_to_user",
                        lambda db, uid, payload, quiet=False: sent.append(payload) or {
                            "sent": 1, "failed": 0, "removed": 0, "subscriptions": 1})
    hunter = User(estate_id=cam.estate_id, email="pedro@estate.local", password_hash="h",
                  role="member")
    db_session.add(hunter)
    db_session.flush()
    db_session.add(NotificationPref(user_id=hunter.id, enabled=True, species_ids=["wild_boar"]))
    db_session.commit()
    t0 = datetime.now(UTC)
    dispatch_new_sightings(db_session, now=t0)  # primes the watermark
    t1 = t0 + timedelta(minutes=15)
    walk = _seen(db_session, cam, t1 - timedelta(minutes=3), "walk.jpg", person_conf=0.8)
    db_session.query(Detection).filter_by(image_id=walk.id).update(
        {"created_at": t1 - timedelta(minutes=1)})
    db_session.commit()
    result = dispatch_new_sightings(db_session, now=t1)
    assert result["notifications"] == 0 and sent == []
    assert db_session.query(Notification).count() == 0

    from app.forecasting.visits import visit_rows

    visits = visit_rows(start=t1 - timedelta(hours=1), end=t1)
    assert db_session.execute(select(visits)).all() == []


# ── an admin's "nobody in it" ───────────────────────────────────────────────────


@requires_db
def test_an_admin_can_say_nobody_is_in_a_frame_and_take_it_back(
    client, db_session, cam, admin, member,
):
    feeder = _seen(db_session, cam, NIGHT, "feeder.jpg", person_conf=0.0, vehicle_conf=0.55)
    url = f"/api/images/{feeder.id}/people"
    assert client.post(url, json={"cleared": True}, headers=member[1]).status_code == 403
    r = client.post(url, json={"cleared": True}, headers=admin[1])
    assert r.json() == {"id": str(feeder.id), "people_cleared": True,
                        "has_person": False, "has_vehicle": False}
    assert _ids(client.get("/api/photos", headers=member[1]).json()["items"]) == [str(feeder.id)]
    assert client.get("/api/photos?people=true", headers=admin[1]).json()["items"] == []
    db_session.refresh(feeder)
    assert feeder.vehicle_conf == 0.55  # what the detector said is kept
    # Nothing to clear on a frame nobody is in.
    boar = _seen(db_session, cam, NIGHT + timedelta(hours=1), "boar.jpg", person_conf=0.0)
    assert client.post(f"/api/images/{boar.id}/people", json={"cleared": True},
                       headers=admin[1]).status_code == 409
    # Undo: an admin's photo again.
    assert client.post(url, json={"cleared": False}, headers=admin[1]).json()["has_vehicle"]
    assert _ids(client.get("/api/photos", headers=member[1]).json()["items"]) == [str(boar.id)]


# ── older photos ────────────────────────────────────────────────────────────────


@requires_db
def test_photos_checked_before_are_looked_at_again_for_people_in_daylight(
    db_session, cam, models,
):
    now = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)  # noon in Madrid
    old_walk = _seen(db_session, cam, now - timedelta(days=2), "oldwalk.jpg")
    old_boar = _seen(db_session, cam, now - timedelta(days=3), "oldboar.jpg")
    flagged = _frame(db_session, cam, now - timedelta(days=4), "flagged.jpg", is_empty_frame=True,
                     reviewed=True, processed_at=now - timedelta(days=4))
    broken = _seen(db_session, cam, now - timedelta(days=5), "broken.jpg")
    long_ago = _seen(db_session, cam, now - timedelta(days=90), "longago.jpg")
    models["boxes"] = {"oldwalk.jpg": [BOAR, PERSON], "oldboar.jpg": [BOAR],
                       "flagged.jpg": [TRUCK]}
    models["raises"]["broken.jpg"] = OSError("cannot identify image file")

    assert checking.check_photos(db_session, now=now.replace(hour=19))["rescanned"] == 0
    result = checking.check_photos(db_session, now=now)
    assert result["rescanned"] == 3 and result["found_on_rescan"] == 0
    for img in (old_walk, old_boar, flagged, broken, long_ago):
        db_session.refresh(img)
    assert (old_walk.person_conf, old_boar.person_conf) == (0.81, 0.0)
    # A hunter's "nothing in it" stands, and the truck in it is on record all the same.
    assert (flagged.is_empty_frame, flagged.reviewed, flagged.vehicle_conf) == (True, True, 0.77)
    # A photo that won't read is left as it was judged, and not tried again.
    assert (broken.person_conf, broken.vehicle_conf, broken.detector_conf) == (0.0, 0.0, None)
    assert long_ago.person_conf is None
    # Kept as a boar: no second sighting from looking again.
    assert db_session.scalar(
        select(Detection.id).where(Detection.image_id == old_walk.id)) is not None
    assert db_session.query(Detection).filter_by(image_id=old_walk.id).count() == 1
    assert checking.check_photos(db_session, now=now)["rescanned"] == 0  # once each


def test_boxes_from_before_people_were_looked_for_are_animals():
    from app.ai.detector import split

    animals, person, vehicle = split([BOAR, PERSON, TRUCK, {**PERSON, "confidence": 0.33}])
    assert animals == [BOAR] and (person, vehicle) == (0.81, 0.77)
    assert split([])[1:] == (0.0, 0.0)
