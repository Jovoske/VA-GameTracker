"""Per-camera email and FTP inbox configuration and progress."""

from alembic import op

revision = "0036_camera_inboxes"
down_revision = "0035_nordic_gamekeeper"
branch_labels = None
depends_on = None


def _constraints(inboxes):
    providers = "'spypoint','ubox','nordic'" + (",'suntek_email','suntek_ftp'" if inboxes else "")
    op.execute(
        "ALTER TABLE camera_accounts DROP CONSTRAINT IF EXISTS ck_camera_accounts_provider_valid"
    )
    op.create_check_constraint(
        op.f("ck_camera_accounts_provider_valid"), "camera_accounts", f"provider IN ({providers})"
    )
    op.execute(
        "ALTER TABLE camera_accounts DROP CONSTRAINT IF EXISTS uq_camera_accounts_provider_username"
    )
    op.execute("DROP INDEX IF EXISTS uq_camera_accounts_provider_login")
    columns = ["provider", "username"] + (["connection_key"] if inboxes else [])
    op.create_unique_constraint(
        op.f("uq_camera_accounts_provider_username"), "camera_accounts", columns
    )
    extra = ", connection_key" if inboxes else ""
    op.execute(
        f"CREATE UNIQUE INDEX uq_camera_accounts_provider_login ON camera_accounts (provider, "
        f"lower(username){extra}) WHERE active"
    )


def upgrade():
    op.execute(
        "ALTER TABLE camera_accounts ADD COLUMN IF NOT EXISTS connection_key varchar NOT NULL "
        "DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE camera_accounts ADD COLUMN IF NOT EXISTS connection_config jsonb NOT NULL "
        "DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE camera_accounts ADD COLUMN IF NOT EXISTS input_cursor jsonb NOT NULL "
        "DEFAULT '{}'::jsonb"
    )
    _constraints(True)


def downgrade():
    # Refuse atomically while an inbox account remains, preserving photos and credentials.
    _constraints(False)
    for name in ("connection_key", "connection_config", "input_cursor"):
        op.drop_column("camera_accounts", name)
