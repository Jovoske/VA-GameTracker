"""per-camera alerts (notification_prefs.muted_camera_ids) and team notes on photos

Revision ID: 0019_camera_alerts_photo_notes
Revises: 0018_image_arrivals
Create Date: 2026-09-26

Each person can mute a camera (the busy feeder) and keep the rest: a JSON list of
the camera ids they hear nothing from, empty for everyone to start with, so every
camera stays on. photo_notes holds the team's "Worth a look" marks, each with an
optional note of up to 140 characters.

Both are no-ops on fresh installs, where 0001's create_all() builds them from the
current models.
"""
import sqlalchemy as sa

from alembic import op

revision = "0019_camera_alerts_photo_notes"
down_revision = "0018_image_arrivals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE notification_prefs "
        "ADD COLUMN IF NOT EXISTS muted_camera_ids jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
    conn = op.get_bind()
    if not conn.exec_driver_sql("SELECT to_regclass('public.photo_notes')").scalar():
        op.create_table(
            "photo_notes",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("image_id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=True),
            sa.Column("text", sa.String(length=140), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["image_id"], ["images.id"],
                name=op.f("fk_photo_notes_image_id_images"), ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"],
                name=op.f("fk_photo_notes_user_id_users"), ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_photo_notes")),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_photo_notes_image_id ON photo_notes (image_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_photo_notes_created_at ON photo_notes (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS photo_notes")
    op.execute("ALTER TABLE notification_prefs DROP COLUMN IF EXISTS muted_camera_ids")
