"""Attach weather + moon + solar to an image AT ITS REAL CAPTURE TIME."""
from __future__ import annotations

from datetime import timezone
from zoneinfo import ZoneInfo

from geoalchemy2.functions import ST_X, ST_Y
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.enrichment.astro import moon_phase, solar
from app.enrichment.weather import weather_at
from app.models import Camera, EnvSnapshot, Image


def _camera_coords(db: Session, camera_id) -> tuple[float, float]:
    row = db.execute(
        select(ST_Y(Camera.location), ST_X(Camera.location)).where(Camera.id == camera_id)
    ).first()
    if row and row[0] is not None and row[1] is not None:
        return float(row[0]), float(row[1])
    return settings.estate_lat, settings.estate_lon


def _to_int(v) -> int | None:
    return int(round(v)) if isinstance(v, (int, float)) else None


def enrich_image(db: Session, image: Image) -> EnvSnapshot | None:
    existing = db.scalar(
        select(EnvSnapshot).where(
            EnvSnapshot.camera_id == image.camera_id,
            EnvSnapshot.observed_at == image.captured_at,
        )
    )
    if existing:
        return existing

    when = image.captured_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    lat, lng = _camera_coords(db, image.camera_id)
    local_date = when.astimezone(ZoneInfo(settings.estate_timezone)).date()

    w = weather_at(lat, lng, when, tz=settings.estate_timezone)
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
