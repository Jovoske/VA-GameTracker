"""sit reports that are never lost or overwritten, one live reservation per stand

Revision ID: 0023_sit_reports
Revises: 0021_client_errors
Create Date: 2026-09-27

- sits.reported_at: the phone's time of the report the server kept. A tap saved
  with no signal can arrive an hour late, after a newer one or after the hunter
  corrected it on Stands; anything older than this is ignored. Existing sits keep
  NULL, which lets their next report through.
- One live reservation per stand and night: a partial unique index on
  sits (stand_id, night) where the sit is not cancelled. It backs up the per-night
  lock taken when a stand is reserved; the lock is what also keeps crossing fire
  lanes apart, which no index can express.
- Before the index can exist, two live reservations of one stand on one night
  (possible before the lock) become one. The sit kept is the one somebody used: a
  report first, then a started sit, then the first reservation. The others are
  cancelled, and what they said is kept in their notes, so nothing is lost.

A no-op on fresh installs, where 0001's create_all() builds both from the models.
"""
from alembic import op

revision = "0023_sit_reports"
down_revision = "0021_client_errors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sits ADD COLUMN IF NOT EXISTS reported_at timestamptz")
    op.execute("""
        WITH ranked AS (
            SELECT id, first_value(id) OVER (
                PARTITION BY stand_id, night
                ORDER BY (outcome <> 'unreported') DESC, (started_at IS NOT NULL) DESC,
                         claimed_at, id
            ) AS keeper
            FROM sits WHERE outcome <> 'cancelled'
        )
        UPDATE sits s SET
            notes = concat_ws(E'\\n', s.notes,
                'Cancelled by the upgrade: a second reservation of this stand that night. '
                || CASE s.outcome WHEN 'unreported' THEN 'Nothing was reported.'
                   ELSE 'Reported: ' || replace(s.outcome, '_', ' ') || '.' END),
            outcome = 'cancelled'
        FROM ranked r WHERE s.id = r.id AND r.id <> r.keeper
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_sits_stand_night_live "
        "ON sits (stand_id, night) WHERE outcome <> 'cancelled'"
    )


def downgrade() -> None:
    # The sits cancelled on the way up stay cancelled: their notes say what they were.
    op.execute("DROP INDEX IF EXISTS uq_sits_stand_night_live")
    op.execute("ALTER TABLE sits DROP COLUMN IF EXISTS reported_at")
