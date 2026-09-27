"""a camera an admin retired stays out of the plan, the alerts and the numbers

Revision ID: 0024_camera_retired
Revises: 0023_sit_reports
Create Date: 2026-09-27

- cameras.retired_at: when an admin retired the camera (taken down, in a drawer).
  Tonight's ranking, the alerts, Insights, the exposure table and the track record
  leave it out; its photos stay in Photos. NULL for every existing camera, so
  nothing changes until somebody retires one.

A no-op on fresh installs, where 0001's create_all() builds it from the models.
"""
from alembic import op

revision = "0024_camera_retired"
down_revision = "0023_sit_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS retired_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS retired_at")
