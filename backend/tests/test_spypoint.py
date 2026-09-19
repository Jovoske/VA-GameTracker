from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.ingestion.spypoint import (
    SpypointClient,
    _extract_coords,
    _extract_signal,
    _parse_dt,
    wall_clock_cursor,
)

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
