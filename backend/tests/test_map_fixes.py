"""Map fixes (plan item 14) and the estate saved for no signal (feature 24).

What these pin down is what a hunter sees on the map: a camera placed by hand stays
where it was put, a mis-tapped outline is refused in words (never a 500), the hill
shape loads without holding the button for half a minute and reaches every stand,
"likely paths" come from the cameras' own sequence of visits, and the box a phone
saves for no signal is one an admin can set and nobody else can.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import estate_area, geo, terrain
from app.core.security import create_access_token
from app.forecasting import thermal
from app.ingestion.spypoint import SpypointCamera
from app.ingestion.sync import upsert_camera
from app.models import (
    AppSetting,
    Camera,
    Detection,
    Estate,
    Image,
    Species,
    Stand,
    TerrainGrid,
    User,
    Zone,
)

from .conftest import requires_db

pytestmark = requires_db
MADRID = ZoneInfo("Europe/Madrid")


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
    e = Estate(name="Piedras Lisas", timezone="Europe/Madrid", lat=39.0947, lon=-1.3608)
    db_session.add(e)
    db_session.add(Species(id="wild_boar", common_name="Wild boar", is_priority=True))
    db_session.commit()
    return e


def _user(db, estate, role="admin"):
    u = User(estate_id=estate.id, email=f"{role}-{uuid.uuid4().hex[:6]}@estate.local",
             password_hash="x", role=role)
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


def _ring(*pts):
    return {"type": "Polygon", "coordinates": [[list(p) for p in pts]]}


SQUARE = _ring((-1.364, 39.093), (-1.362, 39.093), (-1.362, 39.095), (-1.364, 39.095),
               (-1.364, 39.093))


# ── a camera placed by hand stays there (B-09, E-16) ───────────────────────────


def test_a_hand_placed_camera_stays_put_at_the_next_sync(client, db_session, estate):
    """SPYPOINT's position used to overwrite the hunter's every 15 minutes."""
    admin = _user(db_session, estate)
    spy = SpypointCamera(spypoint_id="sp-1", name="PL19", lat=39.20, lng=-1.30)
    cam = upsert_camera(db_session, estate.id, spy)
    db_session.commit()
    assert (cam.lat, cam.lon, cam.location_is_custom) == (39.20, -1.30, False)

    r = client.put(f"/api/cameras/{cam.id}/location", json={"lat": 39.0947, "lng": -1.3608},
                   headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["location_is_custom"] is True and r.json()["provider_location"] is True

    upsert_camera(db_session, estate.id, SpypointCamera(
        spypoint_id="sp-1", name="PL19", lat=39.21, lng=-1.31))
    db_session.commit()
    db_session.refresh(cam)
    assert (cam.lat, cam.lon) == (39.0947, -1.3608), "the hand placement wins"
    assert (cam.provider_lat, cam.provider_lon) == (39.21, -1.31), "the camera's own is kept"

    [shown] = client.get("/api/map/cameras", headers=admin).json()
    assert (shown["lat"], shown["location_is_custom"], shown["provider_location"]) == (
        39.0947, True, True)

    # "Use the camera's own GPS": back to it, and following it again.
    r = client.delete(f"/api/cameras/{cam.id}/location", headers=admin)
    assert r.status_code == 200, r.text
    db_session.refresh(cam)
    assert (cam.lat, cam.lon, cam.location_is_custom) == (39.21, -1.31, False)
    upsert_camera(db_session, estate.id, SpypointCamera(
        spypoint_id="sp-1", name="PL19", lat=39.22, lng=-1.32))
    db_session.commit()
    db_session.refresh(cam)
    assert (cam.lat, cam.lon) == (39.22, -1.32)


def test_a_camera_with_no_gps_lock_keeps_its_position(db_session, estate):
    """(0, 0) or an impossible fix is a camera without a GPS lock, not a position."""
    cam = upsert_camera(db_session, estate.id, SpypointCamera(
        spypoint_id="sp-2", name="PL07", lat=39.1, lng=-1.35))
    for lat, lng in ((0.0, 0.0), (1000.0, -1.35), (float("nan"), 1.0)):
        upsert_camera(db_session, estate.id, SpypointCamera(
            spypoint_id="sp-2", name="PL07", lat=lat, lng=lng))
    db_session.commit()
    db_session.refresh(cam)
    assert (cam.lat, cam.lon, cam.provider_lat) == (39.1, -1.35, 39.1)


def test_placing_a_camera_is_checked_and_admins_only(client, db_session, estate):
    admin, member, viewer = (_user(db_session, estate, r) for r in ("admin", "member", "viewer"))
    cam = Camera(estate_id=estate.id, name="UBox charca")
    other = Estate(name="Elsewhere", timezone="Europe/Madrid")
    db_session.add_all([cam, other])
    db_session.flush()
    theirs = Camera(estate_id=other.id, name="Theirs")
    db_session.add(theirs)
    db_session.commit()
    url = f"/api/cameras/{cam.id}/location"
    for headers in (member, viewer):
        r = client.put(url, json={"lat": 39.09, "lng": -1.36}, headers=headers)
        assert r.status_code == 403
    for bad in ({"lat": 1000, "lng": -1.36}, {"lat": 39.09, "lng": 200}, {"lat": 0, "lng": 0}):
        r = client.put(url, json=bad, headers=admin)
        assert r.status_code == 422, (bad, r.text)
    assert client.put(f"/api/cameras/{theirs.id}/location", json={"lat": 39.09, "lng": -1.36},
                      headers=admin).status_code == 404
    # A camera that never reported a position has none to go back to: said in words.
    r = client.delete(url, headers=admin)
    assert r.status_code == 409 and "Place it by hand" in r.json()["detail"]


# ── outlines are checked, in words (B-10, B-22) ──────────────────────────────


@pytest.mark.parametrize(("polygon", "words"), [
    ({"type": "Point", "coordinates": [1, 2]}, "GeoJSON Polygon"),
    (_ring(("a", "b"), (1, 2), (3, 4)), "two numbers"),
    ({"type": "Polygon", "coordinates": [[[1, 2, 3, 4]]]}, "two numbers"),
    ({"type": "Polygon", "coordinates": [[True, False]]}, "two numbers"),
    ({"type": "Polygon", "coordinates": "x"}, "no corners"),
    (_ring((39.09, -1.36), (39.1, -1.36), (39.1, -100.0)), "off the map"),
    # Two corners and the closing one, or the same corner four times: no ground.
    (_ring((-1.364, 39.093), (-1.362, 39.093), (-1.364, 39.093)), "at least three"),
    (_ring(*[(-1.364, 39.093)] * 4), "at least three"),
    # A bow-tie: the crossed half would count as outside the bedding.
    (_ring((-1.364, 39.093), (-1.362, 39.095), (-1.362, 39.093), (-1.364, 39.095)),
     "crosses itself"),
    # A needle: out and straight back.
    (_ring((-1.364, 39.093), (-1.362, 39.093), (-1.363, 39.093), (-1.363, 39.095)),
     "crosses itself"),
    (_ring((-1.36400, 39.09300), (-1.36399, 39.09300), (-1.36399, 39.09301)), "no area"),
    (_ring((-1.5, 39.0), (-1.2, 39.0), (-1.2, 39.2)), "over 20 km"),
])
def test_a_bad_outline_is_refused_in_words(client, db_session, estate, polygon, words):
    admin = _user(db_session, estate)
    r = client.post("/api/zones", json={"name": "Umbría", "polygon": polygon}, headers=admin)
    assert r.status_code == 422, r.text
    assert words in r.json()["detail"]


def test_a_good_outline_is_kept_tidy(client, db_session, estate):
    """A double tap and the closing corner are dropped and the ring closed again."""
    admin = _user(db_session, estate)
    corners = [(-1.364, 39.093), (-1.362, 39.093), (-1.362, 39.093), (-1.362, 39.095),
               (-1.364, 39.095)]
    r = client.post("/api/zones", json={"name": "  Umbría  ", "polygon": _ring(*corners)},
                    headers=admin)
    assert r.status_code == 201, r.text
    z = r.json()
    assert z["name"] == "Umbría"
    assert z["polygon"]["coordinates"][0] == [
        [-1.364, 39.093], [-1.362, 39.093], [-1.362, 39.095], [-1.364, 39.095], [-1.364, 39.093]]


def test_an_outline_is_renamed_and_redrawn_not_emptied(client, db_session, estate):
    admin, member = _user(db_session, estate), _user(db_session, estate, "member")
    zone = client.post("/api/zones", json={"name": "Umbría", "polygon": SQUARE},
                       headers=admin).json()
    url = f"/api/zones/{zone['id']}"
    for body in ({"name": None}, {"polygon": None}, {"name": "   "}):
        r = client.patch(url, json=body, headers=admin)
        assert r.status_code == 422, (body, r.text)
    assert client.patch(url, json={"name": "Solana"}, headers=member).status_code == 403
    assert client.delete(url, headers=member).status_code == 403
    bigger = _ring((-1.365, 39.092), (-1.361, 39.092), (-1.361, 39.096), (-1.365, 39.096))
    r = client.patch(url, json={"name": " Solana ", "polygon": bigger}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Solana" and len(r.json()["polygon"]["coordinates"][0]) == 5
    assert client.patch(url, json={"polygon": _ring((-1.364, 39.093), (-1.362, 39.095),
                                                     (-1.362, 39.093), (-1.364, 39.095))},
                        headers=admin).status_code == 422


def test_clean_polygon_accepts_a_real_bedding_outline():
    poly = geo.clean_polygon(_ring((-1.3641, 39.0931), (-1.3620, 39.0929), (-1.3612, 39.0948),
                                   (-1.3630, 39.0957), (-1.3645, 39.0949)))
    ring = poly["coordinates"][0]
    assert len(ring) == 6 and ring[0] == ring[-1]


# ── the hill shape (B-18, B-20) ──────────────────────────────────────────────


@pytest.fixture
def background_db(db_session, monkeypatch):
    """The download runs on its own session after the answer: point it at the test DB."""
    from app.core import db as core_db

    monkeypatch.setattr(core_db, "SessionLocal", sessionmaker(bind=db_session.get_bind()))


def _fake_elevations(monkeypatch, fn=None, calls=None):
    def get(lats, lons):
        if calls is not None:
            calls.append(len(lats))
        # A slope falling to the north: higher to the south.
        return [fn(la, lo) if fn else 1000.0 - (la - 39.0) * 10_000
                for la, lo in zip(lats, lons, strict=True)]
    monkeypatch.setattr(terrain, "_get_elevations", get)
    monkeypatch.setattr(terrain, "CHUNK_PAUSE_S", 0)


def test_loading_the_hill_shape_answers_at_once_and_says_how_it_went(
        client, db_session, estate, monkeypatch, background_db):
    admin, viewer = _user(db_session, estate), _user(db_session, estate, "viewer")
    assert client.post("/api/terrain/refresh", headers=viewer).status_code == 403
    assert client.get("/api/terrain/status", headers=viewer).json()["state"] == "none"
    _fake_elevations(monkeypatch)
    r = client.post("/api/terrain/refresh", headers=admin)
    assert r.status_code == 202 and r.json()["state"] == "loading"
    # The TestClient runs the background task before it hands the answer back.
    s = client.get("/api/terrain/status", headers=viewer).json()
    assert s["state"] == "loaded" and s["error"] is None and s["loaded_at"]
    assert client.get("/api/map/tonight", headers=viewer).json()["terrain_loaded"] is True


def test_a_failed_download_says_so_in_one_short_line(
        client, db_session, estate, monkeypatch, background_db):
    """It used to answer with the elevation service's URL: kilobytes of coordinates."""
    admin = _user(db_session, estate)

    def refuse(lats, lons):
        raise RuntimeError("Server error '500' for url 'https://api.open-meteo.com/v1/"
                           "elevation?latitude=" + "39.0%2C" * 400)
    monkeypatch.setattr(terrain, "_get_elevations", refuse)
    client.post("/api/terrain/refresh", headers=admin)
    s = client.get("/api/terrain/status", headers=admin).json()
    assert s["state"] == "failed"
    assert s["error"] == "The elevation service didn’t answer. Try again later."


def test_a_second_press_while_it_loads_starts_nothing_new(client, db_session, estate):
    admin = _user(db_session, estate)
    db_session.add(AppSetting(key=terrain.STATUS_KEY, value={
        "state": "loading", "started_at": datetime.now(UTC).isoformat()}))
    db_session.commit()
    calls = []
    import app.api.routes_zones as rz

    rz_load = rz.load_in_background
    try:
        rz.load_in_background = lambda *a: calls.append(a)
        r = client.post("/api/terrain/refresh", headers=admin)
    finally:
        rz.load_in_background = rz_load
    assert r.status_code == 202 and r.json()["state"] == "loading" and calls == []
    # One stuck for longer than any download is a download that died.
    db_session.get(AppSetting, terrain.STATUS_KEY).value = {
        "state": "loading", "started_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}
    db_session.commit()
    assert client.get("/api/terrain/status", headers=admin).json()["state"] == "failed"


def test_the_hill_shape_reaches_a_stand_3_km_out(db_session, estate, monkeypatch):
    """A fixed 5 km box round the centre told an outlying stand its ground was flat."""
    far = Stand(estate_id=estate.id, name="Barranco norte", lat=39.0947 + 3000 / 111_320,
                lon=-1.3608)
    db_session.add(far)
    db_session.commit()
    _fake_elevations(monkeypatch)
    grid = terrain.fetch_grid(db_session, 39.0947, -1.3608, force=True)
    assert terrain.covers(grid, far.lat, far.lon)
    assert grid.max_lat >= far.lat + 400 / 111_320, "with a margin round it"
    ew, ns = estate_area.side_m({"south": grid.min_lat, "north": grid.max_lat,
                                 "west": grid.min_lon, "east": grid.max_lon})
    assert ns / (grid.steps - 1) <= 260, "posts stay about 250 m apart"
    slope = terrain.slope_at(grid, far.lat, far.lon)
    assert slope["downhill_deg"] == 0 and slope["slope_pct"] > 1.5


def test_the_slope_at_the_edge_is_not_halved(db_session):
    """The edge's clamped central difference used to halve the slope there."""
    n = 5
    grid = TerrainGrid(min_lat=39.0, max_lat=39.0 + 4 * 0.001, min_lon=-1.4, max_lon=-1.396,
                       steps=n, elevations=[100.0 - 10 * i for i in range(n) for _ in range(n)])
    inside = terrain.slope_at(grid, 39.002, -1.398)["slope_pct"]
    edge = terrain.slope_at(grid, 39.0, -1.398)["slope_pct"]
    assert edge == pytest.approx(inside, rel=0.01)


def test_outside_the_hill_shape_is_not_called_flat(db_session, estate):
    grid = TerrainGrid(min_lat=39.0, max_lat=39.01, min_lon=-1.4, max_lon=-1.39, steps=3,
                       elevations=[100.0] * 9)
    db_session.add(grid)
    db_session.commit()
    # A light wind with a direction: with none, there is no forecast to go on (B-05).
    out = thermal.regime(db_session, lat=39.2, lon=-1.2, when=datetime.now(UTC),
                         wind_dir_deg=270.0, wind_speed_kmh=2.0)
    assert out["source"] == "unknown"
    assert "outside the hill shape" in out["text"] and "flat" not in out["text"]


def test_the_map_names_stands_the_hill_shape_does_not_reach(client, db_session, estate):
    viewer = _user(db_session, estate, "viewer")
    db_session.add_all([
        TerrainGrid(min_lat=39.08, max_lat=39.11, min_lon=-1.38, max_lon=-1.34, steps=3,
                    elevations=[100.0] * 9),
        Stand(estate_id=estate.id, name="Puente", lat=39.09, lon=-1.36),
        Stand(estate_id=estate.id, name="Lejos", lat=39.2, lon=-1.36),
        Stand(estate_id=estate.id, name="Sin sitio"),
    ])
    db_session.commit()
    body = client.get("/api/map/tonight", headers=viewer).json()
    assert body["terrain_outside"] == ["Lejos"] and body["routes"] == []


# ── likely paths (G-25) ──────────────────────────────────────────────────────


def _visit(db, cam, when):
    img = Image(camera_id=cam.id, captured_at=when, processed_at=when, is_empty_frame=False,
                original_path="/x.jpg")
    db.add(img)
    db.flush()
    db.add(Detection(image_id=img.id, species_id="wild_boar", species_conf=0.9, group_size=2))


def test_likely_paths_are_the_replays_links_seen_on_more_than_one_night(
        client, db_session, estate):
    """A camera near bedding with sightings used to be a "route" whatever came past."""
    from app.api.routes_map import last_completed_night

    viewer = _user(db_session, estate, "viewer")
    charca = Camera(estate_id=estate.id, name="Charca", lat=39.090, lon=-1.360)
    pozo = Camera(estate_id=estate.id, name="Pozo", lat=39.095, lon=-1.355)
    lejos = Camera(estate_id=estate.id, name="Lejos", lat=39.20, lon=-1.20)
    db_session.add_all([charca, pozo, lejos])
    db_session.flush()
    last = last_completed_night()

    def evening(n, hour, minute=0):
        return datetime.combine(last - timedelta(days=n), time(hour, minute), MADRID)

    for n in (0, 2, 5):  # Charca then Pozo within the hour, three nights
        _visit(db_session, charca, evening(n, 20))
        _visit(db_session, pozo, evening(n, 21))
    _visit(db_session, pozo, evening(1, 22))  # Pozo back to Charca once
    _visit(db_session, charca, evening(1, 23))
    # Lejos is 18 km away: an hour later is not the same animals.
    _visit(db_session, lejos, evening(0, 21, 30))
    _visit(db_session, lejos, evening(2, 21, 30))
    db_session.commit()
    body = client.get("/api/map/paths", headers=viewer).json()
    assert (body["nights"], body["min_nights"]) == (30, 2)
    [path] = body["paths"]
    assert path["cameras"] == ["Charca", "Pozo"] and path["nights"] == 4
    ways = {(w["from_camera_id"], w["to_camera_id"]): w["nights"] for w in path["ways"]}
    assert ways == {(str(charca.id), str(pozo.id)): 3, (str(pozo.id), str(charca.id)): 1}
    assert path["species"] == [{"species_id": "wild_boar", "label": "Wild boar", "nights": 4}]


# ── the estate's box, for the map saved on a phone (feature 24) ─────────────


def test_the_estate_box_is_drawn_round_what_is_placed_until_an_admin_sets_one(
        client, db_session, estate):
    admin, member = _user(db_session, estate), _user(db_session, estate, "member")
    body = client.get("/api/estate", headers=member).json()
    assert body["box_set"] is False
    w, h = body["box_km"]
    assert w == pytest.approx(4.0, abs=0.1) and h == pytest.approx(4.0, abs=0.1), "nothing placed"

    db_session.add_all([Stand(estate_id=estate.id, name="A", lat=39.09, lon=-1.37),
                        Stand(estate_id=estate.id, name="B", lat=39.11, lon=-1.34),
                        Zone(estate_id=estate.id, name="Z", kind="bedding", polygon=SQUARE)])
    db_session.commit()
    box = client.get("/api/estate", headers=member).json()["box"]
    assert box["south"] < 39.09 - 900 / 111_320 and box["north"] > 39.11 + 900 / 111_320
    assert box["west"] < -1.37 and box["east"] > -1.34

    mine = {"south": 39.08, "west": -1.38, "north": 39.12, "east": -1.33}
    assert client.put("/api/estate/box", json=mine, headers=member).status_code == 403
    r = client.put("/api/estate/box", json=mine, headers=admin)
    assert r.status_code == 200 and r.json()["box_set"] is True
    assert client.get("/api/estate", headers=member).json()["box"] == mine
    for bad, words in (({**mine, "north": 39.5}, "km across"),
                       ({**mine, "south": 39.2}, "off the map"),
                       ({**mine, "north": 39.0801, "east": -1.3799}, "too small")):
        r = client.put("/api/estate/box", json=bad, headers=admin)
        assert r.status_code == 422 and words in r.json()["detail"], (bad, r.text)
    assert client.delete("/api/estate/box", headers=admin).json()["box_set"] is False


def test_suggested_box_never_grows_past_a_phones_worth(db_session, estate):
    db_session.add_all([Stand(estate_id=estate.id, name="A", lat=39.0, lon=-1.5),
                        Stand(estate_id=estate.id, name="B", lat=39.4, lon=-1.0)])
    db_session.commit()
    ew, ns = estate_area.side_m(estate_area.suggested_box(db_session))
    assert max(ew, ns) <= estate_area.MAX_SIDE_M + 1


# ── a camera off the estate moves neither box (review R4FE-1) ────────────────

CENTRE = (39.0947, -1.3608)
EAST_M = 1 / (111_320 * 0.776)  # degrees of longitude per metre round 39° N


def _inside(box, lat, lon, margin_m=0.0):
    dlat, dlon = margin_m / 111_320, margin_m * EAST_M
    return (box["south"] + dlat <= lat <= box["north"] - dlat
            and box["west"] + dlon <= lon <= box["east"] - dlon)


def test_a_camera_far_off_moves_neither_box_off_the_estate(client, db_session, estate):
    """A SPYPOINT fix from a cell tower, or a camera taken home to charge, 44 km off:
    both boxes were cut round the middle of everything and covered none of the stands."""
    admin = _user(db_session, estate)
    stands = [Stand(estate_id=estate.id, name=f"Stand {i}", lat=lat, lon=lon)
              for i, (lat, lon) in enumerate([(39.094, -1.361), (39.10, -1.35),
                                              (39.085, -1.37), (39.09, -1.355)])]
    db_session.add_all(stands)
    db_session.add_all([Camera(estate_id=estate.id, name=f"Cam {i}", lat=lat, lon=lon)
                        for i, (lat, lon) in enumerate([(39.095, -1.36), (39.092, -1.365),
                                                        (39.098, -1.357)])])
    db_session.add(Camera(estate_id=estate.id, name="PL-home", lat=38.99, lon=-1.86))
    db_session.commit()

    hill = estate_area.terrain_box(db_session, *CENTRE, terrain.BOX_KM * 1000,
                                   terrain.MAX_BOX_KM * 1000)
    phone = estate_area.suggested_box(db_session)
    for box in (hill, phone):
        assert all(_inside(box, s.lat, s.lon, margin_m=900) for s in stands), box
    assert max(estate_area.side_m(phone)) < 5_000, "round the estate, not out to the camera"
    assert max(estate_area.side_m(hill)) <= terrain.BOX_KM * 1000 + 1

    body = client.get("/api/estate", headers=admin).json()
    assert [(c["name"], c["km"]) for c in body["cameras_left_out"]] == [("PL-home", 44)]


def test_retired_and_disconnected_cameras_are_not_on_the_estate(client, db_session, estate):
    admin = _user(db_session, estate)
    db_session.add(Stand(estate_id=estate.id, name="Centre", lat=CENTRE[0], lon=CENTRE[1]))
    north, south = CENTRE[0] + 5000 / 111_320, CENTRE[0] - 5000 / 111_320
    db_session.add_all([
        Camera(estate_id=estate.id, name="In a drawer", lat=north, lon=CENTRE[1],
               retired_at=datetime.now(UTC)),
        Camera(estate_id=estate.id, name="Login removed", lat=south, lon=CENTRE[1],
               active=False),
    ])
    db_session.commit()
    box = estate_area.suggested_box(db_session)
    assert box["north"] < north and box["south"] > south
    assert client.get("/api/estate", headers=admin).json()["cameras_left_out"] == [], \
        "not out on the estate at all, so not named as left out"


def test_a_box_too_wide_is_cut_round_the_stands_not_its_middle(db_session, estate):
    """Cameras within reach east of the stands make the hill shape's box wider than
    12 km: the cut keeps the stands (with their margin) and loses the far east."""
    lat = CENTRE[0]
    west, east = CENTRE[1] - 2000 * EAST_M, CENTRE[1] + 2000 * EAST_M
    db_session.add_all([Stand(estate_id=estate.id, name="W", lat=lat, lon=west),
                        Stand(estate_id=estate.id, name="E", lat=lat, lon=east)])
    for i, dy in enumerate((-500, 500)):
        db_session.add(Camera(estate_id=estate.id, name=f"Far east {i}", lat=lat + dy / 111_320,
                              lon=east + 7900 * EAST_M))
    db_session.commit()
    box = estate_area.terrain_box(db_session, *CENTRE, terrain.BOX_KM * 1000,
                                  terrain.MAX_BOX_KM * 1000)
    ew, _ = estate_area.side_m(box)
    assert ew == pytest.approx(terrain.MAX_BOX_KM * 1000, rel=0.01), "cut to 12 km"
    for lon in (west, east):
        assert _inside(box, lat, lon, margin_m=900), (box, lon)
