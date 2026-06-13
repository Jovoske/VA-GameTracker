from app.ingestion.spypoint import (
    SpypointClient,
    _extract_coords,
    _extract_signal,
    _parse_dt,
)


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
