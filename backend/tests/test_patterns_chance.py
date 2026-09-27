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
    later = []
    monkeypatch.setattr(patterns, "_start_thread", later.append)
    patterns._WCACHE.clear()
    patterns._KNOWN.clear()
    patterns._REFRESHING.clear()
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
    assert len(later) == 1, "and behind the page, once, without the rush"
    patterns._WCACHE.clear()
    patterns._REFRESHING.clear()


@pytest.mark.parametrize("seed", [3])
def test_every_condition_gets_bars_even_without_a_finding(seed):
    """G-20: a weak difference used to drop the whole card to "Not enough nights to
    compare yet" with 90 nights on the cameras."""
    dates, counts, weather, moon = _season(seed, nights=90)
    s = _scope_drivers(dates, counts, weather, moon, "all")
    assert {d["key"] for d in s["drivers"]} == {
        "moon_illum", "pressure", "pressure_trend", "temp", "wind", "rain", "cloud", "darkness"}


# ── R3BE-3: a season that drifts is not a finding ───────────────────────────

_SKY: dict = {}


def _real_season(seed: int, nights: int, rate) -> tuple:
    """A season on a real calendar: the moon's own cycle, the night lengthening into
    winter, the temperature falling with it and wandering with the weather, pressure
    wandering too. The boar's numbers come from `rate(i, rng)` and nothing else."""
    from app.enrichment.astro import solar

    rng = random.Random(seed)
    start = date(2025, 9, 1) + timedelta(days=rng.randrange(0, 60))
    dates, counts, weather, moon = [], {}, {}, {}
    t_noise = p_noise = 0.0
    for i in range(nights):
        d = start + timedelta(days=i)
        if d not in _SKY:
            _SKY[d] = (moon_phase(datetime(d.year, d.month, d.day, 23, tzinfo=UTC))[1],
                       solar(39.09, -1.36, d).get("darkness_minutes"))
        ds = d.isoformat()
        dates.append(ds)
        t_noise = 0.8 * t_noise + rng.gauss(0, 1.5)
        p_noise = 0.7 * p_noise + rng.gauss(0, 4)
        weather[ds] = {"temp": 18 - 0.12 * i + t_noise, "pressure": 1015 + p_noise,
                       "wind": max(0, 10 + rng.gauss(0, 5)),
                       "rain": rng.choice([0, 0, 0, 0, 0.4, 3.0]),
                       "cloud": max(0, min(100, 50 + rng.gauss(0, 30)))}
        moon[ds] = {"illum": _SKY[d][0], "darkness": _SKY[d][1]}
        b = _poisson(rng, rate(i, rng))
        r = _poisson(rng, 1.0)
        counts[ds] = {"cameras": 1, "all": b + r, "wild_boar": b, "red_deer": r}
    return dates, counts, weather, moon


def test_boar_building_up_through_the_autumn_is_not_a_long_night_finding():
    """Acorns fall and the boar build up from one visit a night to two and a half,
    while the nights lengthen and cool. Tested on raw counts that read as "more wild
    boar on long nights" or "on cool nights" in a quarter of such seasons."""
    seasons, found = 40, []
    for seed in range(seasons):
        season = _real_season(seed, 90, lambda i, rng: 1.0 + 1.5 * i / 90)
        found += [f for f in _findings(*season)]
    seasonal = [f for f in found if f[1] in ("darkness", "temp")]
    assert seasonal == [], seasonal
    assert len(found) <= 3, found


def test_a_sounder_that_wanders_between_feeders_is_not_a_finding():
    """The boar's own numbers drift for a fortnight at a time (a sounder moves to
    another feeder), nothing to do with any condition: still about one season in
    twenty with a finding, not one in seven."""
    def wandering(seed):
        level = [0.0]

        def rate(i, rng):
            level[0] = 0.9 * level[0] + rng.gauss(0, math.sqrt(1 - 0.81) * 0.6)
            return 1.5 * math.exp(level[0])
        return _real_season(seed, 60, rate)

    seasons = 60
    with_finding = sum(1 for seed in range(seasons) if _findings(*wandering(seed)))
    assert with_finding <= 6, f"{with_finding} of {seasons} drifting seasons had a finding"


def test_a_real_moon_pattern_on_a_real_calendar_is_still_found():
    """Taking the season out must not take the moon out with it: the level is read
    over a whole moon cycle."""
    hits = 0
    for seed in range(20):
        season = _real_season(seed, 90, lambda i, rng: 1.0)
        dates, counts, weather, moon = season
        rng = random.Random(500 + seed)
        for ds in dates:
            b = _poisson(rng, 3.0 if moon[ds]["illum"] < 50 else 1.0)
            counts[ds]["wild_boar"], counts[ds]["all"] = b, b + counts[ds]["red_deer"]
        hits += ("wild_boar", "moon_illum") in _findings(dates, counts, weather, moon)
    assert hits >= 15, f"found in {hits} of 20"


# ── R3BE-2: a finding says only what was tested ─────────────────────────────


def test_a_finding_is_about_the_ends_even_when_the_middle_is_busiest():
    """Boar avoid still air and come about as much in middling as in strong wind. What
    was tested is still air against wind; the finding says which end had more, and
    the page words it from those two ends, never "in middling wind"."""
    season = _real_season(3, 90, lambda i, rng: 1.0)
    dates, counts, weather, moon = season
    rng = random.Random(3)
    for ds in dates:
        w = weather[ds]["wind"]
        b = _poisson(rng, 0.4 if w < 8 else (2.6 if w < 12 else 2.2))
        counts[ds]["wild_boar"], counts[ds]["all"] = b, b + counts[ds]["red_deer"]
    scopes = []
    for key, label in SCOPES:
        s = _scope_drivers(dates, counts, weather, moon, key)
        s["key"], s["label"] = key, label
        scopes.append(s)
    _shuffle_test(scopes)
    boar = next(s for s in scopes if s["key"] == "wild_boar")
    wind = next(d for d in boar["drivers"] if d["key"] == "wind")
    rates = {b["label"]: b["rate"] for b in wind["buckets"]}
    assert rates["mid"] > rates["high"] > rates["low"], rates
    assert wind["beats_chance"] is True
    assert wind["favours_high"] is True and wind["favours"] == "wind"


# ── R3BE-5 / G-20: a dry autumn still compares rain ─────────────────────────


def test_a_dry_autumn_compares_dry_nights_with_wet_ones():
    """Rain on one night in eight: two thirds of the nights read 0 mm, the thirds
    tie, and after 90 nights the card still said "Not enough nights to compare"."""
    dates, counts, weather, moon = _season(3, nights=90)
    rng = random.Random(3)
    for ds in dates:
        weather[ds]["rain"] = rng.choice([0.0] * 7 + [2.5])
    s = _scope_drivers(dates, counts, weather, moon, "all")
    assert s["status"]["rain"] == "ok"
    rain = next(d for d in s["drivers"] if d["key"] == "rain")
    low, high = rain["buckets"]
    assert (low["label"], low["min"], low["max"]) == ("low", 0.0, 0.0)
    assert high["label"] == "high" and high["min"] > 0
    assert low["days"] + high["days"] == 90

    # Three wet nights in ninety is too few to say anything about rain: said so,
    # not "Not enough nights".
    for i, ds in enumerate(dates):
        weather[ds]["rain"] = 2.5 if i in (10, 40, 70) else 0.0
    s = _scope_drivers(dates, counts, weather, moon, "all")
    assert s["status"]["rain"] == "no_spread"
    assert not any(d["key"] == "rain" for d in s["drivers"])
    short = _scope_drivers(dates[:8], counts, weather, moon, "all")
    assert short["status"]["rain"] == "insufficient"


# ── R3BE-7: a weather service that hangs never holds the page ────────────────


def _hourly(start: str, end: str, temp: float = 10.0) -> dict:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    times = [f"{(first + timedelta(days=d)).isoformat()}T{h:02d}:00"
             for d in range((last - first).days + 1) for h in range(24)]
    n = len(times)
    return {"hourly": {"time": times, "temperature_2m": [temp] * n,
                       "surface_pressure": [1015.0] * n, "wind_speed_10m": [8.0] * n,
                       "precipitation": [0.0] * n, "cloud_cover": [40.0] * n}}


class _Answer:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


@pytest.fixture
def fresh_weather(monkeypatch):
    patterns._WCACHE.clear()
    patterns._KNOWN.clear()
    patterns._REFRESHING.clear()
    yield
    patterns._WCACHE.clear()
    patterns._KNOWN.clear()
    patterns._REFRESHING.clear()


def test_a_hanging_weather_service_holds_the_page_a_few_seconds_at_most(
    monkeypatch, fresh_weather,
):
    """Open-Meteo hanging rather than refusing: each of two calls waited 30 s, and
    Insights gave up at 30 s with "Could not load the weather findings"."""
    clock = [0.0]
    asked = []

    def hang(url, params=None, timeout=None):
        asked.append(timeout)
        clock[0] += timeout  # waits the whole timeout, then gives up
        raise patterns.httpx.ReadTimeout("timed out")

    monkeypatch.setattr(patterns, "_clock", lambda: clock[0])
    monkeypatch.setattr(patterns.httpx, "get", hang)
    later = []
    monkeypatch.setattr(patterns, "_start_thread", later.append)
    today = datetime.now(UTC).date()
    got = patterns._overnight_weather(39.0, -1.3, today - timedelta(days=60),
                                      today - timedelta(days=1))
    assert clock[0] <= patterns.WEATHER_BUDGET_S
    assert len(asked) == 1, "no time left for the second call: not asked"
    assert all(n["temp"] is None for n in got.values())
    # What didn't come in time is asked for behind the page, with time to spare.
    assert len(later) == 1
    clock[0] = 0.0
    later[0]()
    assert len(asked) == 3 and asked[1] > patterns.WEATHER_BUDGET_S


def test_known_weather_is_served_at_once_and_refreshed_behind(monkeypatch, fresh_weather):
    """Once the weather of a season has been fetched, a new night (or a failed retry)
    never makes a visit wait: what is known is served and the rest asked for behind."""
    later = []
    monkeypatch.setattr(patterns, "_start_thread", later.append)
    calls = []

    def works(url, params=None, timeout=None):
        calls.append(url)
        return _Answer(_hourly(params["start_date"], params["end_date"]))

    monkeypatch.setattr(patterns.httpx, "get", works)
    today = datetime.now(UTC).date()
    start, end = today - timedelta(days=40), today - timedelta(days=2)
    first = patterns._overnight_weather(39.0, -1.3, start, end)
    assert all(n["temp"] == 10.0 for n in first.values())
    tried = len(calls)

    def hang(url, params=None, timeout=None):
        calls.append(url)
        raise patterns.httpx.ReadTimeout("timed out")

    monkeypatch.setattr(patterns.httpx, "get", hang)
    # The next morning the season is a night longer: served at once from what is known.
    got = patterns._overnight_weather(39.0, -1.3, start, end + timedelta(days=1))
    assert len(calls) == tried, "nobody waited on the weather service"
    assert got[start.isoformat()]["temp"] == 10.0
    assert got[(end + timedelta(days=1)).isoformat()]["temp"] is None
    assert len(later) == 1
    # Asked again while that refresh is still out: not a second one.
    patterns._overnight_weather(39.0, -1.3, start, end + timedelta(days=1))
    assert len(later) == 1
    later[0]()  # the refresh runs, fails, and is kept a few minutes with what is known
    assert len(calls) > tried
    key = next(k for k in patterns._WCACHE if k[3] == (end + timedelta(days=1)).isoformat())
    nights, expires = patterns._WCACHE[key]
    assert expires is not None and nights[start.isoformat()]["temp"] == 10.0
    assert patterns._REFRESHING == set()
