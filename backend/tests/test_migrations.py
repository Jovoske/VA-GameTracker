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

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
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
        assert "ubox_event_id" in images
        assert "ubox_uid" in _columns(eng, "cameras")
        assert {"provider_name", "name_is_custom"} <= _columns(eng, "cameras").keys()
        assert {
            "provider", "ubox_min_interval_seconds", "ubox_max_images_per_day"
        } <= _columns(eng, "camera_accounts").keys()
        assert _columns(eng, "sync_log")["details"] == "jsonb"
        notes = _columns(eng, "notifications")
        assert "push_status" in notes and "read_at" in notes
        assert "species_ids" in _columns(eng, "notification_prefs")
    finally:
        eng.dispose()


@requires_db
def test_fresh_upgrade_matches_the_orm_exactly(fresh_db):
    """After `upgrade head`, autogenerate must detect no difference.

    If someone changes models.py without a migration, this fails — which is the only
    guard the create_all convention has.
    """
    command.upgrade(alembic_config(fresh_db), "head")

    import app.models  # noqa: F401
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
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
    """Re-running revisions 0008 onward against an upgraded database is a no-op.

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
        assert _columns(eng, "push_subscriptions")
        assert "ubox_uid" in _columns(eng, "cameras")
        assert "ubox_event_id" in _columns(eng, "images")
        assert "details" in _columns(eng, "sync_log")
    finally:
        eng.dispose()


@requires_db
@pytest.mark.parametrize(
    "legacy_unique", ["camera_accounts_username_key", "uq_camera_accounts_username"]
)
def test_ubox_upgrades_the_actual_prior_schema_without_losing_data(fresh_db, legacy_unique):
    """Exercise real ADD COLUMN work, which create_all's current ORM otherwise hides."""
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0012_notifications")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            # 0001 used today's models even at revision 0012. Restore its actual
            # historical shape before adding rows; either old uniqueness name
            # can exist, depending on whether 0006 or create_all made the table.
            c.execute(text("ALTER TABLE images DROP COLUMN ubox_event_id"))
            c.execute(text("ALTER TABLE cameras DROP COLUMN ubox_uid"))
            c.execute(text("ALTER TABLE camera_accounts DROP COLUMN provider"))
            c.execute(text("ALTER TABLE camera_accounts DROP COLUMN ubox_min_interval_seconds"))
            c.execute(text("ALTER TABLE camera_accounts DROP COLUMN ubox_max_images_per_day"))
            c.execute(text("ALTER TABLE sync_log DROP COLUMN details"))
            c.execute(text(
                f"ALTER TABLE camera_accounts ADD CONSTRAINT {legacy_unique} UNIQUE (username)"
            ))
            estate_id = c.execute(text(
                "INSERT INTO estates (id,name,timezone) "
                "VALUES (gen_random_uuid(),'Existing estate','Europe/Madrid') RETURNING id"
            )).scalar_one()
            account_id = c.execute(text(
                "INSERT INTO camera_accounts (id,estate_id,username,password_enc,active) "
                "VALUES (gen_random_uuid(),:estate,'camera@example.com','encrypted-secret',true) "
                "RETURNING id"
            ), {"estate": estate_id}).scalar_one()
            camera_id = c.execute(text(
                "INSERT INTO cameras (id,estate_id,account_id,spypoint_id,name,active) "
                "VALUES (gen_random_uuid(),:estate,:account,'existing-device','Old camera',true) "
                "RETURNING id"
            ), {"estate": estate_id, "account": account_id}).scalar_one()
            image_id = c.execute(text(
                "INSERT INTO images "
                "(id,camera_id,spypoint_photo_id,captured_at,original_path,reviewed) "
                "VALUES (gen_random_uuid(),:camera,'existing-photo',now(),'original.jpg',false) "
                "RETURNING id"
            ), {"camera": camera_id}).scalar_one()

        command.upgrade(cfg, "head")
        # The same revision must also tolerate a second execution after an upgrade.
        command.stamp(cfg, "0012_notifications")
        command.upgrade(cfg, "head")

        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from app.core.db import Base

        with eng.connect() as c:
            account = c.execute(text(
                "SELECT * FROM camera_accounts WHERE id=:id"
            ), {"id": account_id}).one()
            assert account.provider == "spypoint"
            assert account.password_enc == "encrypted-secret"
            assert account.ubox_min_interval_seconds == 60
            assert account.ubox_max_images_per_day == 500
            camera = c.execute(text(
                "SELECT * FROM cameras WHERE id=:id"
            ), {"id": camera_id}).one()
            assert camera.spypoint_id == "existing-device"
            assert camera.ubox_uid is None
            assert camera.account_id == account_id
            image = c.execute(text(
                "SELECT * FROM images WHERE id=:id"
            ), {"id": image_id}).one()
            assert image.spypoint_photo_id == "existing-photo"
            assert image.original_path == "original.jpg"
            assert image.ubox_event_id is None
            diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
            assert [d for d in diff if "alembic_version" not in repr(d)] == []

        # An email can serve both vendors, but each vendor login belongs to one estate.
        with eng.begin() as c:
            c.execute(text(
                "INSERT INTO camera_accounts "
                "(id,estate_id,provider,username,password_enc,active) "
                "VALUES (gen_random_uuid(),:estate,'ubox','camera@example.com','ubox-secret',true)"
            ), {"estate": estate_id})
        with pytest.raises(IntegrityError), eng.begin() as c:
            c.execute(text(
                "INSERT INTO camera_accounts "
                "(id,estate_id,provider,username,password_enc,active) "
                "VALUES (gen_random_uuid(),:estate,'ubox','camera@example.com','duplicate',true)"
            ), {"estate": estate_id})
        uniques = inspect(eng).get_unique_constraints("camera_accounts")
        assert [u["column_names"] for u in uniques] == [["provider", "username"]]
    finally:
        eng.dispose()


@requires_db
@pytest.mark.parametrize("values", [
    "provider='unknown'",
    "ubox_min_interval_seconds=9",
    "ubox_min_interval_seconds=3601",
    "ubox_max_images_per_day=0",
    "ubox_max_images_per_day=5001",
])
def test_ubox_database_rejects_invalid_provider_and_limits(fresh_db, values):
    command.upgrade(alembic_config(fresh_db), "head")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            c.execute(text(
                "INSERT INTO estates (id,name,timezone) "
                "VALUES (gen_random_uuid(),'Limits test','Europe/Madrid')"
            ))
            c.execute(text(
                "INSERT INTO camera_accounts (id,estate_id,username,password_enc,active) "
                "SELECT gen_random_uuid(),id,'a@example.com','secret',true FROM estates"
            ))
        with pytest.raises(IntegrityError), eng.begin() as c:
            c.execute(text(f"UPDATE camera_accounts SET {values}"))
    finally:
        eng.dispose()


@requires_db
def test_camera_name_upgrade_preserves_names_images_and_saved_overrides(fresh_db):
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0013_ubox")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            # 0001 creates today's ORM; reconstruct the real deployed 0013 shape.
            c.execute(text("ALTER TABLE cameras DROP COLUMN provider_name"))
            c.execute(text("ALTER TABLE cameras DROP COLUMN name_is_custom"))
            estate_id = c.execute(text(
                "INSERT INTO estates (id,name,timezone) "
                "VALUES (gen_random_uuid(),'Existing estate','UTC') RETURNING id"
            )).scalar_one()
            camera_id = c.execute(text(
                "INSERT INTO cameras (id,estate_id,name,ubox_uid,active) "
                "VALUES (gen_random_uuid(),:estate,'Existing camera','device-id',true) RETURNING id"
            ), {"estate": estate_id}).scalar_one()
            image_id = c.execute(text(
                "INSERT INTO images (id,camera_id,captured_at,original_path,reviewed) "
                "VALUES (gen_random_uuid(),:camera,now(),'photo.jpg',false) RETURNING id"
            ), {"camera": camera_id}).scalar_one()
        command.upgrade(cfg, "head")
        with eng.begin() as c:
            camera = c.execute(text("SELECT * FROM cameras WHERE id=:id"), {"id": camera_id}).one()
            assert camera.name == camera.provider_name == "Existing camera"
            assert not camera.name_is_custom
            assert camera.ubox_uid == "device-id"
            assert c.execute(text("SELECT camera_id FROM images WHERE id=:id"),
                             {"id": image_id}).scalar_one() == camera_id
            c.execute(text("UPDATE cameras SET name='My meadow', name_is_custom=true WHERE id=:id"),
                      {"id": camera_id})
        command.stamp(cfg, "0013_ubox")
        command.upgrade(cfg, "head")
        with eng.connect() as c:
            camera = c.execute(text("SELECT * FROM cameras WHERE id=:id"), {"id": camera_id}).one()
            assert camera.name == "My meadow" and camera.name_is_custom
            assert camera.provider_name == "Existing camera"
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
            "INSERT INTO camera_accounts "
            "(id,estate_id,label,username,password_enc,active,created_at) "
            "SELECT gen_random_uuid(), id, 'Guest','g@x.com','fernet-blob',true,now() "
            "FROM estates LIMIT 1"
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
