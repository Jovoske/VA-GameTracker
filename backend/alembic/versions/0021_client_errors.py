"""client_errors: what broke on hunters' phones

Revision ID: 0021_client_errors
Revises: 0019_camera_alerts_photo_notes
Create Date: 2026-09-27

The app posts a crash or a blank screen to /api/client-errors and admins read the
newest few in Settings, with when it happened on the phone (happened_at) as well as
when it arrived. One small table, newest 200 rows kept by the endpoint
itself. A no-op on fresh installs, where 0001's create_all() builds it from the
current models.
"""
import sqlalchemy as sa

from alembic import op

revision = "0021_client_errors"
down_revision = "0019_camera_alerts_photo_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if not conn.exec_driver_sql("SELECT to_regclass('public.client_errors')").scalar():
        op.create_table(
            "client_errors",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=True),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("message", sa.String(length=500), nullable=False),
            sa.Column("stack", sa.Text(), nullable=True),
            sa.Column("route", sa.String(length=200), nullable=True),
            sa.Column("build", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=300), nullable=True),
            sa.Column("happened_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"],
                name=op.f("fk_client_errors_user_id_users"), ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_client_errors")),
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_errors_created_at ON client_errors (created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS client_errors")
