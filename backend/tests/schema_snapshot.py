"""The schema of a database that was migrated, kept in the repo (audit H-08).

0001 runs Base.metadata.create_all() on the *current* models, so a fresh upgrade
always matches models.py, whatever the migrations do: a column added to a model with
no migration passes every fresh-install test, then breaks the server, whose database
was made months ago, with UndefinedColumn on the first screen that reads it.

fixtures/schema/snapshot.sql is `pg_dump --schema-only` of a database migrated to
the head of its day, with its alembic_version row. test_migrations loads it, runs
`upgrade head` and asks autogenerate for the difference from models.py: a model
change that no migration carries shows up there.

Refresh it after adding a migration (not required, but it keeps the upgrade short):

    cd backend
    python -m tests.schema_snapshot            # uses GAMESENSE_TEST_DSN, pg_dump on PATH

It loads the old snapshot, upgrades it and dumps the result, so the new snapshot is
still one that was *migrated*, never one create_all() made from the models.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "schema" / "snapshot.sql"
# psql's own commands (pg_dump 16.10+ writes \restrict lines) mean nothing to a server.
_META = re.compile(r"^\\\S+.*$", re.M)


def revision(sql: str | None = None) -> str:
    """The migration the snapshot was taken at."""
    sql = sql if sql is not None else SNAPSHOT.read_text(encoding="utf-8")
    found = re.search(r"INSERT INTO public\.alembic_version VALUES \('([^']+)'\)", sql)
    if not found:
        raise ValueError("the snapshot has no alembic_version row")
    return found.group(1)


def _libpq(dsn: str) -> dict:
    url = make_url(dsn)
    params = {"dbname": url.database, "user": url.username, "password": url.password,
              "host": url.host or url.query.get("host"), "port": url.port or url.query.get("port")}
    return {k: v for k, v in params.items() if v}


def load(dsn: str, sql: str | None = None) -> None:
    """Build the snapshot's schema in the (empty) database at `dsn`."""
    sql = sql if sql is not None else SNAPSHOT.read_text(encoding="utf-8")
    with psycopg.connect(**_libpq(dsn), autocommit=True) as conn:
        conn.execute(_META.sub("", sql))


def dump(dsn: str) -> str:
    """The database at `dsn` as a snapshot: schema only, no owners, its revision row."""
    pg_dump = os.environ.get("PG_DUMP") or shutil.which("pg_dump") or "pg_dump"
    params = _libpq(dsn)
    env = {**os.environ, **({"PGPASSWORD": params["password"]} if "password" in params else {})}
    args = [pg_dump, "--schema-only", "--no-owner", "--no-privileges",
            *(["-h", str(params["host"])] if "host" in params else []),
            *(["-p", str(params["port"])] if "port" in params else []),
            *(["-U", params["user"]] if "user" in params else []), params["dbname"]]
    schema = subprocess.run(args, env=env, check=True, capture_output=True, text=True).stdout
    with psycopg.connect(**params) as conn:
        at = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    body = "\n".join(line for line in _META.sub("", schema).splitlines()
                     if not line.startswith("-- Dumped "))
    return (f"-- GameSense schema at {at}, as a migrated database has it.\n"
            f"-- Refresh: cd backend && python -m tests.schema_snapshot\n{body.strip()}\n\n"
            f"INSERT INTO public.alembic_version VALUES ('{at}');\n")


def refresh(admin_dsn: str) -> str:
    """Load the snapshot into a scratch database, upgrade it to head, dump it back."""
    from alembic import command

    from .conftest import alembic_config, dsn_for

    name = f"gs_snapshot_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(**_libpq(admin_dsn), autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    dsn = dsn_for(name, admin_dsn)
    try:
        load(dsn)
        command.upgrade(alembic_config(dsn), "head")
        new = dump(dsn)
    finally:
        with psycopg.connect(**_libpq(admin_dsn), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    SNAPSHOT.write_text(new, encoding="utf-8")
    return revision(new)


if __name__ == "__main__":
    from .conftest import ADMIN_DSN

    print(f"snapshot now at {refresh(os.environ.get('GAMESENSE_TEST_DSN', ADMIN_DSN))}",
          file=sys.stderr)
