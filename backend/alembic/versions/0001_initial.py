"""initial schema — extensions + all tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-13
"""
from alembic import op

import app.models  # noqa: F401  (populate metadata)
from app.core.db import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
