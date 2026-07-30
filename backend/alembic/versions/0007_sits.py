"""stand claims and sit outcomes

Revision ID: 0007_sits
Revises: 0006_camera_nights
Create Date: 2026-07-29

Purely additive. `stands` already existed as dead schema and is finally given a
write path; this adds the register of who claimed what, and what came of it.
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_sits"
down_revision = "0006_camera_nights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.exec_driver_sql("SELECT to_regclass('public.sits')").scalar():
        return  # re-entrant

    op.create_table(
        "sits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("stand_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("night", sa.Date(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("species_seen", sa.String(), nullable=True),
        sa.Column("wind_status", sa.String(), nullable=True),
        sa.Column("wind_text", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "outcome IN ('unreported','nothing','seen','shootable_no_shot','shot','cancelled')",
            name=op.f("ck_sits_outcome_valid"),
        ),
        sa.ForeignKeyConstraint(["stand_id"], ["stands.id"], name=op.f("fk_sits_stand_id_stands")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_sits_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sits")),
    )
    op.create_index("ix_sits_night", "sits", ["night"], unique=False)
    op.create_index("ix_sits_stand_night", "sits", ["stand_id", "night"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_sits_stand_night", table_name="sits")
    op.drop_index("ix_sits_night", table_name="sits")
    op.drop_table("sits")
