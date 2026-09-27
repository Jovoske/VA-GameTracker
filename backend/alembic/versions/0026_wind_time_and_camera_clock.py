"""sits: the moment a reservation's wind verdict is for; cameras: a clock put right;
images: when an FTP or email photo arrived

Revision ID: 0026_wind_time_and_camera_clock
Revises: 0025_species_fixes
Create Date: 2026-09-27

- sits.wind_at: the moment the wind verdict saved with a reservation was judged for
  (45 minutes after sunset, or the time of the reservation after dark), so Sit mode
  and Stands can say "for 20:41, as forecast when you reserved". NULL for sits
  reserved before this: their verdict was the 22:00 forecast, and they say so by
  saying nothing.
- cameras.clock_ahead_min: a Suntek camera whose clock ran a whole number of hours
  ahead of the server's receipt (it missed the 25 Oct clock change) has its photo
  times put right on import; this keeps how far, for the camera card. NULL until a
  photo has been checked.
- cameras.clock_ok_photos: photos in a row on time since that clock was found fast;
  the warning goes only after a few, so one late upload can't switch it off.
- images.received_at: when the server got an FTP or email photo, so the Cameras
  page can say how long a camera's photos take to arrive (a slow clock shows as an
  hour's wait). NULL for photos stored before this, and for SPYPOINT and UBox.

A no-op on fresh installs, where 0001's create_all() builds both from the models.
"""
from alembic import op

revision = "0026_wind_time_and_camera_clock"
down_revision = "0025_species_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sits ADD COLUMN IF NOT EXISTS wind_at timestamptz")
    op.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS clock_ahead_min integer")
    op.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS clock_ok_photos integer")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS received_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS received_at")
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS clock_ok_photos")
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS clock_ahead_min")
    op.execute("ALTER TABLE sits DROP COLUMN IF EXISTS wind_at")
