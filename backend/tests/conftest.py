"""Shared pytest fixtures — a real Postgres database per test session.

We test against real PostgreSQL, not SQLite: the schema uses JSONB, ARRAY, UUID,
server-side `timezone()` calls and `date_trunc`, none of which behave the same on
SQLite. A test that passes on SQLite would tell us nothing about production.

Set GAMESENSE_TEST_DSN to point at a scratch Postgres. Tests are skipped (not
failed) when no database is reachable, so the suite stays runnable anywhere.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DEFAULT_DSN = "postgresql+psycopg://postgres@/postgres?host=/tmp&port=55432"
ADMIN_DSN = os.environ.get("GAMESENSE_TEST_DSN", DEFAULT_DSN)


def _server_reachable(dsn: str) -> bool:
    try:
        eng = create_engine(dsn, isolation_level="AUTOCOMMIT")
        with eng.connect() as c:
            c.execute(text("select 1"))
        eng.dispose()
        return True
    except Exception:
        return False


_DB_UP = _server_reachable(ADMIN_DSN)

# Skipping keeps the suite runnable anywhere, but a silent skip is indistinguishable
# from a pass at a glance — a whole file can go green while testing nothing. Set
# GAMESENSE_REQUIRE_DB=1 in CI so a missing database is a loud failure instead.
if os.environ.get("GAMESENSE_REQUIRE_DB") == "1" and not _DB_UP:
    raise RuntimeError(
        f"GAMESENSE_REQUIRE_DB=1 but no PostgreSQL reachable at {ADMIN_DSN}. "
        "Refusing to report a green suite that skipped every database test."
    )

requires_db = pytest.mark.skipif(
    not _DB_UP,
    reason="no test PostgreSQL reachable (set GAMESENSE_TEST_DSN)",
)


@pytest.fixture(scope="session")
def admin_engine():
    eng = create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    yield eng
    eng.dispose()


@pytest.fixture
def fresh_db(admin_engine):
    """An empty, uniquely-named database, dropped afterwards.

    Yields the DSN so a test can run alembic against it, or build an engine.
    """
    name = f"gs_test_{uuid.uuid4().hex[:12]}"
    with admin_engine.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    dsn = ADMIN_DSN.replace("/postgres?", f"/{name}?")
    try:
        yield dsn
    finally:
        with admin_engine.connect() as c:
            c.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"
                ),
                {"n": name},
            )
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))


@pytest.fixture
def db_session(fresh_db):
    """A session against a fresh database with the current ORM schema created."""
    from app.core.db import Base
    import app.models  # noqa: F401  (populate metadata)

    eng = create_engine(fresh_db)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        eng.dispose()


def alembic_config(dsn: str):
    """An Alembic config pointed at `dsn`, with the repo's script location."""
    from alembic.config import Config

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "alembic"))
    cfg.set_main_option("sqlalchemy.url", dsn)
    return cfg
