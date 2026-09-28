"""constraint names: an upgraded server names its keys as a fresh install does

Revision ID: 0034_constraint_names
Revises: 0033_user_language
Create Date: 2026-09-28

- detections.corrected_by's foreign key: 0025 added it with a bare REFERENCES, so
  a server upgraded through 0025 has Postgres' own name for it
  (detections_corrected_by_fkey), where a fresh install has this project's
  (fk_detections_corrected_by_users). Alembic doesn't compare key names, so nothing
  noticed, but a later migration that drops the key by the models' name would
  silently miss it on the server. It is renamed; what it does doesn't change.

A no-op on fresh installs, and on a server whose key already has the models' name.
"""
from alembic import op

revision = "0034_constraint_names"
down_revision = "0033_user_language"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = 'detections_corrected_by_fkey'
                         AND conrelid = 'detections'::regclass)
               AND NOT EXISTS (SELECT 1 FROM pg_constraint
                               WHERE conname = 'fk_detections_corrected_by_users') THEN
                ALTER TABLE detections RENAME CONSTRAINT detections_corrected_by_fkey
                    TO fk_detections_corrected_by_users;
            END IF;
        END $$
    """)


def downgrade() -> None:
    # The models' name is right for every revision; nothing to put back.
    pass
