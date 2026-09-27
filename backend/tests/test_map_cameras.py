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
from sqlalchemy import create_engine, insert, select, text

from app.ai import empty_filter
from app.api import routes_images, routes_map
from app.api.routes_map import NEW_CAP, last_completed_night, night_window
from app.core.config import settings
from app.core.security import create_access_token, image_token
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
    # Named the way the classifier stores them (title case); the map says "Wild boar".
    db_session.add_all([
        Species(id="wild_boar", common_name="Wild Boar", is_priority=True),
        Species(id="red_deer", common_name="Red Deer", is_priority=True),
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
    """One frame. `species` are the detections in it; () is an animal nobody named.

    `empty` is the detector's verdict: False kept, True "nothing in it", None not
    checked yet.
    """
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


def test_thumb_takes_the_photo_pass_in_the_query_like_the_file_does(
    client, db_session, estate, media, tmp_path,
):
    user, _ = _user(db_session, estate, "member")
    cam = _camera(db_session, estate)
    img = _photo(db_session, cam, datetime.now(UTC), path=_jpeg(tmp_path / "a.jpg"))

    assert client.get(f"/api/images/{img.id}/thumb").status_code == 401
    assert client.get(f"/api/images/{img.id}/thumb?token=not-a-token").status_code == 401
    assert client.get(f"/api/images/{img.id}/thumb?token={image_token(user)}").status_code == 200
    # The sign-in itself is not taken in an address (audit C-19, H-13).
    signin = create_access_token(str(user.id))
    assert client.get(f"/api/images/{img.id}/thumb?token={signin}").status_code == 401


def test_photo_files_are_for_this_estates_logins_only(client, db_session, estate, media, tmp_path):
    """A removed login stops seeing photos at once, and another estate never does.

    An <img> can't send a header, so these check the token themselves; they must
    still look the person up, as every other endpoint does.
    """
    cam = _camera(db_session, estate)
    img = _photo(db_session, cam, datetime.now(UTC), path=_jpeg(tmp_path / "a.jpg"))
    guest, guest_h = _user(db_session, estate, "viewer")
    urls = [f"/api/images/{img.id}/thumb", f"/api/images/{img.id}/file"]
    assert [client.get(u, headers=guest_h).status_code for u in urls] == [200, 200]

    other = Estate(name="Elsewhere", timezone="Europe/Madrid")
    db_session.add(other)
    db_session.commit()
    _, stranger = _user(db_session, other, "admin")
    assert [client.get(u, headers=stranger).status_code for u in urls] == [404, 404]
    assert client.post(f"/api/images/{img.id}/flag", headers=stranger,
                       json={"is_empty": True}).status_code == 404

    token = image_token(guest)
    assert [client.get(f"{u}?token={token}").status_code for u in urls] == [200, 200]
    db_session.delete(guest)
    db_session.commit()
    assert [client.get(u, headers=guest_h).status_code for u in urls] == [401, 401]
    assert [client.get(f"{u}?token={token}").status_code for u in urls] == [401, 401]


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


def test_a_photo_stored_while_you_look_still_counts_as_new(client, db_session, estate):
    """A sync stamps its photos with its own start, then shows them when it commits.

    Opening the camera in between must not swallow them: the photo wasn't there to
    see, so once it shows it is new.
    """
    member, headers = _user(db_session, estate, "member")
    now = datetime.now(UTC)
    cams = {
        "Charca": _camera(db_session, estate).id,
        "Empty": _camera(db_session, estate, "Empty").id,
    }
    _photo(db_session, db_session.get(Camera, cams["Charca"]), now - timedelta(hours=2),
           created=now - timedelta(hours=2))
    # Nothing of this test's own left open: every request below starts after the sync.
    db_session.commit()

    sync = create_engine(db_session.get_bind().url)
    try:
        with sync.connect() as conn, conn.begin():
            began = conn.scalar(text("SELECT now()"))
            stored = {}
            for name, cam_id in cams.items():
                stored[name] = conn.scalar(insert(Image).values(
                    camera_id=cam_id, captured_at=now - timedelta(minutes=10),
                    original_path="boar.jpg", is_empty_frame=False,
                ).returning(Image.id))
                conn.execute(insert(Detection).values(
                    image_id=stored[name], species_id="wild_boar", species_conf=0.9,
                ))
            # The hunter opens both cameras while the sync is still downloading.
            for cam_id in cams.values():
                r = client.post(f"/api/cameras/{cam_id}/seen", headers=headers)
                assert r.status_code == 200
                assert datetime.fromisoformat(r.json()["seen_at"]) < began
            before = _map(client, headers)
            assert before["Charca"]["new_count"] == 0 and before["Empty"]["new_count"] == 0
        # Committed: the photos show, and are new to the hunter who opened the cameras.
        after = _map(client, headers)
        assert after["Charca"]["latest"]["image_id"] == str(stored["Charca"])
        assert after["Charca"]["new_count"] == 1
        assert after["Empty"]["new_count"] == 1
    finally:
        sync.dispose()

    # Opening them now clears them.
    for cam_id in cams.values():
        client.post(f"/api/cameras/{cam_id}/seen", headers=headers)
    after = _map(client, headers)
    assert after["Charca"]["new_count"] == 0 and after["Empty"]["new_count"] == 0
    assert len(db_session.scalars(
        select(CameraView).where(CameraView.user_id == member.id)).all()) == 2


def _detector(monkeypatch, *, animal: bool):
    """What the detector pass does to a frame: judge it and stamp it (empty_filter)."""
    monkeypatch.setattr(empty_filter, "detect",
                        lambda path: [{"confidence": 0.9}] if animal else [])


def test_a_frame_still_being_checked_when_you_open_the_camera_is_new_once_kept(
    client, db_session, estate, monkeypatch,
):
    """Opening a camera while its newest frames wait for the detector must not
    swallow them: they weren't on the map to see. Once the detector keeps them they
    are new to everyone who hasn't opened the camera since, the opener included."""
    _, admin = _user(db_session, estate, "admin")
    _, member = _user(db_session, estate, "member")
    cam = _camera(db_session, estate)
    now = datetime.now(UTC)
    _photo(db_session, cam, now - timedelta(hours=3), created=now - timedelta(hours=3))
    for h in (admin, member):
        client.post(f"/api/cameras/{cam.id}/seen", headers=h)

    # A sync stores a burst of three frames and one that will turn out empty.
    burst = [_photo(db_session, cam, now - timedelta(minutes=30), (), empty=None,
                    created=now - timedelta(minutes=5)) for _ in range(3)]
    grass = _photo(db_session, cam, now - timedelta(minutes=20), (), empty=None,
                   created=now - timedelta(minutes=5))
    assert _map(client, member)["Charca"]["new_count"] == 0  # not checked, not on the map

    # The member opens Charca before the detector gets there.
    assert client.post(f"/api/cameras/{cam.id}/seen", headers=member).status_code == 200

    _detector(monkeypatch, animal=True)
    for img in burst:
        empty_filter.scan_image(db_session, img)
    _detector(monkeypatch, animal=False)
    empty_filter.scan_image(db_session, grass)
    db_session.commit()
    for h in (admin, member):
        got = _map(client, h)["Charca"]
        assert got["latest"]["image_id"] in {str(i.id) for i in burst}
        assert got["new_count"] == 3, "photos they could not have seen are marked seen"

    # Opening it now clears it: the check stamps are behind the new mark.
    client.post(f"/api/cameras/{cam.id}/seen", headers=member)
    assert _map(client, member)["Charca"]["new_count"] == 0
    assert _map(client, admin)["Charca"]["new_count"] == 3


def test_a_photo_kept_by_hand_is_new_to_whoever_had_opened_the_camera(client, db_session, estate):
    """The detector said "nothing in it"; a hunter looks and keeps it. It shows on the
    map from then, so it is news to a teammate who had already opened the camera."""
    _, member = _user(db_session, estate, "member")
    _, admin = _user(db_session, estate, "admin")
    cam = _camera(db_session, estate)
    now = datetime.now(UTC)
    missed = _photo(db_session, cam, now - timedelta(hours=1), ("red_deer",), empty=True,
                    created=now - timedelta(minutes=50))
    missed.processed_at = now - timedelta(minutes=45)
    db_session.commit()
    client.post(f"/api/cameras/{cam.id}/seen", headers=member)
    assert _map(client, member)["Charca"]["new_count"] == 0

    r = client.post(f"/api/images/{missed.id}/flag", headers=admin, json={"is_empty": False})
    assert r.status_code == 200
    got = _map(client, member)["Charca"]
    assert got["latest"]["image_id"] == str(missed.id) and got["new_count"] == 1


def test_a_photo_checked_after_it_arrived_is_not_new_once_you_have_looked(
    client, db_session, estate,
):
    """The mark covers what was checked before you looked, not only what had arrived."""
    _, member = _user(db_session, estate, "member")
    cam = _camera(db_session, estate)
    now = datetime.now(UTC)
    img = _photo(db_session, cam, now - timedelta(hours=1), created=now - timedelta(minutes=50))
    img.processed_at = now - timedelta(minutes=10)  # a long detector backlog
    db_session.commit()
    assert _map(client, member)["Charca"]["new_count"] == 1
    client.post(f"/api/cameras/{cam.id}/seen", headers=member)
    assert _map(client, member)["Charca"]["new_count"] == 0


def test_a_history_import_does_not_light_up_the_badge(client, db_session, estate):
    """A backfill stores months-old photos today. They are new to the app, not news."""
    _, headers = _user(db_session, estate, "member")
    _, never = _user(db_session, estate, "viewer")
    cam = _camera(db_session, estate)
    now = datetime.now(UTC)
    last = _photo(db_session, cam, now - timedelta(hours=3), created=now - timedelta(hours=3))
    client.post(f"/api/cameras/{cam.id}/seen", headers=headers)
    db_session.add_all([
        Image(camera_id=cam.id, captured_at=now - timedelta(days=160, minutes=i),
              original_path="april.jpg", is_empty_frame=False, created_at=now)
        for i in range(150)
    ])
    db_session.commit()
    for h in (headers, never):
        got = _map(client, h)["Charca"]
        assert got["latest"]["image_id"] == str(last.id)
        assert got["new_count"] == (0 if h is headers else 1)

    # A camera out of signal for two days delivers them late: those are news.
    _photo(db_session, cam, now - timedelta(days=2), created=now)
    assert _map(client, headers)["Charca"]["new_count"] == 1


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


def test_the_sheet_the_activity_map_and_the_replay_agree_on_a_dawn_visit(
    client, db_session, estate, monkeypatch,
):
    """Last night runs to 08:00 on every map view: a boar heading to bed at 07:10 is
    on the camera's sheet, in the activity circle and in the replay alike."""
    _, headers = _user(db_session, estate, "member")
    night = last_completed_night()
    start, end = night_window(night)
    assert (end - start) == timedelta(hours=14)
    cam = _camera(db_session, estate)
    dawn = _camera(db_session, estate, "Dawn only", lat=39.1, lon=-1.37)
    at = end - timedelta(minutes=50)  # 07:10 local
    for _ in range(3):
        _photo(db_session, cam, at)
    _photo(db_session, cam, start + timedelta(hours=2), ("red_deer",))
    # Only a frame at 06:30 that the detector hasn't reached: the night isn't all known.
    _photo(db_session, dawn, end - timedelta(minutes=90), (), empty=None)

    sheet = _map(client, headers)
    assert sheet["Charca"]["last_night"] == [
        {"species_id": "red_deer", "label": "Red deer", "visits": 1},
        {"species_id": "wild_boar", "label": "Wild boar", "visits": 1},
    ]
    assert sheet["Dawn only"]["last_night_status"] == "checking"
    assert isinstance(sheet["Charca"]["last_night_so_far"], bool)

    act = client.get("/api/map/activity?nights=1", headers=headers).json()
    charca = next(c for c in act["cameras"] if c["name"] == "Charca")
    assert {(s["label"], s["visits"]) for s in charca["by_species"]} == {
        ("Red deer", 1), ("Wild boar", 1),
    }
    replay = client.get(f"/api/map/replay?night={night.isoformat()}", headers=headers).json()
    assert sorted(v["label"] for v in replay["visits"] if v["camera_id"] == str(cam.id)) == [
        "Red deer", "Wild boar",
    ]

    # From 06:00 to 08:00 last night is still going, and the sheet says "so far".
    monkeypatch.setattr(routes_map, "still_running", lambda n: n == night)
    assert _map(client, headers)["Charca"]["last_night_so_far"] is True


def test_every_species_reads_in_sentence_case(client, db_session, estate):
    """"Roe deer", not the stored "Roe Deer", wherever the map names it."""
    db_session.add(Species(id="roe_deer", common_name="Roe Deer"))
    db_session.commit()
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    start, _ = night_window(last_completed_night())
    _photo(db_session, cam, start + timedelta(hours=3), ("roe_deer",))
    got = _map(client, headers)["Charca"]
    assert got["latest"]["label"] == "Roe deer"
    assert got["last_night"] == [{"species_id": "roe_deer", "label": "Roe deer", "visits": 1}]
    act = client.get("/api/map/activity?nights=1", headers=headers).json()
    assert act["species_options"][0]["label"] == "Roe deer"
    one = client.get("/api/map/activity?nights=1&species=roe_deer", headers=headers).json()
    assert one["species_label"] == "Roe deer"


def test_bad_input_on_the_map_is_refused_in_words_not_a_server_error(client, db_session, estate):
    _, headers = _user(db_session, estate)
    r = client.get("/api/map/activity?species=%00", headers=headers)
    assert r.status_code == 404 and r.json()["detail"] == "No such species."
    for night in ("9999-12-31", "1900-01-01"):
        r = client.get(f"/api/map/replay?night={night}", headers=headers)
        assert r.status_code == 422 and r.json()["detail"] == "There is no replay for that night."
    last = last_completed_night().isoformat()
    assert client.get(f"/api/map/replay?night={last}", headers=headers).status_code == 200


def test_last_night_says_how_far_to_trust_it(client, db_session, estate):
    _, headers = _user(db_session, estate)
    night = last_completed_night()
    start, _ = night_window(night)
    up = _camera(db_session, estate, "Up")
    down = _camera(db_session, estate, "Down")
    _camera(db_session, estate, "No record")
    checking = _camera(db_session, estate, "Checking")
    fresh = _camera(db_session, estate, "Fresh")
    credits = _camera(db_session, estate, "Credits")
    db_session.add_all([
        CameraNight(camera_id=up.id, night=night, exposure_state="PRESUMED_UP"),
        CameraNight(camera_id=down.id, night=night, exposure_state="UNKNOWN"),
        CameraNight(camera_id=checking.id, night=night, exposure_state="UNPROCESSED", frames=2),
        CameraNight(camera_id=credits.id, night=night, exposure_state="UNKNOWN", frames=1),
    ])
    db_session.commit()
    # Frames that came in overnight and the detector hasn't reached: there were
    # photos, so "the camera may not have been working" would be wrong.
    _photo(db_session, checking, start + timedelta(hours=5), (), empty=None)
    _photo(db_session, checking, start + timedelta(hours=6), (), empty=True)
    # All checked before the hourly rebuild of camera_nights has a row for the night.
    _photo(db_session, fresh, start + timedelta(hours=2), (), empty=True)
    # Out of photo credits partway through the night: it sent a boar, and maybe not all.
    _photo(db_session, credits, start + timedelta(hours=1))

    cams = _map(client, headers)
    status = {name: (c["last_night_status"], c["last_night"]) for name, c in cams.items()}
    assert status["Up"] == ("watched", [])
    assert status["Down"] == ("blind", [])
    assert status["No record"] == (None, [])
    assert status["Checking"] == ("checking", [])
    assert status["Fresh"] == ("watched", [])
    assert status["Credits"] == (
        "incomplete", [{"species_id": "wild_boar", "label": "Wild boar", "visits": 1}],
    )
    assert cams["No record"]["latest"] is None and cams["No record"]["new_count"] == 0


def test_a_night_the_ai_gave_up_on_is_never_a_quiet_night(client, db_session, estate):
    """Frames the AI failed on three times are not checked: the sheet and the activity
    map must not read them as "watched, nothing came", as the exposure table doesn't."""
    from app.forecasting.exposure import recompute_camera_nights

    _, headers = _user(db_session, estate)
    night = last_completed_night()
    start, _ = night_window(night)
    broken = _camera(db_session, estate, "Broken")
    mixed = _camera(db_session, estate, "Mixed", lat=39.1, lon=-1.37)
    now = datetime.now(UTC)
    for i in range(3):
        img = _photo(db_session, broken, start + timedelta(hours=2, minutes=i), (), empty=None)
        img.ai_attempts, img.ai_failed_at, img.ai_error = 3, now, "OSError: truncated"
    # A boar was named, and one frame of the night could not be read.
    _photo(db_session, mixed, start + timedelta(hours=1))
    lost = _photo(db_session, mixed, start + timedelta(hours=4), (), empty=None)
    lost.ai_attempts, lost.ai_failed_at = 3, now
    db_session.commit()
    recompute_camera_nights(db_session)
    assert db_session.scalar(select(CameraNight.exposure_state).where(
        CameraNight.camera_id == broken.id, CameraNight.night == night)) == "UNPROCESSED"

    cams = _map(client, headers)
    assert (cams["Broken"]["last_night_status"], cams["Broken"]["last_night"]) == (
        "unreadable", [])
    assert cams["Mixed"]["last_night_status"] == "unreadable"
    assert cams["Mixed"]["last_night"] == [
        {"species_id": "wild_boar", "label": "Wild boar", "visits": 1}]

    act = {c["name"]: c for c in client.get(
        "/api/map/activity?nights=1", headers=headers).json()["cameras"]}
    for name in ("Broken", "Mixed"):
        got = act[name]
        assert (got["watched_nights"], got["unreadable_nights"], got["per_night"]) == (0, 1, None)
        assert got["read"] == "Not counted: last night’s photos couldn’t all be checked."

    # A hunter judges the broken frames ("nothing in it"): checked now, a quiet night.
    for img in db_session.scalars(select(Image).where(Image.camera_id == broken.id)):
        r = client.post(f"/api/images/{img.id}/flag", json={"is_empty": True}, headers=headers)
        assert r.status_code == 200
    assert _map(client, headers)["Broken"]["last_night_status"] == "watched"


def test_a_kept_photo_nobody_has_named_is_an_animal_visit(client, db_session, estate):
    """The detector kept it and the species pass hasn't named it (or couldn't).

    It is the camera's photo, labelled "Animal", so last night must not say nothing came.
    """
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    start, _ = night_window(last_completed_night())
    at = start + timedelta(hours=5, minutes=30)
    burst = {_photo(db_session, cam, at, ()).id for _ in range(2)}
    _photo(db_session, cam, start + timedelta(hours=1), ("lagomorph",))  # hidden: never counts
    _photo(db_session, cam, start + timedelta(hours=2), ("red_deer",))

    got = _map(client, headers)["Charca"]
    assert got["latest"]["image_id"] in {str(i) for i in burst}
    assert got["latest"]["label"] == "Animal"
    assert got["last_night"] == [
        {"species_id": "red_deer", "label": "Red deer", "visits": 1},
        {"species_id": None, "label": "Animal", "visits": 1},
    ]
    assert got["last_night_status"] == "watched"


def test_a_frame_the_detector_has_not_checked_is_not_on_the_map_yet(client, db_session, estate):
    """Most frames turn out empty: an unchecked one is neither the map photo nor new."""
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    now = datetime.now(UTC)
    boar = _photo(db_session, cam, now - timedelta(hours=1), created=now - timedelta(minutes=50))
    frame = _photo(db_session, cam, now - timedelta(minutes=5), (), empty=None,
                   created=now - timedelta(minutes=4))

    got = _map(client, headers)["Charca"]
    assert got["latest"]["image_id"] == str(boar.id)
    assert got["new_count"] == 1

    # The detector marks it empty: nothing changes.
    frame.is_empty_frame = True
    db_session.commit()
    got = _map(client, headers)["Charca"]
    assert got["latest"]["image_id"] == str(boar.id) and got["new_count"] == 1

    # Or it keeps it: now it is the camera's photo, and new.
    frame.is_empty_frame = False
    db_session.commit()
    got = _map(client, headers)["Charca"]
    assert got["latest"]["image_id"] == str(frame.id) and got["latest"]["label"] == "Animal"
    assert got["new_count"] == 2


def test_the_camera_sheets_strip_agrees_with_the_map(client, db_session, estate):
    """The strip asks /photos for checked frames only; the Photos page still sees all."""
    _, headers = _user(db_session, estate, "viewer")
    cam = _camera(db_session, estate)
    now = datetime.now(UTC)
    boar = _photo(db_session, cam, now - timedelta(hours=1))
    frame = _photo(db_session, cam, now - timedelta(minutes=5), (), empty=None)

    def feed(query=""):
        r = client.get(f"/api/photos?cameras={cam.id}{query}", headers=headers)
        assert r.status_code == 200, r.text
        return [p["image_id"] for p in r.json()["items"]]

    assert feed() == [str(frame.id), str(boar.id)]
    assert feed("&checked=true") == [str(boar.id)]
    assert _map(client, headers)["Charca"]["latest"]["image_id"] == feed("&checked=true")[0]


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
