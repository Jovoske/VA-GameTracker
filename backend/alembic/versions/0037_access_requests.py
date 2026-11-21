"""Store requests for administrator-approved signup."""

from alembic import op

revision = "0037_access_requests"
down_revision = "0036_camera_inboxes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Revision 0001 already creates this table on fresh installations.
    op.execute("""
        CREATE TABLE IF NOT EXISTS access_requests (
            id uuid CONSTRAINT pk_access_requests PRIMARY KEY,
            email varchar(254) NOT NULL CONSTRAINT uq_access_requests_email UNIQUE,
            password_hash varchar,
            status varchar NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            reviewed_at timestamptz,
            reviewed_by_id uuid CONSTRAINT fk_access_requests_reviewed_by_id_users
                REFERENCES users(id) ON DELETE SET NULL,
            CONSTRAINT ck_access_requests_status_valid
                CHECK (status IN ('pending', 'approved', 'denied')),
            CONSTRAINT ck_access_requests_pending_password
                CHECK ((status = 'pending') = (password_hash IS NOT NULL))
        )
    """)


def downgrade() -> None:
    op.drop_table("access_requests")
