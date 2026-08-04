"""track cloud-vision sex attempts so ambiguous crops aren't re-billed forever

Revision ID: 0007_sex_attempts
Revises: 0006_camera_accounts
Create Date: 2026-07-28

The sex pass only stored a result when the model committed to male/female. Crops it
couldn't judge (deliberately conservative on night IR) stayed sex='unknown' and were
re-sent on every hourly run — thousands of paid API calls re-asking a settled question.
Recording the attempt makes the pass converge.
"""
from alembic import op

revision = "0007_sex_attempts"
down_revision = "0006_camera_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE detections ADD COLUMN IF NOT EXISTS sex_checked_at timestamptz")
    op.execute("ALTER TABLE detections ADD COLUMN IF NOT EXISTS sex_attempts integer NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE detections DROP COLUMN IF EXISTS sex_attempts")
    op.execute("ALTER TABLE detections DROP COLUMN IF EXISTS sex_checked_at")
