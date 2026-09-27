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
    """A provider login whose cameras feed this estate (guests' own accounts).

    The primary SPYPOINT account stays in .env; these are added via Settings. Each
    password is encrypted at rest (Fernet, see app.core.crypto).
    """
    __tablename__ = "camera_accounts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    estate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("estates.id"), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    label: Mapped[str | None] = mapped_column(String)
    provider: Mapped[str] = mapped_column(
        String, nullable=False, default="spypoint", server_default="spypoint"
    )
    username: Mapped[str] = mapped_column(String, nullable=False)
    password_enc: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Limits apply separately to every UBox camera on this account, before download/AI.
    ubox_min_interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default=text("60")
    )
    ubox_max_images_per_day: Mapped[int] = mapped_column(
        Integer, nullable=False, default=500, server_default=text("500")
    )
    # Set once a fetch has imported this login's history; None means that is still due.
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Whether the login still works, for Settings and the camera cards (see
    # app.ingestion.logins). A fetch that could not sign in or list the cameras sets
    # last_error, in words a hunter can act on, and leaves last_ok_at alone.
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    # How many cameras the provider listed last time, so a login shows its cameras
    # before the first import has linked them.
    reported_cameras: Mapped[int | None] = mapped_column(Integer)
    # The provider's sign-in token, encrypted like the password, kept between fetches
    # so a login is not signed in afresh every 15 minutes; None signs in anew.
    session_enc: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("provider IN ('spypoint','ubox')", name="provider_valid"),
        CheckConstraint(
            "ubox_min_interval_seconds BETWEEN 10 AND 3600", name="ubox_interval_valid"
        ),
        CheckConstraint(
            "ubox_max_images_per_day BETWEEN 1 AND 5000", name="ubox_daily_limit_valid"
        ),
        # Device identifiers are global: one provider account belongs to one estate.
        UniqueConstraint("provider", "username", name="uq_camera_accounts_provider_username"),
        # Emails are case-blind: Julle@ and julle@ are one login, fetched once.
        Index(
            "uq_camera_accounts_provider_login", "provider", text("lower(username)"),
            unique=True, postgresql_where=text("active"),
        ),
    )


class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    estate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("estates.id"), nullable=False)
    # Provider account (NULL also covers the primary SPYPOINT login and local imports).
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("camera_accounts.id"))
    spypoint_id: Mapped[str | None] = mapped_column(String, unique=True)
    ubox_uid: Mapped[str | None] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Keep the imported/default label available while an estate uses its own name.
    provider_name: Mapped[str | None] = mapped_column(String)
    name_is_custom: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
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
    # False once no login reaches the camera (its login was removed); a login that
    # lists it again switches it back on. Its photos stay either way.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # When an admin retired it (taken down, in a drawer). A retired camera is left out
    # of tonight's plan, the alerts, the Insights and the track record; its photos
    # stay. Its own column, not `active`: a login that still lists a camera in a
    # drawer would switch that straight back on.
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Suntek (FTP or email): how far ahead of the server's receipt the camera's clock
    # ran on its last photo that came in straight away, in minutes, when a whole-hour
    # error was put right (a camera that missed the clock change); 0 once photos
    # arrive on time again. NULL until the check has seen a photo.
    clock_ahead_min: Mapped[int | None] = mapped_column(Integer)
    # Photos in a row that came in on time since the clock was last found fast: it is
    # called right again only after a few (ftp_import.ON_TIME_TO_CLEAR).
    clock_ok_photos: Mapped[int | None] = mapped_column(Integer)
    # SPYPOINT: every photo captured up to here has been listed, so a routine fetch
    # pages back to it (less an overlap) rather than reading only the newest page.
    photos_listed_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # SPYPOINT: a stretch below photos_listed_to not listed yet (captures after
    # photos_gap_from, up to photos_gap_to), left by a fetch its page cap cut short;
    # later fetches page on through it with what is left of their cap.
    photos_gap_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    photos_gap_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Why the last fetch could not list this camera's photos although its login
    # worked, in words; None once a fetch lists them again.
    fetch_error: Mapped[str | None] = mapped_column(Text)
    # UBox snapshots that would not download, {event_id: [attempts, captured_at]}:
    # retried on later fetches, then given up on so one dead link can't hold the
    # camera's import back (ubox_sync).
    import_failures: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint(
            "spypoint_id IS NULL OR ubox_uid IS NULL", name="provider_exclusive"
        ),
    )


class CameraView(Base):
    """What each person had of each camera when they last opened it on the map.

    seen_at is the newest arrival or check stamp (images.created_at, processed_at)
    among the camera's photos at that moment, not the clock: a photo stored by a sync
    that began before you looked carries an earlier stamp than your look, and must
    still count as new (see routes_map.seen_mark). The count on a camera's map
    callout is its photos that became showable after it: arrived, or were passed by
    the detector or kept by a hunter (routes_map.shown_after). Per person, because
    the team does not look at the same cameras at the same time. No row means never
    opened.
    """

    __tablename__ = "camera_views"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), primary_key=True
    )
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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


class TerrainGrid(Base):
    """Cached elevation grid for the estate — the ground never moves, so fetch once.

    Stored as one row with a flat elevation array rather than a point per row: it is
    read whole every time (to interpolate and to take slope differences), and 625
    rows to answer one question is a lot of round trips for a static surface.
    """
    __tablename__ = "terrain_grid"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    max_lat: Mapped[float] = mapped_column(Float, nullable=False)
    max_lon: Mapped[float] = mapped_column(Float, nullable=False)
    steps: Mapped[int] = mapped_column(Integer, nullable=False)
    elevations: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Zone(Base):
    """Ground the hunter knows and the cameras cannot see — chiefly bedding.

    The wind module can only speak when it knows which way animals approach, and
    nobody can realistically type in "they come from 235 degrees". Drawing where
    they lie up turns that bearing into derived geometry rather than a guess.

    Stored as a GeoJSON Polygon in JSONB: PostGIS was dropped for the native build,
    and estate-scale geometry is simple enough to do in Python (see app/geo.py).
    """
    __tablename__ = "zones"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    estate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("estates.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="bedding")
    name: Mapped[str] = mapped_column(String, nullable=False)
    polygon: Mapped[dict] = mapped_column(JSONB, nullable=False)  # GeoJSON Polygon
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("kind IN ('bedding','feeding','water','no_go')", name="zone_kind_valid"),
        Index("ix_zones_estate_kind", "estate_id", "kind"),
    )


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
    # Hidden species are out of the app altogether: no photos, no counts, no alerts,
    # no advice. Rabbits on a deer estate. The photos stay on disk and in the table,
    # so unhiding brings everything back.
    hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class Image(Base):
    __tablename__ = "images"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    camera_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cameras.id"), nullable=False)
    spypoint_photo_id: Mapped[str | None] = mapped_column(String, unique=True)
    ubox_event_id: Mapped[str | None] = mapped_column(String, unique=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # When the server got it (FTP and email: the receiver's or the mail server's
    # clock). The Cameras page reads how long photos take to arrive from it, which is
    # how a camera clock running slow shows (audit H-17). NULL for the other sources.
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_path: Mapped[str | None] = mapped_column(String)
    # The small WebP the grids and the map show, made on first request (routes_images).
    thumbnail_path: Mapped[str | None] = mapped_column(String)
    annotated_path: Mapped[str | None] = mapped_column(String)
    cdn_url: Mapped[str | None] = mapped_column(String)
    file_hash: Mapped[str | None] = mapped_column(String)
    # Tries at fetching a SPYPOINT photo's file that failed; retried until MAX in sync.
    download_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    is_empty_frame: Mapped[bool | None] = mapped_column(Boolean)
    animal_conf: Mapped[float | None] = mapped_column(Float)
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The AI pass (app.ai.checking): how often checking this photo failed, the last
    # error, and when it was given up on (after MAX_AI_ATTEMPTS). A given-up photo is
    # "not checked", never "checked, nothing in it".
    ai_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    ai_error: Mapped[str | None] = mapped_column(Text)
    ai_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The box confidence the detector ran at; NULL = an older build, at its 0.25.
    detector_conf: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        Index("ix_images_camera_captured", "camera_id", "captured_at"),
        # camera-first index is useless for global min/max/date_trunc scans
        Index("ix_images_captured_at", text("captured_at DESC")),
        # A camera's newest arrival and what arrived since: the map's "new" count.
        Index("ix_images_camera_created", "camera_id", "created_at"),
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
    # DINOv2-L embedding stored as a JSON list (no pgvector).
    embedding: Mapped[list[float] | None] = mapped_column(JSONB)
    model_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_runs.id"))
    # A hunter said what this is from the photo viewer (routes_images.set_species): the
    # species is theirs, and the AI never changes it again (the burst vote leaves it
    # be). Who, for "Fixed by Pedro"; a removed login leaves the fix and no name.
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    corrected_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
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
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
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
    details: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CameraNight(Base):
    """Whether a camera was actually watching on a given night — the denominator.

    Without this, a flat battery, a lost signal, an exhausted photo-credit quota and
    an unprocessed classification backlog all look identical to "no animals here",
    and every rate in the product silently divides by a night that never happened.

    exposure_state:
      CONFIRMED    — frames exist inside the night window and have been processed.
      PRESUMED_UP  — no frames, but frames on the nights either side of a gap of at
                     most two nights; admitted as a true zero. A longer silence is
                     UNKNOWN: a flat battery is not a run of empty nights.
      UNPROCESSED  — frames exist that the AI has not checked yet, or gave up on after
                     failing. NULL: counting these as zero animals is the backlog
                     artefact.
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
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
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

    The outcome only goes up (shot > shootable_no_shot > seen > nothing): a glove
    brushing SAW ANIMALS after a shot must not turn the shot into a sighting. Only
    the hunter's own "What happened?" correction lowers it. `ended_at` is set by END
    SIT, never by a report: seeing animals at 20:15 does not end the sit.
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
    # The phone's time of the report the server kept. A tap saved with no signal can
    # arrive an hour late; anything older than this is ignored.
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    species_seen: Mapped[str | None] = mapped_column(String)
    # What the app told them about the wind, kept verbatim so the advice can later
    # be scored against what actually happened instead of quietly rewritten.
    wind_status: Mapped[str | None] = mapped_column(String)
    wind_text: Mapped[str | None] = mapped_column(Text)
    # The moment that verdict was judged for: the sit time when it was reserved
    # (45 min after sunset), or the reservation itself after dark.
    wind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('unreported','nothing','seen','shootable_no_shot','shot','cancelled')",
            name="outcome_valid",
        ),
        Index("ix_sits_night", "night"),
        Index("ix_sits_stand_night", "stand_id", "night"),
        # One live reservation per stand and night. The per-night lock in
        # routes_stands.claim_stand is the real guard (it also keeps fire lanes
        # apart); this is the backstop.
        Index(
            "uq_sits_stand_night_live", "stand_id", "night",
            unique=True, postgresql_where=text("outcome <> 'cancelled'"),
        ),
    )


class AppSetting(Base):
    """Server-generated state that must outlive a restart but has no business in .env.

    Turning notifications on should not require anyone to hand-edit the server: the
    Web Push (VAPID) key pair is generated on first use and kept here, as is the
    dispatcher's watermark. Values are small JSON documents keyed by name.
    """

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NotificationPref(Base):
    """Which animals a person wants to hear about, and whether they want to at all.

    One row per user; a missing row means "never set up" and the API answers with
    defaults (priority species selected, alerts off). `species_ids` is a JSON list of
    species keys rather than a join table: it is tiny, always read whole, and written
    whole from the settings screen.
    """

    __tablename__ = "notification_prefs"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    species_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Cameras this person hears nothing from (the busy feeder), as camera id strings.
    # Every camera is on until muted, so a camera added later is heard by default.
    muted_camera_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PhotoNote(Base):
    """A photo someone on the team marked "Worth a look", with an optional note.

    The team's own read of the camera output, shown to everyone newest first. `text`
    is NULL for a mark with nothing said. Removing a person keeps what they said
    (user_id goes NULL and the name falls back to "Hunter"); removing the photo
    removes its notes.
    """

    __tablename__ = "photo_notes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    image_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    text: Mapped[str | None] = mapped_column(String(140))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        Index("ix_photo_notes_image_id", "image_id"),
        Index("ix_photo_notes_created_at", "created_at"),
    )


class PushSubscription(Base):
    """A browser's Web Push endpoint: one per installed app or device, owned by a user.

    The endpoint is the identity. A phone that signs in as someone else re-homes its
    row, so a push always goes to whoever is signed in on that device.
    """

    __tablename__ = "push_subscriptions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh: Mapped[str] = mapped_column(String, nullable=False)
    auth: Mapped[str] = mapped_column(String, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
        Index("ix_push_subscriptions_user_id", "user_id"),
    )


class Notification(Base):
    """What was (or would have been) sent: the in-app record behind every push.

    Push is fire-and-forget and phones drop it silently, so the app keeps its own
    copy. The settings screen lists these, which is how a person tells a quiet night
    from a broken subscription.
    """

    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False, default="sighting")
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(String)
    species_id: Mapped[str | None] = mapped_column(ForeignKey("species.id"))
    image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL")
    )
    # sent / failed / no_subscription — how delivery went, for the settings screen.
    push_status: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)


class ClientError(Base):
    """A crash or blank screen on someone's phone, as the app reported it.

    Hunters never see a stack trace and rarely say "it went black" until days
    later, so the app posts what broke to /api/client-errors and admins read the
    last few in Settings. Kept short (the newest 200) because this is a smoke
    alarm, not a log archive: the full stream also goes to the server log.
    Removing a person keeps what their phone reported, with no name on it.
    """

    __tablename__ = "client_errors"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # error / rejection / render / chunk: where in the app it was caught.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    stack: Mapped[str | None] = mapped_column(Text)
    route: Mapped[str | None] = mapped_column(String(200))
    build: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    # When it happened by the phone's clock; a report that waited for signal
    # arrives (created_at) later. Null when the phone didn't say or its clock is off.
    happened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (Index("ix_client_errors_created_at", "created_at"),)
