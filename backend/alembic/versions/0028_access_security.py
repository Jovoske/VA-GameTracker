"""access and security: removing a person just works, sessions can be ended

Revision ID: 0028_access_security
Revises: 0027_camera_location_custom
Create Date: 2026-09-27

- users.token_version: every sign-in token carries it, and one made under an older
  version is refused. A password change moves it on, which signs the lost phone out
  (audit D-07). Existing tokens carry none, which reads as 0, so nobody is signed out
  by this upgrade.
- camera_accounts.former_owner: the email of whoever added a login, kept when that
  person is removed. The login keeps fetching; the admin owns it (owner decision).
- sits.user_id, zones.created_by and camera_accounts.owner_user_id: ON DELETE SET
  NULL. Removing a person who had ever reserved a stand, drawn an area or added a
  camera login failed with a 500 (audit D-05, H-01, I-12). Their sits and areas stay.

The foreign keys are found by what they join, not by name: production built these
tables with raw SQL (0006, 0010), so they carry Postgres' default names
(camera_accounts_owner_user_id_fkey), where a fresh install has this project's
(fk_camera_accounts_owner_user_id_users). A key already SET NULL is left alone, so
this is a no-op on fresh installs, where 0001's create_all() builds today's models.
"""
from sqlalchemy import text

from alembic import op

revision = "0028_access_security"
down_revision = "0027_camera_location_custom"
branch_labels = None
depends_on = None

# (table, column): the references to users that must not stop a removal.
_KEYS = (("sits", "user_id"), ("zones", "created_by"), ("camera_accounts", "owner_user_id"))


def _user_keys(bind, table: str, column: str) -> list[tuple[str, str]]:
    """[(name, on-delete code)] of the foreign keys from table.column to users."""
    return [tuple(r) for r in bind.execute(text(
        "SELECT c.conname, c.confdeltype FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
        "WHERE c.contype = 'f' AND c.conrelid = to_regclass(:t) "
        "AND c.confrelid = to_regclass('users') AND a.attname = :c "
        "AND array_length(c.conkey, 1) = 1"
    ), {"t": table, "c": column}).all()]


def _repoint(bind, on_delete: str) -> None:
    """Make each key's ON DELETE `on_delete` ('SET NULL', or '' for none)."""
    want = "n" if on_delete else "a"  # pg_constraint.confdeltype: SET NULL / NO ACTION
    for table, column in _KEYS:
        keys = _user_keys(bind, table, column)
        if any(code == want for _, code in keys):
            continue
        for name, _ in keys:
            op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{name}"')
        rule = f" ON DELETE {on_delete}" if on_delete else ""
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_{column}_users "
            f"FOREIGN KEY ({column}) REFERENCES users (id){rule}"
        )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE camera_accounts ADD COLUMN IF NOT EXISTS former_owner VARCHAR")
    _repoint(op.get_bind(), "SET NULL")


def downgrade() -> None:
    # Back to keys that refuse a removal, as before. Sits, areas and logins stay; a
    # row whose person was removed meanwhile keeps its empty user, which is allowed.
    _repoint(op.get_bind(), "")
    op.execute("ALTER TABLE camera_accounts DROP COLUMN IF EXISTS former_owner")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS token_version")
