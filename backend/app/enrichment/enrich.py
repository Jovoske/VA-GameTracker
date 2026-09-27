"""Attach weather + moon + solar to an image AT ITS REAL CAPTURE TIME."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.enrichment.astro import moon_phase, solar
from app.enrichment.weather import weather_at
from app.models import Camera, EnvSnapshot, Image


def _camera_coords(db: Session, camera_id) -> tuple[float, float]:
    row = db.execute(
        select(Camera.lat, Camera.lon).where(Camera.id == camera_id)
    ).first()
    if row and row[0] is not None and row[1] is not None:
        return float(row[0]), float(row[1])
    return settings.estate_lat, settings.estate_lon


def _to_int(v) -> int | None:
    return int(round(v)) if isinstance(v, (int, float)) else None


# How far back, and how many a run, "unavailable" weather is looked up again.
REFILL_DAYS = 7
REFILL_PER_RUN = 200


def _fill_weather(snap: EnvSnapshot, w: dict) -> None:
    snap.source = w["source"]
    for field in ("temp_c", "humidity_pct", "pressure_hpa", "wind_speed_kmh",
                  "wind_gust_kmh", "rain_mm"):
        setattr(snap, field, w.get(field))
    snap.wind_dir_deg = _to_int(w.get("wind_dir_deg"))
    snap.cloud_cover_pct = _to_int(w.get("cloud_cover_pct"))


def refill_unavailable(db: Session, *, now: datetime | None = None,
                       limit: int = REFILL_PER_RUN) -> int:
    """Fill in weather stored as "unavailable" while Open-Meteo was down.

    Photos are stored with no weather when Open-Meteo doesn't answer (and for a
    while after, see weather.PAUSE_AFTER_FAILURE_SECONDS), and nothing looks a photo
    up again once it is stored. So every fetch ends here: the last REFILL_DAYS of
    them, newest first, a bounded number a run, stopping at the first that still
    gets no answer. Returns how many were filled in.
    """
    now = now or datetime.now(UTC)
    snaps = db.scalars(
        select(EnvSnapshot)
        .where(EnvSnapshot.source == "unavailable",
               EnvSnapshot.observed_at >= now - timedelta(days=REFILL_DAYS))
        .order_by(EnvSnapshot.observed_at.desc())
        .limit(limit)
    ).all()
    filled = 0
    for snap in snaps:
        lat, lng = _camera_coords(db, snap.camera_id)
        w = weather_at(lat, lng, snap.observed_at, tz=settings.estate_timezone)
        if w.get("source", "unavailable") == "unavailable":
            break  # still down: the next fetch tries again
        if w.get("temp_c") is None:
            continue  # an answer with no numbers in it yet (the archive lags a few days)
        _fill_weather(snap, w)
        filled += 1
    db.commit()
    return filled


def enrich_image(db: Session, image: Image) -> EnvSnapshot | None:
    existing = db.scalar(
        select(EnvSnapshot).where(
            EnvSnapshot.camera_id == image.camera_id,
            EnvSnapshot.observed_at == image.captured_at,
        )
    )
    if existing and existing.source != "unavailable":
        return existing

    when = image.captured_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    lat, lng = _camera_coords(db, image.camera_id)
    local_date = when.astimezone(ZoneInfo(settings.estate_timezone)).date()

    w = weather_at(lat, lng, when, tz=settings.estate_timezone)
    if existing:
        # Stored while Open-Meteo was down: fill the weather in now if it answers.
        if w.get("source", "unavailable") != "unavailable":
            _fill_weather(existing, w)
            db.flush()
        return existing
    phase, illum = moon_phase(when)
    s = solar(lat, lng, local_date)

    snap = EnvSnapshot(
        camera_id=image.camera_id,
        observed_at=image.captured_at,
        source=w.get("source", "open-meteo"),
        temp_c=w.get("temp_c"),
        humidity_pct=w.get("humidity_pct"),
        pressure_hpa=w.get("pressure_hpa"),
        wind_speed_kmh=w.get("wind_speed_kmh"),
        wind_gust_kmh=w.get("wind_gust_kmh"),
        wind_dir_deg=_to_int(w.get("wind_dir_deg")),
        rain_mm=w.get("rain_mm"),
        cloud_cover_pct=_to_int(w.get("cloud_cover_pct")),
        moon_phase=phase,
        moon_illum_pct=illum,
        sunrise=s.get("sunrise"),
        sunset=s.get("sunset"),
        civil_twilight_end=s.get("civil_twilight_end"),
        nautical_twilight_end=s.get("nautical_twilight_end"),
        darkness_minutes=s.get("darkness_minutes"),
    )
    db.add(snap)
    db.flush()
    return snap
