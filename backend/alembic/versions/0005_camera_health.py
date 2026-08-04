"""add camera health fields (last check-in, photo credits, SD, battery level)

Revision ID: 0005_camera_health
Revises: 0004_species_huntable
Create Date: 2026-07-24

SPYPOINT exposes each camera's last check-in, photo-credit usage and SD/battery detail.
Capturing them lets the app tell "no animals here" apart from "camera is dead / out of
credits". ADD COLUMN IF NOT EXISTS keeps this a no-op on fresh installs.
"""
from alembic import op

revision = "0005_camera_health"
down_revision = "0004_species_huntable"
branch_labels = None
depends_on = None

_COLS = [
    ("last_report_at", "timestamptz"),
    ("battery_level", "varchar"),
    ("sd_used_mb", "integer"),
    ("sd_total_mb", "integer"),
    ("photo_count", "integer"),
    ("photo_limit", "integer"),
    ("plan_name", "varchar"),
    ("cycle_end", "timestamptz"),
]


def upgrade() -> None:
    for name, typ in _COLS:
        op.execute(f"ALTER TABLE cameras ADD COLUMN IF NOT EXISTS {name} {typ}")


def downgrade() -> None:
    for name, _ in _COLS:
        op.execute(f"ALTER TABLE cameras DROP COLUMN IF EXISTS {name}")
