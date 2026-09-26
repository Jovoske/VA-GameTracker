"""Photos on the map: small copies of photos, and each camera's latest photo, its
"new to you" count and last night's visits.

What these pin down is what a hunter reads off the map: a count that belongs to the
person looking (not to whoever opened the camera last), a "last night" that counts
arrivals rather than burst frames, and hidden animals and empty frames that never
surface anywhere, not even as the thumbnail on a camera.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PImage
from sqlalchemy import select

from app.api import routes_images
from app.api.routes_map import NEW_CAP, last_completed_night, night_window
from app.core.config import settings
from app.core.security import create_access_token
from app.models import Camera, CameraNight, CameraView, Detection, Estate, Image, Species, User

from .conftest import requires_db

pytestmark = requires_db


@pytest.fixture
def client(db_session):
    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def media(tmp_path, monkeypatch):
    root = tmp_path / "media"
    root.mkdir()
    monkeypatch.setattr(settings, "media_root", str(root))
    return root


@pytest.fixture
def estate(db_session):
    e = Estate(name="Piedras Lisas", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db_session.add(e)
    db_session.add_all([
        Species(id="wild_boar", common_name="Wild boar", is_priority=True),
        Species(id="red_deer", common_name="Red deer", is_priority=True),
        Species(id="lagomorph", common_name="Rabbit", hidden=True),
    ])
    db_session.commit()
    return e


def _user(db, estate, role="admin"):
    u = User(estate_id=estate.id, email=f"{role}-{uuid.uuid4().hex[:6]}@estate.local",
             password_hash="x", role=role)
    db.add(u)
    db.commit()
    return u, {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


def _camera(db, estate, name="Charca", lat=39.095, lon=-1.362):
    c = Camera(estate_id=estate.id, name=name, lat=lat, lon=lon, battery_pct=80, signal_pct=60,
               last_report_at=datetime.now(UTC))
    db.add(c)
    db.commit()
    return c


def _jpeg(path, size=(640, 480), orientation: int | None = None):
    im = PImage.new("RGB", size, (90, 120, 60))
    exif = PImage.Exif()
    if orientation:
        exif[0x0112] = orientation
    im.save(path, "JPEG", quality=85, exif=exif.tobytes())
    return str(path)


def _photo(db, cam, at, species=("wild_boar",), *, empty=False, created=None, path="photo.jpg"):
    """One frame. `species` are the detections in it; () is an animal nobody named."""
    img = Image(camera_id=cam.id, captured_at=at, original_path=path, is_empty_frame=empty,
                created_at=created or at + timedelta(minutes=20))
    db.add(img)
    db.flush()
    for sid in species:
        db.add(Detection(image_id=img.id, species_id=sid, species_conf=0.9))
    db.commit()
    return img


def _map(client, headers) -> dict:
    r = client.get("/api/map/cameras", headers=headers)
    assert r.status_code == 200, r.text
    return {c["name"]: c for c in r.json()}


# ── thumbnails ──────────────────────────────────────────────────────────────


def test_thumb_is_a_small_upright_webp_made_once_and_cached(
    client, db_session, estate, media, tmp_path, monkeypatch,
):
    _, headers = _user(db_session, estate, "viewer")
    cam = _camera(db_session, estate)
    # Orientation 6: the sensor wrote it on its side; upright it is 480 wide by 640 tall.
    src = _jpeg(tmp_path / "side.jpg", (640, 480), orientation=6)
    img = _photo(db_session, cam, datetime.now(UTC), path=src)

    r = client.get(f"/api/images/{img.id}/thumb", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable"
    out = tmp_path / "out.webp"
    out.write_bytes(r.content)
    with PImage.open(out) as thumb:
        assert thumb.format == "WEBP"
        assert thumb.size == (320, 427)  # upright, 320 wide
    db_session.refresh(img)
    assert img.thumbnail_path and img.thumbnail_path.startswith(str(media / "thumbs"))

    # The second request is served from disk, not made again.
    monkeypatch.setattr(routes_images, "make_thumb", lambda *a: pytest.fail("made twice"))
    again = client.get(f"/api/images/{img.id}/thumb", headers=headers)
    assert again.status_code == 200 and again.content == r.content


def test_thumb_takes_the_token_in_the_query_like_the_file_does(
    client, db_session, estate, media, tmp_path,
):
    user, _ = _user(db_session, estate, "member")
    cam = _camera(db_session, estate)
    img = _photo(db_session, cam, datetime.now(UTC), path=_jpeg(tmp_path / "a.jpg"))
    token = create_access_token(str(user.id))

    assert client.get(f"/api/images/{img.id}/thumb").status_code == 401
    assert client.get(f"/api/images/{img.id}/thumb?token=not-a-token").status_code == 401
    assert client.get(f"/api/images/{img.id}/thumb?token={token}").status_code == 200


def test_thumb_404s_for_an_unknown_photo_or_a_missing_file(client, db_session, estate, media):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    gone = _photo(db_session, cam, datetime.now(UTC), path=str(media / "never-written.jpg"))
    assert client.get(f"/api/images/{uuid.uuid4()}/thumb", headers=headers).status_code == 404
    assert client.get(f"/api/images/{gone.id}/thumb", headers=headers).status_code == 404


def test_thumb_outlives_its_original(client, db_session, estate, media, tmp_path):
    """Originals are pruned after a while; the small copy can stay and still shows."""
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    src = tmp_path / "pruned.jpg"
    img = _photo(db_session, cam, datetime.now(UTC), path=_jpeg(src))
    assert client.get(f"/api/images/{img.id}/thumb", headers=headers).status_code == 200
    src.unlink()
    r = client.get(f"/api/images/{img.id}/thumb", headers=headers)
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"


def test_thumb_falls_back_to_the_original_when_it_cannot_be_made(
    client, db_session, estate, media, tmp_path,
):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"\xff\xd8 this is not really a jpeg")
    img = _photo(db_session, cam, datetime.now(UTC), path=str(broken))

    r = client.get(f"/api/images/{img.id}/thumb", headers=headers)
    assert r.status_code == 200
    assert r.content == broken.read_bytes()
    # Not cached for a year: the next request tries to make the small copy again.
    assert "immutable" not in r.headers["cache-control"]
    db_session.refresh(img)
    assert img.thumbnail_path is None
    assert not list(media.rglob("*.tmp"))


# ── seen and new ────────────────────────────────────────────────────────────


def test_new_count_belongs_to_the_person_looking(client, db_session, estate):
    alice, a_headers = _user(db_session, estate, "member")
    _, b_headers = _user(db_session, estate, "viewer")
    cam = _camera(db_session, estate)
    now = datetime.now(UTC)
    for m in (50, 40, 30):
        _photo(db_session, cam, now - timedelta(minutes=m), created=now - timedelta(minutes=m - 5))

    assert _map(client, a_headers)["Charca"]["new_count"] == 3
    assert _map(client, b_headers)["Charca"]["new_count"] == 3

    # Alice opens the camera. Only Alice's count clears; viewers may mark too.
    r = client.post(f"/api/cameras/{cam.id}/seen", headers=a_headers)
    assert r.status_code == 200 and r.json()["camera_id"] == str(cam.id)
    assert _map(client, a_headers)["Charca"]["new_count"] == 0
    assert _map(client, b_headers)["Charca"]["new_count"] == 3
    assert client.post(f"/api/cameras/{cam.id}/seen", headers=b_headers).status_code == 200
    assert _map(client, b_headers)["Charca"]["new_count"] == 0

    # A photo that arrives afterwards is new to both.
    _photo(db_session, cam, now, created=datetime.now(UTC) + timedelta(seconds=5))
    assert _map(client, a_headers)["Charca"]["new_count"] == 1
    assert _map(client, b_headers)["Charca"]["new_count"] == 1

    # Opening it again moves the same row forward rather than adding one.
    client.post(f"/api/cameras/{cam.id}/seen", headers=a_headers)
    rows = db_session.scalars(select(CameraView).where(CameraView.user_id == alice.id)).all()
    assert len(rows) == 1


def test_never_opened_counts_only_the_last_day_and_caps_at_99(client, db_session, estate):
    _, headers = _user(db_session, estate)
    quiet = _camera(db_session, estate, "Quiet")
    busy = _camera(db_session, estate, "Busy")
    now = datetime.now(UTC)
    _photo(db_session, quiet, now - timedelta(days=3), created=now - timedelta(days=3))
    _photo(db_session, quiet, now - timedelta(hours=2), created=now - timedelta(hours=2))
    db_session.add_all([
        Image(camera_id=busy.id, captured_at=now - timedelta(minutes=i), original_path="x.jpg",
              is_empty_frame=False, created_at=now - timedelta(minutes=i))
        for i in range(NEW_CAP + 20)
    ])
    db_session.commit()
    cams = _map(client, headers)
    assert cams["Quiet"]["new_count"] == 1
    assert cams["Busy"]["new_count"] == NEW_CAP


def test_seen_is_only_for_this_estates_cameras(client, db_session, estate):
    _, headers = _user(db_session, estate)
    other = Estate(name="Elsewhere", timezone="Europe/Madrid")
    db_session.add(other)
    db_session.commit()
    theirs = _camera(db_session, other, "Theirs")
    assert client.post(f"/api/cameras/{theirs.id}/seen", headers=headers).status_code == 404
    assert client.post(f"/api/cameras/{uuid.uuid4()}/seen", headers=headers).status_code == 404
    assert client.post(f"/api/cameras/{theirs.id}/seen").status_code in (401, 403)
    assert "Theirs" not in _map(client, headers)


# ── latest photo and last night ─────────────────────────────────────────────


def test_hidden_animals_and_empty_frames_never_reach_the_map(client, db_session, estate):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    start, _ = night_window(last_completed_night())
    arrived = datetime.now(UTC) - timedelta(hours=1)
    boar = _photo(db_session, cam, start + timedelta(hours=2), ("wild_boar",), created=arrived)
    # Newer, but nothing anyone should see: a rabbit, a frame marked "nothing in it",
    # and a photo that is a boar the detector saw but a hunter marked empty.
    _photo(db_session, cam, start + timedelta(hours=3), ("lagomorph",), created=arrived)
    _photo(db_session, cam, start + timedelta(hours=4), (), empty=True, created=arrived)
    _photo(db_session, cam, start + timedelta(hours=5), ("wild_boar",), empty=True, created=arrived)

    got = _map(client, headers)["Charca"]
    assert got["latest"]["image_id"] == str(boar.id)
    assert got["latest"]["label"] == "Wild boar"
    assert got["last_night"] == [{"species_id": "wild_boar", "label": "Wild boar", "visits": 1}]
    # Everything above arrived within the day, but only the boar is new.
    assert got["new_count"] == 1


def test_a_photo_with_a_rabbit_and_a_boar_is_labelled_by_the_boar(client, db_session, estate):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    start, _ = night_window(last_completed_night())
    both = _photo(db_session, cam, start + timedelta(hours=1), ("lagomorph", "wild_boar"))
    got = _map(client, headers)["Charca"]
    assert got["latest"] == {
        "image_id": str(both.id), "captured_at": got["latest"]["captured_at"],
        "species_id": "wild_boar", "label": "Wild boar",
    }
    assert [v["species_id"] for v in got["last_night"]] == ["wild_boar"]


def test_last_night_counts_visits_not_frames(client, db_session, estate):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    start, end = night_window(last_completed_night())
    # A burst of three frames in one second, then the same sounder back 45 min later.
    first = start + timedelta(hours=3)
    for _ in range(3):
        _photo(db_session, cam, first)
    _photo(db_session, cam, first + timedelta(minutes=10))  # still the same visit
    _photo(db_session, cam, first + timedelta(minutes=55))  # a new arrival
    # One stag, two frames.
    _photo(db_session, cam, first + timedelta(hours=1), ("red_deer",))
    _photo(db_session, cam, first + timedelta(hours=1, seconds=1), ("red_deer",))
    # Outside the night: the afternoon before and the morning after.
    _photo(db_session, cam, start - timedelta(hours=2))
    _photo(db_session, cam, end + timedelta(hours=1))

    got = _map(client, headers)["Charca"]
    assert got["last_night"] == [
        {"species_id": "wild_boar", "label": "Wild boar", "visits": 2},
        {"species_id": "red_deer", "label": "Red deer", "visits": 1},
    ]


def test_last_night_says_whether_the_camera_was_watching(client, db_session, estate):
    _, headers = _user(db_session, estate)
    up = _camera(db_session, estate, "Up")
    down = _camera(db_session, estate, "Down")
    _camera(db_session, estate, "No record")
    night = last_completed_night()
    db_session.add_all([
        CameraNight(camera_id=up.id, night=night, exposure_state="PRESUMED_UP"),
        CameraNight(camera_id=down.id, night=night, exposure_state="UNKNOWN"),
    ])
    db_session.commit()
    cams = _map(client, headers)
    assert cams["Up"]["last_night"] == [] and cams["Up"]["last_night_watched"] is True
    assert cams["Down"]["last_night_watched"] is False
    assert cams["No record"]["last_night_watched"] is None
    assert cams["No record"]["latest"] is None and cams["No record"]["new_count"] == 0


def test_map_cameras_carries_position_health_and_who_may_rename(client, db_session, estate):
    _, admin = _user(db_session, estate, "admin")
    _, viewer = _user(db_session, estate, "viewer")
    _camera(db_session, estate)
    got = _map(client, admin)["Charca"]
    assert (got["lat"], got["lon"]) == (39.095, -1.362)
    assert (got["battery_pct"], got["signal_pct"]) == (80, 60)
    assert got["health"]["status"] == "ok"
    assert got["can_rename"] is True
    assert _map(client, viewer)["Charca"]["can_rename"] is False
