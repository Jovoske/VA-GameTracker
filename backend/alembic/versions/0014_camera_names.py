"""Preserve imported camera names alongside estate-specific display names.

Revision ID: 0014_camera_names
Revises: 0013_ubox
Create Date: 2026-09-16

The current-ORM create_all convention means fresh databases already contain the
columns. Existing cameras retain their exact names, identities and photo history.
"""
from alembic import op

revision = "0014_camera_names"
down_revision = "0013_ubox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS provider_name varchar")
    op.execute(
        "ALTER TABLE cameras ADD COLUMN IF NOT EXISTS "
        "name_is_custom boolean NOT NULL DEFAULT false"
    )
    op.execute("UPDATE cameras SET provider_name = name WHERE provider_name IS NULL")


def downgrade() -> None:
    # The effective name remains in cameras.name even when the extra fields go away.
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS name_is_custom")
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS provider_name")
