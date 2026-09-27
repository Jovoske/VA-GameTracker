"""each person's language

Revision ID: 0033_user_language
Revises: 0030_harvest_and_people
Create Date: 2026-09-27

- users.language: the language the app and the server speak to this person, one of
  en, fi, sv, nb, es. Everyone there already is English ('en'), as the app was, until
  they pick another in Settings. Pushes go out in it too (app.i18n).

Existing rows keep what they were. A no-op on fresh installs, where 0001's
create_all() builds it from the models.
"""
from alembic import op

revision = "0033_user_language"
down_revision = "0030_harvest_and_people"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS language VARCHAR NOT NULL DEFAULT 'en'"
    )
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_language_valid")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_language_valid "
        "CHECK (language IN ('en','fi','sv','nb','es'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_language_valid")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS language")
