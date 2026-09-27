"""Team notes on photos ("Worth a look") and per-camera alerts.

What these pin down is what the team reads off the cameras together: a note says
who marked the photo and when, only the author or an admin takes it back, viewers
look but never write, the strips gather the marked photos newest first and never
show a photo the app otherwise hides, and "Tell the team" reaches everyone else who
has alerts on, except where they muted that camera. Muting a camera silences it for
that one person and for nobody else.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token
from app.models import (
    Camera,
    Detection,
    Estate,
    Image,
    Notification,
    NotificationPref,
    PhotoNote,
    Species,
    User,
)
from app.notes import clean_text, compose, photo_url
from app.notifications import dispatch
from app.notifications.dispatch import dispatch_new_sightings
from app.people import name_for

from .conftest import requires_db

# ── names ───────────────────────────────────────────────────────────────────


class _U:
    def __init__(self, email):
        self.email = email


@pytest.mark.parametrize("email,name", [
    ("pedro.garcia@gmail.com", "Pedro"),
    ("PEDRO@x.es", "Pedro"),
    ("jmartin84@x.es", "Jmartin"),
    ("ana_lopez@x.es", "Ana"),
    ("luis+caza@x.es", "Luis"),
    ("maria-jose@x.es", "Maria"),
    ("84.ruiz@x.es", "Ruiz"),
    ("1234@x.es", "Hunter"),
    ("._-@x.es", "Hunter"),
    ("", "Hunter"),
])
def test_name_for_is_the_first_word_of_the_address(email, name):
    assert name_for(_U(email)) == name


def test_name_for_nobody_is_hunter():
    assert name_for(None) == "Hunter"


def test_note_text_is_one_trimmed_line_of_at_most_140():
    with pytest.raises(ValueError, match="characters"):
        clean_text("boar \ud83d")
    assert clean_text(None) is None
    assert clean_text("   ") is None
    assert clean_text("  Big boar,\nthird night\trunning  ") == "Big boar, third night running"
    assert clean_text("x" * 140) == "x" * 140
    with pytest.raises(ValueError, match="140"):
        clean_text("x" * 141)
    # Emoji are made of invisible joiners; they survive.
    assert clean_text("🐗‍ ok") == "🐗‍ ok"


def test_team_push_reads_like_a_text_from_a_friend():
    pedro = _U("pedro.garcia@x.es")
    assert compose("Wild boar", "Charca", pedro, "Big boar, third night running") == (
        "Worth a look: Wild boar at Charca", "Pedro: Big boar, third night running",
    )
    assert compose("Red deer", "PL19", pedro, None) == (
        "Worth a look: Red deer at PL19", "Pedro marked a photo",
    )


# ── the API ─────────────────────────────────────────────────────────────────


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
    e = Estate(name="Piedras Lisas", timezone="Europe/Madrid")
    db_session.add(e)
    db_session.add_all([
        Species(id="wild_boar", common_name="Wild Boar", is_priority=True),
        Species(id="red_deer", common_name="Red Deer", is_priority=True),
        Species(id="lagomorph", common_name="Rabbit", hidden=True),
    ])
    db_session.commit()
    return e


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, db, user_id, payload):
        self.calls.append((user_id, payload))
        return {"sent": 1, "failed": 0, "removed": 0, "subscriptions": 1}


@pytest.fixture
def pushes(db_session, monkeypatch):
    """Pushes recorded, never sent; the after-response delivery uses the test database."""
    from app.core import db as core_db

    rec = _Recorder()
    monkeypatch.setattr(dispatch.push, "send_to_user", rec)
    monkeypatch.setattr(core_db, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    return rec


def _user(db, estate, role="member", email=None, alerts: bool | None = None, muted=()):
    u = User(estate_id=estate.id, email=email or f"{role}-{uuid.uuid4().hex[:6]}@estate.local",
             password_hash="x", role=role)
    db.add(u)
    db.flush()
    if alerts is not None:
        db.add(NotificationPref(user_id=u.id, enabled=alerts, species_ids=["wild_boar"],
                                muted_camera_ids=[str(c) for c in muted]))
    db.commit()
    return u, {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


def _camera(db, estate, name="Charca"):
    c = Camera(estate_id=estate.id, name=name, lat=39.09, lon=-1.36)
    db.add(c)
    db.commit()
    return c


def _photo(db, cam, at=None, species=("wild_boar",), empty=False):
    img = Image(camera_id=cam.id, captured_at=at or datetime.now(UTC), original_path="p.jpg",
                is_empty_frame=empty)
    db.add(img)
    db.flush()
    for sid in species:
        db.add(Detection(image_id=img.id, species_id=sid, species_conf=0.9))
    db.commit()
    return img


def _note(client, headers, img, text=None, tell=False):
    return client.post(f"/api/images/{img.id}/notes", headers=headers,
                       json={"text": text, "tell_team": tell})


@requires_db
def test_a_member_marks_a_photo_and_everyone_reads_it(client, db_session, estate):
    _, pedro = _user(db_session, estate, "member", "pedro.garcia@x.es")
    _, viewer = _user(db_session, estate, "viewer")
    cam = _camera(db_session, estate)
    img = _photo(db_session, cam)

    r = _note(client, pedro, img, "  Big boar,\nthird night running ")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["told"] == 0
    assert body["note"]["text"] == "Big boar, third night running"
    assert body["note"]["name"] == "Pedro" and body["note"]["mine"]
    assert body["can_add"] is True
    assert [n["text"] for n in body["notes"]] == ["Big boar, third night running"]

    # Nothing said is still a mark.
    r = _note(client, pedro, img)
    assert r.status_code == 201 and r.json()["note"]["text"] is None

    seen = client.get(f"/api/images/{img.id}/notes", headers=viewer).json()
    assert seen["can_add"] is False
    assert [(n["name"], n["text"], n["mine"], n["can_remove"]) for n in seen["notes"]] == [
        ("Pedro", "Big boar, third night running", False, False),
        ("Pedro", None, False, False),
    ]


@requires_db
def test_viewers_look_but_never_write(client, db_session, estate):
    _, member = _user(db_session, estate, "member")
    _, viewer = _user(db_session, estate, "viewer")
    img = _photo(db_session, _camera(db_session, estate))
    assert _note(client, viewer, img, "mine").status_code == 403
    note_id = _note(client, member, img, "a boar").json()["note"]["id"]
    assert client.delete(f"/api/photo-notes/{note_id}", headers=viewer).status_code == 403
    assert db_session.query(PhotoNote).count() == 1


@requires_db
def test_only_the_author_or_an_admin_takes_a_note_back(client, db_session, estate):
    _, author = _user(db_session, estate, "member")
    _, other = _user(db_session, estate, "member")
    _, admin = _user(db_session, estate, "admin")
    img = _photo(db_session, _camera(db_session, estate))
    first = _note(client, author, img, "one").json()["note"]["id"]
    second = _note(client, author, img, "two").json()["note"]["id"]

    listed = client.get(f"/api/images/{img.id}/notes", headers=admin).json()["notes"]
    assert [n["can_remove"] for n in listed] == [True, True]  # an admin can
    listed = client.get(f"/api/images/{img.id}/notes", headers=other).json()["notes"]
    assert [n["can_remove"] for n in listed] == [False, False]

    assert client.delete(f"/api/photo-notes/{first}", headers=other).status_code == 403
    r = client.delete(f"/api/photo-notes/{first}", headers=author)
    assert r.status_code == 200 and [n["text"] for n in r.json()["notes"]] == ["two"]
    r = client.delete(f"/api/photo-notes/{second}", headers=admin)
    assert r.status_code == 200 and r.json()["notes"] == []
    assert client.delete(f"/api/photo-notes/{second}", headers=admin).status_code == 404


@requires_db
def test_a_note_is_at_most_140_and_only_on_this_estates_photos(client, db_session, estate):
    _, member = _user(db_session, estate, "member")
    img = _photo(db_session, _camera(db_session, estate))
    r = _note(client, member, img, "x" * 141)
    assert r.status_code == 422 and "140" in r.json()["detail"]
    assert _note(client, member, img, "x" * 140).status_code == 201
    # Half an emoji (a lone surrogate) can't be stored: said in words, not a server error.
    r = client.post(f"/api/images/{img.id}/notes", content=b'{"text": "boar \\ud83d"}',
                    headers={**member, "Content-Type": "application/json"})
    assert r.status_code == 422 and "characters" in r.json()["detail"]

    other = Estate(name="Elsewhere", timezone="Europe/Madrid")
    db_session.add(other)
    db_session.commit()
    theirs = _photo(db_session, _camera(db_session, other, "Theirs"))
    assert _note(client, member, theirs, "hi").status_code == 404
    assert client.get(f"/api/images/{theirs.id}/notes", headers=member).status_code == 404
    assert client.get(f"/api/images/{uuid.uuid4()}/notes", headers=member).status_code == 404


@requires_db
def test_highlights_are_the_marked_photos_newest_mark_first(client, db_session, estate):
    _, member = _user(db_session, estate, "member", "ana.lopez@x.es")
    _, viewer = _user(db_session, estate, "viewer")
    charca, pl19 = _camera(db_session, estate, "Charca"), _camera(db_session, estate, "PL19")
    now = datetime.now(UTC)
    old_photo = _photo(db_session, charca, now - timedelta(days=3))
    new_photo = _photo(db_session, pl19, now - timedelta(hours=2), species=("red_deer",))
    unmarked = _photo(db_session, charca, now - timedelta(hours=1))
    rabbit = _photo(db_session, charca, now - timedelta(hours=1), species=("lagomorph",))
    empty = _photo(db_session, charca, now - timedelta(hours=1), species=(), empty=True)
    assert _note(client, member, new_photo, "look").status_code == 201
    # Notes from before these were hidden: the rabbit's species was hidden later, the
    # other photo was marked "nothing in it" later. Neither shows.
    db_session.add_all([PhotoNote(image_id=rabbit.id, text="look"),
                        PhotoNote(image_id=empty.id, text="look")])
    db_session.commit()
    # The old photo is marked last, so it leads: the strip is ordered by the mark.
    assert _note(client, member, old_photo, "big one").status_code == 201

    items = client.get("/api/photos/highlights", headers=viewer).json()["items"]
    assert [i["image_id"] for i in items] == [str(old_photo.id), str(new_photo.id)]
    top = items[0]
    assert top["camera"] == "Charca" and top["camera_id"] == str(charca.id)
    assert top["label"] == "Wild boar" and top["species_id"] == "wild_boar"
    assert top["notes_count"] == 1
    assert [(n["name"], n["text"], n["mine"]) for n in top["notes"]] == [("Ana", "big one", False)]
    assert str(unmarked.id) not in {i["image_id"] for i in items}

    only = client.get(f"/api/photos/highlights?camera_id={pl19.id}", headers=viewer).json()
    assert [i["image_id"] for i in only["items"]] == [str(new_photo.id)]
    assert len(client.get("/api/photos/highlights?limit=1", headers=viewer).json()["items"]) == 1


@requires_db
def test_photo_lists_carry_the_note_count(client, db_session, estate):
    _, member = _user(db_session, estate, "member")
    cam = _camera(db_session, estate)
    marked = _photo(db_session, cam)
    plain = _photo(db_session, cam, datetime.now(UTC) - timedelta(hours=1))
    _note(client, member, marked, "one")
    _note(client, member, marked, "two")
    want = {str(marked.id): 2, str(plain.id): 0}

    feed = client.get("/api/photos", headers=member).json()["items"]
    assert {i["image_id"]: i["notes_count"] for i in feed} == want
    gallery = client.get(f"/api/cameras/{cam.id}/images", headers=member).json()
    assert {i["id"]: i["notes_count"] for i in gallery} == want
    species = client.get("/api/species/wild_boar/images", headers=member).json()
    assert {i["image_id"]: i["notes_count"] for i in species} == want
    one = client.get(f"/api/photos/{marked.id}", headers=member).json()
    assert one["notes_count"] == 2 and one["camera"] == "Charca" and one["label"] == "Wild boar"


@requires_db
def test_one_photo_by_id_is_what_a_push_opens_and_hidden_ones_are_gone(client, db_session, estate):
    _, member = _user(db_session, estate, "member")
    cam = _camera(db_session, estate)
    rabbit = _photo(db_session, cam, species=("lagomorph",))
    assert client.get(f"/api/photos/{rabbit.id}", headers=member).status_code == 404
    assert client.get(f"/api/photos/{uuid.uuid4()}", headers=member).status_code == 404
    # The fixed paths still answer as themselves, not as a photo id.
    assert client.get("/api/photos/filters", headers=member).status_code == 200
    assert client.get("/api/photos/highlights", headers=member).status_code == 200


@requires_db
def test_tell_the_team_reaches_everyone_else_with_alerts_on(client, db_session, estate, pushes):
    charca, feeder = _camera(db_session, estate, "Charca"), _camera(db_session, estate, "Feeder")
    pedro, pedro_h = _user(db_session, estate, "member", "pedro.garcia@x.es", alerts=True)
    ana, _ = _user(db_session, estate, "viewer", "ana@x.es", alerts=True)
    luis, _ = _user(db_session, estate, "admin", "luis@x.es", alerts=True, muted=[charca.id])
    off, _ = _user(db_session, estate, "member", "off@x.es", alerts=False)
    never, _ = _user(db_session, estate, "member", "never@x.es")  # never opened Settings
    img = _photo(db_session, charca)

    r = _note(client, pedro_h, img, "Big boar, third night running", tell=True)
    assert r.status_code == 201 and r.json()["told"] == 1
    # Luis has alerts on but muted Charca: the phone can say so, not "nobody has alerts on".
    assert r.json()["muted"] == 1

    notes = db_session.query(Notification).all()
    assert [n.user_id for n in notes] == [ana.id]  # not the author, not Luis (muted Charca)
    n = notes[0]
    assert n.kind == "team_note"
    assert n.title == "Worth a look: Wild boar at Charca"
    assert n.body == "Pedro: Big boar, third night running"
    assert n.url == photo_url(img.id) == f"/photos?image={img.id}"
    assert n.image_id == img.id and n.species_id == "wild_boar"
    db_session.refresh(n)
    assert n.push_status == "sent"
    assert [(u, p["title"], p["tag"]) for u, p in pushes.calls] == [
        (ana.id, "Worth a look: Wild boar at Charca", f"note-{img.id}"),
    ]

    # Luis still hears about the camera he didn't mute.
    other = _photo(db_session, feeder, species=("red_deer",))
    r = _note(client, pedro_h, other, None, tell=True)
    assert r.json()["told"] == 2 and r.json()["muted"] == 0
    told = {x.user_id: x for x in db_session.query(Notification).filter_by(image_id=other.id)}
    assert set(told) == {ana.id, luis.id}
    assert told[luis.id].body == "Pedro marked a photo"
    assert told[luis.id].title == "Worth a look: Red deer at Feeder"
    assert off.id not in told and never.id not in told


@requires_db
def test_a_note_taken_back_leaves_no_words_in_the_teams_alerts(client, db_session, estate, pushes):
    charca = _camera(db_session, estate, "Charca")
    _, pedro_h = _user(db_session, estate, "member", "pedro.garcia@x.es", alerts=True)
    _, ana_h = _user(db_session, estate, "viewer", "ana@x.es", alerts=True)
    _, admin_h = _user(db_session, estate, "admin", "luis@x.es", alerts=True)
    img = _photo(db_session, charca)

    def ana_reads():
        r = client.get("/api/notifications", headers=ana_h)
        assert r.status_code == 200, r.text
        return [n["body"] for n in r.json()["items"]]

    rude = _note(client, pedro_h, img, "Big boar, rude words here", tell=True).json()
    kept = _note(client, pedro_h, img, "Second look: a sow too", tell=True).json()
    assert rude["told"] == 2 and kept["told"] == 2
    assert "Pedro: Big boar, rude words here" in ana_reads()

    def remove(note, headers):
        return client.delete(f"/api/photo-notes/{note['note']['id']}", headers=headers)

    assert remove(rude, pedro_h).status_code == 200
    assert ana_reads() == ["Pedro: Second look: a sow too"]
    # An admin taking one back clears it for everyone too.
    assert remove(kept, admin_h).status_code == 200
    assert ana_reads() == []
    assert db_session.query(Notification).filter_by(kind="team_note").count() == 0


@requires_db
def test_a_note_only_goes_on_a_photo_the_team_can_see(client, db_session, estate, pushes):
    _, pedro = _user(db_session, estate, "member", "pedro@x.es", alerts=True)
    _, ana = _user(db_session, estate, "admin", "ana@x.es", alerts=True)
    cam = _camera(db_session, estate, "Barranco Norte")
    empty = _photo(db_session, cam, species=(), empty=True)
    rabbit = _photo(db_session, cam, species=("lagomorph",), empty=True)
    both = _photo(db_session, cam, species=("lagomorph", "wild_boar"))

    # "Nothing in it": refused in words, and nobody is told about a photo they can't open.
    r = _note(client, pedro, empty, "Deer in the back, detector missed it", tell=True)
    assert r.status_code == 409 and "nothing in it" in r.json()["detail"]
    assert db_session.query(PhotoNote).count() == 0
    assert db_session.query(Notification).count() == 0
    # Nothing but hidden animals: no flag on the photo brings it back, so keep can't either.
    r = client.post(f"/api/images/{rabbit.id}/notes", headers=pedro,
                    json={"text": "x", "keep": True})
    assert r.status_code == 409 and "hidden" in r.json()["detail"]
    db_session.expire_all()
    assert db_session.get(Image, rabbit.id).is_empty_frame is True  # and left as it was
    # A hidden animal beside one that shows is an ordinary photo.
    assert _note(client, pedro, both, "boar behind the rabbit").status_code == 201

    # The hunter says there is an animal: the photo is kept, like its Keep button does,
    # and the note, the strip and the push all lead somewhere that opens.
    r = client.post(f"/api/images/{empty.id}/notes", headers=pedro,
                    json={"text": "Deer in the back, detector missed it", "tell_team": True,
                          "keep": True})
    assert r.status_code == 201, r.text
    assert r.json()["kept"] is True and r.json()["told"] == 1
    db_session.expire_all()
    img = db_session.get(Image, empty.id)
    assert img.is_empty_frame is False and img.reviewed is True
    told = db_session.query(Notification).filter_by(image_id=empty.id).one()
    assert told.user_id == (db_session.query(User).filter_by(email="ana@x.es").one().id)
    assert told.title == "Worth a look: Animal at Barranco Norte"
    assert client.get(f"/api/photos/{empty.id}", headers=ana).status_code == 200
    items = client.get("/api/photos/highlights", headers=ana).json()["items"]
    assert str(empty.id) in {i["image_id"] for i in items}
    # Keep on a photo that shows anyway changes nothing.
    r = client.post(f"/api/images/{both.id}/notes", headers=pedro, json={"keep": True})
    assert r.status_code == 201 and r.json()["kept"] is False


@requires_db
def test_the_same_note_saved_twice_is_one_note_and_one_alert(client, db_session, estate, pushes):
    pedro, pedro_h = _user(db_session, estate, "member", "pedro@x.es", alerts=True)
    ana, ana_h = _user(db_session, estate, "member", "ana@x.es", alerts=True)
    cam = _camera(db_session, estate)
    img = _photo(db_session, cam)
    other = _photo(db_session, cam, datetime.now(UTC) - timedelta(hours=1))
    note_id = str(uuid.uuid4())

    def save(headers, image, text, tell=True):
        return client.post(f"/api/images/{image.id}/notes", headers=headers,
                           json={"id": note_id, "text": text, "tell_team": tell})

    first = save(pedro_h, img, "Big boar")
    assert first.status_code == 201 and first.json()["told"] == 1
    assert first.json()["note"]["id"] == note_id and first.json()["again"] is False
    # The phone heard nothing back and the hunter pressed Save again, a word changed.
    again = save(pedro_h, img, "Big boar, third night")
    assert again.status_code == 201, again.text
    assert again.json()["again"] is True and again.json()["told"] == 1
    assert [n["text"] for n in again.json()["notes"]] == ["Big boar, third night"]
    assert db_session.query(PhotoNote).count() == 1
    assert db_session.query(Notification).count() == 1
    assert [u for u, _ in pushes.calls] == [ana.id]
    # Without Tell the team the second time, what was told stays told.
    assert save(pedro_h, img, "Big boar, third night", tell=False).json()["told"] == 1

    # Told the second time only: told then, once.
    late = str(uuid.uuid4())
    r = client.post(f"/api/images/{other.id}/notes", headers=pedro_h,
                    json={"id": late, "text": "sow", "tell_team": False})
    assert r.json()["told"] == 0
    r = client.post(f"/api/images/{other.id}/notes", headers=pedro_h,
                    json={"id": late, "text": "sow", "tell_team": True})
    assert r.json()["told"] == 1
    assert db_session.query(Notification).filter_by(image_id=other.id).count() == 1

    # An id is one note: not somebody else's, and not on another photo.
    assert save(ana_h, img, "mine now").status_code == 409
    assert save(pedro_h, other, "moved").status_code == 409
    db_session.expire_all()
    assert db_session.get(PhotoNote, uuid.UUID(note_id)).text == "Big boar, third night"
    assert db_session.query(PhotoNote).count() == 2


@requires_db
def test_two_saves_at_once_are_still_one_note(db_session, estate, monkeypatch):
    """The retry can reach the server while the first save is still being written."""
    from fastapi import BackgroundTasks

    from app.api import routes_notes

    pedro, _ = _user(db_session, estate, "member", "pedro@x.es", alerts=True)
    _user(db_session, estate, "member", "ana@x.es", alerts=True)
    img = _photo(db_session, _camera(db_session, estate))
    note_id = uuid.uuid4()
    real, inside = routes_notes.tell_team, threading.Event()

    def slow_tell(*a, **kw):
        out = real(*a, **kw)
        inside.set()
        time.sleep(0.5)  # the first save holds its row, not yet committed
        return out

    monkeypatch.setattr(routes_notes, "tell_team", slow_tell)
    open_session = sessionmaker(bind=db_session.get_bind())
    got = {}

    def save(key):
        with open_session() as s:
            body = routes_notes.NoteBody(id=note_id, text="Big boar", tell_team=True)
            got[key] = routes_notes.add_note(img.id, body, s.get(User, pedro.id), s,
                                             BackgroundTasks())

    first = threading.Thread(target=save, args=("first",))
    first.start()
    assert inside.wait(5)
    save("second")  # waits on the first one's row, then finds it saved
    first.join(5)
    assert got["first"]["again"] is False and got["second"]["again"] is True
    assert got["first"]["told"] == got["second"]["told"] == 1
    db_session.expire_all()
    assert db_session.query(PhotoNote).count() == 1
    assert db_session.query(Notification).count() == 1


@requires_db
def test_without_tell_the_team_nobody_is_pushed(client, db_session, estate, pushes):
    _, pedro = _user(db_session, estate, "member", alerts=True)
    _user(db_session, estate, "member", alerts=True)
    img = _photo(db_session, _camera(db_session, estate))
    assert _note(client, pedro, img, "quiet", tell=False).json()["told"] == 0
    assert db_session.query(Notification).count() == 0 and pushes.calls == []


# ── per-camera alerts ───────────────────────────────────────────────────────


@requires_db
def test_a_camera_switch_mutes_it_for_you_only(client, db_session, estate):
    charca, feeder = _camera(db_session, estate, "Charca"), _camera(db_session, estate, "Feeder")
    me, mine = _user(db_session, estate, "viewer")  # a viewer's own alerts are theirs to set
    _, theirs = _user(db_session, estate, "member")

    s = client.get("/api/notifications/settings", headers=mine).json()
    assert s["cameras"] == [
        {"id": str(charca.id), "name": "Charca", "alerts": True},
        {"id": str(feeder.id), "name": "Feeder", "alerts": True},
    ]
    assert s["muted_camera_ids"] == []

    r = client.put(f"/api/notifications/cameras/{feeder.id}", headers=mine, json={"alerts": False})
    assert r.status_code == 200, r.text
    assert r.json() == {"camera_id": str(feeder.id), "alerts": False, "enabled": False,
                        "muted_camera_ids": [str(feeder.id)]}
    # A new row keeps the defaults it would have had: alerts off, the priority animals.
    pref = db_session.get(NotificationPref, me.id)
    db_session.refresh(pref)
    assert pref.enabled is False and pref.species_ids == ["red_deer", "wild_boar"]

    s = client.get("/api/notifications/settings", headers=mine).json()
    assert [c["alerts"] for c in s["cameras"]] == [True, False]
    cams = {c["name"]: c for c in client.get("/api/map/cameras", headers=mine).json()}
    assert cams["Feeder"]["alerts"] is False and cams["Charca"]["alerts"] is True
    assert cams["Feeder"]["alerts_enabled"] is False
    # Somebody else's switches are untouched.
    cams = {c["name"]: c for c in client.get("/api/map/cameras", headers=theirs).json()}
    assert cams["Feeder"]["alerts"] is True

    # Muting twice, then on again: the list stays a set.
    client.put(f"/api/notifications/cameras/{feeder.id}", headers=mine, json={"alerts": False})
    client.put(f"/api/notifications/cameras/{charca.id}", headers=mine, json={"alerts": False})
    r = client.put(f"/api/notifications/cameras/{feeder.id}", headers=mine, json={"alerts": True})
    assert r.json()["muted_camera_ids"] == [str(charca.id)]


@requires_db
def test_camera_mutes_must_name_this_estates_cameras(client, db_session, estate):
    charca = _camera(db_session, estate, "Charca")
    _, h = _user(db_session, estate, "member")
    other = Estate(name="Elsewhere", timezone="Europe/Madrid")
    db_session.add(other)
    db_session.commit()
    theirs = _camera(db_session, other, "Theirs")

    for bad in (["not-a-uuid"], [str(uuid.uuid4())], [str(theirs.id)]):
        r = client.put("/api/notifications/settings", headers=h, json={"muted_camera_ids": bad})
        assert r.status_code == 400 and "Unknown camera" in r.json()["detail"], bad
    r = client.put("/api/notifications/settings", headers=h,
                   json={"muted_camera_ids": [str(charca.id), str(charca.id).upper()]})
    assert r.status_code == 200 and r.json()["muted_camera_ids"] == [str(charca.id)]
    # Leaving it out keeps it; [] turns every camera back on.
    r = client.put("/api/notifications/settings", headers=h, json={"enabled": True})
    assert r.json()["muted_camera_ids"] == [str(charca.id)]
    r = client.put("/api/notifications/settings", headers=h, json={"muted_camera_ids": []})
    assert r.json()["muted_camera_ids"] == []

    assert client.put(f"/api/notifications/cameras/{theirs.id}", headers=h,
                      json={"alerts": False}).status_code == 404
    assert client.put(f"/api/notifications/cameras/{uuid.uuid4()}", headers=h,
                      json={"alerts": False}).status_code == 404


@requires_db
def test_dispatch_never_pushes_a_muted_camera(db_session, estate, pushes):
    charca, feeder = _camera(db_session, estate, "Charca"), _camera(db_session, estate, "Feeder")
    muter, _ = _user(db_session, estate, "member", alerts=True, muted=[feeder.id])
    other, _ = _user(db_session, estate, "member", alerts=True)
    t0 = datetime.now(UTC)
    dispatch_new_sightings(db_session, now=t0)  # primes the cursor

    t1 = t0 + timedelta(minutes=15)

    def sighting(cam, minutes):
        img = Image(camera_id=cam.id, captured_at=t1 - timedelta(minutes=minutes),
                    original_path="x.jpg")
        db_session.add(img)
        db_session.flush()
        db_session.add(Detection(image_id=img.id, species_id="wild_boar", species_conf=0.9,
                                 created_at=t1 - timedelta(minutes=1)))
        db_session.commit()
        return img

    sighting(feeder, 5)
    at_charca = sighting(charca, 8)
    result = dispatch_new_sightings(db_session, now=t1)
    assert result["notifications"] == 2

    got = {n.user_id: n for n in db_session.query(Notification).all()}
    # The muter hears about Charca only, as if the feeder had seen nothing.
    assert got[muter.id].title == "Wild boar at Charca"  # as every other screen writes it
    assert got[muter.id].body.startswith("1 visit at ")
    assert got[muter.id].image_id == at_charca.id
    # Everyone else still hears from the feeder.
    assert got[other.id].title == "Wild boar on 2 cameras"
    assert sorted(u for u, _ in pushes.calls) == sorted([muter.id, other.id])

    # A run with only the muted camera tells the muter nothing at all.
    t2 = t1 + timedelta(minutes=15)
    img = Image(camera_id=feeder.id, captured_at=t2 - timedelta(minutes=3), original_path="y.jpg")
    db_session.add(img)
    db_session.flush()
    db_session.add(Detection(image_id=img.id, species_id="wild_boar", species_conf=0.9,
                             created_at=t2 - timedelta(minutes=1)))
    db_session.commit()
    pushes.calls.clear()
    assert dispatch_new_sightings(db_session, now=t2)["notifications"] == 1
    assert [u for u, _ in pushes.calls] == [other.id]
