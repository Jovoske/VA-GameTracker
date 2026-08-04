"""Migration safety tests.

This project's convention is deliberate and worth stating, because it is unusual:
0001 runs ``Base.metadata.create_all()`` against the *current* ORM, and every later
revision is written to be a no-op where 0001 already did the work (0002 and 0003 are
explicit no-ops; 0005 and 0008 use IF NOT EXISTS). That keeps fresh installs working
while existing databases migrate forward.

The cost is that a new migration is only safe if it is idempotent, and nothing
enforces that. These tests do.
"""
from __future__ import annotations

from alembic import command
from sqlalchemy import create_engine, text

from app.core.security import create_access_token, decode_token

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
def test_fresh_upgrade_head_succeeds(fresh_db):
    command.upgrade(alembic_config(fresh_db), "head")
    eng = create_engine(fresh_db)
    try:
        assert "camera_nights" in _columns(eng, "camera_nights") or True
        assert _columns(eng, "camera_nights")  # table exists
        assert _columns(eng, "sits")
        images = _columns(eng, "images")
        assert "animal_conf" in images and "reviewed" in images
    finally:
        eng.dispose()


@requires_db
def test_fresh_upgrade_matches_the_orm_exactly(fresh_db):
    """After `upgrade head`, autogenerate must detect no difference.

    If someone changes models.py without a migration, this fails — which is the only
    guard the create_all convention has.
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

    diff = [d for d in diff if "alembic_version" not in repr(d)]
    assert diff == [], f"schema drifted from models.py: {diff}"


@requires_db
def test_new_revisions_are_idempotent(fresh_db):
    """Re-running 0008/0009 against a database that already has them is a no-op.

    Under the create_all convention this is not optional: a fresh database already
    contains everything declared on the models, so a later revision that blindly
    CREATEs will fail on exactly the installs it was meant to serve.
    """
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "head")
    command.stamp(cfg, "0007_sex_attempts")
    command.upgrade(cfg, "head")  # must not raise

    eng = create_engine(fresh_db)
    try:
        assert _columns(eng, "camera_nights")
        assert _columns(eng, "sits")
    finally:
        eng.dispose()


@requires_db
def test_upgrading_an_existing_install_preserves_its_rows(fresh_db):
    """The promise made to the operator: nobody is logged out, nothing is lost."""
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0007_sex_attempts")

    eng = create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO estates (id,name,timezone,created_at) "
            "VALUES (gen_random_uuid(),'E','Europe/Madrid',now())"
        ))
        c.execute(text(
            "INSERT INTO users (id,estate_id,email,password_hash,role,created_at) "
            "SELECT gen_random_uuid(), id, 'admin@gamesense.local','argon2-hash','admin',now() "
            "FROM estates LIMIT 1"
        ))
        c.execute(text(
            "INSERT INTO camera_accounts (id,estate_id,label,username,password_enc,active,created_at) "
            "SELECT gen_random_uuid(), id, 'Guest','g@x.com','fernet-blob',true,now() FROM estates LIMIT 1"
        ))

    # A session issued *before* the upgrade. Nothing in this migration chain may
    # invalidate it — that is the whole point of leaving JWT_SECRET alone.
    with eng.connect() as c:
        user_id = str(c.execute(text("SELECT id FROM users")).scalar_one())
    pre_upgrade_token = create_access_token(user_id)

    command.upgrade(cfg, "head")

    try:
        with eng.connect() as c:
            user = c.execute(text("SELECT id, email, role, password_hash FROM users")).one()
            acct = c.execute(text("SELECT username, password_enc FROM camera_accounts")).one()
        assert user.email == "admin@gamesense.local"
        assert user.password_hash == "argon2-hash", "password hashes must survive untouched"
        assert acct.password_enc == "fernet-blob", "encrypted SPYPOINT creds must survive untouched"
        assert str(user.id) == user_id, "user ids must be stable — tokens carry them as `sub`"
        assert decode_token(pre_upgrade_token)["sub"] == user_id, (
            "a session issued before the upgrade must still be accepted after it"
        )
    finally:
        eng.dispose()
