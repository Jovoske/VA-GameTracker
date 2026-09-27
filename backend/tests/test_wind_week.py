"""The wind hour by hour, and the right evenings this week (feature 22).

One wind value at the sit used to cover the whole evening, though the forecast
already held every hour: a hunter couldn't see the wind going wrong at 21:00, or
that Thursday is the evening for a stand. Each test pins one promise: the week in
one forecast call shared with Tonight, the line up front, the same verdict as every
other screen, a stand that can't be judged saying why, and an answer kept for the
hour but never past a change.
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import geo
from app.core.security import create_access_token
from app.enrichment import weather
from app.forecasting import conditions, wind_week
from app.forecasting import model as model_mod
from app.forecasting.exposure import current_night
from app.models import Estate, Stand, User, Zone

from .conftest import requires_db

MADRID = ZoneInfo("Europe/Madrid")
LAT0, LON0 = 39.09, -1.36
# Wind from the north sends the scent south, away from the bedding drawn north of
# the stand: right. From the south it blows into it: wrong.
RIGHT, WRONG = 0.0, 180.0


def _off(east_m: float, north_m: float) -> tuple[float, float]:
    return (LAT0 + math.degrees(north_m / geo.EARTH_R_M),
            LON0 + math.degrees(east_m / (geo.EARTH_R_M * math.cos(math.radians(LAT0)))))


def _poly(*corners: tuple[float, float]) -> dict:
    ring = [[_off(e, n)[1], _off(e, n)[0]] for e, n in corners]
    return {"type": "Polygon", "coordinates": [ring + [ring[0]]]}


def _at(day: date, hour: int) -> datetime:
    day, hour = (day, hour) if hour < 24 else (day + timedelta(days=1), 0)
    return datetime.combine(day, time(hour), tzinfo=MADRID)


# ── one call for the week, the same copy Tonight reads ──────────────────────


class _Answer:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


def _range(start: date, end: date, wind_dir) -> dict:
    """Open-Meteo's answer for start..end, hour by hour on the estate's clock."""
    times, dirs = [], []
    day = start
    while day <= end:
        for h in range(24):
            t = datetime.combine(day, time(h), tzinfo=MADRID)
            times.append(int(t.timestamp()))
            dirs.append(wind_dir(t))
        day += timedelta(days=1)
    n = len(times)
    return {"hourly": {"time": times, "wind_direction_10m": dirs, "wind_speed_10m": [15.0] * n,
                       "cloud_cover": [10.0] * n, "temperature_2m": [12.0] * n}}


@pytest.fixture
def clean_weather(monkeypatch):
    monkeypatch.setattr(weather, "_DAY_CACHE", {})
    monkeypatch.setattr(weather, "_down_until", {})
    monkeypatch.setattr(weather, "_FAILED", set())
    clock = [1000.0]
    monkeypatch.setattr(weather.time, "monotonic", lambda: clock[0])
    return clock


def test_the_week_is_one_call_and_tonight_reads_the_same_copy(monkeypatch, clean_weather):
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(params)
        return _Answer(_range(date.fromisoformat(params["start_date"]),
                              date.fromisoformat(params["end_date"]),
                              lambda t: float(t.hour * 10)))

    monkeypatch.setattr(weather.httpx, "get", get)
    first = current_night()
    got = weather.forecast_hours(LAT0, LON0, first, 9)
    assert len(calls) == 1 and calls[0]["timeformat"] == "unixtime"
    assert (calls[0]["start_date"], calls[0]["end_date"]) == (
        first.isoformat(), (first + timedelta(days=8)).isoformat())
    at = _at(first + timedelta(days=1), 21)
    assert got["hours"][int(at.timestamp())]["wind_dir_deg"] == 210.0
    assert got["stale"] is False and got["fetched_at"] is not None
    # Tonight's wind at the sit comes from the same copy: no second call.
    assert weather.weather_at(LAT0, LON0, at)["wind_dir_deg"] == 210.0
    assert len(calls) == 1
    # Fresh for half an hour, as the rest of the forecast.
    weather.forecast_hours(LAT0, LON0, first, 9)
    assert len(calls) == 1


def test_no_answer_serves_the_last_week_as_old(monkeypatch, clean_weather):
    def works(url, params=None, timeout=None):
        return _Answer(_range(date.fromisoformat(params["start_date"]),
                              date.fromisoformat(params["end_date"]), lambda t: 90.0))

    calls = []

    def down(url, params=None, timeout=None):
        calls.append(1)
        raise weather.httpx.ConnectError("no route")

    monkeypatch.setattr(weather.httpx, "get", works)
    first = current_night()
    before = weather.forecast_hours(LAT0, LON0, first, 9)
    monkeypatch.setattr(weather.httpx, "get", down)
    clean_weather[0] += weather.FORECAST_TTL_SECONDS + 1
    after = weather.forecast_hours(LAT0, LON0, first, 9)
    assert after["stale"] is True and after["hours"] == before["hours"]
    assert after["fetched_at"] == before["fetched_at"]
    weather.forecast_hours(LAT0, LON0, first, 9)
    assert len(calls) == 1, "the failure pauses the forecast: nobody waits on it again"


# ── the week for a stand ─────────────────────────────────────────────────────


@pytest.fixture
def place(db_session):
    e = Estate(name="Piedras Lisas", timezone="Europe/Madrid", lat=LAT0, lon=LON0)
    db_session.add(e)
    db_session.flush()
    admin = User(estate_id=e.id, email="admin@x.es", password_hash="x", role="admin")
    viewer = User(estate_id=e.id, email="viewer@x.es", password_hash="x", role="viewer")
    db_session.add_all([admin, viewer])
    stand = Stand(estate_id=e.id, name="Charca", lat=_off(40, 0)[0], lon=_off(40, 0)[1])
    db_session.add(stand)
    db_session.add(Zone(estate_id=e.id, kind="bedding", name="Umbria",
                        polygon=_poly((-200, 300), (300, 300), (300, 500), (-200, 500))))
    db_session.commit()
    wind_week._CACHE.clear()
    return {"estate": e, "admin": admin, "viewer": viewer, "stand": stand}


def _forecast(right_at: set[datetime], nights: list[date], speed: float = 15.0) -> dict:
    hours = {}
    for n in nights:
        for h in range(0, 25):
            at = _at(n, h)
            hours[int(at.timestamp())] = {"wind_dir_deg": RIGHT if at in right_at else WRONG,
                                          "wind_speed_kmh": speed, "cloud_cover_pct": 10.0}
    return {"hours": hours, "fetched_at": datetime(2026, 9, 24, 12, tzinfo=UTC), "stale": False}


def _use(monkeypatch, fc: dict) -> list:
    asked = []

    def fake(lat, lng, first, days, tz="Europe/Madrid"):
        asked.append((first, days))
        return fc

    monkeypatch.setattr(wind_week, "forecast_hours", fake)
    return asked


@requires_db
def test_the_line_names_tonights_hours_and_the_right_evenings(db_session, place, monkeypatch):
    """"Right wind for Charca: tonight 19–21 h, Thu, Sat" — tonight's right hours
    still to come, and the evenings with a sit's worth (two hours running)."""
    night = date(2026, 9, 24)  # a Thursday
    now = _at(night, 16).astimezone(UTC)
    nights = [night + timedelta(days=d) for d in range(9)]
    right = {_at(night, h) for h in (19, 20, 21)}
    right |= {_at(night + timedelta(days=2), h) for h in (20, 21, 22)}  # Saturday
    right |= {_at(night + timedelta(days=4), 23)}  # Monday: one hour is not an evening
    right |= {_at(night + timedelta(days=5), h) for h in (23, 24)}  # Tuesday, to midnight
    _use(monkeypatch, _forecast(right, nights))

    out = wind_week.week(db_session, now=now)
    assert out["hours"] == [17, 18, 19, 20, 21, 22, 23, 24]
    assert [e["day"] for e in out["evenings"]] == [
        "Tonight", "Fri", "Sat", "Sun", "Mon", "Tue", "Wed"]
    assert out["evenings"][0]["sunset_local"] == conditions.sun_times(night)["sunset_local"]
    s = out["stands"][0]
    assert s["line"] == "Right wind for Charca: tonight 19–21 h, Sat, Tue"
    assert s["right_tonight"] == "19–21 h" and s["right_days"] == ["Sat", "Tue"]
    tonight = s["evenings"][0]
    assert [h["status"] for h in tonight["hours"]] == [
        "scent_carries", "scent_carries", "clean", "clean", "clean",
        "scent_carries", "scent_carries", "scent_carries"]
    seven = tonight["hours"][2]
    assert seven["at_local"] == "19:00" and seven["wind_dir_deg"] == RIGHT
    assert s["evenings"][4]["right"] == ["23 h"] and not s["evenings"][4]["right_evening"]
    assert s["evenings"][5]["right"] == ["23–24 h"] and s["evenings"][5]["right_evening"]


@requires_db
def test_tonights_line_names_the_sit_window_not_the_first_stray_hours(
    db_session, place, monkeypatch
):
    """Right at 17, 19 and 21–23: the line used to name the first two runs, "tonight
    17 h and 19 h", and a hunter read the whole sit as wrong wind (review R6FE-2).
    The runs a sit fits in come first, the longest of them; a single hour only if
    there is room; in time order. Every run stays on the strip."""
    night = date(2026, 9, 24)
    nights = [night + timedelta(days=d) for d in range(9)]
    now = _at(night, 16).astimezone(UTC)
    _use(monkeypatch, _forecast({_at(night, h) for h in (17, 19, 21, 22, 23)}, nights))
    s = wind_week.week(db_session, now=now)["stands"][0]
    assert s["evenings"][0]["right"] == ["17 h", "19 h", "21–23 h"]
    assert s["right_tonight"] == "17 h and 21–23 h"
    assert s["line"] == "Right wind for Charca: tonight 17 h and 21–23 h"
    # Two sits' worth and a stray hour: the two runs, the longer never dropped.
    wind_week._CACHE.clear()
    _use(monkeypatch, _forecast({_at(night, h) for h in (17, 19, 20, 22, 23, 24)}, nights))
    s = wind_week.week(db_session, now=now)["stands"][0]
    assert s["right_tonight"] == "19–20 h and 22–24 h"
    # Three runs of two or more: the two longest, in time order.
    wind_week._CACHE.clear()
    _use(monkeypatch, _forecast({_at(night, h) for h in (17, 18, 20, 21, 22, 23, 24)} - {
        _at(night, 22)}, nights))
    s = wind_week.week(db_session, now=now)["stands"][0]
    assert s["evenings"][0]["right"] == ["17–18 h", "20–21 h", "23–24 h"]
    assert s["right_tonight"] == "17–18 h and 20–21 h"
    # Only stray hours: the first two of them.
    wind_week._CACHE.clear()
    _use(monkeypatch, _forecast({_at(night, h) for h in (18, 20, 22)}, nights))
    s = wind_week.week(db_session, now=now)["stands"][0]
    assert s["right_tonight"] == "18 h and 20 h"


@requires_db
def test_hours_gone_are_left_out_of_tonight(db_session, place, monkeypatch):
    night = date(2026, 9, 24)
    nights = [night + timedelta(days=d) for d in range(9)]
    _use(monkeypatch, _forecast({_at(night, h) for h in (18, 19, 22)}, nights))
    at_8pm = wind_week.week(db_session, now=_at(night, 20).astimezone(UTC) + timedelta(minutes=30))
    s = at_8pm["stands"][0]
    assert s["right_tonight"] == "22 h"
    assert [h["gone"] for h in s["evenings"][0]["hours"]][:5] == [True, True, True, False, False]
    # At 23:30 nothing right is left tonight, and no evening this week has two hours.
    wind_week._CACHE.clear()
    late = wind_week.week(db_session, now=_at(night, 23).astimezone(UTC) + timedelta(minutes=30))
    assert late["stands"][0]["line"] == "No right wind for Charca this week."


@requires_db
def test_after_midnight_the_week_starts_at_the_coming_evening(db_session, place, monkeypatch):
    night = date(2026, 9, 24)
    nights = [night + timedelta(days=d) for d in range(10)]
    _use(monkeypatch, _forecast({_at(night + timedelta(days=1), h) for h in (20, 21)}, nights))
    out = wind_week.week(db_session, now=_at(night + timedelta(days=1), 1).astimezone(UTC))
    # 01:00 on Friday is still Thursday's night; its evening is over.
    assert out["evenings"][0]["night"] == (night + timedelta(days=1)).isoformat()
    assert out["evenings"][0]["day"] == "Fri" and not out["evenings"][0]["tonight"]
    assert len(out["evenings"]) == 7
    assert out["stands"][0]["line"] == "Right wind for Charca: Fri"


@requires_db
def test_a_stand_that_cant_be_judged_says_why(db_session, place, monkeypatch):
    night = date(2026, 9, 24)
    _use(monkeypatch, _forecast(set(), [night + timedelta(days=d) for d in range(9)]))
    loose = Stand(estate_id=place["estate"].id, name="Loma")
    db_session.add(loose)
    db_session.commit()
    now = _at(night, 16).astimezone(UTC)
    out = {s["stand"]: s for s in wind_week.week(db_session, now=now)["stands"]}
    assert out["Loma"]["status"] == "no_position"
    assert out["Loma"]["line"] == "Loma isn’t on the map yet, so its wind can’t be judged."
    # With no bedding anywhere, a placed stand with no arcs says so.
    db_session.query(Zone).delete()
    db_session.commit()
    out = {s["stand"]: s for s in wind_week.week(db_session, now=now)["stands"]}
    assert out["Charca"]["status"] == "no_bedding"
    assert out["Charca"]["line"] == "No bedding drawn yet, so the wind can’t be judged for Charca."
    # Its arcs judge it when there is no bedding (conditions.wind_verdict).
    place["stand"].approach_dirs_deg = [0]
    db_session.commit()
    out = {s["stand"]: s for s in wind_week.week(db_session, now=now)["stands"]}
    assert out["Charca"]["status"] == "ok"
    assert out["Charca"]["evenings"][0]["hours"][0]["status"] == "scent_carries"


@requires_db
def test_no_forecast_is_said_not_read_as_calm(db_session, place, monkeypatch):
    _use(monkeypatch, {"hours": {}, "fetched_at": None, "stale": False})
    out = wind_week.week(db_session, now=_at(date(2026, 9, 24), 16).astimezone(UTC))
    s = out["stands"][0]
    assert s["line"] == "No wind forecast for the week yet."
    assert {h["status"] for e in s["evenings"] for h in e["hours"]} == {"no_wind_data"}
    assert out["forecast_fetched_at"] is None


@requires_db
def test_kept_for_the_hour_and_made_again_when_something_changes(db_session, place, monkeypatch):
    night = date(2026, 9, 24)
    fc = _forecast({_at(night, 20)}, [night + timedelta(days=d) for d in range(9)])
    _use(monkeypatch, fc)
    judged = []
    real = wind_week.wind_verdict

    def counting(*a, **kw):
        judged.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(wind_week, "wind_verdict", counting)
    now = _at(night, 16).astimezone(UTC)
    first = wind_week.week(db_session, now=now)
    n = len(judged)
    assert n == 7 * 8
    assert wind_week.week(db_session, now=now + timedelta(minutes=40)) == first
    assert len(judged) == n, "the same hour: the answer kept"
    # The stand moved: made again.
    place["stand"].lat, place["stand"].lon = _off(40, -600)
    db_session.commit()
    wind_week.week(db_session, now=now + timedelta(minutes=41))
    assert len(judged) == 2 * n
    # Bedding redrawn: made again.
    z = db_session.query(Zone).one()
    z.polygon = _poly((-200, 900), (300, 900), (300, 1100), (-200, 1100))
    db_session.commit()
    wind_week.week(db_session, now=now + timedelta(minutes=42))
    assert len(judged) == 3 * n
    # A newer forecast: made again.
    fc["fetched_at"] = fc["fetched_at"] + timedelta(minutes=31)
    wind_week.week(db_session, now=now + timedelta(minutes=43))
    assert len(judged) == 4 * n
    # The next hour: made again.
    wind_week.week(db_session, now=now + timedelta(hours=1))
    assert len(judged) == 5 * n


# ── the one verdict, on every screen ─────────────────────────────────────────


def _client(db_session):
    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    return app, TestClient(app)


@requires_db
def test_the_hour_of_the_sit_says_what_stands_and_the_map_say(db_session, place, monkeypatch,
                                                                clean_weather):
    """The strip and tonight's verdict read one forecast (the same day copies) and
    judge with one function: at the sit's hour they agree."""
    def get(url, params=None, timeout=None):
        # The wind turns every hour: right on even hours, wrong on odd ones.
        return _Answer(_range(date.fromisoformat(params["start_date"]),
                              date.fromisoformat(params["end_date"]),
                              lambda t: RIGHT if t.hour % 2 == 0 else WRONG))

    monkeypatch.setattr(weather.httpx, "get", get)
    night = current_night()
    # Four in the afternoon of tonight's evening: the sit is 45 min after sunset.
    now = _at(night, 16).astimezone(UTC)
    cond = conditions.tonight_conditions(now)
    sit = conditions.wind_verdict(db_session, place["stand"], cond, now=now)
    week = wind_week.week(db_session, now=now)
    at = datetime.fromisoformat(sit["at"])
    nearest = min(week["stands"][0]["evenings"][0]["hours"],
                  key=lambda h: abs(datetime.fromisoformat(h["at"]) - at))
    assert abs(datetime.fromisoformat(nearest["at"]) - at) <= timedelta(minutes=30)
    assert nearest["status"] == sit["status"] and nearest["wind_dir_deg"] == cond["wind_dir_deg"]


@requires_db
def test_the_api_gives_the_week_and_tonights_verdict_to_anyone_signed_in(
    db_session, place, monkeypatch
):
    night = current_night()
    _use(monkeypatch, _forecast({_at(night + timedelta(days=1), h) for h in (19, 20)},
                                [night + timedelta(days=d) for d in range(10)]))
    cond = {"wind_dir_deg": WRONG, "wind_speed_kmh": 15.0, "wind_now": False,
            "wind_at": _at(night, 20).astimezone(UTC).isoformat(), "sunset_local": "19:56"}
    monkeypatch.setattr(model_mod, "_tonight_conditions", lambda now, night=None: cond)
    app, client = _client(db_session)
    viewer = {"Authorization": f"Bearer {create_access_token(str(place['viewer'].id))}"}
    admin = {"Authorization": f"Bearer {create_access_token(str(place['admin'].id))}"}
    try:
        all_ = client.get("/api/forecast/wind-week", headers=viewer)
        one = client.get("/api/forecast/wind-week", params={"stand": str(place["stand"].id)},
                         headers=viewer).json()
        mapped = client.get("/api/map/tonight", headers=admin).json()
        missing = client.get("/api/forecast/wind-week",
                             params={"stand": "00000000-0000-0000-0000-000000000000"},
                             headers=viewer)
        nobody = client.get("/api/forecast/wind-week")
    finally:
        app.dependency_overrides.clear()
    assert all_.status_code == 200 and missing.status_code == 404
    assert nobody.status_code in (401, 403)
    body = all_.json()
    assert [s["stand"] for s in body["stands"]] == ["Charca"]
    assert one["stands"][0]["stand"] == "Charca"
    assert body["sunset_local"] == "19:56"
    # Tonight's verdict on the week is the map's, word for word.
    on_map = mapped["stands"][0]["wind"]
    got = body["stands"][0]["tonight"]
    assert (got["status"], got["text"], got["at_local"]) == (
        on_map["status"], on_map["text"], on_map["at_local"])
    assert body["stands"][0]["line"].startswith("Right wind for Charca: ")
