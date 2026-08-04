"""add species.huntable — which species appear in hunting advice

Revision ID: 0004_species_huntable
Revises: 0003_reid_embedding
Create Date: 2026-07-24

Advice (the Tonight recommendation + outlook) is filtered to huntable species; stats and
tracking still cover every species. ADD COLUMN IF NOT EXISTS keeps this a no-op on fresh
installs, where 0001's create_all() already builds the column from the current model.
"""
from alembic import op

revision = "0004_species_huntable"
down_revision = "0003_reid_embedding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE species ADD COLUMN IF NOT EXISTS huntable boolean NOT NULL DEFAULT true")


def downgrade() -> None:
    op.execute("ALTER TABLE species DROP COLUMN IF EXISTS huntable")
