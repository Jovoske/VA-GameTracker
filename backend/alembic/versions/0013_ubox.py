"""UBox accounts, device/event identity and import volume controls.

Revision ID: 0013_ubox
Revises: 0012_notifications
Create Date: 2026-09-16

0001 creates the current ORM schema, so every operation also tolerates a fresh
database that already has these columns and constraints. Existing provider logins
retain their credentials and default to SPYPOINT.
"""
import sqlalchemy as sa

from alembic import op

revision = "0013_ubox"
down_revision = "0012_notifications"
branch_labels = None
depends_on = None


def _ensure_unique(table: str, columns: list[str], name: str) -> None:
    constraints = sa.inspect(op.get_bind()).get_unique_constraints(table)
    if not any(c["column_names"] == columns for c in constraints):
        op.create_unique_constraint(op.f(name), table, columns)


def _ensure_check(table: str, name: str, condition: str) -> None:
    constraints = sa.inspect(op.get_bind()).get_check_constraints(table)
    if not any(c["name"] == name for c in constraints):
        op.create_check_constraint(op.f(name), table, condition)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE camera_accounts ADD COLUMN IF NOT EXISTS "
        "provider varchar NOT NULL DEFAULT 'spypoint'"
    )
    op.execute(
        "ALTER TABLE camera_accounts ADD COLUMN IF NOT EXISTS "
        "ubox_min_interval_seconds integer NOT NULL DEFAULT 60"
    )
    op.execute(
        "ALTER TABLE camera_accounts ADD COLUMN IF NOT EXISTS "
        "ubox_max_images_per_day integer NOT NULL DEFAULT 500"
    )
    op.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS ubox_uid varchar")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS ubox_event_id varchar")
    op.execute("ALTER TABLE sync_log ADD COLUMN IF NOT EXISTS details jsonb")

    _ensure_check(
        "camera_accounts", "ck_camera_accounts_provider_valid",
        "provider IN ('spypoint','ubox')",
    )
    _ensure_check(
        "camera_accounts", "ck_camera_accounts_ubox_interval_valid",
        "ubox_min_interval_seconds BETWEEN 10 AND 3600",
    )
    _ensure_check(
        "camera_accounts", "ck_camera_accounts_ubox_daily_limit_valid",
        "ubox_max_images_per_day BETWEEN 1 AND 5000",
    )
    _ensure_check(
        "cameras", "ck_cameras_provider_exclusive",
        "spypoint_id IS NULL OR ubox_uid IS NULL",
    )
    _ensure_unique("cameras", ["ubox_uid"], "uq_cameras_ubox_uid")
    _ensure_unique("images", ["ubox_event_id"], "uq_images_ubox_event_id")
    _ensure_unique(
        "camera_accounts", ["provider", "username"], "uq_camera_accounts_provider_username"
    )
    # 0006's raw SQL used PostgreSQL's default name; create_all used our naming
    # convention. Discover either name so deployed and fresh installs agree.
    for constraint in sa.inspect(op.get_bind()).get_unique_constraints("camera_accounts"):
        if constraint["column_names"] == ["username"]:
            op.drop_constraint(op.f(constraint["name"]), "camera_accounts", type_="unique")


def downgrade() -> None:
    # Restore the previous invariant first. If the same email is now connected to
    # both providers this fails atomically, instead of deleting either account.
    _ensure_unique("camera_accounts", ["username"], "uq_camera_accounts_username")
    op.execute(
        "ALTER TABLE camera_accounts DROP CONSTRAINT IF EXISTS "
        "uq_camera_accounts_provider_username"
    )
    op.execute("ALTER TABLE sync_log DROP COLUMN IF EXISTS details")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS ubox_event_id")
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS ubox_uid")
    op.execute("ALTER TABLE camera_accounts DROP COLUMN IF EXISTS ubox_max_images_per_day")
    op.execute("ALTER TABLE camera_accounts DROP COLUMN IF EXISTS ubox_min_interval_seconds")
    op.execute("ALTER TABLE camera_accounts DROP COLUMN IF EXISTS provider")
