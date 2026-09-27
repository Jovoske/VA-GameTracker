"""images (camera_id, created_at) index for the map's "new" count

Revision ID: 0018_image_arrivals
Revises: 0017_camera_views
Create Date: 2026-09-26

The map's count of photos new to you reads each camera's newest arrival and what
arrived after the one you had seen. Without an index on arrival time that walked
every photo the camera ever took, on every map load.

A no-op on fresh installs, where 0001's create_all() builds it from the models.
"""
from alembic import op

revision = "0018_image_arrivals"
down_revision = "0017_camera_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_images_camera_created ON images (camera_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_images_camera_created")
