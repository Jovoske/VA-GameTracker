"""add zones — hand-drawn ground (bedding) the cameras cannot see

Revision ID: 0010_zones
Revises: 0009_sits
Create Date: 2026-08-04

Wind advice needs to know which way animals approach a stand. Approach arcs stayed
NULL because guessing them produces confident nonsense and nobody types in bearings.
A drawn bedding area makes the bearing derived geometry instead: animals come from
where they lie up. Polygons are GeoJSON in JSONB — PostGIS was dropped for the
native build and this maths is done in Python (app/geo.py).
"""
from alembic import op

revision = "0010_zones"
down_revision = "0009_sits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS zones (
            id uuid PRIMARY KEY,
            estate_id uuid NOT NULL REFERENCES estates(id),
            kind varchar NOT NULL DEFAULT 'bedding'
                CHECK (kind IN ('bedding','feeding','water','no_go')),
            name varchar NOT NULL,
            polygon jsonb NOT NULL,
            notes text,
            created_by uuid REFERENCES users(id),
            created_at timestamptz DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_zones_estate_kind ON zones (estate_id, kind)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS zones")
