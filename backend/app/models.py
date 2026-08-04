"""SQLAlchemy ORM models — the full GameSense schema (see docs/03-database-schema.md)."""
import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_PK = dict(primary_key=True, default=uuid.uuid4)


class Estate(Base):
    __tablename__ = "estates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    name: Mapped[str] = mapped_column(String, nullable=False)
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="Europe/Madrid")
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    estate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("estates.id"))
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("role IN ('admin','member','viewer')", name="role_valid"),)


class CameraAccount(Base):
    """An extra SPYPOINT login whose cameras feed this estate (guests' own accounts).

    The primary account stays in .env; these are added at runtime via Settings. The
    SPYPOINT password is encrypted at rest (Fernet, key derived from JWT_SECRET).
    """
    __tablename__ = "camera_accounts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    estate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("estates.id"), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    label: Mapped[str | None] = mapped_column(String)
    username: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_enc: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    estate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("estates.id"), nullable=False)
    # Which extra SPYPOINT account this camera came from (NULL = the primary .env account).
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("camera_accounts.id"))
    spypoint_id: Mapped[str | None] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    altitude_m: Mapped[float | None] = mapped_column(Float)
    model: Mapped[str | None] = mapped_column(String)
    battery_pct: Mapped[int | None] = mapped_column(Integer)
    signal_pct: Mapped[int | None] = mapped_column(Integer)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Camera health (from SPYPOINT) — surfaced on the Cameras page and used to keep a dead
    # or out-of-credits camera from being read as "no animals" in the forecast.
    last_report_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    battery_level: Mapped[str | None] = mapped_column(String)
    sd_used_mb: Mapped[int | None] = mapped_column(Integer)
    sd_total_mb: Mapped[int | None] = mapped_column(Integer)
    photo_count: Mapped[int | None] = mapped_column(Integer)
    photo_limit: Mapped[int | None] = mapped_column(Integer)
    plan_name: Mapped[str | None] = mapped_column(String)
    cycle_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Stand(Base):
    __tablename__ = "stands"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    estate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("estates.id"), nullable=False)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cameras.id"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    shooting_dirs_deg: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    approach_dirs_deg: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    notes: Mapped[str | None] = mapped_column(Text)


class Species(Base):
    __tablename__ = "species"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # 'sus_scrofa'
    common_name: Mapped[str] = mapped_column(String, nullable=False)
    group_name: Mapped[str | None] = mapped_column(String)
    icon: Mapped[str | None] = mapped_column(String)
    color: Mapped[str | None] = mapped_column(String)
    is_priority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Whether this species appears in hunting advice (Tonight recommendation + outlook).
    # Stats and tracking always cover every species regardless of this flag.
    huntable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class Image(Base):
    __tablename__ = "images"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    camera_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cameras.id"), nullable=False)
    spypoint_photo_id: Mapped[str | None] = mapped_column(String, unique=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    original_path: Mapped[str | None] = mapped_column(String)
    annotated_path: Mapped[str | None] = mapped_column(String)
    cdn_url: Mapped[str | None] = mapped_column(String)
    file_hash: Mapped[str | None] = mapped_column(String)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    is_empty_frame: Mapped[bool | None] = mapped_column(Boolean)
    animal_conf: Mapped[float | None] = mapped_column(Float)
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        Index("ix_images_camera_captured", "camera_id", "captured_at"),
        # camera-first index is useless for global min/max/date_trunc scans
        Index("ix_images_captured_at", text("captured_at DESC")),
    )


class Detection(Base):
    __tablename__ = "detections"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    image_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    species_id: Mapped[str | None] = mapped_column(ForeignKey("species.id"))
    species_conf: Mapped[float | None] = mapped_column(Float)
    sex: Mapped[str] = mapped_column(String, default="unknown")
    sex_conf: Mapped[float | None] = mapped_column(Float)
    # Cloud-vision sex pass bookkeeping. Without these, a crop the model can't judge stays
    # sex='unknown' and gets re-sent (and re-billed) on every scheduled run, forever.
    sex_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sex_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    age_class: Mapped[str] = mapped_column(String, default="unknown")
    age_conf: Mapped[float | None] = mapped_column(Float)
    group_size: Mapped[int | None] = mapped_column(Integer)
    group_type: Mapped[str | None] = mapped_column(String)
    bbox: Mapped[dict | None] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(JSONB)  # DINOv2-L embedding stored as a JSON list (no pgvector)
    model_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("sex IN ('male','female','unknown')", name="sex_valid"),
        CheckConstraint(
            "age_class IN ('juvenile','young_adult','mature_adult','old','unknown')",
            name="age_valid",
        ),
        # image_id is the join in essentially every query in the app.
        Index("ix_detections_image_id", "image_id"),
        Index("ix_detections_species_image", "species_id", "image_id"),
    )


class Individual(Base):
    __tablename__ = "individuals"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    estate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("estates.id"), nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    species_id: Mapped[str | None] = mapped_column(ForeignKey("species.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    thumbnail_path: Mapped[str | None] = mapped_column(String)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("status IN ('active','missing','archived')", name="status_valid"),
    )


class DetectionIndividual(Base):
    __tablename__ = "detection_individual"
    detection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("detections.id", ondelete="CASCADE"), primary_key=True
    )
    individual_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("individuals.id", ondelete="CASCADE"), primary_key=True
    )
    match_conf: Mapped[float] = mapped_column(Float, nullable=False)
    confirmed_by_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class EnvSnapshot(Base):
    __tablename__ = "env_snapshots"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    camera_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cameras.id"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    temp_c: Mapped[float | None] = mapped_column(Float)
    humidity_pct: Mapped[float | None] = mapped_column(Float)
    pressure_hpa: Mapped[float | None] = mapped_column(Float)
    wind_speed_kmh: Mapped[float | None] = mapped_column(Float)
    wind_gust_kmh: Mapped[float | None] = mapped_column(Float)
    wind_dir_deg: Mapped[int | None] = mapped_column(Integer)
    rain_mm: Mapped[float | None] = mapped_column(Float)
    cloud_cover_pct: Mapped[int | None] = mapped_column(Integer)
    moon_phase: Mapped[str | None] = mapped_column(String)
    moon_illum_pct: Mapped[float | None] = mapped_column(Float)
    moon_rise: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    moon_set: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sunrise: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sunset: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    civil_twilight_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nautical_twilight_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    darkness_minutes: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("camera_id", "observed_at", name="uq_env_camera_time"),)


class Forecast(Base):
    __tablename__ = "forecasts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cameras.id"))
    stand_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stands.id"))
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    species_id: Mapped[str | None] = mapped_column(ForeignKey("species.id"))
    individual_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("individuals.id"))
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    best_window_start: Mapped[time | None] = mapped_column(Time(timezone=True))
    best_window_end: Mapped[time | None] = mapped_column(Time(timezone=True))
    confidence: Mapped[float | None] = mapped_column(Float)
    factors: Mapped[dict | None] = mapped_column(JSONB)
    model_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_runs.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_forecasts_date_camera", "target_date", "camera_id"),)


class ForecastOutcome(Base):
    __tablename__ = "forecast_outcomes"
    forecast_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecasts.id", ondelete="CASCADE"), primary_key=True
    )
    occurred: Mapped[bool | None] = mapped_column(Boolean)
    actual_count: Mapped[int | None] = mapped_column(Integer)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Correlation(Base):
    __tablename__ = "correlations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    estate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("estates.id"))
    scope: Mapped[str | None] = mapped_column(String)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    strength: Mapped[float | None] = mapped_column(Float)
    sample_size: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelRun(Base):
    __tablename__ = "model_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    kind: Mapped[str | None] = mapped_column(String)
    name: Mapped[str | None] = mapped_column(String)
    version: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict | None] = mapped_column(JSONB)


class SyncLog(Base):
    __tablename__ = "sync_log"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cameras.id"))
    photos_synced: Mapped[int | None] = mapped_column(Integer)
    images_downloaded: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CameraNight(Base):
    """Whether a camera was actually watching on a given night — the denominator.

    Without this, a flat battery, a lost signal, an exhausted photo-credit quota and
    an unprocessed classification backlog all look identical to "no animals here",
    and every rate in the product silently divides by a night that never happened.

    exposure_state:
      CONFIRMED    — frames exist inside the night window and have been processed.
      PRESUMED_UP  — no frames, but frames exist either side; admitted as a true zero.
      UNPROCESSED  — frames exist but have not been through the detector yet. NULL:
                     counting these as zero animals is the backlog artefact.
      UNKNOWN      — anything else, including nights the camera was out of photo
                     credits. NULL, and the excluded count is reported.
    """

    __tablename__ = "camera_nights"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    camera_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cameras.id"), nullable=False)
    night: Mapped[date] = mapped_column(Date, nullable=False)
    exposure_state: Mapped[str] = mapped_column(String, nullable=False)
    frames: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    empty_frames: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("camera_id", "night", name="uq_camera_night"),
        CheckConstraint(
            "exposure_state IN ('CONFIRMED','PRESUMED_UP','UNPROCESSED','UNKNOWN')",
            name="exposure_state_valid",
        ),
        Index("ix_camera_nights_night", "night"),
    )

    @property
    def counts_as_observed(self) -> bool:
        """Only these two states may contribute a denominator or a true zero."""
        return self.exposure_state in ("CONFIRMED", "PRESUMED_UP")


class Sit(Base):
    """A claimed stand for a night, and what came of it.

    The claim is written *before* the sit, at 18:00, because claiming has a selfish
    payoff — you claim to get the wind verdict and to find out whether anyone else
    is on that ridge. That is why this row exists even when nobody ever reports an
    outcome, and it is what makes hunting pressure measurable at all.

    `outcome` is never silently 'nothing': a sit nobody reported on is UNREPORTED.
    Conflating "I saw nothing" with "I didn't say" would poison the only ground
    truth this system will ever have.
    """

    __tablename__ = "sits"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    stand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stands.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    night: Mapped[date] = mapped_column(Date, nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String, nullable=False, default="unreported")
    species_seen: Mapped[str | None] = mapped_column(String)
    # What the app told them about the wind, kept verbatim so the advice can later
    # be scored against what actually happened instead of quietly rewritten.
    wind_status: Mapped[str | None] = mapped_column(String)
    wind_text: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('unreported','nothing','seen','shootable_no_shot','shot','cancelled')",
            name="outcome_valid",
        ),
        Index("ix_sits_night", "night"),
        Index("ix_sits_stand_night", "stand_id", "night"),
    )
