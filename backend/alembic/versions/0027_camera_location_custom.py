"""cameras: a position set by hand wins over the provider's GPS

Revision ID: 0027_camera_location_custom
Revises: 0026_wind_time_and_camera_clock
Create Date: 2026-09-27

- cameras.location_is_custom: someone placed the camera on the map. The SPYPOINT
  sync used to copy the camera's reported position over it every 15 minutes, often a
  cell-tower guess kilometres off, so a hand placement snapped back (audit B-09,
  E-16). A custom position is kept until someone asks for the camera's own again.
- cameras.provider_lat / provider_lon: the last position the provider reported, kept
  apart from the one the map uses, so "Use the camera's own GPS" has one to go back to.

Existing rows: a camera that has a position but no SPYPOINT id can only have been
placed by hand (UBox and FTP cameras report none), so it is marked custom. A SPYPOINT
camera's position may be its own or a hand placement not yet overwritten: it is left
as the provider's, which is how it behaved until now.

A no-op on fresh installs, where 0001's create_all() builds the columns from the
models.
"""
from alembic import op

revision = "0027_camera_location_custom"
down_revision = "0026_wind_time_and_camera_clock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cameras ADD COLUMN IF NOT EXISTS location_is_custom BOOLEAN "
        "NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS provider_lat DOUBLE PRECISION")
    op.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS provider_lon DOUBLE PRECISION")
    op.execute(
        "UPDATE cameras SET location_is_custom = true "
        "WHERE spypoint_id IS NULL AND lat IS NOT NULL AND lon IS NOT NULL "
        "AND NOT location_is_custom"
    )


def downgrade() -> None:
    # The positions the map uses stay; only the flag and the provider's copy go.
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS provider_lon")
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS provider_lat")
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS location_is_custom")
