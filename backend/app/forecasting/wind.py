"""Wind versus stand geometry — pure trigonometry, no training data, no model.

The first thing any guide checks, and the only decisive variable in this product
that needs zero nights of history. It is also the one most easily turned into
confident nonsense, so the competence boundary is part of the output rather than a
footnote.

Three deliberate limits, each of which produces a different answer rather than a
silent guess:

1. **Below LIGHT_WIND_KMH the synoptic wind does not decide anything.** Weather
   comes from a single grid point of order 2-11 km covering the whole estate; in a
   barranco on a calm evening, thermal drainage dominates and that grid cell cannot
   see it. Saying "clean for this stand" then is worse than saying nothing, because
   the hunter can smell the truth at the truck and will stop believing the app.
2. **No arcs entered means no verdict.** An approach arc nobody supplied is not an
   approach arc of zero degrees.
3. **It never vetoes.** It reports; the hunter decides. A wrong veto on a good
   stand costs more trust than a wrong "clean" costs animals.
"""
from __future__ import annotations

from dataclasses import dataclass

# Below this, thermals dominate and a single-grid-point wind is not informative.
LIGHT_WIND_KMH = 8.0

# Scent does not travel in a line. A 45-degree downwind cone is the usual working
# assumption for a hunter's plume at stand distances.
SCENT_CONE_DEG = 45.0

COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def compass(deg: float) -> str:
    return COMPASS[round(deg / 45.0) % 8]


def normalise(deg: float) -> float:
    return deg % 360.0


def angular_distance(a: float, b: float) -> float:
    """Smallest angle between two bearings, 0-180."""
    d = abs(normalise(a) - normalise(b)) % 360.0
    return 360.0 - d if d > 180.0 else d


def arcs_overlap(a: float, b: float, half_width_a: float, half_width_b: float) -> bool:
    return angular_distance(a, b) <= (half_width_a + half_width_b)


@dataclass
class WindVerdict:
    status: str          # clean | scent_carries | too_light | no_geometry | no_wind_data
    text: str
    scent_bearing: float | None = None
    conflicting_approach: float | None = None

    @property
    def is_advice(self) -> bool:
        """Whether this says anything actionable about the stand at all."""
        return self.status in ("clean", "scent_carries")


def assess(
    *,
    stand_name: str,
    wind_dir_deg: float | None,
    wind_speed_kmh: float | None,
    approach_dirs_deg: list[int] | None,
    alternative_stand: str | None = None,
) -> WindVerdict:
    """Where does the hunter's scent go, and does it cross the animals' approach?

    `wind_dir_deg` follows the meteorological convention: the direction the wind
    blows FROM. Scent therefore travels toward the opposite bearing, and getting
    this backwards would invert every verdict — hence the explicit +180.
    """
    if wind_dir_deg is None or wind_speed_kmh is None:
        return WindVerdict(
            status="no_wind_data",
            text=f"No wind data for tonight — check it yourself before sitting {stand_name}.",
        )

    scent_bearing = normalise(wind_dir_deg + 180.0)
    from_txt = compass(wind_dir_deg)
    speed = round(wind_speed_kmh)

    if wind_speed_kmh < LIGHT_WIND_KMH:
        return WindVerdict(
            status="too_light",
            scent_bearing=scent_bearing,
            text=(
                f"Wind {from_txt} {speed} km/h — too light to call. Thermals will decide "
                "this one; read them at the truck."
            ),
        )

    if not approach_dirs_deg:
        return WindVerdict(
            status="no_geometry",
            scent_bearing=scent_bearing,
            text=(
                f"Wind {from_txt} {speed} km/h — no approach arcs recorded for "
                f"{stand_name}, so this one's yours to solve."
            ),
        )

    half_cone = SCENT_CONE_DEG / 2.0
    for approach in approach_dirs_deg:
        # Approach bearings are recorded as directions animals come FROM, which is
        # where the scent must not go.
        if arcs_overlap(scent_bearing, float(approach), half_cone, 0.0):
            divert = f" Take {alternative_stand} instead." if alternative_stand else ""
            return WindVerdict(
                status="scent_carries",
                scent_bearing=scent_bearing,
                conflicting_approach=float(approach),
                text=(
                    f"Wind {from_txt} {speed} km/h — your scent carries straight into the "
                    f"{compass(approach)} approach at {stand_name}.{divert}"
                ),
            )

    return WindVerdict(
        status="clean",
        scent_bearing=scent_bearing,
        text=(
            f"Wind {from_txt} {speed} km/h — clean for {stand_name}. Your scent goes "
            f"{compass(scent_bearing)}, away from the approaches."
        ),
    )


def shooting_arcs_conflict(
    a_dirs: list[int] | None, b_dirs: list[int] | None, *, half_width: float = 20.0
) -> bool:
    """Do two stands' shooting arcs overlap?

    Used to refuse two simultaneous claims that would put hunters in each other's
    fire lanes. Absent geometry returns False: this must never manufacture a
    conflict out of missing data, only report one it can actually see.
    """
    if not a_dirs or not b_dirs:
        return False
    return any(
        arcs_overlap(float(a), float(b), half_width, half_width) for a in a_dirs for b in b_dirs
    )
