"""Database engine, session factory, and declarative base."""
from collections.abc import Generator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

# Stable, predictable constraint/index names → clean Alembic autogenerate diffs.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# JIT off: every query here is a short read or write, and the planner's row guesses
# for the visit queries (a few EXISTS per photo) are far enough off that Postgres
# would spend most of a Tonight or Insights call compiling LLVM code it runs once.
_connect_args = (
    {"options": "-c jit=off"} if settings.database_url.startswith("postgresql") else {}
)
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True,
                       connect_args=_connect_args)


def server_sessions(bind) -> sessionmaker:
    """Sessions as the server makes them. They don't autoflush: an object only
    db.add()ed is not in the database yet, so a query, or a db.get() by its key, does
    not find it before the commit. The tests make theirs here too (tests/conftest.py):
    on an autoflushing test session a fetch passed that failed every time on the
    server, where a row added twice broke its primary key (28 Sep 2026)."""
    return sessionmaker(bind=bind, autoflush=False, expire_on_commit=False, class_=Session)


SessionLocal = server_sessions(engine)


def error_name(exc: BaseException) -> str:
    """What went wrong, in a few words to keep and show: the exception's class and, when
    the database refused a write, the rule it broke ("IntegrityError: pk_app_settings",
    or "IntegrityError: app_settings.value" for a NOT NULL, which has no name of its own).

    A fetch that failed said only "IntegrityError", and without the server's log
    nobody could tell which of a dozen writes it was, or which rule (28 Sep 2026).
    """
    name = type(exc).__name__
    # SQLAlchemy's errors carry the driver's (psycopg) as .orig, with its diagnostics.
    diag = getattr(getattr(exc, "orig", None) or exc, "diag", None)
    if diag is None:
        return name
    rule = getattr(diag, "constraint_name", None)
    if not rule and getattr(diag, "column_name", None):
        rule = ".".join(p for p in (getattr(diag, "table_name", None), diag.column_name) if p)
    return f"{name}: {rule}" if rule else name


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
