"""Migration safety tests.

These exist because the migration chain was broken in a way that no test could
catch: 0001 called ``Base.metadata.create_all()``, so it produced whatever the ORM
looked like at run time. A fresh database therefore already had the columns 0002
tried to add, and ``alembic upgrade head`` died with DuplicateColumn — which, under
``set -e`` in entrypoint.sh, means the API container never starts.

Coverage note (honest): PostGIS and pgvector are not installed in CI, so the
*literal* legacy column types cannot be reproduced here. What is tested is the
migration's control flow — that it adds the native columns, moves a non-JSONB
embedding aside instead of casting it, preserves existing rows, and is idempotent.
The geography backfill is guarded on `pg_extension`, so on a database without
PostGIS it is correctly skipped rather than erroring.
"""
from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from .conftest import alembic_config, requires_db


def _columns(engine, table: str) -> dict[str, str]:
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = :t"
            ),
            {"t": table},
        ).all()
    return {r[0]: r[1] for r in rows}


@requires_db
def test_upgrade_head_succeeds_on_a_fresh_database(fresh_db):
    """The regression test for the bug that stopped fresh installs booting."""
    command.upgrade(alembic_config(fresh_db), "head")

    eng = create_engine(fresh_db)
    try:
        images = _columns(eng, "images")
        # 0002's columns must be present -- added by 0002, not by 0001.
        assert "animal_conf" in images
        assert "reviewed" in images
        assert _columns(eng, "detections")["embedding"] == "jsonb"
    finally:
        eng.dispose()


@requires_db
def test_fresh_upgrade_matches_the_orm_exactly(fresh_db):
    """After `upgrade head`, autogenerate must detect no difference.

    This is the check that makes the frozen 0001 safe to keep frozen: if someone
    changes models.py without writing a migration, this fails.
    """
    command.upgrade(alembic_config(fresh_db), "head")

    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    import app.models  # noqa: F401
    from app.core.db import Base

    eng = create_engine(fresh_db)
    try:
        with eng.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        eng.dispose()

    # Ignore alembic's own bookkeeping table.
    diff = [d for d in diff if "alembic_version" not in repr(d)]
    assert diff == [], f"schema drifted from models.py: {diff}"


def _build_legacy_database(dsn: str) -> None:
    """A database shaped like one created before the native-PostgreSQL move.

    Built by running 0001+0002 and then mutating the result back towards the old
    shape, so the fixture stays honest about what actually differs.
    """
    command.upgrade(alembic_config(dsn), "0002_image_review")
    eng = create_engine(dsn)
    with eng.begin() as c:
        # Old shape: geography columns instead of lat/lon.
        for table, geo in (("estates", "centroid"), ("cameras", "location"), ("stands", "location")):
            c.execute(text(f"ALTER TABLE {table} DROP COLUMN lat"))
            c.execute(text(f"ALTER TABLE {table} DROP COLUMN lon"))
            c.execute(text(f"ALTER TABLE {table} ADD COLUMN {geo} TEXT"))
        # Old shape: fixed-width embedding rather than JSONB (pgvector stand-in).
        c.execute(text("ALTER TABLE detections DROP COLUMN embedding"))
        c.execute(text("ALTER TABLE detections ADD COLUMN embedding REAL[]"))
        # Real data that must survive the upgrade.
        c.execute(
            text(
                "INSERT INTO estates (id, name, timezone, created_at) "
                "VALUES (gen_random_uuid(), 'Piedras Lisas', 'Europe/Madrid', now())"
            )
        )
        c.execute(
            text(
                "INSERT INTO users (id, estate_id, email, password_hash, role, created_at) "
                "SELECT gen_random_uuid(), id, :e, 'argon2-hash', :r, now() FROM estates LIMIT 1"
            ),
            {"e": "guest@estate.local", "r": "member"},
        )
    eng.dispose()
    # Stamp forward to just before the reconciliation migration.
    command.stamp(alembic_config(dsn), "0003_reid_embedding")


@requires_db
def test_legacy_database_gains_native_columns_without_losing_rows(fresh_db):
    _build_legacy_database(fresh_db)
    eng = create_engine(fresh_db)
    try:
        with eng.connect() as c:
            users_before = c.execute(text("SELECT count(*) FROM users")).scalar()
        assert users_before == 1

        command.upgrade(alembic_config(fresh_db), "head")

        cams = _columns(eng, "cameras")
        assert cams["lat"] == "double precision"
        assert cams["lon"] == "double precision"
        # Legacy column retained, never dropped.
        assert "location" in cams

        dets = _columns(eng, "detections")
        assert dets["embedding"] == "jsonb"
        assert "embedding_legacy" in dets, "legacy embedding must be kept, not cast"

        with eng.connect() as c:
            # The user-visible promise: existing logins survive untouched.
            row = c.execute(
                text("SELECT email, role, password_hash FROM users")
            ).one()
        assert row.email == "guest@estate.local"
        assert row.role == "member"
        assert row.password_hash == "argon2-hash"
    finally:
        eng.dispose()


@requires_db
def test_reconciliation_is_idempotent(fresh_db):
    """Re-running must not rename embedding a second time or duplicate columns."""
    _build_legacy_database(fresh_db)
    command.upgrade(alembic_config(fresh_db), "head")

    eng = create_engine(fresh_db)
    try:
        # Force 0004 to run again against an already-reconciled database.
        command.stamp(alembic_config(fresh_db), "0003_reid_embedding")
        command.upgrade(alembic_config(fresh_db), "head")

        dets = _columns(eng, "detections")
        assert dets["embedding"] == "jsonb"
        assert "embedding_legacy" in dets
        assert "embedding_legacy_legacy" not in dets
    finally:
        eng.dispose()


@requires_db
def test_native_database_is_untouched_by_reconciliation(fresh_db):
    """A database already on the native shape must not gain an embedding_legacy."""
    command.upgrade(alembic_config(fresh_db), "head")
    eng = create_engine(fresh_db)
    try:
        dets = _columns(eng, "detections")
        assert dets["embedding"] == "jsonb"
        assert "embedding_legacy" not in dets
    finally:
        eng.dispose()
