"""Tonight's sky and air, at the time of the sit, and the one wind verdict a stand gets.

Tonight, a reservation, Sit mode, Stands and the map used to answer "is the wind
right for this stand?" with two models at two different moments: Tonight and the
reservation with hand-typed approach arcs against the 22:00 forecast, the map and
Stands with the drawn bedding and the slope wind as it was when the page was opened.
The same stand could be "Wind is right" on one screen and "Wind is wrong" on the
next (audit A-09, J-04, G-09). Everything here answers once, for every screen:

- **When.** The sit: 45 minutes after tonight's sunset, once the evening air has
  settled, or now once that has passed, until 06:00. "Tonight" is the night key
  (06:00 to 06:00), so at 00:30 it is the night still under way, never the next
  evening (A-11, G-10); and at 07:00 it is the coming evening, judged for its sit,
  not for the dawn air. A dawn sit still on after 06:00 asks for the present
  itself (tonight_conditions with its night). Every verdict says the time it is for.
- **What.** The bedding and thermals model (bedding.stand_wind_report). A stand off
  the map or with no bedding drawn falls back to its approach arcs, if it has any;
  otherwise it says what it can't judge, never "calm".
- **No connection held.** The forecast comes from Open-Meteo, which can hang: the
  caller's transaction is ended first (release), so a slow forecast never holds a
  pooled connection that Photos and sign-in are waiting for (K-04).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import geo
from app.core.config import settings
from app.core.logging import get_logger
from app.enrichment.astro import moon_phase, phase_words, solar
from app.enrichment.weather import weather_at
from app.forecasting.exposure import current_night
from app.forecasting.thermal import SETTLING
from app.forecasting.wind import assess, compass
from app.i18n import t
from app.models import Camera, Stand

log = get_logger(__name__)

# The verdicts that say something about the stand. The rest say why they can't.
ADVICE = ("clean", "scent_carries")

# Tonight's top camera is judged at the stand nearest it, within this far. Stands
# placed on the map are never linked to a camera, so a link alone left Tonight
# judging the wind at a camera, named as if it were a stand (J-04).
NEAR_STAND_M = 500.0


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.estate_timezone)


def clock(when: datetime | None) -> str | None:
    """"19:56" on the estate's clock."""
    return when.astimezone(_tz()).strftime("%H:%M") if when else None


def _sun(day: date) -> dict:
    return solar(settings.estate_lat, settings.estate_lon, day)


def sunset_of(night: date) -> datetime | None:
    """Sunset on the evening of `night` (aware)."""
    return _sun(night).get("sunset")


@lru_cache(maxsize=512)
def sun_times(night: date) -> dict:
    """"19:56" and "07:58": the sunset that starts `night` and the sunrise that ends
    it, on the estate's clock. What a saved sit shows with no signal."""
    return {"sunset_local": clock(sunset_of(night)),
            "sunrise_local": clock(_sun(night + timedelta(days=1)).get("sunrise"))}


def sit_time(now: datetime | None = None) -> tuple[datetime, bool]:
    """The moment tonight's wind is judged for, and whether that is now.

    45 minutes after tonight's sunset, when drainage has settled and most of an
    evening sit is still to come; now once that has passed, until 06:00 (somebody
    still out after midnight, or a dawn sit that started before then).

    From 06:00 the night key is the coming evening, so the morning reads that
    evening's sit: judging it by the dawn air told a hunter planning at 07:00 that
    the evening's wind was the morning's (R4BE-1). A dawn sit still on after 06:00
    is judged for now by asking with its own night (tonight_conditions).
    """
    now = now or datetime.now(UTC)
    night = current_night(now)
    if night < now.astimezone(_tz()).date():
        return now, True  # before 06:00: the night under way
    sunset = sunset_of(night)
    if sunset is None:
        return now, True
    settled = sunset + SETTLING
    return (now, True) if now >= settled else (settled, False)


def tonight_conditions(now: datetime | None = None, *, night: date | None = None) -> dict:
    """Tonight's sun, moon and forecast, the forecast at the sit time (sit_time).

    `night` is for a sit whose night is already over and is still on (a dawn sit
    after 06:00): that night's sun, and the air now. Any other night is ignored.

    No database: the caller ends its transaction first (release). A forecast that
    can't be had leaves the wind None, which every verdict reads as "no wind
    forecast", never as calm.
    """
    now = now or datetime.now(UTC)
    if night is not None and night < current_night(now):
        at, is_now = now, True
    else:
        night = current_night(now)
        at, is_now = sit_time(now)
    evening, morning = _sun(night), _sun(night + timedelta(days=1))
    sunset, sunrise = evening.get("sunset"), morning.get("sunrise")
    phase, illum = moon_phase(at)
    w: dict = {}
    try:
        w = weather_at(settings.estate_lat, settings.estate_lon, at, tz=settings.estate_timezone)
    except Exception as e:  # never let the weather break the plan
        log.warning("conditions.weather_failed", error=str(e))
    return {
        "night": night.isoformat(),
        "moon_phase": phase_words(phase), "moon_illum": illum,
        "darkness_minutes": evening.get("darkness_minutes"),
        "sunset": sunset.isoformat() if sunset else None,
        "sunset_local": clock(sunset),
        "sunrise": sunrise.isoformat() if sunrise else None,
        "sunrise_local": clock(sunrise),
        # The moment the wind below is for: every wind verdict is labelled with it.
        "wind_at": at.isoformat(), "wind_at_local": clock(at), "wind_now": is_now,
        "wind_dir_deg": w.get("wind_dir_deg"), "wind_speed_kmh": w.get("wind_speed_kmh"),
        "temp_c": w.get("temp_c"), "pressure_hpa": w.get("pressure_hpa"),
        "cloud_cover_pct": w.get("cloud_cover_pct"), "rain_mm": w.get("rain_mm"),
        # When Open-Meteo made the forecast shown, and whether it is an old copy
        # served because it didn't answer.
        "forecast_fetched_at": w.get("fetched_at"),
        "forecast_stale": bool(w.get("stale")),
    }


def release(db: Session) -> None:
    """End the session's transaction before a slow call, so its pooled connection
    goes back for Photos and sign-in to use. What it loaded stays readable; the
    next query takes a connection again."""
    try:
        db.commit()
    except Exception:
        db.rollback()


def _when(cond: dict, now: datetime | None) -> tuple[datetime, bool]:
    raw = cond.get("wind_at")
    if raw:
        try:
            at = datetime.fromisoformat(raw)
            return at, bool(cond.get("wind_now"))
        except (TypeError, ValueError):
            pass
    return sit_time(now)


def _reading(wind_dir: float, wind_speed: float) -> str:
    return t("wind.reading", dir=compass(wind_dir), speed=round(wind_speed))


def _unjudged(stand: Stand, wind_dir, wind_speed, placed: bool) -> dict:
    """A stand the bedding model can't judge, and that has no approach arcs either."""
    if wind_dir is None or wind_speed is None:
        return {"status": "no_wind_data", "text": t("wind.no_forecast_stand", stand=stand.name)}
    if not placed:
        return {"status": "no_position",
                "text": t("wind.no_position", reading=_reading(wind_dir, wind_speed),
                          stand=stand.name)}
    return {"status": "no_bedding",
            "text": t("wind.no_bedding", reading=_reading(wind_dir, wind_speed))}


def wind_verdict(db: Session, stand: Stand, cond: dict, *, now: datetime | None = None) -> dict:
    """The one wind verdict for a stand tonight, at the sit time `cond` is for.

    The bedding and thermals model when the stand is on the map and bedding is
    drawn; its approach arcs when not and it has some; otherwise the reason it
    can't be judged. `at`/`at_local` is the moment judged, `now` whether that is
    the present rather than the coming sit.
    """
    from app.forecasting import bedding

    at, is_now = _when(cond, now)
    wind_dir, wind_speed = cond.get("wind_dir_deg"), cond.get("wind_speed_kmh")
    placed = stand.lat is not None and stand.lon is not None
    if placed and bedding.bedding_zones(db):
        report = bedding.stand_wind_report(
            db, stand_name=stand.name, lat=stand.lat, lon=stand.lon,
            wind_dir_deg=wind_dir, wind_speed_kmh=wind_speed,
            cloud_pct=cond.get("cloud_cover_pct"), when=at,
        )
    elif stand.approach_dirs_deg:
        v = assess(stand_name=stand.name, wind_dir_deg=wind_dir, wind_speed_kmh=wind_speed,
                   approach_dirs_deg=stand.approach_dirs_deg)
        report = {"status": v.status, "text": v.text, "source": "arcs"}
        if v.scent_bearing is not None:
            report["scent_bearing"] = round(v.scent_bearing)
    else:
        report = _unjudged(stand, wind_dir, wind_speed, placed)
    return {
        **report,
        "is_advice": report["status"] in ADVICE,
        "at": at.isoformat(), "at_local": clock(at), "now": is_now,
        "stand": stand.name, "stand_id": str(stand.id),
    }


def stand_for_camera(db: Session, camera_id) -> Stand | None:
    """The stand a hunter would sit for a camera: the one linked to it if it is on
    the map, else the nearest placed stand within NEAR_STAND_M, else a linked stand
    nobody has placed yet (which says so).

    A linked stand off the map used to win over a placed one 100 m away, so Tonight
    said "isn't on the map yet" while the seat next to it could be judged."""
    linked = db.scalars(
        select(Stand).where(Stand.camera_id == camera_id).order_by(Stand.name)
    ).all()
    for s in linked:
        if s.lat is not None and s.lon is not None:
            return s
    cam = db.get(Camera, camera_id)
    best, best_d = None, NEAR_STAND_M
    if cam is not None and cam.lat is not None and cam.lon is not None:
        for s in db.scalars(select(Stand).order_by(Stand.name)).all():
            if s.lat is None or s.lon is None:
                continue
            d = geo.distance_m(cam.lat, cam.lon, s.lat, s.lon)
            if d <= best_d:
                best, best_d = s, d
    return best or (linked[0] if linked else None)


def no_stand_verdict(camera: str, cond: dict, *, now: datetime | None = None) -> dict:
    """Tonight's wind line when no stand is near the recommended camera."""
    at, is_now = _when(cond, now)
    wind_dir, wind_speed = cond.get("wind_dir_deg"), cond.get("wind_speed_kmh")
    if wind_dir is None or wind_speed is None:
        status, text = "no_wind_data", t("wind.no_forecast")
    else:
        status = "no_stand"
        text = t("wind.no_stand", reading=_reading(wind_dir, wind_speed), camera=camera)
    return {"status": status, "text": text, "is_advice": False,
            "at": at.isoformat(), "at_local": clock(at), "now": is_now,
            "stand": None, "stand_id": None}
