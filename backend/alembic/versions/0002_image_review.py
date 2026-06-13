"""add animal_conf + reviewed to images

Revision ID: 0002_image_review
Revises: 0001_initial
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_image_review"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Max MegaDetector animal confidence per frame → lets us re-threshold without re-scanning.
    op.add_column("images", sa.Column("animal_conf", sa.Float(), nullable=True))
    # User has manually confirmed/overridden empty-vs-animal → auto-scan won't touch it.
    op.add_column(
        "images",
        sa.Column("reviewed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("images", "reviewed")
    op.drop_column("images", "animal_conf")
