"""Wind geometry tests.

Pure trigonometry, so this is the one part of the forecast that can be tested
exhaustively without any data at all. The cases that matter most are the ones
where the app must decline to answer.
"""
from __future__ import annotations

import pytest

from app.forecasting.wind import (
    LIGHT_WIND_KMH,
    angular_distance,
    assess,
    compass,
    shooting_arcs_conflict,
)


def test_compass_wraps_correctly():
    assert compass(0) == "N"
    assert compass(90) == "E"
    assert compass(180) == "S"
    assert compass(270) == "W"
    assert compass(359) == "N"


@pytest.mark.parametrize(
    "a,b,expected",
    [(0, 10, 10), (350, 10, 20), (0, 180, 180), (10, 350, 20), (180, 181, 1)],
)
def test_angular_distance_takes_the_short_way(a, b, expected):
    assert angular_distance(a, b) == pytest.approx(expected)


def test_scent_travels_opposite_to_the_wind_source():
    """Meteorological convention: wind_dir is where it blows FROM.

    Getting this backwards inverts every verdict in the product, so it is pinned.
    """
    v = assess(
        stand_name="Puente",
        wind_dir_deg=180,          # southerly: blowing from the south
        wind_speed_kmh=15,
        approach_dirs_deg=[0],     # animals come from the north
    )
    # Scent travels north (0) -- straight into the approach.
    assert v.scent_bearing == pytest.approx(0.0)
    assert v.status == "scent_carries"


def test_clean_when_scent_goes_away_from_the_approach():
    v = assess(
        stand_name="Puente",
        wind_dir_deg=0,            # northerly, scent travels south
        wind_speed_kmh=15,
        approach_dirs_deg=[0],     # animals come from the north
    )
    assert v.status == "clean"
    assert "clean for Puente" in v.text


def test_light_wind_declines_to_answer():
    """The competence boundary: below ~8 km/h a single grid point sees no barranco."""
    v = assess(
        stand_name="Puente",
        wind_dir_deg=180,
        wind_speed_kmh=LIGHT_WIND_KMH - 0.1,
        approach_dirs_deg=[0],     # would otherwise be a 'scent_carries'
    )
    assert v.status == "too_light"
    assert v.is_advice is False
    assert "thermals" in v.text.lower()


def test_missing_arcs_are_not_treated_as_zero():
    for arcs in (None, []):
        v = assess(
            stand_name="Solana", wind_dir_deg=180, wind_speed_kmh=20, approach_dirs_deg=arcs
        )
        assert v.status == "no_geometry"
        assert v.is_advice is False
        assert "yours to solve" in v.text


def test_missing_wind_is_reported_not_guessed():
    v = assess(
        stand_name="Solana", wind_dir_deg=None, wind_speed_kmh=None, approach_dirs_deg=[0]
    )
    assert v.status == "no_wind_data"
    assert v.is_advice is False


def test_it_suggests_an_alternative_when_it_has_one():
    v = assess(
        stand_name="Puente",
        wind_dir_deg=180,
        wind_speed_kmh=15,
        approach_dirs_deg=[0],
        alternative_stand="Solana",
    )
    assert "Take Solana instead" in v.text


def test_scent_cone_has_width():
    """A 45-degree cone means a near-miss bearing still counts as busted."""
    # Scent travels to 0 (N). An approach 20 degrees off is inside the +/-22.5 cone.
    v = assess(
        stand_name="P", wind_dir_deg=180, wind_speed_kmh=15, approach_dirs_deg=[20]
    )
    assert v.status == "scent_carries"
    # 30 degrees off is outside it.
    v2 = assess(
        stand_name="P", wind_dir_deg=180, wind_speed_kmh=15, approach_dirs_deg=[30]
    )
    assert v2.status == "clean"


def test_it_never_vetoes():
    """Every outcome is a statement; none is a refusal to let the hunter sit."""
    for wind, arcs in ((180, [0]), (5, [0]), (180, None), (None, [0])):
        v = assess(
            stand_name="P",
            wind_dir_deg=wind,
            wind_speed_kmh=15 if wind is not None else None,
            approach_dirs_deg=arcs,
        )
        assert v.text and not v.text.startswith("DO NOT")


# ── safety: overlapping fire lanes ──────────────────────────────────────────


def test_overlapping_shooting_arcs_are_detected():
    assert shooting_arcs_conflict([90], [100]) is True     # 10 deg apart, arcs are +/-20
    assert shooting_arcs_conflict([90], [180]) is False


def test_missing_shooting_geometry_never_invents_a_conflict():
    """Absent data must not manufacture a safety warning; it has no information."""
    assert shooting_arcs_conflict(None, [90]) is False
    assert shooting_arcs_conflict([], [90]) is False
    assert shooting_arcs_conflict(None, None) is False
