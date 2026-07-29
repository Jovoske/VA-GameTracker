"""initial schema — all tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-13

FROZEN. This migration used to call ``Base.metadata.create_all()``, which meant it
created whatever the ORM happened to look like *at the moment it ran* — so a fresh
database got today's columns and then 0002 tried to add columns that already
existed, failing with DuplicateColumn and leaving the API unable to start. A
migration must describe one fixed point in history, never a moving target. The
statements below reproduce the schema as of this revision and must not be edited to
track model changes; add a new revision instead.

This frozen form uses plain lat/lon floats and JSONB, matching the native
PostgreSQL build. Databases created before that change carry PostGIS geography and
pgvector columns instead — 0004 reconciles them without dropping anything.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.sqltypes import Text

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "estates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_estates")),
    )
    op.create_table(
        "model_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_runs")),
    )
    op.create_table(
        "species",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("common_name", sa.String(), nullable=False),
        sa.Column("group_name", sa.String(), nullable=True),
        sa.Column("icon", sa.String(), nullable=True),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("is_priority", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_species")),
    )
    op.create_table(
        "cameras",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("estate_id", sa.UUID(), nullable=False),
        sa.Column("spypoint_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("altitude_m", sa.Float(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("battery_pct", sa.Integer(), nullable=True),
        sa.Column("signal_pct", sa.Integer(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["estate_id"], ["estates.id"], name=op.f("fk_cameras_estate_id_estates")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cameras")),
        sa.UniqueConstraint("spypoint_id", name=op.f("uq_cameras_spypoint_id")),
    )
    op.create_table(
        "correlations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("estate_id", sa.UUID(), nullable=True),
        sa.Column("scope", sa.String(), nullable=True),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("strength", sa.Float(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["estate_id"], ["estates.id"], name=op.f("fk_correlations_estate_id_estates")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_correlations")),
    )
    op.create_table(
        "individuals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("estate_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("species_id", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("thumbnail_path", sa.String(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active','missing','archived')", name=op.f("ck_individuals_status_valid")),
        sa.ForeignKeyConstraint(["estate_id"], ["estates.id"], name=op.f("fk_individuals_estate_id_estates")),
        sa.ForeignKeyConstraint(["species_id"], ["species.id"], name=op.f("fk_individuals_species_id_species")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_individuals")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("estate_id", sa.UUID(), nullable=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('admin','member','viewer')", name=op.f("ck_users_role_valid")),
        sa.ForeignKeyConstraint(["estate_id"], ["estates.id"], name=op.f("fk_users_estate_id_estates")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "env_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("camera_id", sa.UUID(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("temp_c", sa.Float(), nullable=True),
        sa.Column("humidity_pct", sa.Float(), nullable=True),
        sa.Column("pressure_hpa", sa.Float(), nullable=True),
        sa.Column("wind_speed_kmh", sa.Float(), nullable=True),
        sa.Column("wind_gust_kmh", sa.Float(), nullable=True),
        sa.Column("wind_dir_deg", sa.Integer(), nullable=True),
        sa.Column("rain_mm", sa.Float(), nullable=True),
        sa.Column("cloud_cover_pct", sa.Integer(), nullable=True),
        sa.Column("moon_phase", sa.String(), nullable=True),
        sa.Column("moon_illum_pct", sa.Float(), nullable=True),
        sa.Column("moon_rise", sa.DateTime(timezone=True), nullable=True),
        sa.Column("moon_set", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sunrise", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sunset", sa.DateTime(timezone=True), nullable=True),
        sa.Column("civil_twilight_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nautical_twilight_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("darkness_minutes", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], name=op.f("fk_env_snapshots_camera_id_cameras")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_env_snapshots")),
        sa.UniqueConstraint("camera_id", "observed_at", name="uq_env_camera_time"),
    )
    op.create_table(
        "images",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("camera_id", sa.UUID(), nullable=False),
        sa.Column("spypoint_photo_id", sa.String(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_path", sa.String(), nullable=True),
        sa.Column("annotated_path", sa.String(), nullable=True),
        sa.Column("cdn_url", sa.String(), nullable=True),
        sa.Column("file_hash", sa.String(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("is_empty_frame", sa.Boolean(), nullable=True),
        # animal_conf and reviewed are added by 0002 — deliberately absent here.
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], name=op.f("fk_images_camera_id_cameras")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_images")),
        sa.UniqueConstraint("spypoint_photo_id", name=op.f("uq_images_spypoint_photo_id")),
    )
    op.create_index("ix_images_camera_captured", "images", ["camera_id", "captured_at"], unique=False)
    op.create_table(
        "stands",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("estate_id", sa.UUID(), nullable=False),
        sa.Column("camera_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("shooting_dirs_deg", sa.ARRAY(sa.Integer()), nullable=True),
        sa.Column("approach_dirs_deg", sa.ARRAY(sa.Integer()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], name=op.f("fk_stands_camera_id_cameras")),
        sa.ForeignKeyConstraint(["estate_id"], ["estates.id"], name=op.f("fk_stands_estate_id_estates")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stands")),
    )
    op.create_table(
        "sync_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("camera_id", sa.UUID(), nullable=True),
        sa.Column("photos_synced", sa.Integer(), nullable=True),
        sa.Column("images_downloaded", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], name=op.f("fk_sync_log_camera_id_cameras")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_log")),
    )
    op.create_table(
        "detections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("image_id", sa.UUID(), nullable=False),
        sa.Column("species_id", sa.String(), nullable=True),
        sa.Column("species_conf", sa.Float(), nullable=True),
        sa.Column("sex", sa.String(), nullable=False),
        sa.Column("sex_conf", sa.Float(), nullable=True),
        sa.Column("age_class", sa.String(), nullable=False),
        sa.Column("age_conf", sa.Float(), nullable=True),
        sa.Column("group_size", sa.Integer(), nullable=True),
        sa.Column("group_type", sa.String(), nullable=True),
        sa.Column("bbox", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("embedding", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("model_run_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "age_class IN ('juvenile','young_adult','mature_adult','old','unknown')",
            name=op.f("ck_detections_age_valid"),
        ),
        sa.CheckConstraint("sex IN ('male','female','unknown')", name=op.f("ck_detections_sex_valid")),
        sa.ForeignKeyConstraint(
            ["image_id"], ["images.id"], name=op.f("fk_detections_image_id_images"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["model_run_id"], ["model_runs.id"], name=op.f("fk_detections_model_run_id_model_runs")
        ),
        sa.ForeignKeyConstraint(["species_id"], ["species.id"], name=op.f("fk_detections_species_id_species")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_detections")),
    )
    op.create_table(
        "forecasts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("camera_id", sa.UUID(), nullable=True),
        sa.Column("stand_id", sa.UUID(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("species_id", sa.String(), nullable=True),
        sa.Column("individual_id", sa.UUID(), nullable=True),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("best_window_start", sa.Time(timezone=True), nullable=True),
        sa.Column("best_window_end", sa.Time(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("factors", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("model_run_id", sa.UUID(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], name=op.f("fk_forecasts_camera_id_cameras")),
        sa.ForeignKeyConstraint(
            ["individual_id"], ["individuals.id"], name=op.f("fk_forecasts_individual_id_individuals")
        ),
        sa.ForeignKeyConstraint(
            ["model_run_id"], ["model_runs.id"], name=op.f("fk_forecasts_model_run_id_model_runs")
        ),
        sa.ForeignKeyConstraint(["species_id"], ["species.id"], name=op.f("fk_forecasts_species_id_species")),
        sa.ForeignKeyConstraint(["stand_id"], ["stands.id"], name=op.f("fk_forecasts_stand_id_stands")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecasts")),
    )
    op.create_index("ix_forecasts_date_camera", "forecasts", ["target_date", "camera_id"], unique=False)
    op.create_table(
        "detection_individual",
        sa.Column("detection_id", sa.UUID(), nullable=False),
        sa.Column("individual_id", sa.UUID(), nullable=False),
        sa.Column("match_conf", sa.Float(), nullable=False),
        sa.Column("confirmed_by_user", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["detection_id"],
            ["detections.id"],
            name=op.f("fk_detection_individual_detection_id_detections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["individual_id"],
            ["individuals.id"],
            name=op.f("fk_detection_individual_individual_id_individuals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("detection_id", "individual_id", name=op.f("pk_detection_individual")),
    )
    op.create_table(
        "forecast_outcomes",
        sa.Column("forecast_id", sa.UUID(), nullable=False),
        sa.Column("occurred", sa.Boolean(), nullable=True),
        sa.Column("actual_count", sa.Integer(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["forecast_id"],
            ["forecasts.id"],
            name=op.f("fk_forecast_outcomes_forecast_id_forecasts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("forecast_id", name=op.f("pk_forecast_outcomes")),
    )


def downgrade() -> None:
    for table in (
        "forecast_outcomes",
        "detection_individual",
        "forecasts",
        "detections",
        "sync_log",
        "stands",
        "images",
        "env_snapshots",
        "users",
        "individuals",
        "correlations",
        "cameras",
        "species",
        "model_runs",
        "estates",
    ):
        op.drop_table(table)
