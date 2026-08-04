"""camera exposure per night

Revision ID: 0008_camera_nights
Revises: 0007_sex_attempts
Create Date: 2026-07-29

Adds the denominator. Purely additive: a new table, no existing column touched.
It is populated by a recompute job, so an empty table after upgrade is expected
and harmless — callers fall back to the old behaviour until it is filled.
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_camera_nights"
down_revision = "0007_sex_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.exec_driver_sql("SELECT to_regclass('public.camera_nights')").scalar():
        return  # re-entrant: stamping backwards and re-upgrading must be a no-op

    op.create_table(
        "camera_nights",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("camera_id", sa.UUID(), nullable=False),
        sa.Column("night", sa.Date(), nullable=False),
        sa.Column("exposure_state", sa.String(), nullable=False),
        sa.Column("frames", sa.Integer(), nullable=False),
        sa.Column("empty_frames", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "exposure_state IN ('CONFIRMED','PRESUMED_UP','UNPROCESSED','UNKNOWN')",
            name=op.f("ck_camera_nights_exposure_state_valid"),
        ),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], name=op.f("fk_camera_nights_camera_id_cameras")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_camera_nights")),
        sa.UniqueConstraint("camera_id", "night", name="uq_camera_night"),
    )
    # Idempotent index creation, matching this project's convention: 0001 runs
    # create_all() against the current ORM, so a fresh database already has anything
    # declared on the models, while an existing database does not.
    op.execute("CREATE INDEX IF NOT EXISTS ix_camera_nights_night ON camera_nights (night)")
    # detections.image_id is the join in essentially every query and was unindexed.
    op.execute("CREATE INDEX IF NOT EXISTS ix_detections_image_id ON detections (image_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_detections_species_image "
        "ON detections (species_id, image_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_images_captured_at ON images (captured_at DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_images_captured_at", table_name="images")
    op.drop_index("ix_detections_species_image", table_name="detections")
    op.drop_index(op.f("ix_detections_image_id"), table_name="detections")
    op.drop_index("ix_camera_nights_night", table_name="camera_nights")
    op.drop_table("camera_nights")
