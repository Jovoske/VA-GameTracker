"""camera_views: when each person last opened each camera; images.thumbnail_path

Revision ID: 0017_camera_views
Revises: 0016_species_hidden
Create Date: 2026-09-26

The map shows each camera's latest photo with a count of the photos that are new to
you, which needs to know when you last opened that camera. One row per person and
camera. images.thumbnail_path records the small WebP the grids and the map use,
made on first request.

Both are no-ops on fresh installs, where 0001's create_all() builds them from the
current models.
"""
import sqlalchemy as sa

from alembic import op

revision = "0017_camera_views"
down_revision = "0016_species_hidden"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if not conn.exec_driver_sql("SELECT to_regclass('public.camera_views')").scalar():
        op.create_table(
            "camera_views",
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("camera_id", sa.UUID(), nullable=False),
            sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"],
                name=op.f("fk_camera_views_user_id_users"), ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["camera_id"], ["cameras.id"],
                name=op.f("fk_camera_views_camera_id_cameras"), ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("user_id", "camera_id", name=op.f("pk_camera_views")),
        )
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS thumbnail_path varchar")


def downgrade() -> None:
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS thumbnail_path")
    op.execute("DROP TABLE IF EXISTS camera_views")
