"""Alembic environment — uses app settings + the ORM metadata."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  (register all tables on Base.metadata)
from app.core.config import settings
from app.core.db import Base

config = context.config

# The URL comes from app settings in normal operation. A caller (the test suite, or
# `alembic -x db_url=...`) may point migrations at a different database instead — we
# must not clobber an explicitly supplied URL, or migrations become untestable.
_explicit = context.get_x_argument(as_dictionary=True).get("db_url") or (
    config.get_main_option("sqlalchemy.url", None) or ""
).strip()
DB_URL = _explicit or settings.database_url
config.set_main_option("sqlalchemy.url", DB_URL)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = DB_URL
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
