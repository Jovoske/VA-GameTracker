"""Nordic Gamekeeper accounts and stable camera/photo identities.

Revision ID: 0035_nordic_gamekeeper
Revises: 0034_constraint_names

0001 creates the current ORM schema, so fresh installs and repeated upgrades must
also tolerate these columns and constraints already being present.
"""
import sqlalchemy as sa

from alembic import op

revision = "0035_nordic_gamekeeper"
down_revision = "0034_constraint_names"
branch_labels = None
depends_on = None


def _ensure_unique(table: str, column: str) -> None:
    constraints = sa.inspect(op.get_bind()).get_unique_constraints(table)
    if not any(c["column_names"] == [column] for c in constraints):
        op.create_unique_constraint(op.f(f"uq_{table}_{column}"), table, [column])


def _check(table: str, name: str, condition: str) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.create_check_constraint(op.f(name), table, condition)


def upgrade() -> None:
    op.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS nordic_id varchar")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS nordic_photo_id varchar")
    _ensure_unique("cameras", "nordic_id")
    _ensure_unique("images", "nordic_photo_id")
    _check("camera_accounts", "ck_camera_accounts_provider_valid",
           "provider IN ('spypoint','ubox','nordic')")
    _check("cameras", "ck_cameras_provider_exclusive",
           "(spypoint_id IS NULL OR ubox_uid IS NULL) AND "
           "(spypoint_id IS NULL OR nordic_id IS NULL) AND "
           "(ubox_uid IS NULL OR nordic_id IS NULL)")


def downgrade() -> None:
    # If Nordic accounts remain, fail atomically rather than deleting their logins.
    _check("camera_accounts", "ck_camera_accounts_provider_valid",
           "provider IN ('spypoint','ubox')")
    _check("cameras", "ck_cameras_provider_exclusive",
           "spypoint_id IS NULL OR ubox_uid IS NULL")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS nordic_photo_id")
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS nordic_id")
