"""camera login status, gap-free SPYPOINT paging, retried downloads, one copy per login

Revision ID: 0020_camera_login_status
Revises: 0019_camera_alerts_photo_notes
Create Date: 2026-09-27

- camera_accounts gets what a fetch learnt about the login (last_attempt_at,
  last_ok_at, last_error in hunter words, reported_cameras), so Settings and the
  camera cards can say "SPYPOINT refused the password" instead of staying green.
- camera_accounts.session_enc: the provider's sign-in token, encrypted, kept between
  fetches so a login is not signed in afresh every 15 minutes.
- cameras.photos_listed_to: how far back a SPYPOINT camera's photos have all been
  listed, so a routine fetch pages back to it instead of reading only the newest 100.
  Left empty here: the first fetch after the upgrade pages back to the newest photo
  already stored instead.
- cameras.photos_gap_from / photos_gap_to: a stretch a fetch cut short by its page
  cap has not listed yet, which later fetches page on through.
- cameras.fetch_error: why the last fetch could not list the camera's photos although
  its login worked.
- cameras.import_failures: UBox snapshots that would not download, retried a few
  times and then given up on.
- images.download_attempts: a SPYPOINT photo whose file failed to download is
  retried on later fetches, up to a cap.
- A login is one login whatever the case of its email: a later active copy of the
  same provider login is switched off (its cameras move to the first copy, their
  photos untouched) and a partial unique index keeps it that way.
- A UBox camera whose login was removed (UBox always links its login) is switched
  off, so it stops being reported as a flat battery.

A no-op on fresh installs, where 0001's create_all() builds all of it from the models.
"""
from alembic import op

revision = "0020_camera_login_status"
down_revision = "0019_camera_alerts_photo_notes"
branch_labels = None
depends_on = None

_DUPLICATES = """
    WITH ranked AS (
        SELECT id, first_value(id) OVER (
            PARTITION BY provider, lower(username) ORDER BY created_at, id
        ) AS keeper
        FROM camera_accounts WHERE active
    )
"""


def upgrade() -> None:
    for column in (
        "last_attempt_at timestamptz", "last_ok_at timestamptz", "last_error text",
        "reported_cameras integer", "session_enc text",
    ):
        op.execute(f"ALTER TABLE camera_accounts ADD COLUMN IF NOT EXISTS {column}")
    for column in (
        "photos_listed_to timestamptz", "photos_gap_from timestamptz",
        "photos_gap_to timestamptz", "fetch_error text",
    ):
        op.execute(f"ALTER TABLE cameras ADD COLUMN IF NOT EXISTS {column}")
    op.execute(
        "ALTER TABLE cameras "
        "ADD COLUMN IF NOT EXISTS import_failures jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE images ADD COLUMN IF NOT EXISTS download_attempts integer NOT NULL DEFAULT 0"
    )
    op.execute(_DUPLICATES + """
        UPDATE cameras c SET account_id = r.keeper
        FROM ranked r WHERE c.account_id = r.id AND r.id <> r.keeper
    """)
    op.execute(_DUPLICATES + """
        UPDATE camera_accounts a SET active = false
        FROM ranked r WHERE a.id = r.id AND r.id <> r.keeper
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_camera_accounts_provider_login "
        "ON camera_accounts (provider, lower(username)) WHERE active"
    )
    op.execute(
        "UPDATE cameras SET active = false "
        "WHERE ubox_uid IS NOT NULL AND account_id IS NULL AND active"
    )


def downgrade() -> None:
    # Logins and cameras switched off above stay off: which were on is not recorded.
    op.execute("DROP INDEX IF EXISTS uq_camera_accounts_provider_login")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS download_attempts")
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS import_failures")
    for column in ("fetch_error", "photos_gap_to", "photos_gap_from", "photos_listed_to"):
        op.execute(f"ALTER TABLE cameras DROP COLUMN IF EXISTS {column}")
    for column in (
        "session_enc", "reported_cameras", "last_error", "last_ok_at", "last_attempt_at",
    ):
        op.execute(f"ALTER TABLE camera_accounts DROP COLUMN IF EXISTS {column}")
