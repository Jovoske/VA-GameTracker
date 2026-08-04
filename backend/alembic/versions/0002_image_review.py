"""add animal_conf + reviewed to images

Revision ID: 0002_image_review
Revises: 0001_initial
Create Date: 2026-06-13

On the native build, 0001 runs Base.metadata.create_all() against the *current* ORM
metadata, so the images table is already created with animal_conf and reviewed. This
migration therefore has nothing to add on a fresh database and is a no-op kept only to
preserve alembic history (same treatment as 0003).
"""

revision = "0002_image_review"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass  # no-op: columns are created by 0001's create_all()


def downgrade() -> None:
    pass  # no-op
