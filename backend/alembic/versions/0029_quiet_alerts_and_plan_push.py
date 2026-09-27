"""notifications: quiet hours, tonight's plan push, and what each alert counted

Revision ID: 0029_quiet_alerts_and_plan_push
Revises: 0028_access_security
Create Date: 2026-09-27

- notification_prefs.quiet_start / quiet_end: a person's quiet hours on the estate's
  clock. Nothing buzzes inside them; what comes in is sent as one message after.
- notification_prefs.plan_push: opted in to tonight's plan, once a day about two
  hours before sunset (feature 19). Off for everyone until they turn it on.
- notifications.detail: what a sighting alert counted (visits, cameras, first and
  last time), so a second sounder inside two hours updates the banner on the phone
  quietly with the running total instead of buzzing again (audit K-06), and the
  message after a sit or quiet hours adds up what waited (J-21).

Existing rows keep what they were: no quiet hours, no plan push, and old alerts
with no detail (a later update counts from the next one).

A no-op on fresh installs, where 0001's create_all() builds the columns from the
models.
"""
from alembic import op

revision = "0029_quiet_alerts_and_plan_push"
down_revision = "0028_access_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE notification_prefs ADD COLUMN IF NOT EXISTS quiet_start TIME")
    op.execute("ALTER TABLE notification_prefs ADD COLUMN IF NOT EXISTS quiet_end TIME")
    op.execute(
        "ALTER TABLE notification_prefs ADD COLUMN IF NOT EXISTS plan_push BOOLEAN "
        "NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS detail JSONB")


def downgrade() -> None:
    # The alerts themselves stay; only the counts behind them and the choices go.
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS detail")
    op.execute("ALTER TABLE notification_prefs DROP COLUMN IF EXISTS plan_push")
    op.execute("ALTER TABLE notification_prefs DROP COLUMN IF EXISTS quiet_end")
    op.execute("ALTER TABLE notification_prefs DROP COLUMN IF EXISTS quiet_start")
