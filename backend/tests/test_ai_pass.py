"""The AI pass runs reliably (plan item 5) and reads the estate's animals right (item 17).

The heavy models are not installed here: the detector and the species model are
replaced by stand-ins that answer what each test needs.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import jobs
from app.ai import checking, grouping, species
from app.forecasting.exposure import recompute_camera_nights
from app.models import Camera, CameraNight, Detection, Estate, Image, Species

from .conftest import requires_db

BOAR = [{"confidence": 0.93, "bbox": [100.0, 100.0, 400.0, 300.0]}]


@pytest.fixture
def cam(db_session):
    estate = Estate(name="Piedras Lisas", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db_session.add(estate)
    db_session.flush()
    c = Camera(estate_id=estate.id, name="Puente", active=True)
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def models(monkeypatch):
    """Stand-in models: `boxes[path]` is what the detector sees in a photo (default: a
    boar), `raises[path]` makes it fail on that photo, and the species model says boar."""
    state = {"boxes": {}, "raises": {}, "calls": [], "species": ("wild_boar", "Wild Boar", 0.9),
             "broken": None}

    def detect(path):
        state["calls"].append(path)
        if state["broken"]:
            raise RuntimeError(state["broken"])
        if path in state["raises"]:
            raise state["raises"][path]
        return state["boxes"].get(path, BOAR)

    def classify(path, bbox):
        return state["species"](path) if callable(state["species"]) else state["species"]

    monkeypatch.setattr(checking, "load_models", lambda: None)
    monkeypatch.setattr(checking, "detect_animals", detect)
    monkeypatch.setattr(species, "detect_animals", detect)
    monkeypatch.setattr(species, "classify_crop", classify)
    monkeypatch.setattr(checking, "models_work", lambda: state["broken"])
    monkeypatch.setattr("app.notifications.dispatch.dispatch_new_sightings", lambda db: None)
    return state


def _frame(db, cam, at, path=None, **kw):
    img = Image(camera_id=cam.id, captured_at=at, original_path=path or f"{uuid.uuid4()}.jpg",
                **kw)
    db.add(img)
    db.commit()
    return img


NIGHT = datetime(2026, 9, 20, 20, 0, tzinfo=UTC)


# ── failures are counted, never stored as "watched, nothing seen" ────────────────


@requires_db
def test_a_model_that_cannot_load_stops_the_pass_and_touches_nothing(db_session, cam):
    """The real loader here: ultralytics is not installed, as after a broken deploy."""
    img = _frame(db_session, cam, NIGHT)
    result = checking.check_photos(db_session)
    assert result["status"] == "stopped"
    assert "The animal detector could not start" in result["reason"]
    db_session.refresh(img)
    assert (img.processed_at, img.is_empty_frame, img.ai_attempts) == (None, None, 0)
    note = jobs.read_note(db_session, checking.STATUS)
    assert note["stopped"] == result["reason"] and note["waiting"] == 1
    recompute_camera_nights(db_session)
    assert db_session.scalar(select(CameraNight.exposure_state)) == "UNPROCESSED"


@requires_db
def test_a_photo_that_fails_is_tried_again_then_given_up_on_and_its_night_stays_unchecked(
    db_session, cam, models,
):
    bad = _frame(db_session, cam, NIGHT, path="corrupt.jpg")
    good = _frame(db_session, cam, NIGHT + timedelta(minutes=40), path="good.jpg")
    models["raises"]["corrupt.jpg"] = OSError("cannot identify image file")
    first = checking.check_photos(db_session)
    assert (first["failed"], first["given_up"], first["by_species"]) == (1, 0, {"wild_boar": 1})
    for _ in range(checking.MAX_AI_ATTEMPTS - 1):
        checking.check_photos(db_session)
    db_session.refresh(bad)
    db_session.refresh(good)
    assert bad.ai_attempts == checking.MAX_AI_ATTEMPTS and bad.ai_failed_at is not None
    assert "cannot identify image file" in bad.ai_error
    assert bad.processed_at is None and bad.is_empty_frame is None  # never a judgement
    assert good.is_empty_frame is False and good.processed_at is not None
    # Given up on: not retried any more, shown as such, and the night is not "watched".
    calls = len(models["calls"])
    checking.check_photos(db_session)
    assert len(models["calls"]) == calls
    assert checking.photo_states(db_session, [bad.id, good.id]) == {bad.id: "failed"}
    recompute_camera_nights(db_session)
    assert db_session.scalar(select(CameraNight.exposure_state)) == "UNPROCESSED"
    # An admin can have them tried again after a fix.
    assert checking.retry_failed(db_session) == 1
    models["raises"].clear()
    checking.check_photos(db_session)
    db_session.refresh(bad)
    assert bad.ai_failed_at is None and bad.ai_attempts == 0 and bad.processed_at is not None


@requires_db
def test_a_model_that_breaks_mid_run_stops_the_pass_without_blaming_the_photos(
    db_session, cam, models,
):
    frames = [_frame(db_session, cam, NIGHT + timedelta(hours=i)) for i in range(7)]
    models["broken"] = "CUDA out of memory"
    result = checking.check_photos(db_session)
    assert result["status"] == "stopped" and "not counted against the photos" in result["reason"]
    for f in frames:
        db_session.refresh(f)
        assert (f.ai_attempts, f.processed_at) == (0, None)
    # Fewer than BREAKER waiting, and no success after them: still not blamed.
    for f in frames[2:]:
        db_session.delete(f)
    db_session.commit()
    assert checking.check_photos(db_session)["status"] == "stopped"
    assert all(db_session.get(Image, f.id).ai_attempts == 0 for f in frames[:2])


@requires_db
def test_each_frame_goes_through_the_detector_once(db_session, cam, models):
    kept = _frame(db_session, cam, NIGHT, path="boar.jpg")
    empty = _frame(db_session, cam, NIGHT + timedelta(minutes=1), path="grass.jpg")
    models["boxes"]["grass.jpg"] = [{"confidence": 0.07, "bbox": [0, 0, 5, 5]}]
    result = checking.check_photos(db_session)
    assert (result["animal"], result["empty"]) == (1, 1)
    assert sorted(models["calls"]) == ["boar.jpg", "grass.jpg"]
    det = db_session.scalar(select(Detection).where(Detection.image_id == kept.id))
    assert det.bbox["boxes"][0]["confidence"] == 0.93  # the boxes are kept with it
    db_session.refresh(empty)
    # The faint box is stored (the 0.10 cut-off applies, not ultralytics' 0.25).
    assert empty.is_empty_frame is True and empty.animal_conf == 0.07
    assert empty.detector_conf == 0.05


@requires_db
def test_two_runs_never_write_two_sightings_for_one_photo(db_session, cam, models):
    img = _frame(db_session, cam, NIGHT, is_empty_frame=False, processed_at=NIGHT)
    assert species.classify_image(db_session, img, boxes=BOAR) == "wild_boar"
    db_session.commit()
    assert species.classify_image(db_session, img, boxes=BOAR) is None
    assert db_session.query(Detection).count() == 1


@requires_db
def test_a_second_run_on_the_same_photo_waits_for_the_first_ones_sighting(
    db_session, cam, models,
):
    """A run that took over a stalled run's lock can reach the same photo: the photo's
    row is locked while a sighting is written, so the second sees it and adds none."""
    import threading

    img = _frame(db_session, cam, NIGHT, is_empty_frame=False, processed_at=NIGHT)
    first = sessionmaker(bind=db_session.get_bind())()
    second = sessionmaker(bind=db_session.get_bind())()
    try:
        assert species.classify_image(first, first.get(Image, img.id), boxes=BOAR) == "wild_boar"
        got: list = []
        other = threading.Thread(target=lambda: got.append(
            species.classify_image(second, second.get(Image, img.id), boxes=BOAR)))
        other.start()
        other.join(0.5)
        assert other.is_alive()  # waiting on the first run's row lock
        first.commit()
        other.join(10)
        second.commit()
        assert got == [None]
    finally:
        first.close()
        second.close()
    assert db_session.query(Detection).filter_by(image_id=img.id).count() == 1


@requires_db
def test_a_run_that_lost_its_lock_stops_checking(db_session, cam, models, monkeypatch):
    """It stalled past LOCK_STALE and another run took the lock: it stops at the next
    photo instead of checking the same photos alongside the new owner."""
    import json

    frames = [_frame(db_session, cam, NIGHT + timedelta(minutes=i)) for i in range(3)]
    monkeypatch.setattr(jobs, "CHECK_SECONDS", 0)
    lock = jobs.try_acquire("pipeline", "sync")
    jobs.run_under(lock)
    try:
        assert not jobs.lock_lost()
        data = json.loads(lock.path.read_text())
        lock.path.write_text(json.dumps({**data, "token": "the-new-owner"}))
        result = checking.check_photos(db_session)
    finally:
        jobs.run_under(None)
        lock.release()
    assert result["status"] == "lost" and result["checked"] == 0
    assert models["calls"] == []
    assert all(db_session.get(Image, f.id).processed_at is None for f in frames)
    # The run that has the lock now says how the pass went, not this one.
    assert jobs.read_note(db_session, checking.STATUS) == {}
    assert jobs.holder("pipeline") is not None  # never removed the new owner's lock
    jobs.lock_path("pipeline").unlink()


@requires_db
def test_a_hunters_flag_while_the_detector_looks_is_never_overwritten(db_session, cam, models):
    img = _frame(db_session, cam, NIGHT, path="grass.jpg")
    other = sessionmaker(bind=db_session.get_bind())()

    def detect_while_hunter_flags(path):
        # The hunter hides it ("nothing in it") while the detector is looking at it.
        mine = other.get(Image, img.id)
        mine.is_empty_frame, mine.reviewed, mine.processed_at = True, True, datetime.now(UTC)
        other.commit()
        return BOAR

    models["boxes"] = {}
    checking_detect = checking.detect_animals
    try:
        checking.detect_animals = detect_while_hunter_flags
        checking.check_photos(db_session)
    finally:
        checking.detect_animals = checking_detect
        other.close()
    db_session.refresh(img)
    assert (img.reviewed, img.is_empty_frame) == (True, True)
    assert db_session.query(Detection).count() == 0


@requires_db
def test_a_photo_flagged_before_the_detector_reached_it_does_not_blind_its_night(
    db_session, cam, models,
):
    from fastapi.testclient import TestClient

    from app.core.db import get_db
    from app.core.security import create_access_token
    from app.main import app
    from app.models import User

    user = User(estate_id=cam.estate_id, email="m@x.local", password_hash="x", role="member")
    db_session.add(user)
    img = _frame(db_session, cam, NIGHT)
    app.dependency_overrides[get_db] = lambda: db_session
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    try:
        with TestClient(app) as client:
            r = client.post(f"/api/images/{img.id}/flag", json={"is_empty": True},
                            headers=headers)
            assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()
    db_session.refresh(img)
    assert img.processed_at is not None
    recompute_camera_nights(db_session)
    assert db_session.scalar(select(CameraNight.exposure_state)) == "CONFIRMED"


@requires_db
def test_a_backlog_is_taken_newest_first_a_run_at_a_time(db_session, cam, models):
    frames = [_frame(db_session, cam, NIGHT - timedelta(hours=i)) for i in range(5)]
    first = checking.check_photos(db_session, limit=2)
    assert first["checked"] == 2 and first["waiting"] == 3
    assert {i for i in (frames[0].id, frames[1].id)} == {
        i.id for i in db_session.scalars(select(Image).where(Image.processed_at.isnot(None)))}


@requires_db
def test_old_empties_are_looked_at_again_in_daylight_at_the_lower_cut_off(db_session, cam, models):
    now = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)  # noon in Madrid
    old = _frame(db_session, cam, now - timedelta(days=3), path="faint.jpg",
                 is_empty_frame=True, animal_conf=0.0, processed_at=now - timedelta(days=3))
    blank = _frame(db_session, cam, now - timedelta(days=4), path="blank.jpg",
                   is_empty_frame=True, animal_conf=0.0, processed_at=now - timedelta(days=4))
    models["boxes"]["faint.jpg"] = [{"confidence": 0.18, "bbox": [10.0, 10.0, 60.0, 50.0]}]
    models["boxes"]["blank.jpg"] = []
    night = checking.check_photos(db_session, now=now.replace(hour=19))
    assert night["rescanned"] == 0  # not at dusk
    result = checking.check_photos(db_session, now=now)
    assert (result["rescanned"], result["found_on_rescan"]) == (2, 1)
    db_session.refresh(old)
    db_session.refresh(blank)
    assert old.is_empty_frame is False and old.detector_conf == 0.05
    assert db_session.query(Detection).filter_by(image_id=old.id).count() == 1
    assert blank.is_empty_frame is True and blank.detector_conf == 0.05
    assert checking.check_photos(db_session, now=now)["rescanned"] == 0  # once each


# ── what gets named, and how ──────────────────────────────────────────────────


@requires_db
def test_only_animals_that_can_be_here_are_named_and_only_when_the_model_is_sure(
    db_session, cam, models,
):
    reads = {"moose.jpg": ("moose", "Moose", 0.97), "unsure.jpg": ("fox", "Fox", 0.31),
             "dog.jpg": ("dog", "Dog", 0.92), "boar.jpg": ("wild_boar", "Wild Boar", 0.88)}
    models["species"] = lambda path: reads[path]
    for n, path in enumerate(reads):
        _frame(db_session, cam, NIGHT + timedelta(hours=n), path=path)
    checking.check_photos(db_session)
    named = {img.original_path: det.species_id for det, img in db_session.execute(
        select(Detection, Image).join(Image, Image.id == Detection.image_id))}
    assert named == {"moose.jpg": None, "unsure.jpg": None, "dog.jpg": "dog",
                     "boar.jpg": "wild_boar"}
    guess = db_session.scalar(select(Detection.bbox).join(Image).where(
        Image.original_path == "unsure.jpg"))["guess"]
    assert guess == {"species": "fox", "name": "Fox", "conf": 0.31}  # kept for re-tuning
    assert db_session.get(Species, "moose") is None
    # A farm dog is tracked but not in the advice; boar is.
    assert db_session.get(Species, "dog").huntable is False
    assert db_session.get(Species, "wild_boar").huntable is True


def test_the_species_model_only_picks_among_the_estates_animals():
    from app.ai import classifier

    probs = [0.0] * len(classifier.DEEPFAUNE_CLASSES)
    probs[classifier.DEEPFAUNE_CLASSES.index("moose")] = 0.6
    probs[classifier.DEEPFAUNE_CLASSES.index("red deer")] = 0.3
    assert classifier._best_allowed(probs) == ("red_deer", "Red Deer", 0.3)
    assert not {"moose", "bison", "reindeer", "chamois", "wolf"} & classifier.ESTATE_CLASSES


def test_a_box_inside_a_box_is_one_animal_not_a_sow_with_piglets():
    whole = {"confidence": 0.92, "bbox": [100, 100, 500, 400]}
    head = {"confidence": 0.31, "bbox": [110, 120, 220, 230]}
    assert grouping.group_type([whole, head], "wild_boar") == (1, "solitary")


def test_a_second_adult_further_back_is_not_a_calf():
    near = {"confidence": 0.9, "bbox": [100, 200, 500, 600]}
    far = {"confidence": 0.8, "bbox": [700, 100, 800, 200]}  # feet far up the frame
    assert grouping.group_type([near, far], "red_deer") == (2, "herd")
    calf = {"confidence": 0.8, "bbox": [520, 420, 680, 590]}  # small, same ground line
    assert grouping.group_type([near, calf], "red_deer") == (2, "hind_with_calf")
    assert grouping.group_type([near, calf], "wild_boar") == (2, "sow_with_piglets")


def test_a_square_crop_is_centred_on_the_box():
    from app.ai.classifier import square

    assert square([100, 200, 400, 300]) == (100, 100, 400, 400)


@requires_db
def test_the_frames_of_one_visit_take_the_species_they_agree_on(db_session, cam, models):
    reads = {"a.jpg": ("red_deer", "Red Deer", 0.8), "b.jpg": ("fallow_deer", "Fallow Deer", 0.6),
             "c.jpg": ("red_deer", "Red Deer", 0.7), "d.jpg": ("fox", "Fox", 0.3),
             "e.jpg": ("fox", "Fox", 0.95), "later.jpg": ("fallow_deer", "Fallow Deer", 0.6)}
    models["species"] = lambda path: reads[path]
    at = {"a.jpg": 0, "b.jpg": 40, "c.jpg": 80, "d.jpg": 120, "e.jpg": 160, "later.jpg": 1200}
    for path, secs in at.items():
        _frame(db_session, cam, NIGHT + timedelta(seconds=secs), path=path)
    checking.check_photos(db_session)
    got = {img.original_path: det.species_id for det, img in db_session.execute(
        select(Detection, Image).join(Image, Image.id == Detection.image_id))}
    assert got == {
        "a.jpg": "red_deer", "b.jpg": "red_deer", "c.jpg": "red_deer",
        "d.jpg": "red_deer",  # could not name it alone: the visit says red deer
        "e.jpg": "fox",  # sure of itself: keeps its own
        "later.jpg": "fallow_deer",  # 18 minutes on: a visit of its own
    }
    voted = db_session.scalar(select(Detection).join(Image).where(Image.original_path == "b.jpg"))
    assert voted.bbox["own"] == {"species": "fallow_deer", "conf": 0.6}


@requires_db
def test_a_vote_that_changes_the_species_forgets_the_sex_judged_for_the_old_one(
    db_session, cam,
):
    from app.forecasting.model import class_label

    for sid, name in (("red_deer", "Red Deer"), ("wild_boar", "Wild Boar")):
        db_session.add(Species(id=sid, common_name=name, is_priority=True, huntable=True))
    db_session.commit()
    frames = [_frame(db_session, cam, NIGHT + timedelta(seconds=30 * i), is_empty_frame=False,
                     processed_at=NIGHT) for i in range(3)]
    hind = Detection(image_id=frames[0].id, species_id="red_deer", species_conf=0.6,
                     bbox={"boxes": []}, sex="female", sex_conf=0.8, sex_attempts=1,
                     sex_checked_at=NIGHT)
    db_session.add(hind)
    for f in frames[1:]:
        db_session.add(Detection(image_id=f.id, species_id="wild_boar", species_conf=0.8,
                                 bbox={"boxes": []}))
    db_session.commit()
    species.vote_bursts(db_session, [frames[2].id])
    db_session.commit()
    db_session.refresh(hind)
    # Not a "Sow": the stag/hind answer was about a red deer. The boar/sow pass looks
    # at it afresh, and the frame's own reading is kept, so the vote can be undone.
    assert (hind.species_id, hind.sex, hind.sex_conf, hind.sex_attempts) == (
        "wild_boar", "unknown", None, 0)
    assert class_label(hind.species_id, "Wild Boar", hind.sex, hind.group_type) == "Wild boar"
    assert hind.bbox["own"] == {"species": "red_deer", "conf": 0.6}


@requires_db
def test_a_hunters_flag_on_a_photo_the_ai_gave_up_on_is_a_check(db_session, cam, models):
    """Keep or "nothing in it" is the hunter's judgement: the photo no longer says
    "Couldn't check", and its night counts."""
    from app.api.routes_images import FlagBody, flag_image
    from app.models import User

    user = User(estate_id=cam.estate_id, email="a@x", password_hash="x", role="admin")
    db_session.add(user)
    db_session.commit()
    now = datetime.now(UTC)
    kept = _frame(db_session, cam, NIGHT, path="boar.jpg", ai_attempts=3, ai_failed_at=now,
                  ai_error="OSError: cannot identify image file")
    empty = _frame(db_session, cam, NIGHT + timedelta(minutes=5), path="grass.jpg",
                   ai_attempts=3, ai_failed_at=now)
    unreadable = _frame(db_session, cam, NIGHT + timedelta(minutes=50), path="cut.jpg",
                        ai_attempts=3, ai_failed_at=now)
    flag_image(kept.id, FlagBody(is_empty=False), user, db_session)
    flag_image(empty.id, FlagBody(is_empty=True), user, db_session)
    flag_image(unreadable.id, FlagBody(is_empty=False), user, db_session)
    ids = [kept.id, empty.id, unreadable.id]
    assert checking.photo_states(db_session, ids) == {kept.id: "waiting", unreadable.id: "waiting"}

    # The kept ones get one more try at naming the animal; one still can't be read.
    models["raises"]["cut.jpg"] = OSError("image file is truncated")
    checking.check_photos(db_session)
    assert checking.photo_states(db_session, ids) == {}
    named = {img.original_path: det.species_id for det, img in db_session.execute(
        select(Detection, Image).join(Image, Image.id == Detection.image_id))}
    # Not "couldn't check" over the hunter's word: an animal nobody has named.
    assert named == {"boar.jpg": "wild_boar", "cut.jpg": None}
    db_session.refresh(unreadable)
    assert unreadable.ai_failed_at is None and "truncated" in unreadable.ai_error
    assert checking.failed_count(db_session) == 0
    recompute_camera_nights(db_session)
    assert db_session.scalar(select(CameraNight.exposure_state)) == "CONFIRMED"


# ── what the hunter and the admin see ─────────────────────────────────────────


@requires_db
def test_photos_not_checked_yet_or_given_up_on_say_so(db_session, cam, models):
    from app.api.routes_photos import _items

    waiting = _frame(db_session, cam, NIGHT)
    failed = _frame(db_session, cam, NIGHT, ai_failed_at=NIGHT, ai_attempts=3)
    kept = _frame(db_session, cam, NIGHT, is_empty_frame=False, processed_at=NIGHT)
    db_session.add(Detection(image_id=kept.id, species_id=None, species_conf=0.3))
    db_session.commit()
    rows = [type("R", (), {"id": i.id, "captured_at": NIGHT, "camera_id": cam.id,
                           "name": "Puente"}) for i in (waiting, failed, kept)]
    labels = [(i["label"], i["checking"]) for i in _items(db_session, rows)]
    assert labels == [("Not checked yet", "waiting"), ("Couldn’t check", "failed"),
                      ("Animal", None)]


@requires_db
def test_admin_status_shows_the_ai_backlog_and_its_last_error(db_session, cam, monkeypatch):
    from app.api.routes_admin import status

    _frame(db_session, cam, NIGHT)
    _frame(db_session, cam, NIGHT, ai_failed_at=NIGHT, ai_attempts=3)
    checking.check_photos(db_session)  # the real loader: no ultralytics here
    ai = status(None, db_session)["ai"]
    assert (ai["waiting"], ai["failed"]) == (1, 1)
    assert "could not start" in ai["stopped"] and ai["last_error_at"]
    held = jobs.try_acquire("pipeline", "sync")
    assert status(None, db_session)["ai"]["running_since"] is not None
    held.release()
    # Look for repeats holds the same lock, but it is not checking photos.
    held = jobs.try_acquire("pipeline", "reid")
    assert status(None, db_session)["ai"]["running_since"] is None
    held.release()
    assert status(None, db_session)["ai"]["log_file"].endswith("pipeline.log")


# ── the cloud stag/hind pass ──────────────────────────────────────────────────


def _api_error(kind):
    import anthropic
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    if kind == "connection":
        return anthropic.APIConnectionError(request=request)

    def status_error(cls, code, message):
        return cls(message, response=httpx.Response(code, request=request), body=None)

    return {
        "auth": status_error(anthropic.AuthenticationError, 401, "invalid x-api-key"),
        "credit": status_error(anthropic.BadRequestError, 400,
                               "Your credit balance is too low to access the Anthropic API."),
        "bad_image": status_error(anthropic.BadRequestError, 400, "Could not process image"),
    }[kind]


@pytest.fixture
def deer(db_session, cam):
    db_session.add(Species(id="red_deer", common_name="Red Deer"))
    db_session.commit()
    dets = []
    for n in range(3):
        img = _frame(db_session, cam, NIGHT - timedelta(days=n), is_empty_frame=False,
                     processed_at=NIGHT)
        det = Detection(image_id=img.id, species_id="red_deer", species_conf=0.9)
        db_session.add(det)
        dets.append(det)
    db_session.commit()
    return dets


@requires_db
@pytest.mark.parametrize(("kind", "words"), [
    ("connection", "Couldn't reach Anthropic"),
    ("auth", "refused the API key"),
    ("credit", "out of credit"),
])
def test_a_cloud_failure_is_not_the_photos_attempt_and_stops_the_pass(
    db_session, deer, monkeypatch, kind, words,
):
    from app.ai import vision_sex

    calls = []

    def fail(path, bbox, sp, month=None):
        calls.append(path)
        raise _api_error(kind)

    monkeypatch.setattr(vision_sex, "classify_sex", fail)
    out = vision_sex.sex_pass(db_session, limit=10)
    assert words in out["stopped"] and len(calls) == 1  # stopped at the first
    assert all(d.sex_attempts == 0 and d.sex == "unknown" for d in deer)
    note = jobs.read_note(db_session, vision_sex.STATUS)
    assert words in note["stopped"] and note["waiting"] == 3
    # Recovered: every crop still gets its one attempt.
    monkeypatch.setattr(vision_sex, "classify_sex", lambda *a, **k: vision_sex.SexCall(
        sex="male", label="stag", confidence=0.9, cues="branched antlers"))
    assert vision_sex.sex_pass(db_session, limit=10)["red_deer"]["by_label"] == {"stag": 3}


@requires_db
def test_a_request_about_one_bad_photo_counts_and_the_pass_goes_on(db_session, deer, monkeypatch):
    from app.ai import vision_sex

    seen = []

    def judge(path, bbox, sp, month=None):
        seen.append(path)
        if len(seen) == 1:
            raise _api_error("bad_image")
        return vision_sex.SexCall(sex="female", label="hind", confidence=0.8, cues="no pedicles")

    monkeypatch.setattr(vision_sex, "classify_sex", judge)
    out = vision_sex.sex_pass(db_session, limit=10)
    assert out["stopped"] is None and out["red_deer"]["processed"] == 3
    # Newest first: tonight's stag before last week's backlog.
    newest = max(deer, key=lambda d: db_session.get(Image, d.image_id).captured_at)
    assert seen[0] == db_session.get(Image, newest.image_id).original_path
    assert all(d.sex_attempts == 1 for d in deer)


def test_the_stag_hind_prompt_knows_when_stags_have_cast():
    from app.ai.vision_sex import deer_prompt

    march = deer_prompt(3)
    assert "March" in march and "NOT" in march and "pedicles" in march
    assert "hard, branched antlers" in deer_prompt(10)
    assert "velvet" in deer_prompt(6)


# ── model files ───────────────────────────────────────────────────────────────


def test_a_download_cut_short_leaves_nothing_behind(tmp_path, monkeypatch):
    import httpx

    from app.ai import detector

    class Stream:
        def __init__(self, body, length):
            self.body, self.headers = body, {"content-length": str(length)}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield self.body

    path = str(tmp_path / "MDV6.pt")
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: Stream(b"x" * 1024, 5000))
    with pytest.raises(OSError, match="cut short"):
        detector.download("https://x/w.pt", path, timeout=1, what="detector")
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: Stream(b"x" * 5000, 5000))
    detector.download("https://x/w.pt", path, timeout=1, what="detector")
    assert [p.name for p in tmp_path.iterdir()] == ["MDV6.pt"]


def test_weights_are_removed_only_when_the_file_is_broken_and_fetched_at_most_daily(
    tmp_path, monkeypatch,
):
    """Out of memory or a library that won't import says nothing about the file: it is
    kept (it used to be deleted, and 1.2 GB fetched again every 15 minutes)."""
    import pickle
    import sys
    import types

    from app.ai import classifier, detector
    from app.core.config import settings

    monkeypatch.setattr(settings, "models_root", str(tmp_path))
    weights = tmp_path / classifier._FILE
    downloads: list = []

    def download(url, path, **kw):
        downloads.append(path)
        with open(path, "wb") as f:
            f.write(b"w" * 4096)

    monkeypatch.setattr(detector, "download", download)
    fake_torch = types.ModuleType("torch")
    fake_timm = types.ModuleType("timm")
    fake_timm.create_model = lambda *a, **k: object()
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "timm", fake_timm)
    monkeypatch.setattr(classifier, "_model", None)

    def load_raising(error):
        def load(*a, **k):
            raise error
        fake_torch.load = load

    weights.write_bytes(b"w" * 4096)
    for error in (RuntimeError("DefaultCPUAllocator: not enough memory: you tried to "
                               "allocate 1216348160 bytes."), MemoryError()):
        load_raising(error)
        with pytest.raises(type(error)):
            classifier.load()
        assert weights.exists()
    assert downloads == []

    # A file cut short or not a checkpoint: removed, and fetched again once.
    load_raising(pickle.UnpicklingError("invalid load key, '<'."))
    with pytest.raises(pickle.UnpicklingError):
        classifier.load()
    assert not weights.exists()
    with pytest.raises(pickle.UnpicklingError):
        classifier.load()  # downloaded again, and still broken: removed again
    assert downloads == [str(weights)] and not weights.exists()
    # Not again today: a load that keeps failing never pulls the file every run.
    with pytest.raises(RuntimeError, match="downloaded again after"):
        classifier.load()
    assert downloads == [str(weights)]
    marker = json.loads((tmp_path / (classifier._FILE + ".bad")).read_text())
    marker["downloaded_at"] -= detector.REDOWNLOAD_SECONDS + 1
    (tmp_path / (classifier._FILE + ".bad")).write_text(json.dumps(marker))
    with pytest.raises(pickle.UnpicklingError):
        classifier.load()
    assert len(downloads) == 2

    # The detector: an ultralytics that can't import what the file needs keeps it.
    dweights = tmp_path / detector._MODEL_FILE
    dweights.write_bytes(b"y" * 4096)
    fake_ul = types.ModuleType("ultralytics")

    def yolo(path):
        raise ModuleNotFoundError("No module named 'dill'")

    fake_ul.YOLO = yolo
    monkeypatch.setitem(sys.modules, "ultralytics", fake_ul)
    monkeypatch.setattr(detector, "_model", None)
    with pytest.raises(ModuleNotFoundError):
        detector.load()
    assert dweights.exists()
    fake_ul.YOLO = lambda path: object()
    detector.load()
    assert not (tmp_path / (detector._MODEL_FILE + ".bad")).exists()


# ── weather on the photo path ─────────────────────────────────────────────────


@requires_db
def test_a_slow_weather_service_is_asked_once_and_filled_in_later(db_session, cam, monkeypatch):
    import httpx

    from app.enrichment import enrich, weather

    monkeypatch.setattr(weather, "_down_until", 0.0)
    monkeypatch.setattr(weather, "_DAY_CACHE", {})
    calls = []

    def down(*a, **k):
        calls.append(k.get("timeout"))
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "get", down)
    frames = [_frame(db_session, cam, NIGHT + timedelta(minutes=i)) for i in range(5)]
    snaps = [enrich.enrich_image(db_session, f) for f in frames]
    assert calls == [weather.TIMEOUT_SECONDS]  # once, not once per photo
    assert {s.source for s in snaps} == {"unavailable"}

    class Answer:
        def raise_for_status(self):
            pass

        def json(self):
            hours = [f"2026-09-20T{h:02d}:00" for h in range(24)]
            return {"hourly": {"time": hours, "temperature_2m": [14.0] * 24}}

    monkeypatch.setattr(weather, "_down_until", 0.0)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: Answer())
    again = enrich.enrich_image(db_session, frames[0])
    assert again.id == snaps[0].id and again.temp_c == 14.0 and again.source != "unavailable"


@requires_db
def test_weather_stored_while_open_meteo_was_down_is_filled_in_by_the_next_fetch(
    db_session, cam, models, monkeypatch,
):
    import httpx

    from app.enrichment import enrich, weather
    from app.ingestion.fetch import check_and_recount
    from app.models import EnvSnapshot

    monkeypatch.setattr(weather, "_down_until", 0.0)
    monkeypatch.setattr(weather, "_DAY_CACHE", {})
    recent = datetime.now(UTC) - timedelta(hours=20)

    def down(*a, **k):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "get", down)
    for i in range(3):
        enrich.enrich_image(db_session, _frame(db_session, cam, recent + timedelta(minutes=i)))
    old = _frame(db_session, cam, recent - timedelta(days=30))
    enrich.enrich_image(db_session, old)
    db_session.commit()
    # Still down: the fetch ends as before, nothing filled in, asked once.
    monkeypatch.setattr(weather, "_down_until", 0.0)
    assert check_and_recount(db_session)[0]["weather_refilled"] == 0

    class Answer:
        def raise_for_status(self):
            pass

        def json(self):
            day = recent.astimezone(ZoneInfo("Europe/Madrid")).date().isoformat()
            return {"hourly": {"time": [f"{day}T{h:02d}:00" for h in range(24)],
                               "temperature_2m": [14.0] * 24}}

    monkeypatch.setattr(weather, "_down_until", 0.0)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: Answer())
    assert check_and_recount(db_session)[0]["weather_refilled"] == 3
    db_session.expire_all()
    got = {s.observed_at == old.captured_at: (s.source, s.temp_c)
           for s in db_session.scalars(select(EnvSnapshot))}
    assert got[False] == ("open-meteo-forecast", 14.0)
    assert got[True] == ("unavailable", None)  # a month old: left alone, bounded


# ── Look for repeats ──────────────────────────────────────────────────────────


@requires_db
def test_look_for_repeats_runs_as_a_job_and_says_where_it_is(db_session, spawned):
    from app.api.routes_animals import recompute_animals, recompute_status

    assert recompute_animals(None, db_session)["status"] == "started"
    assert spawned == [("reid",)]
    assert recompute_status(None, db_session)["state"] == "queued"
    marker = jobs.try_acquire("reid", "reid")
    assert recompute_animals(None, db_session)["status"] == "busy"
    held = jobs.try_acquire("pipeline", "sync")
    assert recompute_status(None, db_session)["state"] == "waiting"
    held.release()
    marker.release()
    jobs.note(db_session, "reid_status", state="done", result={"new_candidates": 4})
    assert recompute_status(None, db_session)["result"] == {"new_candidates": 4}


@requires_db
def test_repeat_visitors_are_grouped_as_before(db_session, cam):
    np = pytest.importorskip("numpy")
    from app.ai import reid
    from app.models import DetectionIndividual, Individual

    db_session.add(Species(id="wild_boar", common_name="Wild Boar"))
    rng = np.random.default_rng(1)
    for base in rng.normal(size=(3, 64)):
        for _ in range(4):
            v = base + rng.normal(scale=0.01, size=64)
            img = _frame(db_session, cam, NIGHT, is_empty_frame=False, processed_at=NIGHT)
            db_session.add(Detection(image_id=img.id, species_id="wild_boar", species_conf=0.9,
                                     embedding=list(map(float, v / np.linalg.norm(v)))))
    db_session.commit()
    assert reid.cluster(db_session)["new_candidates"] == 3
    sizes = sorted(db_session.query(DetectionIndividual).filter_by(individual_id=i.id).count()
                   for i in db_session.query(Individual))
    assert sizes == [4, 4, 4]


# ── the buttons start jobs, never run them in the web server ──────────────────


@requires_db
def test_the_check_button_starts_a_job_and_reads_running_until_it_has_the_lock(
    db_session, cam, spawned,
):
    from app.api.routes_cameras import sync_status, trigger_sync

    assert trigger_sync(None, db_session)["status"] == "started"
    assert spawned == [("sync",)]
    # Its process is still starting: not someone else's old result.
    assert sync_status(None, db_session)["status"] == "running"
    held = jobs.try_acquire("pipeline", "sync")
    assert trigger_sync(None, db_session)["status"] == "busy"
    assert spawned == [("sync",)]
    held.release()


@requires_db
def test_the_check_button_queues_a_fetch_behind_another_job_and_says_so(
    db_session, cam, spawned,
):
    """Look for repeats (or the plan, or the score) holds the lock: no fetch is running,
    so "Already checking" would be untrue. The fetch waits for it instead."""
    from app.api.routes_cameras import sync_status, trigger_sync

    reid = jobs.try_acquire("pipeline", "reid")
    r = trigger_sync(None, db_session)
    assert r["status"] == "queued" and r["since"] is not None
    assert r["note"] == ("The server is looking for repeat visitors. "
                         "New photos come in when it finishes.")
    assert spawned == [("sync", "queued")]
    assert sync_status(None, db_session)["status"] == "running"
    queued = jobs.try_acquire("fetchqueue", "sync")  # its process, waiting for the lock
    again = trigger_sync(None, db_session)
    assert again["status"] == "queued" and "Already asked" in again["note"]
    assert spawned == [("sync", "queued")]  # one is on its way: not a second
    reid.release()
    # Look for repeats ran for a while, and the queued fetch has not taken the lock
    # yet: still running, never an older fetch's result read as this one's.
    from app.models import SyncLog

    jobs.note(db_session, "fetch_request", at=datetime.now(UTC) - timedelta(minutes=20))
    db_session.add(SyncLog(status="ok", started_at=datetime.now(UTC) - timedelta(hours=1),
                           details={"provider": "pipeline"}))
    db_session.commit()
    assert sync_status(None, db_session)["status"] == "running"
    queued.release()
    assert sync_status(None, db_session)["status"] == "ok"


@requires_db
def test_the_sex_pass_button_is_busy_while_a_pass_runs(db_session, spawned, monkeypatch):
    from app.api.routes_admin import sex_pass

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    held = jobs.try_acquire("sexpass", "sex")
    assert sex_pass(None)["status"] == "busy" and spawned == []
    held.release()
    assert sex_pass(None)["status"] == "started" and spawned == [("sex",)]
