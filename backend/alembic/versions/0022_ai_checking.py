"""images: the AI pass keeps count of its failures; old misreads are put back in line

Revision ID: 0022_ai_checking
Revises: 0021_client_errors
Create Date: 2026-09-27

A detector or species-model failure used to be recorded as "checked, animal kept, no
species", so a broken model read as a watched night with nothing on it and the frame
was retried on every run forever. Now each photo carries how many times checking it
failed (ai_attempts), the last error (ai_error) and, after a few tries, when it was
given up on (ai_failed_at): a given-up photo keeps its night "not checked", never
"watched, nothing seen". detector_conf is the box confidence the detector was run
at, so frames it judged empty at its old 0.25 cut-off can be looked at again.

Data, all bounded and idempotent:
- A photo a hunter flagged before the detector reached it had no processed_at, so its
  night stayed "not checked" for good. It is stamped with its arrival time (not now,
  so it does not turn up as new on the map).
- A photo the detector failed on was stored as "kept" with no confidence and no
  sighting. It goes back to "not checked yet" and is looked at again.
- Red deer called hinds from February to April were judged by a prompt that took
  "no antlers" for a hind while stags have cast. They are sent to be judged again.

A no-op on fresh installs, where 0001's create_all() builds the columns from the
models (and there are no rows to put right).
"""
from alembic import op

revision = "0022_ai_checking"
down_revision = "0021_client_errors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS ai_attempts INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS ai_failed_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS ai_error TEXT")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS detector_conf DOUBLE PRECISION")

    op.execute(
        "UPDATE images SET processed_at = COALESCE(created_at, now()) "
        "WHERE reviewed AND processed_at IS NULL"
    )
    op.execute(
        "UPDATE images SET processed_at = NULL, is_empty_frame = NULL "
        "WHERE reviewed = false AND is_empty_frame = false AND animal_conf IS NULL "
        "AND original_path IS NOT NULL AND processed_at IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM detections d WHERE d.image_id = images.id)"
    )
    op.execute(
        "UPDATE detections d SET sex = 'unknown', sex_conf = NULL, sex_attempts = 0, "
        "sex_checked_at = NULL FROM images i "
        "WHERE d.image_id = i.id AND d.species_id = 'red_deer' AND d.sex = 'female' "
        "AND EXTRACT(MONTH FROM i.captured_at AT TIME ZONE 'Europe/Madrid') IN (2, 3, 4)"
    )


def downgrade() -> None:
    # The data put right above stays put right: none of it is wrong under 0021.
    for column in ("detector_conf", "ai_error", "ai_failed_at", "ai_attempts"):
        op.execute(f"ALTER TABLE images DROP COLUMN IF EXISTS {column}")
