from datetime import UTC, datetime, timezone
from zoneinfo import ZoneInfo

from app.ingestion.spypoint import (
    SpypointCamera,
    SpypointClient,
    SpypointError,
    SpypointPhoto,
    _extract_coords,
    _extract_signal,
    _parse_dt,
    wall_clock_cursor,
)

from .conftest import requires_db

MADRID = ZoneInfo("Europe/Madrid")


def test_photo_url_prefers_large():
    p = {"large": {"host": "h1", "path": "a/b.jpg"}, "small": {"host": "h2", "path": "c.jpg"}}
    assert SpypointClient.photo_url(p) == "https://h1/a/b.jpg"


def test_photo_url_falls_back_to_small():
    assert SpypointClient.photo_url({"large": {}, "small": {"host": "h2", "path": "c.jpg"}}) == "https://h2/c.jpg"


def test_photo_url_fallback_url_field():
    assert SpypointClient.photo_url({"url": "https://x/y.jpg"}) == "https://x/y.jpg"


def test_parse_camera_extracts_name_battery_signal():
    cam = {"id": "c1", "config": {"name": "PL14"},
           "status": {"batteryPercentage": 80, "signal": {"bar": 4}}}
    parsed = SpypointClient._parse_camera(cam)
    assert parsed.spypoint_id == "c1"
    assert parsed.name == "PL14"
    assert parsed.battery_pct == 80
    assert parsed.signal_pct == 80  # 4 bars * 20


def test_extract_signal_variants():
    assert _extract_signal(55) == 55
    assert _extract_signal({"percentage": 70}) == 70
    assert _extract_signal({"bar": 3}) == 60
    assert _extract_signal(None) is None


def test_extract_coords_position_is_lng_lat():
    lat, lng = _extract_coords({"coordinates": [{"position": [-1.36, 39.09]}]})
    assert lat == 39.09
    assert lng == -1.36


def test_parse_dt_iso_is_aware():
    dt = _parse_dt("2026-04-13T18:52:10.000Z")
    assert dt.year == 2026
    assert dt.tzinfo is not None


def test_parse_dt_reads_spypoint_z_as_camera_wall_clock():
    # The camera stamped the frame 10:30 (CEST); SPYPOINT sends it as 10:30Z.
    dt = _parse_dt("2026-09-19T10:30:00.000Z", MADRID)
    assert dt == datetime(2026, 9, 19, 8, 30, tzinfo=timezone.utc)
    assert dt.astimezone(MADRID).strftime("%H:%M") == "10:30"
    # Winter: the offset follows the date, not a fixed two hours.
    dt = _parse_dt("2026-01-10T07:15:00.000Z", MADRID)
    assert dt == datetime(2026, 1, 10, 6, 15, tzinfo=timezone.utc)


def test_parse_dt_trusts_a_real_offset_and_reads_naive_as_local():
    dt = _parse_dt("2026-09-19T10:30:00+02:00", MADRID)
    assert dt == datetime(2026, 9, 19, 8, 30, tzinfo=timezone.utc)
    assert _parse_dt("2026-09-19T10:30:00", MADRID) == dt
    assert _parse_dt("garbage", MADRID) is None


def test_wall_clock_cursor_round_trips_with_parse():
    instant = datetime(2026, 9, 19, 8, 30, tzinfo=timezone.utc)
    cursor = wall_clock_cursor(instant, MADRID)
    assert cursor == "2026-09-19T10:30:00.000Z"
    assert _parse_dt(cursor, MADRID) == instant


def test_list_photos_uses_camera_timezone(monkeypatch):
    client = SpypointClient("u", "p", camera_timezone="Europe/Madrid")
    payload = {"photos": [
        {"id": "a", "originDate": "2026-09-19T10:30:00.000Z",
         "large": {"host": "h", "path": "a.jpg"}},
        {"id": "b", "originDate": ""},
    ]}

    class _Resp:
        def json(self):
            return payload

    seen = {}

    def fake_request(method, path, **kw):
        seen.update(kw.get("json") or {})
        return _Resp()

    monkeypatch.setattr(client, "_request", fake_request)
    photos = client.list_photos("cam", date_end=client.date_cursor(
        datetime(2026, 9, 19, 8, 30, tzinfo=timezone.utc)))
    assert [p.spypoint_id for p in photos] == ["a"]
    assert photos[0].captured_at == datetime(2026, 9, 19, 8, 30, tzinfo=timezone.utc)
    assert seen["dateEnd"] == "2026-09-19T10:30:00.000Z"


def test_parse_camera_real_spypoint_shape():
    cam = {
        "id": "c2",
        "config": {"name": "PL19"},
        "status": {
            "batteries": [90, 0, 0],
            "activePowerSource": 0,
            "powerSources": [{"percentage": 90}],
            "signal": {"bar": 3, "processed": {"percentage": 88}},
            "model": "FLEX-M",
        },
    }
    p = SpypointClient._parse_camera(cam)
    assert p.battery_pct == 90
    assert p.signal_pct == 88
    assert p.model == "FLEX-M"


# ── sync: one commit per camera ─────────────────────────────────────────────


@requires_db
def test_sync_shows_each_cameras_photos_as_soon_as_that_camera_is_done(db_session, monkeypatch):
    """One camera's photos are visible before the next camera starts, and a camera
    that fails is left as it was for the next run (as in the UBox sync): it takes
    none of the cameras before it with it, nor the sync log."""
    from sqlalchemy import create_engine, func, select

    from app.core.config import settings
    from app.ingestion import sync
    from app.models import Camera, Estate, Image, SyncLog

    db_session.add(Estate(name="Piedras Lisas", timezone="Europe/Madrid"))
    db_session.commit()
    monkeypatch.setattr(settings, "spypoint_username", "owner@example.com")
    monkeypatch.setattr(settings, "spypoint_password", "secret")
    monkeypatch.setattr(sync, "enrich_image", lambda db, image: None)
    others = create_engine(db_session.get_bind().url)
    seen_by_others: list[int] = []
    shot = datetime(2026, 9, 25, 21, 40, tzinfo=UTC)

    class FakeClient:
        def __init__(self, *_):
            pass

        def login(self):
            pass

        def list_cameras(self):
            return [SpypointCamera("sp-1", "Charca"), SpypointCamera("sp-2", "Pinar Alto"),
                    SpypointCamera("sp-3", "Barranco")]

        def list_photos(self, spypoint_id, limit=100, date_end=None):
            # What anyone else can see right now, e.g. a hunter opening the map.
            with others.connect() as c:
                seen_by_others.append(c.scalar(select(func.count(Image.id))))
            photos = [SpypointPhoto(f"{spypoint_id}-p{i}", shot, url="") for i in range(2)]
            if spypoint_id == "sp-2":
                # Half its photos stored, then the connection drops.
                sync._ingest_photo(db_session, self, None, db_session.scalar(
                    select(Camera).where(Camera.spypoint_id == "sp-2")), photos[0])
                raise SpypointError("connection reset")
            return photos

        def download(self, url):
            return b""

        def close(self):
            pass

    monkeypatch.setattr(sync, "SpypointClient", FakeClient)
    try:
        result = sync.sync_all(db_session)
    finally:
        others.dispose()

    assert seen_by_others == [0, 2, 2]  # Charca's two were out before Pinar Alto began
    assert result["status"] == "ok" and result["total"] == 4
    assert [r.get("error") for r in result["cameras"]] == [None, "connection reset", None]
    by_camera = dict(db_session.execute(
        select(Camera.name, func.count(Image.id)).outerjoin(Image).group_by(Camera.name)
    ).all())
    assert by_camera == {"Charca": 2, "Barranco": 2}
    log = db_session.scalar(select(SyncLog))
    assert (log.status, log.images_downloaded) == ("ok", 4) and log.finished_at is not None
