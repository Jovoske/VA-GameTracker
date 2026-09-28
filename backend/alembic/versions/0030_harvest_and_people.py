"""the harvest book, and people and vehicles on camera

Revision ID: 0030_harvest_and_people
Revises: 0029_quiet_alerts_and_plan_push
Create Date: 2026-09-27

- harvests: one line per animal taken (feature 23): the sit it came from (optional),
  its stand, who shot it and the name the record carries, species, sex, age class,
  the seal (precinto) number, weight, notes, and when. Removing a person or a stand
  keeps the line (the keys go NULL); a species can't be removed while a line names it.
- sits.no_harvest_at: a SHOT that left nothing to log (a miss, or not found), so the
  morning card stops asking.
- images.person_conf / vehicle_conf: MegaDetector's surest person and vehicle box
  (feature 25), NULL until the detector has looked for them; images.people_cleared:
  an admin said nobody is in it. Existing photos keep NULL: the AI pass looks at the
  last month's again in daylight hours (app.ai.checking), a few at a time.

Existing rows keep what they were. A no-op on fresh installs, where 0001's
create_all() builds all of it from the models.
"""
import sqlalchemy as sa

from alembic import op

revision = "0030_harvest_and_people"
down_revision = "0029_quiet_alerts_and_plan_push"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS person_conf DOUBLE PRECISION")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS vehicle_conf DOUBLE PRECISION")
    op.execute(
        "ALTER TABLE images ADD COLUMN IF NOT EXISTS people_cleared BOOLEAN NOT NULL "
        "DEFAULT false"
    )
    op.execute("ALTER TABLE sits ADD COLUMN IF NOT EXISTS no_harvest_at TIMESTAMPTZ")
    conn = op.get_bind()
    if not conn.exec_driver_sql("SELECT to_regclass('public.harvests')").scalar():
        op.create_table(
            "harvests",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("sit_id", sa.UUID(), nullable=True),
            sa.Column("stand_id", sa.UUID(), nullable=True),
            sa.Column("user_id", sa.UUID(), nullable=True),
            sa.Column("hunter", sa.String(length=60), nullable=False),
            sa.Column("species_id", sa.String(), nullable=False),
            sa.Column("sex", sa.String(), server_default=sa.text("'unknown'"), nullable=False),
            sa.Column(
                "age_class", sa.String(), server_default=sa.text("'unknown'"), nullable=False
            ),
            sa.Column("seal", sa.String(length=40), nullable=True),
            sa.Column("weight_kg", sa.Float(), nullable=True),
            sa.Column("notes", sa.String(length=500), nullable=True),
            sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.UUID(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.CheckConstraint(
                "sex IN ('male','female','unknown')", name=op.f("ck_harvests_sex_valid")
            ),
            sa.CheckConstraint(
                "age_class IN ('juvenile','young_adult','mature_adult','old','unknown')",
                name=op.f("ck_harvests_age_valid"),
            ),
            sa.CheckConstraint(
                "weight_kg IS NULL OR (weight_kg > 0 AND weight_kg < 1000)",
                name=op.f("ck_harvests_weight_valid"),
            ),
            sa.ForeignKeyConstraint(
                ["sit_id"], ["sits.id"], name=op.f("fk_harvests_sit_id_sits"),
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["stand_id"], ["stands.id"], name=op.f("fk_harvests_stand_id_stands"),
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"], name=op.f("fk_harvests_user_id_users"),
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["created_by"], ["users.id"], name=op.f("fk_harvests_created_by_users"),
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["species_id"], ["species.id"], name=op.f("fk_harvests_species_id_species"),
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_harvests")),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_harvests_taken_at ON harvests (taken_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_harvests_sit_id ON harvests (sit_id)")


def downgrade() -> None:
    # The harvest book goes with its table: export the season first (Settings).
    op.execute("DROP TABLE IF EXISTS harvests")
    op.execute("ALTER TABLE sits DROP COLUMN IF EXISTS no_harvest_at")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS people_cleared")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS vehicle_conf")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS person_conf")
