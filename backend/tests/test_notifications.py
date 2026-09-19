"""Notifications: message composition (pure) and dispatch against a real database.

The pure half runs anywhere. The database half needs GAMESENSE_TEST_DSN, like every
other schema-touching test here; push delivery is replaced by a recorder so no test
ever talks to a push service.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.notifications import dispatch
from app.notifications.dispatch import (
    SpeciesDigest,
    compose,
    compose_summary,
    dispatch_new_sightings,
    group_by_species,
    sighting_url,
)
from app.notifications.vapid import _generate_pem, public_key_from_pem

from .conftest import requires_db

MADRID = ZoneInfo("Europe/Madrid")
T0 = datetime(2026, 9, 15, 20, 14, tzinfo=timezone.utc)  # 22:14 in Madrid (CEST)


def _rows(*items):
    """(species_id, name, image_id, captured_at, camera)."""
    return list(items)


# ── composition ────────────────────────────────────────────────────────────────


def test_group_by_species_counts_frames_not_animals():
    img = uuid.uuid4()
    rows = _rows(
        ("wild_boar", "Wild boar", img, T0, "PL19"),
        ("wild_boar", "Wild boar", img, T0, "PL19"),  # second animal, same frame
        ("wild_boar", "Wild boar", uuid.uuid4(), T0 - timedelta(minutes=5), "PL19"),
        ("red_deer", "Red deer", uuid.uuid4(), T0 - timedelta(hours=1), "MP14"),
    )
    d = group_by_species(rows)
    assert set(d) == {"wild_boar", "red_deer"}
    assert len(d["wild_boar"].images) == 2
    assert d["wild_boar"].latest_at == T0
    assert d["wild_boar"].latest_image_id == img
    assert d["wild_boar"].cameras == {"PL19": 2}


def test_compose_one_camera_names_it_in_the_title():
    d = SpeciesDigest("wild_boar", "Wild boar")
    d.add(uuid.uuid4(), T0 - timedelta(minutes=9), "PL19")
    d.add(uuid.uuid4(), T0, "PL19")
    title, body = compose(d, MADRID)
    assert title == "Wild boar at PL19"
    assert body == "2 photos, latest 22:14."


def test_compose_single_photo_is_singular():
    d = SpeciesDigest("fox", "Fox")
    d.add(uuid.uuid4(), T0, "MP14-waterhole")
    assert compose(d, MADRID) == ("Fox at MP14-waterhole", "1 photo, latest 22:14.")


def test_compose_many_cameras_lists_them_busiest_first():
    d = SpeciesDigest("red_deer", "Red deer")
    d.add(uuid.uuid4(), T0 - timedelta(hours=2), "PL15B")
    d.add(uuid.uuid4(), T0 - timedelta(hours=1), "MP14")
    d.add(uuid.uuid4(), T0, "MP14")
    title, body = compose(d, MADRID)
    assert title == "Red deer on 2 cameras"
    assert body == "3 photos at MP14 and PL15B, latest 22:14."


def test_sighting_url_opens_the_species_gallery_on_the_photo():
    image = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert sighting_url("wild_boar", image) == f"/animals?species=wild_boar&image={image}"
    assert sighting_url("red deer", None) == "/animals?species=red+deer"


def test_compose_summary_when_a_run_has_many_species():
    ds = []
    for i, (sid, name) in enumerate([("a", "Badger"), ("b", "Fox"), ("c", "Wild boar")]):
        d = SpeciesDigest(sid, name)
        for _ in range(i + 1):
            d.add(uuid.uuid4(), T0 - timedelta(minutes=i), "PL19")
        ds.append(d)
    title, body = compose_summary(ds, MADRID)
    assert title == "6 new sightings, 3 species"
    assert body == "Wild boar, Fox and Badger, latest 22:14."


def test_vapid_public_key_is_an_uncompressed_p256_point():
    pub = public_key_from_pem(_generate_pem())
    # 65 raw bytes -> 87 base64url chars, no padding; 0x04 leads every uncompressed point.
    assert len(pub) == 87
    assert pub.startswith("B")
    assert "=" not in pub and "+" not in pub and "/" not in pub


# ── dispatch against the database ──────────────────────────────────────────────


class _Recorder:
    """Stands in for push.send_to_user: remembers what would have gone where."""

    def __init__(self, subscriptions: int = 0, sent: int = 0):
        self.calls: list[tuple[uuid.UUID, dict]] = []
        self.subscriptions = subscriptions
        self.sent = sent

    def __call__(self, db, user_id, payload):
        self.calls.append((user_id, payload))
        return {"sent": self.sent, "failed": 0, "removed": 0, "subscriptions": self.subscriptions}


def _seed(db):
    from app.models import Camera, Estate, NotificationPref, Species, User

    estate = Estate(name="Test", timezone="Europe/Madrid")
    db.add(estate)
    db.flush()
    cam = Camera(estate_id=estate.id, name="PL19")
    db.add(cam)
    db.add_all([
        Species(id="wild_boar", common_name="Wild boar", is_priority=True),
        Species(id="red_deer", common_name="Red deer", is_priority=True),
        Species(id="bird", common_name="Bird", is_priority=False),
    ])
    users = {}
    for name, enabled, wants in [
        ("boar", True, ["wild_boar"]),
        ("deer", True, ["red_deer"]),
        ("off", False, ["wild_boar"]),
    ]:
        u = User(estate_id=estate.id, email=f"{name}@x.test", password_hash="h", role="member")
        db.add(u)
        db.flush()
        db.add(NotificationPref(user_id=u.id, enabled=enabled, species_ids=wants))
        users[name] = u
    db.commit()
    return cam, users


def _sighting(db, cam, species_id: str, captured_at: datetime, created_at: datetime):
    from app.models import Detection, Image

    img = Image(camera_id=cam.id, captured_at=captured_at, original_path="x.jpg")
    db.add(img)
    db.flush()
    det = Detection(image_id=img.id, species_id=species_id, species_conf=0.9, created_at=created_at)
    db.add(det)
    db.commit()
    return img


@requires_db
def test_first_run_primes_and_announces_nothing_old(db_session, monkeypatch):
    from app.models import Notification

    rec = _Recorder()
    monkeypatch.setattr(dispatch.push, "send_to_user", rec)
    cam, _ = _seed(db_session)
    now = datetime.now(timezone.utc)
    _sighting(db_session, cam, "wild_boar", now - timedelta(minutes=10), now - timedelta(minutes=1))

    assert dispatch_new_sightings(db_session, now=now)["status"] == "primed"
    assert db_session.query(Notification).count() == 0
    assert rec.calls == []
    # and the same old detection is not announced on the next run either
    assert dispatch_new_sightings(db_session, now=now + timedelta(minutes=15))["status"] == "nothing_new"


@requires_db
def test_only_people_who_asked_for_that_animal_are_told(db_session, monkeypatch):
    from app.models import Notification

    rec = _Recorder(subscriptions=1, sent=1)
    monkeypatch.setattr(dispatch.push, "send_to_user", rec)
    cam, users = _seed(db_session)
    t0 = datetime.now(timezone.utc)
    dispatch_new_sightings(db_session, now=t0)

    t1 = t0 + timedelta(minutes=15)
    img = _sighting(db_session, cam, "wild_boar", t1 - timedelta(minutes=3), t1 - timedelta(minutes=1))
    _sighting(db_session, cam, "wild_boar", t1 - timedelta(minutes=8), t1 - timedelta(minutes=1))
    _sighting(db_session, cam, "bird", t1 - timedelta(minutes=2), t1 - timedelta(minutes=1))

    result = dispatch_new_sightings(db_session, now=t1)
    assert result["status"] == "ok"
    assert result["notifications"] == 1 and result["pushed"] == 1

    notes = db_session.query(Notification).all()
    assert len(notes) == 1
    n = notes[0]
    assert n.user_id == users["boar"].id
    assert n.title == "Wild boar at PL19"
    assert n.body.startswith("2 photos, latest ")
    assert n.species_id == "wild_boar"
    assert n.image_id == img.id
    assert n.push_status == "sent"
    assert n.url == f"/animals?species=wild_boar&image={img.id}"

    assert len(rec.calls) == 1
    user_id, payload = rec.calls[0]
    assert user_id == users["boar"].id
    assert payload["tag"] == "sighting-wild_boar"
    assert payload["title"] == "Wild boar at PL19"

    # nothing is announced twice
    assert dispatch_new_sightings(db_session, now=t1 + timedelta(minutes=15))["status"] == "nothing_new"


@requires_db
def test_backfilled_history_advances_the_cursor_silently(db_session, monkeypatch):
    from app.models import Notification

    rec = _Recorder()
    monkeypatch.setattr(dispatch.push, "send_to_user", rec)
    cam, _ = _seed(db_session)
    t0 = datetime.now(timezone.utc)
    dispatch_new_sightings(db_session, now=t0)

    t1 = t0 + timedelta(minutes=15)
    _sighting(db_session, cam, "wild_boar", t1 - timedelta(days=40), t1 - timedelta(minutes=1))

    result = dispatch_new_sightings(db_session, now=t1)
    assert result == {"status": "ok", "species": 0, "notifications": 0, "pushed": 0}
    assert db_session.query(Notification).count() == 0
    assert dispatch_new_sightings(db_session, now=t1 + timedelta(minutes=15))["status"] == "nothing_new"


@requires_db
def test_unsubscribed_users_still_get_the_in_app_record(db_session, monkeypatch):
    from app.models import Notification

    rec = _Recorder(subscriptions=0, sent=0)
    monkeypatch.setattr(dispatch.push, "send_to_user", rec)
    cam, users = _seed(db_session)
    t0 = datetime.now(timezone.utc)
    dispatch_new_sightings(db_session, now=t0)
    t1 = t0 + timedelta(minutes=15)
    _sighting(db_session, cam, "red_deer", t1 - timedelta(minutes=3), t1 - timedelta(minutes=1))

    dispatch_new_sightings(db_session, now=t1)
    n = db_session.query(Notification).one()
    assert n.user_id == users["deer"].id
    assert n.push_status == "no_subscription"


@requires_db
def test_defaults_for_a_user_who_never_opened_settings(db_session):
    from app.models import Estate, User
    from app.notifications.prefs import effective_prefs

    _seed(db_session)
    estate = db_session.query(Estate).first()
    u = User(estate_id=estate.id, email="new@x.test", password_hash="h", role="member")
    db_session.add(u)
    db_session.commit()
    enabled, species = effective_prefs(db_session, u.id)
    assert enabled is False
    assert species == ["red_deer", "wild_boar"]  # priority species, not the bird


@requires_db
def test_many_species_in_one_run_collapse_to_a_summary(db_session, monkeypatch):
    from app.models import Notification, NotificationPref, Species

    rec = _Recorder(subscriptions=1, sent=1)
    monkeypatch.setattr(dispatch.push, "send_to_user", rec)
    cam, users = _seed(db_session)
    extra = [f"sp{i}" for i in range(6)]
    db_session.add_all([Species(id=s, common_name=s.upper()) for s in extra])
    pref = db_session.get(NotificationPref, users["boar"].id)
    pref.species_ids = extra
    db_session.commit()

    t0 = datetime.now(timezone.utc)
    dispatch_new_sightings(db_session, now=t0)
    t1 = t0 + timedelta(minutes=15)
    for s in extra:
        _sighting(db_session, cam, s, t1 - timedelta(minutes=2), t1 - timedelta(minutes=1))

    result = dispatch_new_sightings(db_session, now=t1)
    assert result["notifications"] == 1
    n = db_session.query(Notification).one()
    assert n.title == "6 new sightings, 6 species"
    assert n.species_id is None
    assert rec.calls[0][1]["tag"] == "sighting-summary"


@pytest.mark.parametrize(
    "names,expected",
    [
        (["A"], "A"),
        (["A", "B"], "A and B"),
        (["A", "B", "C"], "A, B and C"),
        (["A", "B", "C", "D", "E"], "A, B and 3 more"),
    ],
)
def test_join_reads_like_a_sentence(names, expected):
    assert dispatch._join(names) == expected
