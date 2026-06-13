from datetime import datetime, timezone

from app.enrichment.astro import MOON_PHASES, moon_phase, solar
from app.enrichment.weather import _closest_hour_index


def test_moon_phase_valid():
    phase, illum = moon_phase(datetime(2026, 6, 13, tzinfo=timezone.utc))
    assert phase in MOON_PHASES
    assert 0 <= illum <= 100


def test_solar_has_sun_times_and_darkness():
    s = solar(39.09, -1.36, datetime(2026, 6, 13).date())
    assert s["sunrise"] is not None
    assert s["sunset"] is not None
    assert s["darkness_minutes"] is not None
    assert 0 < s["darkness_minutes"] < 1440


def test_closest_hour_index_picks_nearest():
    times = ["2026-06-13T20:00", "2026-06-13T21:00", "2026-06-13T22:00"]
    assert _closest_hour_index(times, datetime(2026, 6, 13, 21, 20)) == 1


def test_closest_hour_index_empty():
    assert _closest_hour_index([], datetime(2026, 6, 13, 21, 20)) is None
