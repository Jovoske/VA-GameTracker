"""notifications — per-user animal preferences, Web Push subscriptions, sent log

Revision ID: 0012_notifications
Revises: 0011_terrain
Create Date: 2026-09-16

Purely additive, and re-entrant under the create_all convention (a fresh database
already has these tables from 0001). Four tables:

    app_settings        server-generated state (VAPID key pair, dispatch watermark)
    notification_prefs  which animals each user wants to hear about
    push_subscriptions  each device's Web Push endpoint, owned by a user
    notifications       what was sent, so the app can show it and a person can tell a
                        quiet night from a broken subscription
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_notifications"
down_revision = "0011_terrain"
branch_labels = None
depends_on = None


def _exists(conn, table: str) -> bool:
    return bool(conn.exec_driver_sql(f"SELECT to_regclass('public.{table}')").scalar())


def upgrade() -> None:
    conn = op.get_bind()

    if not _exists(conn, "app_settings"):
        op.create_table(
            "app_settings",
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
            ),
            sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
        )

    if not _exists(conn, "notification_prefs"):
        op.create_table(
            "notification_prefs",
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("species_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
            ),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"],
                name=op.f("fk_notification_prefs_user_id_users"), ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notification_prefs")),
        )

    if not _exists(conn, "push_subscriptions"):
        op.create_table(
            "push_subscriptions",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("endpoint", sa.Text(), nullable=False),
            sa.Column("p256dh", sa.String(), nullable=False),
            sa.Column("auth", sa.String(), nullable=False),
            sa.Column("user_agent", sa.String(), nullable=True),
            sa.Column("failures", sa.Integer(), nullable=False),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
            ),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"],
                name=op.f("fk_push_subscriptions_user_id_users"), ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_push_subscriptions")),
            sa.UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
        )
        op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"], unique=False)

    if not _exists(conn, "notifications"):
        op.create_table(
            "notifications",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("url", sa.String(), nullable=True),
            sa.Column("species_id", sa.String(), nullable=True),
            sa.Column("image_id", sa.UUID(), nullable=True),
            sa.Column("push_status", sa.String(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
            ),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"],
                name=op.f("fk_notifications_user_id_users"), ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["species_id"], ["species.id"], name=op.f("fk_notifications_species_id_species"),
            ),
            sa.ForeignKeyConstraint(
                ["image_id"], ["images.id"],
                name=op.f("fk_notifications_image_id_images"), ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        )
        op.create_index(
            "ix_notifications_user_created", "notifications", ["user_id", "created_at"], unique=False
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notifications")
    op.execute("DROP TABLE IF EXISTS push_subscriptions")
    op.execute("DROP TABLE IF EXISTS notification_prefs")
    op.execute("DROP TABLE IF EXISTS app_settings")
