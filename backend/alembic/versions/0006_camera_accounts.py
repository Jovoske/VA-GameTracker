"""add camera_accounts (extra SPYPOINT logins) + cameras.account_id

Revision ID: 0006_camera_accounts
Revises: 0005_camera_health
Create Date: 2026-07-27

Guests log in with their own GameSense user and can connect their own SPYPOINT account;
the sync pulls every active account's cameras into the estate. IF NOT EXISTS keeps this
a no-op on fresh installs where 0001's create_all() already built it.
"""
from alembic import op

revision = "0006_camera_accounts"
down_revision = "0005_camera_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS camera_accounts (
            id uuid PRIMARY KEY,
            estate_id uuid NOT NULL REFERENCES estates(id),
            owner_user_id uuid REFERENCES users(id),
            label varchar,
            username varchar NOT NULL UNIQUE,
            password_enc varchar NOT NULL,
            active boolean NOT NULL DEFAULT true,
            last_sync_at timestamptz,
            created_at timestamptz DEFAULT now()
        )
        """
    )
    op.execute(
        "ALTER TABLE cameras ADD COLUMN IF NOT EXISTS account_id uuid REFERENCES camera_accounts(id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS account_id")
    op.execute("DROP TABLE IF EXISTS camera_accounts")
