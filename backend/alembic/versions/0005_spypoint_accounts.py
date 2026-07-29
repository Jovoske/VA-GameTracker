"""multiple SPYPOINT accounts per estate

Revision ID: 0005_spypoint_accounts
Revises: 0004_reconcile_native
Create Date: 2026-07-29

Cameras on one estate can be split across several SPYPOINT logins. Until now the
credentials lived in two settings and the sync built a single client from them.

Existing setups must survive untouched, so this migration *adopts* whatever is in
SPYPOINT_USERNAME / SPYPOINT_PASSWORD as the first account and attaches every
existing camera to it. Those environment variables keep working exactly as before;
they are now the bootstrap for account #1 rather than the only way to configure one.
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_spypoint_accounts"
down_revision = "0004_reconcile_native"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    already = conn.exec_driver_sql(
        "SELECT to_regclass('public.spypoint_accounts')"
    ).scalar()
    if already:
        # Re-entrant: an operator who stamps backwards and re-upgrades should get a
        # no-op, not a DuplicateTable crash on a live database.
        _adopt_env_account(conn)
        return

    op.create_table(
        "spypoint_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("estate_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_enc", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["estate_id"], ["estates.id"], name=op.f("fk_spypoint_accounts_estate_id_estates")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spypoint_accounts")),
        sa.UniqueConstraint("username", name=op.f("uq_spypoint_accounts_username")),
    )

    op.execute(
        "ALTER TABLE cameras ADD COLUMN IF NOT EXISTS spypoint_account_id UUID "
        "REFERENCES spypoint_accounts(id)"
    )

    # spypoint_id was globally unique; it is now unique *per account*. Relaxing a
    # constraint cannot lose rows. Drop by discovered name so this works whether the
    # constraint came from the frozen 0001 or from the old create_all().
    existing = conn.exec_driver_sql(
        """
        SELECT con.conname FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE rel.relname = 'cameras' AND con.contype = 'u'
          AND pg_get_constraintdef(con.oid) = 'UNIQUE (spypoint_id)'
        """
    ).scalars().all()
    for name in existing:
        op.execute(f'ALTER TABLE cameras DROP CONSTRAINT "{name}"')

    op.execute(
        "ALTER TABLE cameras ADD CONSTRAINT uq_camera_account_spypoint "
        "UNIQUE (spypoint_account_id, spypoint_id)"
    )

    _adopt_env_account(conn)


def _adopt_env_account(conn) -> None:
    """Turn the configured env credentials into account #1, if there is one."""
    from app.core.config import settings
    from app.core.security import encrypt_secret

    username = (settings.spypoint_username or "").strip()
    if not username:
        return  # nothing configured; accounts can be added through the API instead

    estate_id = conn.exec_driver_sql(
        "SELECT id FROM estates ORDER BY created_at LIMIT 1"
    ).scalar()
    if estate_id is None:
        return  # not seeded yet; startup adoption will handle it (see app.seed)

    already = conn.exec_driver_sql(
        "SELECT id FROM spypoint_accounts WHERE username = %(u)s", {"u": username}
    ).scalar()
    if already is not None:
        return

    conn.exec_driver_sql(
        """
        INSERT INTO spypoint_accounts (id, estate_id, label, username, password_enc, active, created_at)
        VALUES (gen_random_uuid(), %(e)s, %(l)s, %(u)s, %(p)s, true, now())
        """,
        {
            "e": estate_id,
            "l": "Main account",
            "u": username,
            "p": encrypt_secret(settings.spypoint_password) if settings.spypoint_password else None,
        },
    )
    # Attach every pre-existing camera to it — they all came from this login.
    conn.exec_driver_sql(
        """
        UPDATE cameras SET spypoint_account_id = (
            SELECT id FROM spypoint_accounts WHERE username = %(u)s
        ) WHERE spypoint_account_id IS NULL
        """,
        {"u": username},
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cameras DROP CONSTRAINT IF EXISTS uq_camera_account_spypoint")
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS spypoint_account_id")
    op.execute(
        "ALTER TABLE cameras ADD CONSTRAINT uq_cameras_spypoint_id UNIQUE (spypoint_id)"
    )
    op.drop_table("spypoint_accounts")
