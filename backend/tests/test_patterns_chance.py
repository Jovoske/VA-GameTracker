"""Insights stops presenting chance as findings (plan item 11).

The weather and moon comparison used to print "More sightings on a dark moon" in
86-99% of seasons made of pure noise, and counted nights the cameras were down as
quiet nights. These pin the two fixes: the series is built from nights the cameras
were watching, and nothing is a finding unless it beats a shuffle test.
"""
from __future__ import annotations

import math
import random
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.enrichment.astro import moon_phase
from app.forecasting import patterns
from app.forecasting.exposure import current_night, recompute_camera_nights
from app.forecasting.patterns import SCOPES, _scope_drivers, _shuffle_test
from app.models import Camera, Detection, Estate, Image, Species

from .conftest import requires_db

MADRID = ZoneInfo("Europe/Madrid")


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _season(seed: int, nights: int = 60, boar=lambda row: 2.0):
    """A season's conditions, and counts drawn from `boar(conditions)`."""
    rng = random.Random(seed)
    start = date(2025, 10, 1)
    dates, counts, weather, moon = [], {}, {}, {}
    for i in range(nights):
        ds = (start + timedelta(days=i)).isoformat()
        dates.append(ds)
        weather[ds] = {"temp": rng.uniform(2, 20), "pressure": rng.uniform(990, 1030),
                       "wind": rng.uniform(0, 30), "rain": rng.choice([0, 0, 0, 0.4, 3.0]),
                       "cloud": rng.uniform(0, 100)}
        moon[ds] = {"illum": rng.uniform(0, 100), "darkness": 700 + i}
        b = _poisson(rng, boar({**weather[ds], **moon[ds]}))
        d = _poisson(rng, 1.0)
        counts[ds] = {"cameras": 1, "all": b + d, "wild_boar": b, "red_deer": d}
    return dates, counts, weather, moon


def _findings(dates, counts, weather, moon) -> list[tuple[str, str]]:
    scopes = []
    for key, label in SCOPES:
        s = _scope_drivers(dates, counts, weather, moon, key)
        s["key"], s["label"] = key, label
        scopes.append(s)
    _shuffle_test(scopes)
    return [(s["key"], d["key"]) for s in scopes for d in s["drivers"] if d["beats_chance"]]


def test_pure_noise_is_almost_never_a_finding():
    """Counts that have nothing to do with the weather or the moon: at most about one
    season in twenty may show a finding. It used to be nearly every one."""
    seasons = 25
    with_finding = sum(1 for seed in range(seasons) if _findings(*_season(seed)))
    assert with_finding <= 3, f"{with_finding} of {seasons} noise seasons had a finding"


def test_a_real_difference_is_found():
    """Boar three times as busy on a dark moon, over 60 nights: that stands out."""
    season = _season(99, boar=lambda row: 3.0 if row["illum"] < 50 else 1.0)
    found = _findings(*season)
    assert ("wild_boar", "moon_illum") in found
    assert all(var == "moon_illum" for _, var in found)


def test_the_answer_does_not_change_between_visits():
    season = _season(7, boar=lambda row: 2.5 if row["illum"] < 50 else 1.5)
    assert _findings(*season) == _findings(*season)


# ── the series: watched nights only ─────────────────────────────────────────


def _at(night: date, hour: int) -> datetime:
    day = night if hour >= 6 else night + timedelta(days=1)
    return datetime.combine(day, time(hour), tzinfo=MADRID).astimezone(UTC)


@requires_db
def test_a_dead_camera_near_full_moon_is_not_a_dark_moon_finding(db_session, monkeypatch):
    """The same two or three boar visits every night, and the camera dead (no frames
    at all) on the nights near full moon. Zero-filled, that read "About 1.1 sightings
    a day with a bright moon, about 2.5 with a dark moon", and "More sightings on a
    dark moon". Those nights are now left out: no finding, no bright-moon zeros."""
    monkeypatch.setattr(patterns, "_overnight_weather", lambda *a: {})
    estate = Estate(name="E", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db_session.add(estate)
    db_session.add(Species(id="wild_boar", common_name="Wild Boar", huntable=True))
    db_session.flush()
    cam = Camera(estate_id=estate.id, name="Puente", active=True)
    db_session.add(cam)
    db_session.flush()
    tonight = current_night()
    watched = 0
    for n in range(1, 91):
        night = tonight - timedelta(days=n)
        _, illum = moon_phase(datetime(night.year, night.month, night.day, 23, tzinfo=UTC))
        if illum > 75:
            continue  # the camera is dead: not a frame
        watched += 1
        empty = Image(camera_id=cam.id, captured_at=_at(night, 19), is_empty_frame=True,
                      processed_at=_at(night, 19))
        db_session.add(empty)
        for hour in ((21, 1) if n % 2 else (21, 23, 3)):
            img = Image(camera_id=cam.id, captured_at=_at(night, hour), is_empty_frame=False,
                        processed_at=_at(night, hour))
            db_session.add(img)
            db_session.flush()
            db_session.add(Detection(image_id=img.id, species_id="wild_boar", group_size=1))
    db_session.commit()
    recompute_camera_nights(db_session)

    got = patterns.compute_patterns(db_session)
    assert got["tested"] is True
    boar = next(s for s in got["scopes"] if s["key"] == "wild_boar")
    # The dead spells are longer than two nights, so they are not presumed watched.
    assert boar["total_nights"] == watched
    moon = next(d for d in boar["drivers"] if d["key"] == "moon_illum")
    assert moon["beats_chance"] is False
    assert all(b["rate"] >= 2 for b in moon["buckets"]), "no zero-filled bright moon"
    # No weather history: said so per condition, not "not enough nights".
    assert boar["status"]["temp"] == "unavailable"
    assert boar["status"]["moon_illum"] == "ok"


# ── G-20: a failed weather fetch is asked again soon ────────────────────────


def test_a_failed_weather_fetch_is_not_kept_all_day(monkeypatch):
    calls = []

    class Down:
        def __call__(self, *a, **k):
            calls.append(1)
            raise OSError("no route to archive-api.open-meteo.com")

    monkeypatch.setattr(patterns.httpx, "get", Down())
    patterns._WCACHE.clear()
    start = date.today() - timedelta(days=40)
    end = date.today() - timedelta(days=1)
    first = patterns._overnight_weather(39.0, -1.3, start, end)
    assert all(v["temp"] is None for v in first.values())
    tried = len(calls)
    patterns._overnight_weather(39.0, -1.3, start, end)
    assert len(calls) == tried, "asked again at once: the cache holds it a few minutes"
    key = next(iter(patterns._WCACHE))
    nights, expires = patterns._WCACHE[key]
    assert expires is not None and expires - datetime.now(UTC) <= timedelta(minutes=10)
    patterns._WCACHE[key] = (nights, datetime.now(UTC) - timedelta(seconds=1))
    patterns._overnight_weather(39.0, -1.3, start, end)
    assert len(calls) == 2 * tried, "after a few minutes it is asked again"
    patterns._WCACHE.clear()


@pytest.mark.parametrize("seed", [3])
def test_every_condition_gets_bars_even_without_a_finding(seed):
    """G-20: a weak difference used to drop the whole card to "Not enough nights to
    compare yet" with 90 nights on the cameras."""
    dates, counts, weather, moon = _season(seed, nights=90)
    s = _scope_drivers(dates, counts, weather, moon, "all")
    assert {d["key"] for d in s["drivers"]} == {
        "moon_illum", "pressure", "pressure_trend", "temp", "wind", "rain", "cloud", "darkness"}
