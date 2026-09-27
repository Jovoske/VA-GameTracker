"""Photos and Animals (plan item 13) and fixing a wrong species from the photo viewer
(plan feature 20).

What these pin down is what a hunter sees: every frame of a burst can be paged to,
the Animals gallery reaches its oldest photo, a name given to an animal survives
"Look for repeats" and merges, a camera card counts what its strip shows, and a
species a hunter fixed stays fixed, with every list and count following it.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai import species as species_ai
from app.ai.checking import WAITING
from app.ai.classifier import ESTATE_KEYS, common_name, default_name
from app.api.routes_species import class_filter
from app.core.security import create_access_token
from app.forecasting.model import class_label, sentence_case
from app.models import (
    Camera,
    Detection,
    DetectionIndividual,
    Estate,
    Image,
    Individual,
    Species,
    User,
)

from .conftest import requires_db

pytestmark = requires_db

NIGHT = datetime(2026, 9, 20, 21, 0, tzinfo=UTC)


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
    # As the classifier named them before (title case), and rabbits hidden.
    db_session.add_all([
        Species(id="wild_boar", common_name="Wild Boar", is_priority=True),
        Species(id="red_deer", common_name="Red Deer", is_priority=True),
        Species(id="fox", common_name="Fox"),
        Species(id="lagomorph", common_name="Rabbit", hidden=True),
    ])
    db_session.commit()
    return e


def _user(db, estate, role="member", email=None):
    u = User(estate_id=estate.id, email=email or f"{role}-{uuid.uuid4().hex[:6]}@estate.local",
             password_hash="x", role=role)
    db.add(u)
    db.commit()
    return u, {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


def _camera(db, estate, name="Charca"):
    c = Camera(estate_id=estate.id, name=name, lat=39.09, lon=-1.36)
    db.add(c)
    db.commit()
    return c


def _photo(db, cam, at, species=("wild_boar",), *, empty=False, sex="unknown",
           group_type=None, conf=0.8, embedding=None, commit=True):
    """One frame. `species` are its sightings; () an animal nobody named; `empty`
    the detector's verdict (None: not checked yet)."""
    img = Image(camera_id=cam.id, captured_at=at, original_path="p.jpg", is_empty_frame=empty,
                processed_at=None if empty is None else at)
    db.add(img)
    db.flush()
    for sid in species:
        db.add(Detection(image_id=img.id, species_id=sid, species_conf=conf, sex=sex,
                         group_type=group_type, embedding=embedding,
                         bbox={"boxes": [], "guess": {"species": sid, "conf": conf}}))
    if commit:
        db.commit()
    return img


def _feed(client, headers, **params):
    """Every photo the feed pages to, following next_before/next_before_id."""
    seen, cursor = [], {}
    for _ in range(100):
        r = client.get("/api/photos", headers=headers, params={**params, **cursor})
        assert r.status_code == 200, r.text
        page = r.json()
        seen += page["items"]
        if not page["next_before"]:
            return seen
        cursor = {"before": page["next_before"], "before_id": page["next_before_id"]}
    raise AssertionError("the feed never ended")


# ── paging (C-03, I-19, J-13) ─────────────────────────────────────────────────


def test_every_frame_of_a_burst_is_reached_across_a_page_break(client, db_session, estate):
    """58 photos and a 4-frame Suntek burst stamped with one minute: paging by 60
    used to reach 60 of the 62, the rest of the burst lost at the page break."""
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    burst = NIGHT - timedelta(hours=1)
    for i in range(58):
        _photo(db_session, cam, NIGHT - timedelta(minutes=i), commit=False)
    for _ in range(4):
        _photo(db_session, cam, burst, commit=False)
    db_session.commit()
    for limit in (60, 59, 2, 3):
        got = _feed(client, headers, limit=limit)
        ids = [p["image_id"] for p in got]
        assert len(ids) == len(set(ids)) == 62, f"limit {limit}"
    # Newest first, and the burst's frames in id order within their minute.
    times = [p["captured_at"] for p in got]
    assert times == sorted(times, reverse=True)


def test_an_older_app_paging_by_time_alone_still_works(client, db_session, estate):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    for i in range(5):
        _photo(db_session, cam, NIGHT - timedelta(minutes=i))
    first = client.get("/api/photos?limit=2", headers=headers).json()
    older = client.get("/api/photos", headers=headers,
                       params={"limit": 10, "before": first["next_before"]}).json()
    assert len(first["items"]) + len(older["items"]) == 5


# ── Animals: names that stick (C-10, F-11, C-11, C-12) ────────────────────────


def _repeat_visitors(db, cam, n=4):
    """n boar sightings the re-ID groups as one animal (identical embeddings)."""
    return [_photo(db, cam, NIGHT - timedelta(minutes=5 * i), embedding=[1.0, 0.0, 0.0, 0.0])
            for i in range(n)]


def test_a_named_animal_survives_look_for_repeats(client, db_session, estate):
    from app.ai.reid import cluster

    _, admin = _user(db_session, estate, "admin")
    cam = _camera(db_session, estate)
    _repeat_visitors(db_session, cam)
    cluster(db_session)
    animals = client.get("/api/animals", headers=admin).json()
    assert [a["label"] for a in animals] == ["Wild Boar #1"]

    r = client.patch(f"/api/animals/{animals[0]['id']}", headers=admin,
                     json={"label": "  Cyclops ", "notes": "left ear torn"})
    assert r.status_code == 200 and r.json()["label"] == "Cyclops"
    cluster(db_session)
    cluster(db_session)
    after = client.get("/api/animals", headers=admin).json()
    assert [(a["label"], a["confirmed"]) for a in after] == [("Cyclops", True)]
    detail = client.get(f"/api/animals/{after[0]['id']}", headers=admin).json()
    assert detail["notes"] == "left ear torn"


def test_notes_or_a_status_alone_also_keep_the_animal(client, db_session, estate):
    from app.ai.reid import cluster

    _, admin = _user(db_session, estate, "admin")
    cam = _camera(db_session, estate)
    _repeat_visitors(db_session, cam)
    cluster(db_session)
    ind = client.get("/api/animals", headers=admin).json()[0]
    client.patch(f"/api/animals/{ind['id']}", headers=admin, json={"status": "missing"})
    cluster(db_session)
    kept = client.get(f"/api/animals/{ind['id']}", headers=admin)
    assert kept.status_code == 200 and kept.json()["status"] == "missing"


def test_a_blank_name_is_refused_in_words_and_members_cannot_rename(client, db_session, estate):
    from app.ai.reid import cluster

    _, admin = _user(db_session, estate, "admin")
    _, member = _user(db_session, estate, "member")
    cam = _camera(db_session, estate)
    _repeat_visitors(db_session, cam)
    cluster(db_session)
    ind = client.get("/api/animals", headers=admin).json()[0]
    r = client.patch(f"/api/animals/{ind['id']}", headers=admin, json={"label": "   "})
    assert r.status_code == 422 and r.json()["detail"] == "Type a name first."
    r = client.patch(f"/api/animals/{ind['id']}", headers=member, json={"label": "Cyclops"})
    assert r.status_code == 403
    assert client.get("/api/animals", headers=admin).json()[0]["label"] == "Wild Boar #1"


def _individual(db, estate, cam, label, n, notes=None):
    ind = Individual(estate_id=estate.id, label=label, species_id="wild_boar", notes=notes)
    db.add(ind)
    db.flush()
    for img in [_photo(db, cam, NIGHT - timedelta(hours=len(label), minutes=i), commit=False)
                for i in range(n)]:
        det = db.scalar(select(Detection).where(Detection.image_id == img.id))
        db.add(DetectionIndividual(detection_id=det.id, individual_id=ind.id, match_conf=0.95))
    db.commit()
    return ind


def test_merging_keeps_the_name_a_hunter_typed(client, db_session, estate):
    """'Cyclops' (1 sighting) merged into 'Wild boar #1' (3): it used to come out as
    'Wild boar #1', the typed name thrown away."""
    _, admin = _user(db_session, estate, "admin")
    cam = _camera(db_session, estate)
    big = _individual(db_session, estate, cam, "Wild boar #1", 3, notes="by the pond")
    named = _individual(db_session, estate, cam, "Cyclops", 1, notes="left ear torn")
    r = client.post("/api/animals/merge", headers=admin,
                    json={"target_id": str(big.id), "source_ids": [str(named.id)]})
    assert r.status_code == 200 and r.json()["label"] == "Cyclops"
    got = client.get(f"/api/animals/{big.id}", headers=admin).json()
    assert got["label"] == "Cyclops" and len(got["sightings"]) == 4
    assert got["notes"] == "by the pond\nleft ear torn"

    # Two named ones: the name the hunter picked when asked.
    other = _individual(db_session, estate, cam, "Old tusker", 2)
    r = client.post("/api/animals/merge", headers=admin, json={
        "target_id": str(big.id), "source_ids": [str(other.id)], "label": "Old tusker"})
    assert r.json()["label"] == "Old tusker"


# ── the species gallery pages past 300 (C-18, I-28) ────────────────────────────


def test_the_species_gallery_reaches_its_oldest_photo(client, db_session, estate):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    for i in range(305):
        _photo(db_session, cam, NIGHT - timedelta(minutes=10 * i), commit=False)
    # A second boar sighting on one photo is still one photo.
    img = _photo(db_session, cam, NIGHT + timedelta(minutes=1), commit=False)
    db_session.add(Detection(image_id=img.id, species_id="wild_boar", species_conf=0.4))
    db_session.commit()
    spotted = {s["id"]: s for s in client.get("/api/species/spotted", headers=headers).json()}
    assert spotted["wild_boar"]["count"] == 306

    seen, cursor = [], {}
    while True:
        page = client.get("/api/species/wild_boar/photos", headers=headers,
                          params={"limit": 100, **cursor}).json()
        seen += page["items"]
        if not page["next_before"]:
            break
        cursor = {"before": page["next_before"], "before_id": page["next_before_id"]}
    assert len({p["image_id"] for p in seen}) == len(seen) == 306
    # An older app's one list: the newest 300, as it asked.
    assert len(client.get("/api/species/wild_boar/images", headers=headers).json()) == 300


@pytest.mark.parametrize("species_id", ["wild_boar", "red_deer"])
def test_a_class_gallery_is_exactly_the_photos_with_that_label(client, db_session, estate,
                                                               species_id):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    labels = {}
    n = 0
    name = db_session.get(Species, species_id).common_name
    for sex in ("male", "female", "unknown"):
        for gt in (None, "solitary", "sow_with_piglets", "sounder", "hind_with_calf", "herd"):
            n += 1
            img = _photo(db_session, cam, NIGHT - timedelta(minutes=n), species=(species_id,),
                         sex=sex, group_type=gt, commit=False)
            labels[str(img.id)] = class_label(species_id, name, sex, gt)
    db_session.commit()
    for label in set(labels.values()):
        got = client.get(f"/api/species/{species_id}/photos", headers=headers,
                         params={"label": label, "limit": 200}).json()["items"]
        assert {p["image_id"] for p in got} == {i for i, lb in labels.items() if lb == label}
        assert {p["label"] for p in got} == {label}
    assert client.get(f"/api/species/{species_id}/photos", headers=headers,
                      params={"label": "Nothing like it"}).json()["items"] == []


def test_class_filter_for_any_other_species_is_its_name():
    assert str(class_filter("fox", "Fox", None)) == "true"
    assert str(class_filter("fox", "Fox", "Fox")) == "true"
    assert str(class_filter("fox", "Fox", "Stag")) == "false"


# ── camera cards (C-15, C-17, I-25) ─────────────────────────────────────────


def test_the_camera_card_counts_what_its_strip_shows(client, db_session, estate):
    """1 boar, 3 rabbit-only (hidden), 2 empty, 1 not checked yet, 1 with no file:
    '1 with animals, 2 empty'. It used to say 7 with animals."""
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    _photo(db_session, cam, NIGHT)
    for i in range(3):
        _photo(db_session, cam, NIGHT - timedelta(minutes=i + 1), species=("lagomorph",))
    for i in range(2):
        _photo(db_session, cam, NIGHT - timedelta(hours=1, minutes=i), species=(), empty=True)
    _photo(db_session, cam, NIGHT - timedelta(hours=2), species=(), empty=None)
    gone = _photo(db_session, cam, NIGHT - timedelta(hours=3))
    gone.original_path = None
    db_session.commit()
    card = client.get("/api/cameras", headers=headers).json()[0]
    assert (card["animal_count"], card["unchecked_count"], card["empty_count"],
            card["image_count"]) == (1, 1, 2, 8)
    assert card["last_capture"].startswith("2026-09-20T21:00")
    # The strip lists the checked animal photo and the one still to check; the card
    # says which is which, so at dusk the two never disagree.
    strip = client.get(f"/api/cameras/{cam.id}/images", headers=headers).json()
    assert len(strip) == card["animal_count"] + card["unchecked_count"]
    assert sorted(str(p["checking"]) for p in strip) == ["None", "waiting"]
    with_empty = client.get(f"/api/cameras/{cam.id}/images?include_empty=true",
                            headers=headers).json()
    assert len(with_empty) == len(strip) + card["empty_count"]


def test_listing_cameras_costs_the_same_for_two_as_for_ten(client, db_session, estate):
    from sqlalchemy import event

    _, headers = _user(db_session, estate)
    sent = []

    def count(*_args, **_kw):
        sent.append(1)

    queries = []
    for n in range(10):
        _photo(db_session, _camera(db_session, estate, name=f"Cam {n}"), NIGHT)
        if n not in (1, 9):
            continue
        sent.clear()
        event.listen(db_session.get_bind(), "before_cursor_execute", count)
        try:
            assert len(client.get("/api/cameras", headers=headers).json()) == n + 1
        finally:
            event.remove(db_session.get_bind(), "before_cursor_execute", count)
        queries.append(len(sent))
    assert queries[0] == queries[1], "one query for every camera's counts, not four each"


def test_the_strip_labels_a_photo_as_photos_does(client, db_session, estate):
    """A boar photo with a hidden rabbit in it is 'Wild boar', never 'Rabbit'; a lone
    male boar is 'Boar' on both pages (it was 'Boar ♂' here)."""
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    both = _photo(db_session, cam, NIGHT, species=("wild_boar", "lagomorph"))
    male = _photo(db_session, cam, NIGHT - timedelta(minutes=5), sex="male",
                  group_type="solitary")
    strip = {p["id"]: p for p in client.get(f"/api/cameras/{cam.id}/images",
                                            headers=headers).json()}
    feed = {p["image_id"]: p for p in client.get("/api/photos", headers=headers).json()["items"]}
    for img in (both, male):
        assert strip[str(img.id)]["label"] == feed[str(img.id)]["label"]
    assert strip[str(both.id)]["label"] == "Wild boar"
    assert strip[str(male.id)]["label"] == "Boar"


def test_the_strip_pages_back_by_time_and_id(client, db_session, estate):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    for _ in range(5):
        _photo(db_session, cam, NIGHT, commit=False)
    db_session.commit()
    first = client.get(f"/api/cameras/{cam.id}/images?limit=3", headers=headers).json()
    last = first[-1]
    rest = client.get(f"/api/cameras/{cam.id}/images", headers=headers, params={
        "limit": 3, "before": last["captured_at"], "before_id": last["id"]}).json()
    assert len({p["id"] for p in first + rest}) == 5


# ── downloads in local time (C-20) ──────────────────────────────────────────


def test_a_download_is_named_on_the_estates_clock():
    from app.api.routes_images import download_name

    # 20:05 UTC is 22:05 in Madrid in summer, 21:05 in winter.
    assert download_name("PL19", datetime(2026, 9, 25, 20, 5, 7, tzinfo=UTC)) == (
        "PL19_2026-09-25_22-05-07.jpg")
    assert download_name("PL19", datetime(2026, 11, 25, 20, 5, tzinfo=UTC)) == (
        "PL19_2026-11-25_21-05-00.jpg")
    # Two frames of a burst, and two photos in the hour the clocks go back (02:00 to
    # 03:00 comes twice on 25 Oct), are two files, not one saved over the other.
    burst = datetime(2026, 9, 25, 20, 5, 7, tzinfo=UTC)
    assert download_name("PL19", burst) != download_name("PL19", burst + timedelta(seconds=20))
    first = datetime(2026, 10, 25, 0, 30, 10, tzinfo=UTC)   # 02:30:10 CEST
    second = datetime(2026, 10, 25, 1, 30, 40, tzinfo=UTC)  # 02:30:40 CET
    assert download_name("PL19", first) != download_name("PL19", second)


# ── photo files: cached long, small copies made as the photos are checked (E-24) ──


def test_a_photo_file_is_kept_by_the_phone(client, db_session, estate, tmp_path):
    """The original never changes once stored, so the viewer's photo, its preloaded
    neighbours and a saved copy are fetched once, not every time the night is paged."""
    from PIL import Image as PImage

    user, _ = _user(db_session, estate)
    cam = _camera(db_session, estate)
    img = _photo(db_session, cam, NIGHT)
    img.original_path = str(tmp_path / "a.jpg")
    PImage.new("RGB", (64, 48), (90, 120, 60)).save(img.original_path, "JPEG")
    db_session.commit()
    token = create_access_token(str(user.id))
    for url in (f"/api/images/{img.id}/file", f"/api/images/{img.id}/file?download=1"):
        r = client.get(f"{url}{'&' if '?' in url else '?'}token={token}")
        assert r.status_code == 200
        assert r.headers["cache-control"] == "private, max-age=31536000, immutable"
    # A photo with no file yet is not cached as missing.
    img.original_path = None
    db_session.commit()
    r = client.get(f"/api/images/{img.id}/file?token={token}")
    assert r.status_code == 404 and "immutable" not in r.headers.get("cache-control", "")


def test_the_ai_pass_makes_the_small_copy_of_each_animal_photo(db_session, estate, tmp_path,
                                                                monkeypatch):
    from PIL import Image as PImage

    from app.ai import checking
    from app.core.config import settings

    monkeypatch.setattr(settings, "media_root", str(tmp_path / "media"))
    cam = _camera(db_session, estate)
    photos = {}
    for name, at in (("boar", NIGHT), ("grass", NIGHT - timedelta(hours=1))):
        img = _photo(db_session, cam, at, species=(), empty=None)
        img.original_path = str(tmp_path / f"{name}.jpg")
        PImage.new("RGB", (1600, 900), (90, 120, 60)).save(img.original_path, "JPEG")
        photos[name] = img
    db_session.commit()
    boxes = {photos["boar"].original_path: [{"bbox": [0.1, 0.1, 0.5, 0.5], "confidence": 0.9}]}
    monkeypatch.setattr(checking, "load_models", lambda: None)
    monkeypatch.setattr(checking, "detect_animals", lambda path: boxes.get(path, []))
    monkeypatch.setattr(species_ai, "classify_crop",
                        lambda path, bbox: ("wild_boar", "Wild boar", 0.9))
    checking.check_photos(db_session, now=datetime(2026, 9, 21, 20, 0, tzinfo=UTC))
    db_session.expire_all()
    boar, grass = (db_session.get(Image, photos[k].id) for k in ("boar", "grass"))
    assert grass.is_empty_frame is True and grass.thumbnail_path is None
    assert boar.thumbnail_path == str(tmp_path / "media" / "thumbs" / str(boar.id)[:2]
                                      / f"{boar.id}.webp")
    with PImage.open(boar.thumbnail_path) as thumb:
        assert thumb.size == (320, 180)

    # A file the thumbnail can't be made from never holds the pass up.
    bad = _photo(db_session, cam, NIGHT + timedelta(hours=1), species=(), empty=None)
    bad.original_path = str(tmp_path / "bad.jpg")
    (tmp_path / "bad.jpg").write_bytes(b"not a photo")
    db_session.commit()
    boxes[bad.original_path] = boxes[photos["boar"].original_path]
    got = checking.check_photos(db_session, now=datetime(2026, 9, 21, 21, 0, tzinfo=UTC))
    assert got["checked"] == 1 and got["failed"] == 0
    db_session.expire_all()
    assert db_session.get(Image, bad.id).thumbnail_path is None


# ── feature 20: fixing a wrong species from the viewer ─────────────────────────


def test_a_member_fixes_a_species_and_every_list_follows(client, db_session, estate):
    _, pedro = _user(db_session, estate, "member", "pedro.garcia@x.es")
    cam = _camera(db_session, estate)
    img = _photo(db_session, cam, NIGHT, sex="male", group_type="solitary")
    _photo(db_session, cam, NIGHT - timedelta(days=1))

    r = client.post(f"/api/images/{img.id}/species", headers=pedro, json={"species_id": "fox"})
    assert r.status_code == 200, r.text
    fixed = r.json()
    assert (fixed["label"], fixed["species_id"], fixed["fixed_by"]) == ("Fox", "fox", "Pedro")
    assert fixed["hidden"] is False and fixed["empty"] is False

    feed = {p["image_id"]: p for p in client.get("/api/photos", headers=pedro).json()["items"]}
    assert (feed[str(img.id)]["label"], feed[str(img.id)]["fixed_by"]) == ("Fox", "Pedro")
    chips = {s["id"]: s["count"] for s in client.get("/api/photos/filters",
                                                     headers=pedro).json()["species"]}
    assert chips == {"wild_boar": 1, "fox": 1}
    spotted = {s["id"]: s["count"] for s in client.get("/api/species/spotted",
                                                       headers=pedro).json()}
    assert spotted == {"wild_boar": 1, "fox": 1}
    fox = client.get("/api/species/fox/photos", headers=pedro).json()["items"]
    assert [p["image_id"] for p in fox] == [str(img.id)] and fox[0]["fixed_by"] == "Pedro"
    strip = client.get(f"/api/cameras/{cam.id}/images", headers=pedro).json()
    assert {p["id"]: p["label"] for p in strip}[str(img.id)] == "Fox"

    # The counts the map and the forecast read follow the sighting too.
    from app.forecasting.exposure import visits_by_night

    by_species = {}
    for (_, _, sid), v in visits_by_night(db_session).items():
        by_species[sid] = by_species.get(sid, 0) + v["visits"]
    assert by_species == {"fox": 1, "wild_boar": 1}

    det = db_session.scalar(select(Detection).where(Detection.image_id == img.id))
    db_session.refresh(det)
    # A stag's sex belongs to the stag: a fox is looked at again as a fox.
    assert (det.sex, det.corrected_at is not None) == ("unknown", True)


def test_the_ai_never_changes_a_hunters_fix(client, db_session, estate, monkeypatch):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    # A burst: the model is sure of boar on the frames around the one fixed to fox.
    before = _photo(db_session, cam, NIGHT - timedelta(seconds=30), conf=0.97)
    img = _photo(db_session, cam, NIGHT, conf=0.97)
    after = _photo(db_session, cam, NIGHT + timedelta(seconds=30), conf=0.97)
    client.post(f"/api/images/{img.id}/species", headers=headers, json={"species_id": "fox"})

    # The visit follows the fix at once, and a later vote changes nothing back.
    assert species_ai.vote_bursts(db_session, [before.id, img.id, after.id]) == 0
    db_session.commit()
    # The species model is never asked again: it isn't waiting, and a run that got to
    # it anyway writes nothing over it.
    assert db_session.scalar(select(Image.id).where(Image.id == img.id, WAITING)) is None
    monkeypatch.setattr(species_ai, "detect_animals", lambda path: [])
    monkeypatch.setattr(species_ai, "classify_crop",
                        lambda path, bbox: ("wild_boar", "Wild boar", 0.99))
    assert species_ai.classify_image(db_session, db_session.get(Image, img.id)) is None
    db_session.commit()
    dets = db_session.scalars(select(Detection).where(Detection.image_id == img.id)).all()
    assert [d.species_id for d in dets] == ["fox"]

    # A frame of the visit the model can't name, checked later, is the hunter's fox too,
    # though the model was sure of boar on two frames and the hunter looked at one.
    late = _photo(db_session, cam, NIGHT + timedelta(seconds=10), species=("fox",), conf=0.3)
    det = db_session.scalar(select(Detection).where(Detection.image_id == late.id))
    det.species_id = None
    det.bbox = {"boxes": [], "own": {"species": None, "conf": 0.3}}
    db_session.commit()
    species_ai.vote_bursts(db_session, [late.id])
    db_session.commit()
    db_session.refresh(det)
    assert det.species_id == "fox"


def test_a_photo_the_ai_never_named_or_never_reached_can_be_named(client, db_session, estate):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    waiting = _photo(db_session, cam, NIGHT, species=(), empty=None)
    assert db_session.scalar(select(Image.id).where(Image.id == waiting.id, WAITING))
    r = client.post(f"/api/images/{waiting.id}/species", headers=headers,
                    json={"species_id": "red_deer"})
    assert r.json()["label"] == "Red deer"
    assert db_session.scalar(select(Image.id).where(Image.id == waiting.id, WAITING)) is None

    # Undo: the sighting the hunter added goes, and the AI looks at it again.
    r = client.delete(f"/api/images/{waiting.id}/species", headers=headers)
    assert r.status_code == 200 and r.json()["species_id"] is None
    assert db_session.scalars(select(Detection).where(Detection.image_id == waiting.id)).all() == []
    assert db_session.scalar(select(Image.id).where(Image.id == waiting.id, WAITING))


def test_a_photo_marked_nothing_in_it_can_be_named_and_undone(client, db_session, estate):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    img = _photo(db_session, cam, NIGHT, species=(), empty=True)
    assert client.get("/api/photos", headers=headers).json()["items"] == []
    client.post(f"/api/images/{img.id}/species", headers=headers, json={"species_id": "wild_boar"})
    assert [p["label"] for p in client.get("/api/photos", headers=headers).json()["items"]] == [
        "Wild boar"]
    client.delete(f"/api/images/{img.id}/species", headers=headers)
    db_session.refresh(img)
    assert img.is_empty_frame is True
    assert client.get("/api/photos", headers=headers).json()["items"] == []


def test_undo_puts_back_exactly_what_the_ai_said(client, db_session, estate):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    img = _photo(db_session, cam, NIGHT, species=("red_deer",), sex="male", group_type="solitary",
                 conf=0.83)
    client.post(f"/api/images/{img.id}/species", headers=headers, json={"species_id": "fox"})
    # A second fix keeps the AI's word to go back to.
    client.post(f"/api/images/{img.id}/species", headers=headers, json={"species_id": "wild_boar"})
    r = client.delete(f"/api/images/{img.id}/species", headers=headers)
    assert (r.json()["label"], r.json()["fixed_by"]) == ("Stag", None)
    det = db_session.scalar(select(Detection).where(Detection.image_id == img.id))
    db_session.refresh(det)
    assert (det.species_id, det.sex, det.species_conf, det.corrected_at) == (
        "red_deer", "male", 0.83, None)
    assert "ai" not in det.bbox


def _visits(db):
    from app.forecasting.exposure import visits_by_night

    out = {}
    for (_, _, sid), v in visits_by_night(db).items():
        out[sid] = out.get(sid, 0) + v["visits"]
    return out


def test_a_fix_to_one_frame_of_a_burst_fixes_the_visit(client, db_session, estate):
    """A fox the AI called boar on every frame of its burst: the hunter fixes the frame
    on screen, and the visit is one fox, not a fox and a boar. A badger the model is
    sure of in the same minutes is another animal and stays one. Undo puts every
    frame back as the AI had it, the boar's sex and its animal (Animals) included."""
    _, headers = _user(db_session, estate)
    db_session.add(Species(id="badger", common_name="Badger"))
    cam = _camera(db_session, estate)
    first = _photo(db_session, cam, NIGHT, conf=0.97, sex="male", group_type="solitary")
    middle = _photo(db_session, cam, NIGHT + timedelta(seconds=5))
    last = _photo(db_session, cam, NIGHT + timedelta(seconds=10))
    badger = _photo(db_session, cam, NIGHT + timedelta(seconds=40), species=("badger",),
                    conf=0.95)
    tusker = Individual(estate_id=estate.id, label="Tusker", species_id="wild_boar")
    db_session.add(tusker)
    db_session.flush()
    first_det = db_session.scalar(select(Detection).where(Detection.image_id == first.id))
    db_session.add(DetectionIndividual(detection_id=first_det.id, individual_id=tusker.id,
                                       match_conf=0.9, confirmed_by_user=True))
    db_session.commit()
    assert _visits(db_session) == {"wild_boar": 1, "badger": 1}

    r = client.post(f"/api/images/{middle.id}/species", headers=headers,
                    json={"species_id": "fox"}).json()
    assert r["label"] == "Fox"
    assert [(p["image_id"], p["label"], p["fixed_by"]) for p in r["visit"]] == [
        (str(first.id), "Fox", None), (str(last.id), "Fox", None)]
    assert _visits(db_session) == {"fox": 1, "badger": 1}
    labels = {p["image_id"]: p["label"] for p in client.get("/api/photos", headers=headers)
              .json()["items"]}
    assert labels == {str(first.id): "Fox", str(middle.id): "Fox", str(last.id): "Fox",
                      str(badger.id): "Badger"}
    # The fox is no longer one of Tusker's visits, and the AI's next vote leaves it be.
    assert db_session.scalars(select(DetectionIndividual)).all() == []
    assert species_ai.vote_bursts(db_session, [first.id, middle.id, last.id]) == 0

    r = client.delete(f"/api/images/{middle.id}/species", headers=headers).json()
    assert (r["label"], r["fixed_by"]) == ("Wild boar", None)
    assert {p["image_id"]: p["label"] for p in r["visit"]} == {
        str(first.id): "Boar", str(last.id): "Wild boar"}
    assert _visits(db_session) == {"wild_boar": 1, "badger": 1}
    db_session.expire_all()
    det = db_session.get(Detection, first_det.id)
    assert (det.species_id, det.sex, det.species_conf) == ("wild_boar", "male", 0.97)
    assert not {"before_hand", "vote"} & set(det.bbox)
    link = db_session.scalars(select(DetectionIndividual)).one()
    assert (link.individual_id, link.confirmed_by_user) == (tusker.id, True)


def test_two_frames_fixed_to_two_animals_are_two_animals(client, db_session, estate):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    frames = [_photo(db_session, cam, NIGHT + timedelta(seconds=s)) for s in (0, 5, 10)]
    client.post(f"/api/images/{frames[0].id}/species", headers=headers,
                json={"species_id": "fox"})
    r = client.post(f"/api/images/{frames[2].id}/species", headers=headers,
                    json={"species_id": "wild_boar"}).json()
    # The first fix made the whole burst a fox. The second says there were two
    # animals: the frame between goes back to what the AI said of it.
    assert [(p["image_id"], p["label"]) for p in r["visit"]] == [(str(frames[1].id), "Wild boar")]
    labels = [p["label"] for p in client.get("/api/photos", headers=headers).json()["items"]]
    assert sorted(labels) == ["Fox", "Wild boar", "Wild boar"]


def test_undo_on_a_photo_never_checked_lets_the_detector_look(client, db_session, estate,
                                                                monkeypatch):
    """A frame still waiting for the detector, fixed by mistake and then Undo: it is
    waiting again, and the detector marks it empty as it does the frame beside it.
    It used to stay an "Animal" for good, the detector skipped."""
    from app.ai import checking

    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    control = _photo(db_session, cam, NIGHT - timedelta(hours=1), species=(), empty=None)
    waiting = _photo(db_session, cam, NIGHT, species=(), empty=None)
    client.post(f"/api/images/{waiting.id}/species", headers=headers, json={"species_id": "fox"})
    client.delete(f"/api/images/{waiting.id}/species", headers=headers)
    db_session.expire_all()
    img = db_session.get(Image, waiting.id)
    assert (img.processed_at, img.reviewed, img.is_empty_frame) == (None, False, None)

    monkeypatch.setattr(checking, "load_models", lambda: None)
    monkeypatch.setattr(checking, "detect_animals", lambda path: [])
    monkeypatch.setattr(species_ai, "classify_crop",
                        lambda path, bbox: ("wild_boar", "Wild boar", 0.2))
    checking.check_photos(db_session, now=datetime(2026, 9, 21, 20, 0, tzinfo=UTC))
    db_session.expire_all()
    assert db_session.get(Image, control.id).is_empty_frame is True
    assert db_session.get(Image, waiting.id).is_empty_frame is True
    assert client.get("/api/photos", headers=headers).json()["items"] == []


def test_undo_puts_the_photo_back_as_the_ai_left_it(client, db_session, estate):
    """Empty by the AI (so the daytime rescan may look again), or given up on: after a
    fix and Undo it is exactly that again, not "checked by a hunter"."""
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    empty = _photo(db_session, cam, NIGHT, species=(), empty=True)
    failed = _photo(db_session, cam, NIGHT - timedelta(hours=2), species=(), empty=None)
    failed.ai_attempts, failed.ai_error = 3, "OSError: truncated file"
    failed.ai_failed_at = NIGHT + timedelta(hours=1)
    db_session.commit()

    def state(img):
        db_session.refresh(img)
        return (img.processed_at, img.reviewed, img.is_empty_frame, img.ai_attempts,
                img.ai_failed_at, img.ai_error)

    for img in (empty, failed):
        before = state(img)
        client.post(f"/api/images/{img.id}/species", headers=headers, json={"species_id": "fox"})
        assert state(img) != before
        client.delete(f"/api/images/{img.id}/species", headers=headers)
        assert state(img) == before
    feed = client.get("/api/photos", headers=headers).json()["items"]
    assert [p["label"] for p in feed] == ["Couldn’t check"]


def test_nothing_here_hides_a_false_alarm_from_every_list(client, db_session, estate):
    _, member = _user(db_session, estate, "member")
    _, viewer = _user(db_session, estate, "viewer")
    cam = _camera(db_session, estate)
    img = _photo(db_session, cam, NIGHT)
    r = client.post(f"/api/images/{img.id}/flag", headers=viewer, json={"is_empty": True})
    assert r.status_code == 403
    assert client.post(f"/api/images/{img.id}/flag", headers=member,
                       json={"is_empty": True}).status_code == 200
    assert client.get("/api/photos", headers=member).json()["items"] == []
    assert client.get("/api/photos/filters", headers=member).json()["species"] == []
    assert client.get("/api/species/spotted", headers=member).json() == []
    assert client.get("/api/species/wild_boar/photos", headers=member).json()["items"] == []
    assert client.get("/api/cameras", headers=member).json()[0]["animal_count"] == 0


def test_who_may_fix_what(client, db_session, estate):
    _, viewer = _user(db_session, estate, "viewer")
    _, member = _user(db_session, estate, "member")
    cam = _camera(db_session, estate)
    img = _photo(db_session, cam, NIGHT)
    url = f"/api/images/{img.id}/species"
    assert client.post(url, headers=viewer, json={"species_id": "fox"}).status_code == 403
    assert client.delete(url, headers=viewer).status_code == 403
    r = client.post(url, headers=member, json={"species_id": "moose"})
    assert (r.status_code, r.json()["detail"]) == (422, "Pick one of the animals on the list.")
    other = Estate(name="Elsewhere", timezone="Europe/Madrid")
    db_session.add(other)
    db_session.commit()
    _, stranger = _user(db_session, other, "admin")
    assert client.post(url, headers=stranger, json={"species_id": "fox"}).status_code == 404


def test_a_fix_to_a_hidden_animal_says_the_photo_leaves_the_lists(client, db_session, estate):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    img = _photo(db_session, cam, NIGHT)
    r = client.post(f"/api/images/{img.id}/species", headers=headers,
                    json={"species_id": "lagomorph"}).json()
    assert (r["label"], r["hidden"]) == ("Rabbit", True)
    assert client.get("/api/photos", headers=headers).json()["items"] == []


def test_a_fixed_sighting_leaves_an_animal_of_another_species(client, db_session, estate):
    """Cyclops' two frames a minute apart are one visit: fixed to a fox, the visit
    leaves the boar; Undo brings both frames back to it."""
    _, headers = _user(db_session, estate, "admin")
    cam = _camera(db_session, estate)
    ind = _individual(db_session, estate, cam, "Cyclops", 2)
    first = db_session.scalars(select(DetectionIndividual)).first()
    det = db_session.get(Detection, first.detection_id)
    url = f"/api/images/{det.image_id}/species"
    client.post(url, headers=headers, json={"species_id": "fox"})
    assert client.get(f"/api/animals/{ind.id}", headers=headers).json()["sightings"] == []
    client.delete(url, headers=headers)
    assert len(client.get(f"/api/animals/{ind.id}", headers=headers).json()["sightings"]) == 2


def test_a_species_never_seen_before_gets_its_readable_name(client, db_session, estate):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    img = _photo(db_session, cam, NIGHT)
    r = client.post(f"/api/images/{img.id}/species", headers=headers,
                    json={"species_id": "mustelid"}).json()
    assert r["label"] == "Marten or weasel"
    sp = db_session.get(Species, "mustelid")
    assert (sp.common_name, sp.huntable) == ("Marten or weasel", False)


# ── readable species names (F-24) ────────────────────────────────────────────


def test_species_names_are_hunters_words():
    assert common_name("wild boar") == "Wild boar"
    assert common_name("lagomorph") == "Hare or rabbit"
    assert common_name("micromammal") == "Mouse or rat"
    assert common_name("mustelid") == "Marten or weasel"
    assert common_name("equid") == "Horse or donkey"
    assert default_name("red_deer") == "Red deer"
    names = [default_name(k) for k in ESTATE_KEYS]
    assert not {"Micromammal", "Mustelid", "Equid", "Lagomorph", "Rabbit"} & set(names)
    # The old classifier names are written as a sentence writes them, but a name
    # somebody typed keeps its capitals, title case included.
    assert sentence_case("Roe Deer") == "Roe deer"
    assert sentence_case("Wild Boar") == "Wild boar"
    assert sentence_case("Hare or rabbit") == "Hare or rabbit"
    assert sentence_case("Big Tusker's sow") == "Big Tusker's sow"
    assert sentence_case("Iberian Ibex") == "Iberian Ibex"
    assert sentence_case("Fox (Red)") == "Fox (Red)"
    assert class_label("ibex", "Iberian Ibex", None, None) == "Iberian Ibex"
    # A boar or deer nobody could sex is called by the species' name, renamed or not.
    assert class_label("wild_boar", "Wild Boar", None, None) == "Wild boar"
    assert class_label("wild_boar", "Jabalí", None, None) == "Jabalí"
    assert class_label("wild_boar", "Jabalí", "male", None) == "Boar"
    assert class_label("red_deer", "Ciervo", None, "herd") == "Ciervo (herd)"
    assert class_label("red_deer", None, None, None) == "Red deer"


def test_the_viewer_offers_every_animal_of_the_estate(client, db_session, estate):
    _, headers = _user(db_session, estate)
    cam = _camera(db_session, estate)
    _photo(db_session, cam, NIGHT, species=("fox",))
    got = client.get("/api/species/choices", headers=headers).json()
    assert {c["id"] for c in got} == set(ESTATE_KEYS)
    by_id = {c["id"]: c for c in got}
    assert by_id["lagomorph"]["name"] == "Rabbit" and by_id["lagomorph"]["hidden"] is True
    assert by_id["micromammal"]["name"] == "Mouse or rat"
    assert by_id["wild_boar"]["name"] == "Wild boar"
    # The big game first, then what the cameras have seen; the rest behind "more".
    assert [c["big_game"] for c in got[:6]] == [True] * 6
    assert got[6]["id"] == "fox" and got[6]["likely"] is True
    assert by_id["genet"]["likely"] is False


def test_an_admin_renames_an_animal_and_can_go_back(client, db_session, estate):
    _, admin = _user(db_session, estate, "admin")
    _, member = _user(db_session, estate, "member")
    cam = _camera(db_session, estate)
    _photo(db_session, cam, NIGHT, species=("fox",))
    r = client.patch("/api/species/fox", headers=admin, json={"common_name": "  Red   fox "})
    assert r.status_code == 200 and r.json()["common_name"] == "Red fox"
    chips = client.get("/api/photos/filters", headers=admin).json()["species"]
    assert [c["common_name"] for c in chips] == ["Red fox"]
    assert client.get("/api/photos", headers=admin).json()["items"][0]["label"] == "Red fox"
    assert client.patch("/api/species/fox", headers=member,
                        json={"common_name": "Zorro"}).status_code == 403
    assert client.patch("/api/species/fox", headers=admin,
                        json={"common_name": "   "}).status_code == 422
    # Switching the advice leaves the name alone; null brings back the app's own.
    client.patch("/api/species/fox", headers=admin, json={"huntable": True})
    assert db_session.get(Species, "fox").common_name == "Red fox"
    r = client.patch("/api/species/fox", headers=admin, json={"common_name": None})
    assert r.json()["common_name"] == "Fox" == r.json()["default_name"]


def test_a_renamed_species_is_called_so_on_every_tile(client, db_session, estate):
    """Renamed in Settings, a boar nobody could sex is the new name on the tiles,
    the Animals classes and the class gallery; a title-case name keeps its capitals,
    and Settings and the tiles write it alike."""
    _, admin = _user(db_session, estate, "admin")
    cam = _camera(db_session, estate)
    plain = _photo(db_session, cam, NIGHT)
    _photo(db_session, cam, NIGHT - timedelta(hours=1), sex="male")
    r = client.patch("/api/species/wild_boar", headers=admin, json={"common_name": "jabalí"})
    assert r.json()["common_name"] == "Jabalí"
    feed = {p["image_id"]: p["label"] for p in client.get("/api/photos", headers=admin)
            .json()["items"]}
    assert feed[str(plain.id)] == "Jabalí"
    boar = {s["id"]: s for s in client.get("/api/species/spotted", headers=admin).json()}
    assert {c["label"] for c in boar["wild_boar"]["classes"]} == {"Jabalí", "Boar"}
    gallery = client.get("/api/species/wild_boar/photos", headers=admin,
                         params={"label": "Jabalí"}).json()["items"]
    assert [p["image_id"] for p in gallery] == [str(plain.id)]

    client.patch("/api/species/fox", headers=admin, json={"common_name": "Red Fox"})
    choices = {c["id"]: c["name"] for c in client.get("/api/species/choices",
                                                      headers=admin).json()}
    assert choices["fox"] == "Red Fox"
    listed = {s["id"]: s["common_name"] for s in client.get("/api/species",
                                                            headers=admin).json()}
    assert listed["fox"] == "Red Fox"


# ── free disk space (E-24) ─────────────────────────────────────────────────


def test_settings_is_told_when_the_photo_disk_runs_low(client, db_session, estate, monkeypatch):
    import shutil
    from collections import namedtuple

    _, admin = _user(db_session, estate, "admin")
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(100 * 1024**3, 0, 1024**3))
    disk = client.get("/api/admin/status", headers=admin).json()["disk"]
    assert disk == {"free_gb": 1.0, "total_gb": 100.0, "low": True}
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(100 * 1024**3, 0, 40 * 1024**3))
    assert client.get("/api/admin/status", headers=admin).json()["disk"]["low"] is False
