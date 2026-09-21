"""add species.hidden: animals kept out of the app altogether

Revision ID: 0016_species_hidden
Revises: 0015_spypoint_local_time
Create Date: 2026-09-21

huntable only keeps a species out of the advice; its photos and counts still show
everywhere. hidden removes it from photos, counts, alerts and advice (a hidden
species is also switched out of advice and out of every alert list). ADD COLUMN IF
NOT EXISTS keeps this a no-op on fresh installs, where 0001's create_all() builds
the column from the current model.
"""
from alembic import op

revision = "0016_species_hidden"
down_revision = "0015_spypoint_local_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE species ADD COLUMN IF NOT EXISTS hidden boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE species DROP COLUMN IF EXISTS hidden")
