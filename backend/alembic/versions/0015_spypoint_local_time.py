"""Re-read stored SPYPOINT capture times as camera wall clock, not UTC.

Revision ID: 0015_spypoint_local_time
Revises: 0014_camera_names
Create Date: 2026-09-19

SPYPOINT reports ``originDate`` as the camera's own clock with a ``Z`` stapled on,
and the importer took that ``Z`` literally, so every SPYPOINT photo was stored
ahead of its true instant by the estate's UTC offset (a 10:30 stamp displayed as
12:30 in summer). The importer now reads those values as wall times in the
estate timezone; this revision applies the same correction to the rows already
imported, and to the environment snapshots keyed to them, so the gallery,
notifications and hour patterns agree with the stamp printed on the photo.

A shift is not naturally idempotent, so a marker in app_settings records that it
ran; a second execution (or a fresh database, which has nothing to shift) is a
no-op. FTP and UBox imports already carry real instants and are left alone.
"""
import json

import sqlalchemy as sa

from alembic import op
from app.core.config import settings

revision = "0015_spypoint_local_time"
down_revision = "0014_camera_names"
branch_labels = None
depends_on = None

MARKER = "spypoint_capture_times_localized"

# ``timestamptz AT TIME ZONE 'UTC'`` yields the stored wall clock as a naive value;
# ``naive AT TIME ZONE <zone>`` reads that wall clock in <zone> and returns the real
# instant. Reversed for downgrade.
TO_INSTANT = "((%s AT TIME ZONE 'UTC') AT TIME ZONE :tz)"
TO_WALL = "((%s AT TIME ZONE :tz) AT TIME ZONE 'UTC')"


def _marked(conn) -> bool:
    return conn.execute(
        sa.text("SELECT 1 FROM app_settings WHERE key = :k"), {"k": MARKER}
    ).first() is not None


def _shift(conn, expr: str) -> None:
    tz = {"tz": settings.estate_timezone}
    # Snapshots are matched to their image by (camera, instant); keep that link.
    # A snapshot whose corrected time is already taken (only possible across a DST
    # change) is dropped rather than violating uq_env_camera_time.
    conn.execute(sa.text(
        "DELETE FROM env_snapshots e USING images i "
        "WHERE i.camera_id = e.camera_id AND i.captured_at = e.observed_at "
        "AND i.spypoint_photo_id IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM env_snapshots x WHERE x.camera_id = e.camera_id "
        f"AND x.observed_at = {expr % 'e.observed_at'})"
    ), tz)
    conn.execute(sa.text(
        f"UPDATE env_snapshots e SET observed_at = {expr % 'e.observed_at'} "
        "FROM images i "
        "WHERE i.camera_id = e.camera_id AND i.captured_at = e.observed_at "
        "AND i.spypoint_photo_id IS NOT NULL"
    ), tz)
    conn.execute(sa.text(
        f"UPDATE images SET captured_at = {expr % 'captured_at'} "
        "WHERE spypoint_photo_id IS NOT NULL"
    ), tz)


def upgrade() -> None:
    conn = op.get_bind()
    if _marked(conn):
        return
    _shift(conn, TO_INSTANT)
    conn.execute(sa.text(
        "INSERT INTO app_settings (key, value) VALUES (:k, CAST(:v AS jsonb))"
    ), {"k": MARKER, "v": json.dumps({"timezone": settings.estate_timezone})})


def downgrade() -> None:
    conn = op.get_bind()
    if not _marked(conn):
        return
    _shift(conn, TO_WALL)
    conn.execute(sa.text("DELETE FROM app_settings WHERE key = :k"), {"k": MARKER})
