"""add terrain_grid — cached elevation, for thermal drainage winds

Revision ID: 0011_terrain
Revises: 0010_zones
Create Date: 2026-08-04

On a calm evening the synoptic forecast is not the wind the hunter stands in: cold
air drains downhill after sunset. Which way downhill points is a property of the
ground, so the elevation grid is fetched once from Open-Meteo and kept.
"""
from alembic import op

revision = "0011_terrain"
down_revision = "0010_zones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS terrain_grid (
            id uuid PRIMARY KEY,
            min_lat double precision NOT NULL,
            min_lon double precision NOT NULL,
            max_lat double precision NOT NULL,
            max_lon double precision NOT NULL,
            steps integer NOT NULL,
            elevations jsonb NOT NULL,
            created_at timestamptz DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS terrain_grid")
