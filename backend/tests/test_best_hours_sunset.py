"""Best hours follow sunset (plan item 8).

Sunset in Alatoz moves about three hours between early August and late October, the
clock change included. A season's histogram of clock hours kept sending hunters out
after the animals had come: on 26 Oct it said 20:00 to 23:00 for boar that arrive
from 18:56 (audit G-05, J-08). These pin the window to each night's sunset.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.enrichment.astro import moon_phase
from app.forecasting import model
from app.forecasting.model import SLOT_MIN, _sunset, _sunset_window

from .conftest import requires_db

MADRID = ZoneInfo("Europe/Madrid")


def _slots(nights, offsets_min) -> dict:
    """Visits per (night, quarter hour of the clock) for arrivals `offsets_min` after
    each night's sunset."""
    out: dict = {}
    for night in nights:
        for off in offsets_min:
            local = (_sunset(night) + timedelta(minutes=off)).astimezone(MADRID)
            slot = (local.hour * 60 + local.minute) // SLOT_MIN
            out[(night, slot)] = out.get((night, slot), 0) + 1
    return out


def _clock(hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(2026, 1, 1, h, m)


def _span(start: date, end: date) -> list[date]:
    return [start + timedelta(days=d) for d in range((end - start).days + 1)]


def test_after_the_clock_change_the_window_is_on_the_boar_not_an_hour_late():
    """Boar 45, 70 and 90 min after every sunset from 1 Aug to 24 Oct."""
    slots = _slots(_span(date(2026, 8, 1), date(2026, 10, 24)), (45, 70, 90))
    tonight = date(2026, 10, 26)
    w = _sunset_window(slots, tonight)
    sunset = _sunset(tonight).astimezone(MADRID)
    assert sunset.strftime("%H:%M").startswith("18:1")  # CET, after 25 Oct
    first = (sunset + timedelta(minutes=45)).replace(tzinfo=None)
    last = (sunset + timedelta(minutes=90)).replace(tzinfo=None)
    start = _clock(w["start"]).replace(year=first.year, month=first.month, day=first.day)
    end = start + timedelta(hours=3)
    # In the seat before the first of them, and still there after the last.
    assert start <= first and end >= last
    assert w["share_pct"] == 100
    assert w["start_hour"] in (17, 18) and w["start_hour"] != 20


def test_the_same_boar_give_the_same_hours_after_sunset_all_season():
    slots = _slots(_span(date(2026, 8, 1), date(2026, 9, 20)), (60, 75))
    aug = _sunset_window(slots, date(2026, 8, 5))
    late_oct = _sunset_window(slots, date(2026, 10, 27))
    assert aug["after_sunset_min"] == late_oct["after_sunset_min"]
    # ...which is about three hours earlier on the clock by late October.
    moved = _clock(aug["start"]) - _clock(late_oct["start"])
    assert timedelta(hours=2, minutes=30) <= moved <= timedelta(hours=3, minutes=30)


def test_the_recent_weeks_count_most():
    """In August they came three hours after dark; for the last fortnight within the
    first hour. The window follows the fortnight."""
    tonight = date(2026, 10, 1)
    old = _slots(_span(tonight - timedelta(days=60), tonight - timedelta(days=31)), (240, 250))
    recent = _slots(_span(tonight - timedelta(days=14), tonight - timedelta(days=1)), (30, 40))
    w = _sunset_window({**old, **recent}, tonight)
    assert w["after_sunset_min"] <= 30
    assert w["share_pct"] > 50


def test_nobody_is_sent_out_at_three_in_the_morning():
    slots = _slots(_span(date(2026, 9, 1), date(2026, 9, 20)), (420, 430, 440))  # ~03:00
    w = _sunset_window(slots, date(2026, 9, 26))
    assert w["start_hour"] in model.SITTABLE_HOURS


def test_moon_names_are_centred_on_the_phase():
    """The full moon of 26 Sep 2026 (16:49 UTC) read "Waxing Gibbous" that morning and
    "Full Moon" three nights later (audit F-21)."""
    assert moon_phase(datetime(2026, 9, 26, 6, 49, tzinfo=UTC))[0] == "Full Moon"
    assert moon_phase(datetime(2026, 9, 26, 22, tzinfo=UTC))[0] == "Full Moon"
    assert moon_phase(datetime(2026, 9, 30, 12, tzinfo=UTC))[0] == "Waning Gibbous"
    assert moon_phase(datetime(2026, 9, 22, 12, tzinfo=UTC))[0] == "Waxing Gibbous"


# ── through the plan ─────────────────────────────────────────────────────────


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(model, "_tonight_conditions", lambda now: {"moon_phase": "New Moon"})


@requires_db
def test_tonight_says_the_hours_from_sunset(db_session, offline):
    from app.forecasting.exposure import current_night, recompute_camera_nights
    from app.models import Camera, Detection, Estate, Image, Species

    e = Estate(name="E", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db_session.add(e)
    db_session.add(Species(id="wild_boar", common_name="Wild boar", huntable=True,
                           is_priority=True))
    db_session.flush()
    cam = Camera(estate_id=e.id, name="Puente", active=True, last_report_at=datetime.now(UTC))
    db_session.add(cam)
    db_session.flush()
    tonight = current_night()
    for n in range(1, 21):
        night = tonight - timedelta(days=n)
        img = Image(camera_id=cam.id, captured_at=_sunset(night) + timedelta(minutes=60),
                    is_empty_frame=False, processed_at=datetime.now(UTC), reviewed=False)
        db_session.add(img)
        db_session.flush()
        db_session.add(Detection(image_id=img.id, species_id="wild_boar", group_size=1))
    db_session.commit()
    recompute_camera_nights(db_session)

    out = model.forecast_tonight(db_session)
    w = out["recommended"]["best_window"]
    assert set(w) >= {"start", "end", "start_hour", "end_hour", "after_sunset_min"}
    assert out["factors"][-1]["text"].startswith(f"Best hours {w['start']} to {w['end']}, from ")
    assert "sunset" in out["factors"][-1]["text"]
    arrival = (_sunset(tonight) + timedelta(minutes=60)).astimezone(MADRID)
    start = datetime.combine(tonight, time(*map(int, w["start"].split(":"))), tzinfo=MADRID)
    assert start <= arrival <= start + timedelta(hours=3)

    # The claim written for scoring keeps the minutes.
    from sqlalchemy import select

    from app.forecasting.scoring import persist_tonight
    from app.models import Forecast

    persist_tonight(db_session, out, target=tonight)
    saved = db_session.scalar(select(Forecast))
    assert saved.best_window_start.strftime("%H:%M") == w["start"]


@requires_db
def test_the_dark_exit_follows_sunset_too(db_session):
    from app.forecasting.exposure import current_night
    from app.forecasting.inference import SIT_ENDS_AFTER_SUNSET, dark_exit
    from app.models import Camera, Detection, Estate, Image, Species, Stand

    e = Estate(name="E", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db_session.add(e)
    db_session.add(Species(id="wild_boar", common_name="Wild boar", huntable=True,
                           is_priority=True))
    db_session.flush()
    cam = Camera(estate_id=e.id, name="Puente", active=True)
    db_session.add(cam)
    db_session.flush()
    stand = Stand(estate_id=e.id, name="Puente alto", camera_id=cam.id)
    db_session.add(stand)
    tonight = current_night()
    # Every night: boar from sunset to 3 h 30 after it, so the first hour after a
    # normal sit is busy, and the next is empty.
    for n in range(1, 40):
        night = tonight - timedelta(days=n)
        for off in (30, 90, 150, 200):
            img = Image(camera_id=cam.id, captured_at=_sunset(night) + timedelta(minutes=off),
                        is_empty_frame=False, processed_at=datetime.now(UTC), reviewed=False)
            db_session.add(img)
            db_session.flush()
            db_session.add(Detection(image_id=img.id, species_id="wild_boar", group_size=1))
    db_session.commit()

    out = dark_exit(db_session, stand)
    expected = _sunset(tonight) + SIT_ENDS_AFTER_SUNSET + timedelta(hours=1)
    quarter = datetime.fromtimestamp(round(expected.timestamp() / 900) * 900, tz=UTC)
    assert out["reason"] is None and out["share_pct"] == 0.0
    assert out["time"] == quarter.astimezone(MADRID).strftime("%H:%M")
    assert "visits" in out["text"]
