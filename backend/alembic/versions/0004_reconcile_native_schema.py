"""reconcile pre-native (PostGIS/pgvector) databases with the native schema

Revision ID: 0004_reconcile_native
Revises: 0003_reid_embedding
Create Date: 2026-07-29

The commit that moved GameSense onto vanilla PostgreSQL changed three geography
columns to lat/lon floats and the pgvector embedding to JSONB — in models.py only.
Because 0001 was ``create_all()`` at the time, a *fresh* database silently got the
new shape while an *existing* one kept the old, both reporting the same alembic
head. This migration makes an old database match the new ORM.

Safety rules, because this runs against a live estate database:

* Nothing is ever dropped. Legacy columns are kept (or renamed aside), so a
  mistaken assumption here costs disk, not data.
* Every step is guarded and idempotent — running it twice, or on an already-native
  database, is a no-op.
* No PostGIS/pgvector import is required for this file to load. Old databases have
  those extensions; new ones do not, and the guards mean neither path errors.
"""
from alembic import op

revision = "0004_reconcile_native"
down_revision = "0003_reid_embedding"
branch_labels = None
depends_on = None


# (table, legacy geography column) — lat/lon are added and backfilled from it.
_GEO = (("estates", "centroid"), ("cameras", "location"), ("stands", "location"))


def upgrade() -> None:
    conn = op.get_bind()

    for table, geo_col in _GEO:
        # 1. Ensure the native columns exist. Safe on every database.
        op.execute(
            f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION'
        )
        op.execute(
            f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION'
        )

        # 2. Backfill from the legacy geography column, only where it exists, only
        #    where PostGIS is actually available, and only for rows not yet filled.
        #    ST_X/ST_Y are resolved at runtime inside the DO block, so this file
        #    parses fine on a database that has never heard of PostGIS.
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = '{table}' AND column_name = '{geo_col}'
                ) AND EXISTS (
                    SELECT 1 FROM pg_extension WHERE extname = 'postgis'
                ) THEN
                    EXECUTE format(
                        'UPDATE %I SET lat = ST_Y(%I::geometry), lon = ST_X(%I::geometry) '
                        'WHERE %I IS NOT NULL AND (lat IS NULL OR lon IS NULL)',
                        '{table}', '{geo_col}', '{geo_col}', '{geo_col}'
                    );
                END IF;
            END $$;
            """
        )

    # 3. detections.embedding: the ORM now expects JSONB. If this database still has
    #    a pgvector column (or anything else), move it aside rather than casting it —
    #    a bad cast on a 1024-dim vector column is unrecoverable, and embeddings are
    #    always recomputable from the source images. The legacy data stays on disk
    #    under embedding_legacy for anyone who wants it.
    embed_type = conn.exec_driver_sql(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'detections' AND column_name = 'embedding'"
    ).scalar()

    if embed_type is not None and embed_type != "jsonb":
        op.execute(
            "ALTER TABLE detections RENAME COLUMN embedding TO embedding_legacy"
        )
        op.execute("ALTER TABLE detections ADD COLUMN embedding JSONB")
    elif embed_type is None:
        op.execute("ALTER TABLE detections ADD COLUMN IF NOT EXISTS embedding JSONB")


def downgrade() -> None:
    # Deliberately not reversible: the only destructive interpretation of "undo"
    # would be dropping lat/lon (and the data backfilled into them). Legacy columns
    # were never removed, so an old application version still finds what it needs.
    pass
