"""Weather and wind: fresh, and one answer everywhere (plan item 7).

Each test pins one way the wind used to mislead: a forecast fetched after midnight
served all day, a slow Open-Meteo holding every page and the database pool, the dark
before dawn read as a sunny afternoon, the map judging the sit at lunchtime, the
scent cone aimed at the middle of the bedding, no forecast shown as a calm night,
and three screens giving three verdicts for one stand.
"""
from __future__ import annotations

import threading
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import geo
from app.core.security import create_access_token
from app.enrichment import weather
from app.forecasting import conditions, thermal
from app.forecasting import model as model_mod
from app.models import Camera, Estate, Image, Stand, TerrainGrid, User, Zone

from .conftest import requires_db

MADRID = ZoneInfo("Europe/Madrid")


def local(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=MADRID)


# ── the forecast cache (F-03, G-08, A-10, B-15, I-04, J-07) ─────────────────


class _Answer:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


def _day(wind_dir: float, day: date, speed: float = 15.0) -> dict:
    start = datetime.combine(day, time(0), tzinfo=MADRID)
    times = [int((start + timedelta(hours=h)).timestamp()) for h in range(24)]
    return {"hourly": {"time": times, "wind_direction_10m": [wind_dir] * 24,
                       "wind_speed_10m": [speed] * 24, "temperature_2m": [12.0] * 24}}


@pytest.fixture
def clean_weather(monkeypatch):
    monkeypatch.setattr(weather, "_DAY_CACHE", {})
    monkeypatch.setattr(weather, "_down_until", 0.0)
    clock = [1000.0]
    monkeypatch.setattr(weather.time, "monotonic", lambda: clock[0])
    return clock


def _tonight_at() -> datetime:
    return datetime.now(UTC) + timedelta(hours=2)


def test_the_forecast_is_fetched_again_after_half_an_hour(monkeypatch, clean_weather):
    """The first request after midnight used to fix the wind for the whole day."""
    at = _tonight_at()
    upstream = {"dir": 90.0}
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(params)
        return _Answer(_day(upstream["dir"], date.fromisoformat(params["start_date"])))

    monkeypatch.setattr(weather.httpx, "get", get)
    assert weather.weather_at(39.09, -1.36, at)["wind_dir_deg"] == 90.0
    upstream["dir"] = 270.0
    clean_weather[0] += 10 * 60
    assert weather.weather_at(39.09, -1.36, at)["wind_dir_deg"] == 90.0  # still fresh
    assert len(calls) == 1
    clean_weather[0] += weather.FORECAST_TTL_SECONDS
    got = weather.weather_at(39.09, -1.36, at)
    assert got["wind_dir_deg"] == 270.0 and got["stale"] is False and got["fetched_at"]
    assert len(calls) == 2
    # Asked for by the instant: the hours are unix seconds (F-22).
    assert calls[0]["timeformat"] == "unixtime"


def test_a_failed_refresh_serves_the_last_forecast_and_pauses(monkeypatch, clean_weather):
    """No signal at dusk used to take the wind away altogether; and each request
    waited on Open-Meteo again."""
    at = _tonight_at()
    calls = []

    def works(url, params=None, timeout=None):
        calls.append(timeout)
        return _Answer(_day(200.0, date.fromisoformat(params["start_date"])))

    def down(url, params=None, timeout=None):
        calls.append(timeout)
        raise weather.httpx.ReadTimeout("timed out")

    monkeypatch.setattr(weather.httpx, "get", works)
    first = weather.weather_at(39.09, -1.36, at)
    monkeypatch.setattr(weather.httpx, "get", down)
    clean_weather[0] += weather.FORECAST_TTL_SECONDS + 1
    stale = weather.weather_at(39.09, -1.36, at)
    assert stale["wind_dir_deg"] == 200.0 and stale["stale"] is True
    assert stale["fetched_at"] == first["fetched_at"]
    # Short timeouts, on the request path too.
    assert calls[-1] == weather.TIMEOUT and weather.TIMEOUT.connect == 3
    for _ in range(5):
        weather.weather_at(39.09, -1.36, at)
    assert len(calls) == 2, "the failure is remembered: nobody waits on it again"


def test_no_forecast_at_all_is_unavailable_and_asked_once(monkeypatch, clean_weather):
    calls = []

    def down(url, params=None, timeout=None):
        calls.append(1)
        raise weather.httpx.ConnectError("no route")

    monkeypatch.setattr(weather.httpx, "get", down)
    for _ in range(3):
        assert weather.weather_at(39.09, -1.36, _tonight_at()) == {"source": "unavailable"}
    assert len(calls) == 1


def test_an_archive_day_is_kept(monkeypatch, clean_weather):
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(url)
        return _Answer(_day(10.0, date.fromisoformat(params["start_date"])))

    monkeypatch.setattr(weather.httpx, "get", get)
    old = datetime.now(UTC) - timedelta(days=40)
    weather.weather_at(39.09, -1.36, old)
    clean_weather[0] += 10 * weather.FORECAST_TTL_SECONDS
    got = weather.weather_at(39.09, -1.36, old)
    assert calls == [weather.ARCHIVE_URL] and got["source"] == "open-meteo-archive"


def test_one_fetch_at_a_time_and_the_rest_serve_their_copy(monkeypatch, clean_weather):
    """Sixteen phones at dusk used to make sixteen calls to a hanging Open-Meteo."""
    at = _tonight_at()
    monkeypatch.setattr(weather.httpx, "get", lambda url, params=None, timeout=None: _Answer(
        _day(90.0, date.fromisoformat(params["start_date"]))))
    weather.weather_at(39.09, -1.36, at)
    clean_weather[0] += weather.FORECAST_TTL_SECONDS + 1

    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow(url, params=None, timeout=None):
        calls.append(1)
        entered.set()
        release.wait(5)
        return _Answer(_day(180.0, date.fromisoformat(params["start_date"])))

    monkeypatch.setattr(weather.httpx, "get", slow)
    first: dict = {}
    t = threading.Thread(target=lambda: first.update(weather.weather_at(39.09, -1.36, at)))
    t.start()
    assert entered.wait(5)
    # While that one waits on Open-Meteo, the others get the copy there is at once.
    others = [weather.weather_at(39.09, -1.36, at) for _ in range(5)]
    release.set()
    t.join(5)
    assert len(calls) == 1
    assert {o["wind_dir_deg"] for o in others} == {90.0}
    assert first["wind_dir_deg"] == 180.0


def test_the_two_hours_after_the_clock_change_are_two_hours():
    """25 Oct: 02:30 summer time and 02:30 winter time got the same hour (F-22)."""
    first = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)   # 02:30 CEST
    second = datetime(2026, 10, 25, 1, 30, tzinfo=UTC)  # 02:30 CET
    start = datetime(2026, 10, 24, 22, 0, tzinfo=UTC)   # 00:00 local
    times = [int((start + timedelta(hours=h)).timestamp()) for h in range(25)]
    a = weather._closest_hour_index(times, first.astimezone(MADRID))
    b = weather._closest_hour_index(times, second.astimezone(MADRID))
    assert (a, b) == (2, 3)


# ── when the wind is judged (A-11, G-10, B-04) ───────────────────────────────


def test_the_sit_is_45_minutes_after_sunset_or_now_once_dark():
    sunset = conditions.sunset_of(date(2026, 9, 26))
    at, now = conditions.sit_time(local(2026, 9, 26, 14).astimezone(UTC))
    assert (at, now) == (sunset + timedelta(minutes=45), False)
    late = local(2026, 9, 26, 22, 10).astimezone(UTC)
    assert conditions.sit_time(late) == (late, True)
    # After midnight it is still the night under way, not the next evening.
    after_midnight = local(2026, 9, 27, 0, 30).astimezone(UTC)
    assert conditions.sit_time(after_midnight) == (after_midnight, True)
    # And a dawn sit before sunrise is judged now.
    dawn = local(2026, 9, 27, 6, 45).astimezone(UTC)
    assert conditions.sit_time(dawn) == (dawn, True)


def test_after_midnight_the_weather_is_the_night_under_way(monkeypatch):
    """At 00:30 it used to sample 22:00 of the NEXT evening, and the sun of the UTC day."""
    asked = []
    monkeypatch.setattr(conditions, "weather_at", lambda lat, lon, when, tz: asked.append(when) or {
        "wind_dir_deg": 180.0, "wind_speed_kmh": 12.0, "fetched_at": "x", "stale": False})
    now = local(2026, 9, 27, 0, 30).astimezone(UTC)
    cond = conditions.tonight_conditions(now)
    assert asked == [now]
    assert cond["night"] == "2026-09-26" and cond["wind_now"] is True
    assert cond["sunset_local"] == conditions.clock(conditions.sunset_of(date(2026, 9, 26)))
    assert cond["wind_at_local"] == "00:30"

    asked.clear()
    lunch = local(2026, 9, 26, 13).astimezone(UTC)
    cond = conditions.tonight_conditions(lunch)
    assert asked == [conditions.sunset_of(date(2026, 9, 26)) + timedelta(minutes=45)]
    assert cond["wind_now"] is False


def test_sunset_follows_the_clock_change():
    assert conditions.clock(conditions.sunset_of(date(2026, 9, 26))).startswith("19:5")
    assert conditions.clock(conditions.sunset_of(date(2026, 10, 26))).startswith("18:")


# ── thermals (G-07, A-22, B-05) ──────────────────────────────────────────────


@pytest.mark.parametrize(("when", "draining", "settled"), [
    (local(2026, 9, 26, 6, 45), True, True),    # dark before a 07:57 sunrise
    (local(2026, 11, 10, 7, 30), True, True),   # dark before a 07:43 sunrise
    (local(2026, 9, 26, 14), False, True),       # afternoon: upslope
    (local(2026, 9, 26, 20, 0), True, False),    # just after sunset: still settling
    (local(2026, 9, 26, 21, 30), True, True),
    (local(2026, 9, 27, 1, 0), True, True),      # 01:00 is not "around dusk"
])
def test_drainage_follows_the_real_sunrise_and_sunset(when, draining, settled):
    assert thermal.air_draining(when.astimezone(UTC)) == (draining, settled)


def test_no_forecast_is_not_a_calm_night():
    reg = thermal.regime(None, lat=39.09, lon=-1.36, when=datetime.now(UTC),
                         wind_dir_deg=None, wind_speed_kmh=None)
    assert reg["source"] == "unknown" and reg["wind_dir_deg"] is None
    assert "No wind forecast" in reg["text"]


# ── the scent cone against the bedding outline (B-03) ────────────────────────

LAT0, LON0 = 39.09, -1.36


def _off(east_m: float, north_m: float) -> tuple[float, float]:
    """(lat, lon) this far from LAT0, LON0."""
    import math

    return (LAT0 + math.degrees(north_m / geo.EARTH_R_M),
            LON0 + math.degrees(east_m / (geo.EARTH_R_M * math.cos(math.radians(LAT0)))))


def _poly(*corners: tuple[float, float]) -> dict:
    ring = [[lon, lat] for lat, lon in (_off(e, n) for e, n in corners)]
    return {"type": "Polygon", "coordinates": [ring + [ring[0]]]}


# A strip 1.2 km long and 150 m deep, drawn with four taps.
STRIP = _poly((0, 0), (1200, 0), (1200, 150), (0, 150))


def test_distance_is_to_the_nearest_edge_not_corner():
    lat, lon = _off(600, -200)  # 200 m south of the middle of the long edge
    assert geo.distance_to_polygon_m(STRIP, lat, lon) == pytest.approx(200, abs=2)
    assert geo.distance_to_polygon_m(STRIP, *_off(600, 75)) == 0.0


def test_scent_into_the_near_end_of_a_long_strip_is_a_hit():
    """Aimed at the middle, this read 'clean ... 255 m to the nearest'."""
    lat, lon = _off(20, -250)  # 250 m south of the west end
    reach = geo.cone_reaches_polygon(STRIP, lat, lon, bearing_deg=0.0, half_deg=16.0,
                                     range_m=900.0)
    assert reach == pytest.approx(250, abs=2)
    # Pointing away, or out of range, misses.
    assert geo.cone_reaches_polygon(STRIP, lat, lon, 180.0, 16.0, 900.0) is None
    assert geo.cone_reaches_polygon(STRIP, lat, lon, 0.0, 16.0, 200.0) is None


def test_a_cone_crossing_an_edge_between_corners_is_a_hit():
    """Neither corner is inside the cone; the edge between them is."""
    lat, lon = _off(600, -300)
    reach = geo.cone_reaches_polygon(STRIP, lat, lon, 0.0, 5.0, 400.0)
    assert reach == pytest.approx(300, abs=2)
    # Aimed 20° off square, the nearest bedding in the cone is where its near side
    # crosses the edge: 300 m / cos 15°.
    reach = geo.cone_reaches_polygon(STRIP, lat, lon, 20.0, 5.0, 400.0)
    assert reach == pytest.approx(310.6, abs=2)


# ── one verdict everywhere (A-09, J-04, G-09, B-14) ──────────────────────────


@pytest.fixture
def place(db_session):
    e = Estate(name="Piedras Lisas", timezone="Europe/Madrid", lat=LAT0, lon=LON0)
    db_session.add(e)
    db_session.flush()
    admin = User(estate_id=e.id, email="admin@x.es", password_hash="x", role="admin")
    db_session.add(admin)
    cam = Camera(estate_id=e.id, name="PL19", active=True, lat=LAT0, lon=LON0,
                 last_report_at=datetime.now(UTC))
    db_session.add(cam)
    db_session.flush()
    # Placed on the map: no camera link, no arcs. Bedding 300 m north.
    stand = Stand(estate_id=e.id, name="Puente", lat=_off(40, 0)[0], lon=_off(40, 0)[1])
    db_session.add(stand)
    db_session.add(Zone(estate_id=e.id, kind="bedding", name="Umbria",
                        polygon=_poly((-200, 300), (300, 300), (300, 500), (-200, 500))))
    db_session.commit()
    return {"estate": e, "admin": admin, "camera": cam, "stand": stand}


def _client(db_session):
    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    return app, TestClient(app)


def _cond(wind_dir, speed, at: datetime | None = None, **kw):
    at = at or local(2026, 9, 26, 20, 41).astimezone(UTC)
    return {"wind_dir_deg": wind_dir, "wind_speed_kmh": speed, "wind_at": at.isoformat(),
            "wind_at_local": conditions.clock(at), "wind_now": False,
            "sunset_local": "19:56", **kw}


@requires_db
def test_tonight_the_map_stands_sit_mode_and_the_reservation_agree(
    db_session, place, monkeypatch
):
    """Same stand, same wind: Tonight said 'judge it yourself' naming a camera, the
    map said 'Wind is wrong', and the reservation (so Sit mode) 'not set up'."""
    cond = _cond(180.0, 15.0)  # from the south: scent north, into Umbria
    monkeypatch.setattr(model_mod, "_tonight_conditions", lambda now: cond)
    stand = place["stand"]
    # Tonight judges the stand nearest its camera (Map-placed stands have no link).
    assert conditions.stand_for_camera(db_session, place["camera"].id).id == stand.id
    direct = conditions.wind_verdict(db_session, stand, cond)
    assert direct["status"] == "scent_carries" and direct["is_advice"]
    assert direct["at_local"] == "20:41" and direct["stand"] == "Puente"

    app, client = _client(db_session)
    headers = {"Authorization": f"Bearer {create_access_token(str(place['admin'].id))}"}
    try:
        mapped = client.get("/api/map/tonight", headers=headers).json()
        on_map = next(s["wind"] for s in mapped["stands"] if s["id"] == str(stand.id))
        in_seat = client.get(f"/api/stands/{stand.id}/wind", headers=headers).json()
        sit = client.post("/api/sits", json={"stand_id": str(stand.id)}, headers=headers).json()
    finally:
        app.dependency_overrides.clear()
    for other in (on_map, in_seat):
        assert (other["status"], other["text"], other["at_local"]) == (
            direct["status"], direct["text"], "20:41")
    assert (sit["wind_status"], sit["wind_text"]) == (direct["status"], direct["text"])
    assert datetime.fromisoformat(sit["wind_at"]) == datetime.fromisoformat(cond["wind_at"])
    assert in_seat["sunset_local"] == "19:56"
    assert mapped["conditions"]["wind_at_local"] == "20:41"


@requires_db
def test_tonight_names_the_stand_it_judged(db_session, place, monkeypatch):
    from app.forecasting.exposure import current_night, recompute_camera_nights
    from app.models import Detection, Species

    monkeypatch.setattr(model_mod, "_tonight_conditions", lambda now: _cond(180.0, 15.0))
    db_session.add(Species(id="wild_boar", common_name="Wild boar", huntable=True,
                           is_priority=True))
    tonight = current_night()
    for n in range(1, 21):
        day = tonight - timedelta(days=n)
        img = Image(camera_id=place["camera"].id,
                    captured_at=datetime.combine(day, time(21), tzinfo=MADRID),
                    is_empty_frame=False, processed_at=datetime.now(UTC), reviewed=False)
        db_session.add(img)
        db_session.flush()
        db_session.add(Detection(image_id=img.id, species_id="wild_boar", group_size=1))
    db_session.commit()
    recompute_camera_nights(db_session)
    out = model_mod.forecast_tonight(db_session)
    assert out["recommended"]["camera"] == "PL19"
    assert out["wind"]["stand"] == "Puente" and out["wind"]["status"] == "scent_carries"
    assert "PL19" not in out["wind"]["text"]


@requires_db
def test_with_no_stand_near_tonight_says_so(db_session, place):
    far = conditions.no_stand_verdict("PL19", _cond(180.0, 15.0))
    assert far["status"] == "no_stand" and not far["is_advice"] and "PL19" in far["text"]
    none = conditions.no_stand_verdict("PL19", _cond(None, None))
    assert none["status"] == "no_wind_data"


@requires_db
def test_a_stand_off_the_map_falls_back_to_its_arcs_or_says_why(db_session, place):
    e = place["estate"]
    arcs = Stand(estate_id=e.id, name="Solana", approach_dirs_deg=[0])
    bare = Stand(estate_id=e.id, name="Loma")
    db_session.add_all([arcs, bare])
    db_session.commit()
    by_arcs = conditions.wind_verdict(db_session, arcs, _cond(180.0, 15.0))
    assert by_arcs["status"] == "scent_carries"
    v = conditions.wind_verdict(db_session, bare, _cond(180.0, 15.0))
    assert v["status"] == "no_position" and "Wind S 15 km/h" in v["text"]
    assert conditions.wind_verdict(db_session, bare, _cond(None, None))["status"] == "no_wind_data"


@requires_db
def test_no_forecast_reads_no_wind_forecast_on_the_map(db_session, place, monkeypatch):
    monkeypatch.setattr(model_mod, "_tonight_conditions", lambda now: _cond(None, None))
    app, client = _client(db_session)
    headers = {"Authorization": f"Bearer {create_access_token(str(place['admin'].id))}"}
    try:
        mapped = client.get("/api/map/tonight", headers=headers).json()
    finally:
        app.dependency_overrides.clear()
    assert mapped["airflow"]["source"] == "unknown"
    assert "No wind forecast" in mapped["airflow"]["text"]
    assert {s["wind"]["status"] for s in mapped["stands"]} == {"no_wind_data"}


def _slope_north(db_session) -> None:
    """A hillside falling steadily to the north over the estate (terrain grid)."""
    n = 20
    half = 0.03
    elev = [400.0 + (i * 10.0) for i in range(n) for _ in range(n)]  # i grows north: uphill
    elev = [1000.0 - v for v in elev]  # so north is downhill
    db_session.add(TerrainGrid(min_lat=LAT0 - half, max_lat=LAT0 + half, min_lon=LON0 - half,
                               max_lon=LON0 + half, steps=n, elevations=elev))
    db_session.commit()


@requires_db
def test_a_calm_evening_is_judged_as_the_sit_at_any_hour(db_session, place, monkeypatch):
    """At lunch the map used to read the midday upslope air: stand 'clean', while at
    the sit cold air drained its scent straight into the bedding below."""
    _slope_north(db_session)
    evening = conditions.sunset_of(date(2026, 9, 26)) + timedelta(minutes=45)
    monkeypatch.setattr(model_mod, "_tonight_conditions",
                        lambda now: _cond(90.0, 3.0, at=evening))
    app, client = _client(db_session)
    headers = {"Authorization": f"Bearer {create_access_token(str(place['admin'].id))}"}
    try:
        mapped = client.get("/api/map/tonight", headers=headers).json()
    finally:
        app.dependency_overrides.clear()
    assert mapped["airflow"]["source"] == "katabatic"
    stand = mapped["stands"][0]["wind"]
    assert stand["source"] == "katabatic" and stand["status"] == "scent_carries"


@requires_db
def test_the_scent_safe_shading_uses_the_stands_plume(db_session, place):
    """At 25 km/h 20 of 660 shaded squares disagreed with a stand placed on them."""
    from app.forecasting import bedding

    at = local(2026, 9, 26, 21).astimezone(UTC)
    shade = bedding.safe_ground(db_session, wind_dir_deg=200.0, wind_speed_kmh=25.0, when=at)
    assert shade["status"] == "ok" and shade["cells"]
    for cell in shade["cells"][::7]:
        report = bedding.stand_wind_report(
            db_session, stand_name="x", lat=cell["lat"], lon=cell["lon"],
            wind_dir_deg=200.0, wind_speed_kmh=25.0, when=at)
        assert (report["status"] == "clean") == cell["safe"], cell


@requires_db
def test_the_forecast_waits_with_no_database_connection_held(db_session, place, monkeypatch):
    """A hanging Open-Meteo used to hold a pooled connection per request, until
    Photos and sign-in timed out for everyone (K-04)."""
    from sqlalchemy import text

    seen = []

    def weather_now(now):
        # Whatever the request read before is committed: its connection is back.
        seen.append(db_session.in_transaction())
        return _cond(180.0, 15.0)

    monkeypatch.setattr(model_mod, "_tonight_conditions", weather_now)
    db_session.execute(text("select 1"))
    assert db_session.in_transaction()
    app, client = _client(db_session)
    headers = {"Authorization": f"Bearer {create_access_token(str(place['admin'].id))}"}
    try:
        for path in ("/api/forecast/tonight", "/api/map/tonight",
                     f"/api/stands/{place['stand'].id}/wind"):
            assert client.get(path, headers=headers).status_code == 200
        assert client.post("/api/sits", json={"stand_id": str(place["stand"].id)},
                           headers=headers).status_code == 201
    finally:
        app.dependency_overrides.clear()
    assert seen == [False, False, False, False]
