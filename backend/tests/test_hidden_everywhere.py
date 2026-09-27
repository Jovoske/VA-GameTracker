"""Hidden animals and hidden photos stay hidden everywhere (plan item 10).

Two ways a hunter takes something out of the app: hiding a species in Settings
("rabbits, fox: not interested"), and marking a photo "nothing in it" when the AI
saw a boar in a bush. One test per screen below says the hidden thing never
appears there, counted or shown, and that marking a photo reaches the plan and the
track record, not only the photo lists.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.forecasting import model
from app.forecasting.exposure import current_night, recompute_camera_nights, visits_by_night
from app.models import (
    Camera,
    Detection,
    DetectionIndividual,
    Estate,
    Forecast,
    ForecastOutcome,
    Image,
    Individual,
    Species,
    User,
)

from .conftest import requires_db

MADRID = ZoneInfo("Europe/Madrid")
TONIGHT = current_night()


def ago(n: int) -> date:
    return TONIGHT - timedelta(days=n)


def at(night: date, hour: int, minute: int = 0) -> datetime:
    day = night if hour >= 6 else night + timedelta(days=1)
    return datetime.combine(day, time(hour, minute), tzinfo=MADRID).astimezone(UTC)


class World:
    """Piedras Lisas with two cameras: Charca sees real boar and a lot of foxes the
    owner hid; Matorral's "boar" on six of the last seven nights is a bush."""

    def __init__(self, db):
        self.db = db
        self.estate = Estate(name="Piedras Lisas", timezone="Europe/Madrid")
        db.add(self.estate)
        db.add_all([
            Species(id="wild_boar", common_name="Wild Boar", huntable=True, is_priority=True),
            # Hidden: out of the app. is_priority stays as it was, and must not matter.
            Species(id="fox", common_name="Fox", huntable=False, hidden=True, is_priority=True),
        ])
        db.flush()
        self.member = User(estate_id=self.estate.id, email="pedro@x.local",
                           password_hash="x", role="member")
        db.add(self.member)
        now = datetime.now(UTC)
        self.charca = Camera(estate_id=self.estate.id, name="Charca", last_report_at=now)
        self.matorral = Camera(estate_id=self.estate.id, name="Matorral", last_report_at=now)
        db.add_all([self.charca, self.matorral])
        db.flush()
        self.bush: list[Image] = []
        for n in range(1, 21):
            for cam in (self.charca, self.matorral):
                self.photo(cam, ago(n), 20, None)  # an empty frame: watching
            if n % 4 == 0:
                self.photo(self.charca, ago(n), 22, "wild_boar")
            # Foxes all day at Charca, every night, and a crowd last night.
            for hour in (11, 12, 13, 23) if n > 1 else (11, 12, 13, 19, 21, 23, 1, 3):
                self.photo(self.charca, ago(n), hour, "fox")
            if n <= 7 and n != 4:
                self.bush.append(self.photo(self.matorral, ago(n), 21, "wild_boar"))
        db.commit()
        recompute_camera_nights(db)

    def photo(self, cam, night, hour, species) -> Image:
        img = Image(camera_id=cam.id, captured_at=at(night, hour), processed_at=at(night, hour),
                    is_empty_frame=species is None, reviewed=False,
                    original_path=f"/nonexistent/{cam.name}-{night}-{hour}.jpg")
        self.db.add(img)
        self.db.flush()
        if species:
            self.db.add(Detection(image_id=img.id, species_id=species, group_size=1))
        return img

    def headers(self):
        token = create_access_token(str(self.member.id), {"role": "member"})
        return {"Authorization": f"Bearer {token}"}

    def hide_the_bush(self, client):
        for img in self.bush:
            got = client.post(f"/api/images/{img.id}/flag", json={"is_empty": True},
                              headers=self.headers())
            assert got.status_code == 200


@pytest.fixture
def world(db_session, monkeypatch):
    monkeypatch.setattr(model, "_tonight_conditions", lambda now: {"moon_phase": "New Moon"})
    return World(db_session)


@pytest.fixture
def client(db_session):
    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Tonight ─────────────────────────────────────────────────────────────────


@requires_db
def test_a_photo_marked_nothing_in_it_stops_counting_on_tonight(world, client, db_session):
    """K-05: the photos disappeared from Photos, and Tonight kept recommending the
    spot on the strength of those same photos."""
    before = model.forecast_tonight(db_session)
    assert before["recommended"]["camera"] == "Matorral"
    assert before["recommended"]["reason"] == "Wild boar seen 6 of 20 nights at this camera."

    world.hide_the_bush(client)
    after = model.forecast_tonight(db_session)
    assert [w["camera"] for w in after["where"]] == ["Charca"]
    assert after["recommended"]["reason"] == "Wild boar seen 5 of 20 nights at this camera."
    assert "Fox" not in str(after)


@requires_db
def test_hidden_foxes_never_reach_the_changed_line(world, db_session):
    """Eight hidden foxes last night against a usual four made "busier than usual"."""
    got = model.whats_changed(db_session)
    assert got["kind"] == "none", got
    visits = visits_by_night(db_session)
    assert not any(species == "fox" for _, _, species in visits)


@requires_db
def test_hidden_and_marked_photos_are_not_alerts(world, client, db_session):
    from app.forecasting.alerts import compute_alerts

    world.hide_the_bush(client)
    feed = compute_alerts(db_session)
    assert not any(a["title"] == "Fox" for a in feed)
    # The only boar in the last two days was the bush.
    assert not any(a["type"] == "sighting" for a in feed)


# ── Insights ────────────────────────────────────────────────────────────────


@requires_db
def test_hidden_foxes_never_reach_the_insights(world, client, db_session):
    """Hidden foxes at midday used to make "Your cameras are busiest between 11:00
    and 14:00", and put Charca at the top of "Most of the action"."""
    world.hide_the_bush(client)
    got = client.get("/api/insights", headers=world.headers()).json()
    assert "Fox" not in str(got["composition"]) and "fox" not in str(got["correlations"])
    assert {c["label"]: c["visits"] for c in got["composition"]} == {"Wild boar": 5}
    photos = client.get("/api/insights/class", params={"label": "Wild boar"},
                        headers=world.headers()).json()
    assert len(photos["items"]) == 5 and photos["next_before"] is None
    assert {p["camera"] for p in photos["items"]} == {"Charca"}
    assert client.get("/api/insights/class", params={"label": "Fox"},
                      headers=world.headers()).json()["items"] == []


@requires_db
def test_hidden_foxes_and_marked_photos_never_reach_the_weather_patterns(world, client,
                                                                          db_session):
    from app.forecasting.patterns import _nightly_activity

    world.hide_the_bush(client)
    nights, counts = _nightly_activity(db_session)
    assert len(nights) == 20
    # Five real boar nights, two watching cameras each: half a visit per camera.
    assert sum(1 for c in counts.values() if c.get("all")) == 5
    assert all(c.get("all", 0) == pytest.approx(0.5) for c in counts.values() if c.get("all"))
    assert not any("fox" in c for c in counts.values())


# ── Animals, Photos, the fold on Tonight ────────────────────────────────────


@requires_db
def test_a_marked_photo_leaves_the_animals_page_and_the_chips(world, client, db_session):
    """C-05: Animals said "Wild boar · Seen today" with the bush as its picture."""
    world.hide_the_bush(client)
    spotted = client.get("/api/species/spotted", headers=world.headers()).json()
    assert [s["id"] for s in spotted] == ["wild_boar"]
    assert spotted[0]["count"] == 5
    bush_ids = {str(img.id) for img in world.bush}
    assert spotted[0]["thumb_image_id"] not in bush_ids
    gallery = client.get("/api/species/wild_boar/images", headers=world.headers()).json()
    assert len(gallery) == 5 and not {g["image_id"] for g in gallery} & bush_ids
    chips = client.get("/api/photos/filters", headers=world.headers()).json()["species"]
    assert chips == [{"id": "wild_boar", "common_name": "Wild boar", "count": 5}]
    overview = client.get("/api/analytics/overview", headers=world.headers()).json()
    assert overview["by_species"] == [{"species": "Wild Boar", "count": 5}]


@requires_db
def test_a_hidden_species_has_no_named_animals(world, client, db_session):
    """C-23: a hidden fox came back as "Fox #1" under Named animals."""
    fox_detection = db_session.query(Detection).filter_by(species_id="fox").first()
    boar_detection = db_session.query(Detection).filter_by(species_id="wild_boar").first()
    for species, det in (("fox", fox_detection), ("wild_boar", boar_detection)):
        ind = Individual(estate_id=world.estate.id, label=f"{species} #1", species_id=species)
        db_session.add(ind)
        db_session.flush()
        db_session.add(DetectionIndividual(detection_id=det.id, individual_id=ind.id,
                                           match_conf=0.99))
    db_session.commit()
    named = client.get("/api/animals", headers=world.headers()).json()
    assert [a["species_id"] for a in named] == ["wild_boar"]


# ── The track record ────────────────────────────────────────────────────────


@requires_db
def test_marking_a_photo_grades_the_night_again(world, client, db_session):
    """A night already graded "boar came" on the bush is graded again when the hunter
    says there was nothing in it, so the track record doesn't keep the AI's mistake."""
    from app.forecasting.scoring import evaluate_night

    night = ago(2)
    fc = Forecast(camera_id=world.matorral.id, target_date=night, species_id="wild_boar",
                  probability=0.3, factors={"verdict": "WORTH_A_LOOK"})
    db_session.add(fc)
    db_session.commit()
    evaluate_night(db_session, night=night)
    assert db_session.get(ForecastOutcome, fc.id).occurred is True

    world.hide_the_bush(client)
    db_session.expire_all()
    assert db_session.get(ForecastOutcome, fc.id).occurred is False
