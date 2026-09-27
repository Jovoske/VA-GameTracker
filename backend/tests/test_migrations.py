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
from sqlalchemy.exc import DBAPIError, IntegrityError

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


def _index(engine, table: str, name: str) -> list[str] | None:
    """The columns of index `name` on `table`, or None when there is no such index."""
    for ix in inspect(engine).get_indexes(table):
        if ix["name"] == name:
            return ix["column_names"]
    return None


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
        assert set(_columns(eng, "camera_views")) == {"user_id", "camera_id", "seen_at"}
        assert "thumbnail_path" in images
        assert _index(eng, "images", "ix_images_camera_created") == ["camera_id", "created_at"]
        assert _columns(eng, "notification_prefs")["muted_camera_ids"] == "jsonb"
        assert set(_columns(eng, "photo_notes")) == {
            "id", "image_id", "user_id", "text", "created_at",
        }
        assert _index(eng, "photo_notes", "ix_photo_notes_image_id") == ["image_id"]
        assert _index(eng, "photo_notes", "ix_photo_notes_created_at") == ["created_at"]
        assert set(_columns(eng, "client_errors")) == {
            "id", "user_id", "kind", "message", "stack", "route", "build", "user_agent",
            "happened_at", "created_at",
        }
        assert _index(eng, "client_errors", "ix_client_errors_created_at") == ["created_at"]
        assert {"ai_attempts", "ai_error", "ai_failed_at", "detector_conf"} <= set(images)
        assert "reported_at" in _columns(eng, "sits")
        assert _index(eng, "sits", "uq_sits_stand_night_live") == ["stand_id", "night"]
        assert _columns(eng, "cameras")["retired_at"] == "timestamp with time zone"
        assert {"corrected_at", "corrected_by"} <= set(_columns(eng, "detections"))
        assert _columns(eng, "sits")["wind_at"] == "timestamp with time zone"
        assert _columns(eng, "cameras")["clock_ahead_min"] == "integer"
        prefs = _columns(eng, "notification_prefs")
        assert prefs["quiet_start"] == "time without time zone"
        assert prefs["plan_push"] == "boolean"
        assert _columns(eng, "notifications")["detail"] == "jsonb"
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
        assert _columns(eng, "camera_views")
        assert "thumbnail_path" in _columns(eng, "images")
        assert _index(eng, "images", "ix_images_camera_created")
        assert "muted_camera_ids" in _columns(eng, "notification_prefs")
        assert _columns(eng, "photo_notes")
        assert "last_error" in _columns(eng, "camera_accounts")
        assert "photos_listed_to" in _columns(eng, "cameras")
        assert "download_attempts" in _columns(eng, "images")
        assert _columns(eng, "client_errors")
        assert "ai_failed_at" in _columns(eng, "images")
        assert "reported_at" in _columns(eng, "sits")
        assert _index(eng, "sits", "uq_sits_stand_night_live")
        assert "retired_at" in _columns(eng, "cameras")
        assert "corrected_by" in _columns(eng, "detections")
        assert "wind_at" in _columns(eng, "sits")
        assert {"clock_ahead_min", "clock_ok_photos"} <= set(_columns(eng, "cameras"))
        assert "received_at" in _columns(eng, "images")
        assert {"quiet_start", "quiet_end", "plan_push"} <= set(_columns(eng, "notification_prefs"))
        assert "detail" in _columns(eng, "notifications")
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


@requires_db
def test_camera_views_upgrade_down_and_up_again_keeping_the_photos(fresh_db):
    """0017 on a real 0016 database, then back down and up again.

    0001 builds today's ORM even at 0016, so the 0016 shape is restored by hand
    first; otherwise the upgrade would have nothing to do and prove nothing.
    """
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0016_species_hidden")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            c.execute(text("DROP TABLE camera_views"))
            c.execute(text("ALTER TABLE images DROP COLUMN thumbnail_path"))
            estate_id = c.execute(text(
                "INSERT INTO estates (id,name,timezone) "
                "VALUES (gen_random_uuid(),'Existing estate','Europe/Madrid') RETURNING id"
            )).scalar_one()
            user_id = c.execute(text(
                "INSERT INTO users (id,estate_id,email,password_hash,role) "
                "VALUES (gen_random_uuid(),:e,'m@x.local','h','member') RETURNING id"
            ), {"e": estate_id}).scalar_one()
            camera_id = c.execute(text(
                "INSERT INTO cameras (id,estate_id,name,name_is_custom,active) "
                "VALUES (gen_random_uuid(),:e,'Charca',false,true) RETURNING id"
            ), {"e": estate_id}).scalar_one()
            image_id = c.execute(text(
                "INSERT INTO images (id,camera_id,captured_at,original_path,reviewed) "
                "VALUES (gen_random_uuid(),:c,now(),'photo.jpg',false) RETURNING id"
            ), {"c": camera_id}).scalar_one()

        command.upgrade(cfg, "head")
        with eng.begin() as c:
            assert c.execute(text("SELECT original_path, thumbnail_path FROM images WHERE id=:i"),
                             {"i": image_id}).one() == ("photo.jpg", None)
            c.execute(text("INSERT INTO camera_views (user_id,camera_id,seen_at) "
                           "VALUES (:u,:c,now())"), {"u": user_id, "c": camera_id})
            # One row per person and camera.
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(text("INSERT INTO camera_views (user_id,camera_id,seen_at) "
                               "VALUES (:u,:c,now())"), {"u": user_id, "c": camera_id})
        with eng.connect() as c:
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            from app.core.db import Base

            diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
            assert [d for d in diff if "alembic_version" not in repr(d)] == []

        # Removing the person removes what they had seen, nothing else.
        with eng.begin() as c:
            c.execute(text("DELETE FROM users WHERE id=:u"), {"u": user_id})
            assert c.execute(text("SELECT count(*) FROM camera_views")).scalar_one() == 0
            assert c.execute(text("SELECT count(*) FROM cameras")).scalar_one() == 1

        command.downgrade(cfg, "0016_species_hidden")
        assert "camera_views" not in inspect(eng).get_table_names()
        assert "thumbnail_path" not in _columns(eng, "images")
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM images")).scalar_one() == 1

        command.upgrade(cfg, "head")
        command.stamp(cfg, "0016_species_hidden")
        command.upgrade(cfg, "head")  # and again: a no-op, not an error
        assert set(_columns(eng, "camera_views")) == {"user_id", "camera_id", "seen_at"}
        assert "thumbnail_path" in _columns(eng, "images")
    finally:
        eng.dispose()


@requires_db
def test_image_arrivals_index_upgrade_down_and_up_again(fresh_db):
    """0018 on a real 0017 database: the index the map's "new" count reads."""
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0017_camera_views")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            # 0001 builds today's ORM, index included; restore the 0017 shape first.
            c.execute(text("DROP INDEX ix_images_camera_created"))
            estate_id = c.execute(text(
                "INSERT INTO estates (id,name,timezone) "
                "VALUES (gen_random_uuid(),'Existing estate','Europe/Madrid') RETURNING id"
            )).scalar_one()
            camera_id = c.execute(text(
                "INSERT INTO cameras (id,estate_id,name,name_is_custom,active) "
                "VALUES (gen_random_uuid(),:e,'Charca',false,true) RETURNING id"
            ), {"e": estate_id}).scalar_one()
            c.execute(text(
                "INSERT INTO images (id,camera_id,captured_at,original_path,reviewed) "
                "VALUES (gen_random_uuid(),:c,now(),'photo.jpg',false)"
            ), {"c": camera_id})
        assert _index(eng, "images", "ix_images_camera_created") is None

        command.upgrade(cfg, "head")
        assert _index(eng, "images", "ix_images_camera_created") == ["camera_id", "created_at"]
        with eng.connect() as c:
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            from app.core.db import Base

            diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
            assert [d for d in diff if "alembic_version" not in repr(d)] == []

        command.downgrade(cfg, "0017_camera_views")
        assert _index(eng, "images", "ix_images_camera_created") is None
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM images")).scalar_one() == 1

        command.upgrade(cfg, "head")
        command.stamp(cfg, "0017_camera_views")
        command.upgrade(cfg, "head")  # and again: a no-op, not an error
        assert _index(eng, "images", "ix_images_camera_created") == ["camera_id", "created_at"]
    finally:
        eng.dispose()


@requires_db
def test_camera_alerts_and_photo_notes_upgrade_down_and_up_again(fresh_db):
    """0019 on a real 0018 database: people's alert choices survive and every camera
    starts on; notes go with their photo but outlive the person who wrote them."""
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0018_image_arrivals")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            # 0001 builds today's ORM; restore the 0018 shape first.
            c.execute(text("DROP TABLE photo_notes"))
            c.execute(text("ALTER TABLE notification_prefs DROP COLUMN muted_camera_ids"))
            estate_id = c.execute(text(
                "INSERT INTO estates (id,name,timezone) "
                "VALUES (gen_random_uuid(),'Existing estate','Europe/Madrid') RETURNING id"
            )).scalar_one()
            user_id = c.execute(text(
                "INSERT INTO users (id,estate_id,email,password_hash,role) "
                "VALUES (gen_random_uuid(),:e,'pedro@x.local','h','member') RETURNING id"
            ), {"e": estate_id}).scalar_one()
            c.execute(text(
                "INSERT INTO notification_prefs (user_id,enabled,species_ids) "
                "VALUES (:u,true,'[\"wild_boar\"]'::jsonb)"
            ), {"u": user_id})
            camera_id = c.execute(text(
                "INSERT INTO cameras (id,estate_id,name,name_is_custom,active) "
                "VALUES (gen_random_uuid(),:e,'Charca',false,true) RETURNING id"
            ), {"e": estate_id}).scalar_one()
            image_id = c.execute(text(
                "INSERT INTO images (id,camera_id,captured_at,original_path,reviewed) "
                "VALUES (gen_random_uuid(),:c,now(),'photo.jpg',false) RETURNING id"
            ), {"c": camera_id}).scalar_one()

        command.upgrade(cfg, "head")
        with eng.begin() as c:
            pref = c.execute(text("SELECT enabled, species_ids, muted_camera_ids "
                                  "FROM notification_prefs")).one()
            assert pref == (True, ["wild_boar"], [])  # kept, and every camera on
            for words in (None, "Big boar, third night running"):
                c.execute(text("INSERT INTO photo_notes (id,image_id,user_id,text) "
                               "VALUES (gen_random_uuid(),:i,:u,:t)"),
                          {"i": image_id, "u": user_id, "t": words})
            with pytest.raises(DBAPIError), c.begin_nested():
                c.execute(text("INSERT INTO photo_notes (id,image_id,text) "
                               "VALUES (gen_random_uuid(),:i,:t)"), {"i": image_id, "t": "x" * 141})
        with eng.connect() as c:
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            from app.core.db import Base

            diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
            assert [d for d in diff if "alembic_version" not in repr(d)] == []

        # The person goes, what they said stays; the photo goes, its notes go.
        with eng.begin() as c:
            c.execute(text("DELETE FROM users WHERE id=:u"), {"u": user_id})
            assert c.execute(text("SELECT count(*) FROM photo_notes "
                                  "WHERE user_id IS NULL")).scalar_one() == 2
            c.execute(text("DELETE FROM images WHERE id=:i"), {"i": image_id})
            assert c.execute(text("SELECT count(*) FROM photo_notes")).scalar_one() == 0

        command.downgrade(cfg, "0018_image_arrivals")
        assert "photo_notes" not in inspect(eng).get_table_names()
        assert "muted_camera_ids" not in _columns(eng, "notification_prefs")
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM cameras")).scalar_one() == 1

        command.upgrade(cfg, "head")
        command.stamp(cfg, "0018_image_arrivals")
        command.upgrade(cfg, "head")  # and again: a no-op, not an error
        assert "muted_camera_ids" in _columns(eng, "notification_prefs")
        assert _index(eng, "photo_notes", "ix_photo_notes_image_id") == ["image_id"]
    finally:
        eng.dispose()


@requires_db
def test_camera_login_status_upgrade_down_and_up_again(fresh_db):
    """0020 on a real 0019 database: a login added twice (in two cases) becomes one,
    its cameras and photos kept; a UBox camera whose login was removed is switched
    off; every photo starts with no failed download against it."""
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0019_camera_alerts_photo_notes")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            # 0001 builds today's ORM; restore the 0019 shape first.
            c.execute(text("DROP TABLE client_errors"))
            c.execute(text("DROP INDEX uq_camera_accounts_provider_login"))
            for table, column in (
                ("camera_accounts", "last_attempt_at"), ("camera_accounts", "last_ok_at"),
                ("camera_accounts", "last_error"), ("camera_accounts", "reported_cameras"),
                ("camera_accounts", "session_enc"),
                ("cameras", "photos_listed_to"), ("cameras", "import_failures"),
                ("cameras", "photos_gap_from"), ("cameras", "photos_gap_to"),
                ("cameras", "fetch_error"), ("images", "download_attempts"),
            ):
                c.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
            estate_id = c.execute(text(
                "INSERT INTO estates (id,name,timezone) "
                "VALUES (gen_random_uuid(),'Existing estate','Europe/Madrid') RETURNING id"
            )).scalar_one()
            first, second = (c.execute(text(
                "INSERT INTO camera_accounts (id,estate_id,username,provider,password_enc,"
                "active,created_at) VALUES (gen_random_uuid(),:e,:u,'spypoint','x',true,"
                "now() - make_interval(days => :d)) RETURNING id"
            ), {"e": estate_id, "u": user, "d": days}).scalar_one()
                for user, days in (("julle@x.local", 2), ("Julle@x.local", 1)))
            doubled = c.execute(text(
                "INSERT INTO cameras (id,estate_id,account_id,spypoint_id,name,"
                "name_is_custom,active) VALUES (gen_random_uuid(),:e,:a,'sp-1','Charca',"
                "false,true) RETURNING id"
            ), {"e": estate_id, "a": second}).scalar_one()
            orphan = c.execute(text(
                "INSERT INTO cameras (id,estate_id,ubox_uid,name,name_is_custom,active) "
                "VALUES (gen_random_uuid(),:e,'ubox-1','Orchard',false,true) RETURNING id"
            ), {"e": estate_id}).scalar_one()
            suntek = c.execute(text(
                "INSERT INTO cameras (id,estate_id,name,name_is_custom,active) "
                "VALUES (gen_random_uuid(),:e,'Suntek',false,true) RETURNING id"
            ), {"e": estate_id}).scalar_one()
            c.execute(text(
                "INSERT INTO images (id,camera_id,spypoint_photo_id,captured_at,reviewed) "
                "VALUES (gen_random_uuid(),:c,'p-1',now(),false)"
            ), {"c": doubled})

        command.upgrade(cfg, "head")
        with eng.begin() as c:
            accounts = dict(c.execute(text(
                "SELECT id, active FROM camera_accounts")).all())
            assert accounts == {first: True, second: False}  # the first copy stays
            cameras = dict(c.execute(text("SELECT id, active FROM cameras")).all())
            assert cameras == {doubled: True, orphan: False, suntek: True}
            assert c.execute(text("SELECT account_id FROM cameras WHERE id=:c"),
                             {"c": doubled}).scalar_one() == first
            assert c.execute(text(
                "SELECT download_attempts, spypoint_photo_id FROM images")).one() == (0, "p-1")
            assert c.execute(text("SELECT import_failures FROM cameras WHERE id=:c"),
                             {"c": orphan}).scalar_one() == {}
            # Nothing listed or failing yet: the first fetch finds its own place.
            assert c.execute(text(
                "SELECT photos_listed_to, photos_gap_from, photos_gap_to, fetch_error "
                "FROM cameras WHERE id=:c"), {"c": doubled}).one() == (None, None, None, None)
            assert c.execute(text("SELECT session_enc FROM camera_accounts WHERE id=:a"),
                             {"a": first}).scalar_one() is None
            # One active copy of a login from now on, whatever the case of its email.
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(text(
                    "INSERT INTO camera_accounts (id,estate_id,username,provider,"
                    "password_enc,active) VALUES (gen_random_uuid(),:e,'JULLE@x.local',"
                    "'spypoint','x',true)"), {"e": estate_id})
        with eng.connect() as c:
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            from app.core.db import Base

            diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
            assert [d for d in diff if "alembic_version" not in repr(d)] == []

        command.downgrade(cfg, "0019_camera_alerts_photo_notes")
        assert "last_error" not in _columns(eng, "camera_accounts")
        assert "photos_listed_to" not in _columns(eng, "cameras")
        gone = {"photos_gap_from", "photos_gap_to", "fetch_error"}
        assert not gone & set(_columns(eng, "cameras"))
        assert "session_enc" not in _columns(eng, "camera_accounts")
        assert "download_attempts" not in _columns(eng, "images")
        assert _index(eng, "camera_accounts", "uq_camera_accounts_provider_login") is None
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM images")).scalar_one() == 1
            assert c.execute(text("SELECT count(*) FROM camera_accounts")).scalar_one() == 2

        command.upgrade(cfg, "head")
        command.stamp(cfg, "0019_camera_alerts_photo_notes")
        command.upgrade(cfg, "head")  # and again: a no-op, not an error
        assert "last_ok_at" in _columns(eng, "camera_accounts")
        assert "import_failures" in _columns(eng, "cameras")
    finally:
        eng.dispose()


@requires_db
def test_client_errors_upgrade_down_and_up_again(fresh_db):
    """0021 on a real 0020 database: the new table arrives empty beside the rows already
    there, a report outlives the person whose phone sent it, and going back down
    removes only the reports."""
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0020_camera_login_status")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            # 0001 builds today's ORM; restore the 0020 shape first.
            c.execute(text("DROP TABLE client_errors"))
            estate_id = c.execute(text(
                "INSERT INTO estates (id,name,timezone) "
                "VALUES (gen_random_uuid(),'Existing estate','Europe/Madrid') RETURNING id"
            )).scalar_one()
            user_id = c.execute(text(
                "INSERT INTO users (id,estate_id,email,password_hash,role) "
                "VALUES (gen_random_uuid(),:e,'pedro@x.local','h','member') RETURNING id"
            ), {"e": estate_id}).scalar_one()

        command.upgrade(cfg, "head")
        with eng.begin() as c:
            assert c.execute(text("SELECT count(*) FROM users")).scalar_one() == 1
            assert c.execute(text("SELECT count(*) FROM client_errors")).scalar_one() == 0
            c.execute(text(
                "INSERT INTO client_errors (id,user_id,kind,message,route,happened_at) "
                "VALUES (gen_random_uuid(),:u,'chunk',:m,'/map',now() - interval '3 hours')"
            ), {"u": user_id, "m": "Failed to fetch dynamically imported module"})
            with pytest.raises(DBAPIError), c.begin_nested():
                c.execute(text("INSERT INTO client_errors (id,kind,message) "
                               "VALUES (gen_random_uuid(),'error',:m)"), {"m": "x" * 501})
        with eng.connect() as c:
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            from app.core.db import Base

            diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
            assert [d for d in diff if "alembic_version" not in repr(d)] == []

        with eng.begin() as c:
            c.execute(text("DELETE FROM users WHERE id=:u"), {"u": user_id})
            assert c.execute(text("SELECT count(*) FROM client_errors "
                                  "WHERE user_id IS NULL")).scalar_one() == 1

        command.downgrade(cfg, "0020_camera_login_status")
        assert "client_errors" not in inspect(eng).get_table_names()
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM estates")).scalar_one() == 1

        command.upgrade(cfg, "head")
        command.stamp(cfg, "0020_camera_login_status")
        command.upgrade(cfg, "head")  # and again: a no-op, not an error
        assert _index(eng, "client_errors", "ix_client_errors_created_at") == ["created_at"]
    finally:
        eng.dispose()


@requires_db
def test_ai_checking_upgrade_puts_old_misreads_right_and_goes_down_and_up_again(fresh_db):
    """0022 on a real 0021 database: the new columns arrive with their defaults, a photo
    flagged before the detector saw it stops blinding its night, a detector failure
    stored as "kept" goes back to be checked, spring "hinds" are judged again, and
    nothing else moves."""
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0021_client_errors")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            # 0001 builds today's ORM; restore the 0021 shape first.
            for col in ("ai_attempts", "ai_error", "ai_failed_at", "detector_conf"):
                c.execute(text(f"ALTER TABLE images DROP COLUMN {col}"))
            c.execute(text("DROP INDEX uq_sits_stand_night_live"))  # 0023, after this one
            c.execute(text("ALTER TABLE sits DROP COLUMN reported_at"))
            estate_id = c.execute(text(
                "INSERT INTO estates (id,name,timezone) "
                "VALUES (gen_random_uuid(),'Existing estate','Europe/Madrid') RETURNING id"
            )).scalar_one()
            camera_id = c.execute(text(
                "INSERT INTO cameras (id,estate_id,name,name_is_custom,active) "
                "VALUES (gen_random_uuid(),:e,'Charca',false,true) RETURNING id"
            ), {"e": estate_id}).scalar_one()
            c.execute(text("INSERT INTO species (id,common_name,is_priority,huntable,hidden) "
                           "VALUES ('red_deer','Red Deer',true,true,false)"))

            def image(**kw):
                cols = {"captured_at": "2026-03-10 21:00+00", "original_path": "p.jpg",
                        "reviewed": False, "created_at": "2026-03-10 21:05+00", **kw}
                names = ",".join(cols)
                marks = ",".join(f":{k}" for k in cols)
                return c.execute(text(
                    f"INSERT INTO images (id,camera_id,{names}) "
                    f"VALUES (gen_random_uuid(),:cam,{marks}) RETURNING id"
                ), {"cam": camera_id, **cols}).scalar_one()

            flagged = image(reviewed=True, is_empty_frame=True)
            failed = image(is_empty_frame=False, processed_at="2026-03-10 22:00+00")
            named = image(is_empty_frame=False, processed_at="2026-03-10 22:00+00")
            clean = image(is_empty_frame=True, animal_conf=0.02,
                          processed_at="2026-03-10 22:00+00")
            autumn = image(captured_at="2026-10-10 21:00+00", is_empty_frame=False,
                           animal_conf=0.9, processed_at="2026-10-10 22:00+00")

            def deer(img, sex):
                return c.execute(text(
                    "INSERT INTO detections (id,image_id,species_id,species_conf,sex,sex_conf,"
                    "sex_attempts,age_class) VALUES (gen_random_uuid(),:i,'red_deer',0.9,:s,"
                    "0.8,1,'unknown') RETURNING id"), {"i": img, "s": sex}).scalar_one()

            spring_hind = deer(named, "female")
            autumn_hind = deer(autumn, "female")

        command.upgrade(cfg, "head")
        with eng.begin() as c:
            def row(i):
                return c.execute(text(
                    "SELECT processed_at, is_empty_frame, ai_attempts, ai_failed_at, "
                    "detector_conf FROM images WHERE id=:i"), {"i": i}).one()

            assert str(row(flagged)[0]).startswith("2026-03-10 21:05")  # its arrival, not now
            assert row(failed)[:3] == (None, None, 0)
            assert row(named)[1] is False and row(named)[0] is not None
            assert row(clean)[1] is True and row(clean)[3:] == (None, None)
            sexes = dict(c.execute(text(
                "SELECT id, sex || ':' || sex_attempts FROM detections")).all())
            assert sexes == {spring_hind: "unknown:0", autumn_hind: "female:1"}
        with eng.connect() as c:
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            from app.core.db import Base

            diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
            assert [d for d in diff if "alembic_version" not in repr(d)] == []

        command.downgrade(cfg, "0021_client_errors")
        assert not {"ai_attempts", "ai_error", "ai_failed_at", "detector_conf"} & set(
            _columns(eng, "images"))
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM images")).scalar_one() == 5

        command.upgrade(cfg, "head")
        command.stamp(cfg, "0021_client_errors")
        command.upgrade(cfg, "head")  # and again: a no-op, not an error
        assert {"ai_attempts", "ai_error", "ai_failed_at", "detector_conf"} <= set(
            _columns(eng, "images"))
    finally:
        eng.dispose()


@requires_db
def test_sit_reports_upgrade_down_and_up_again(fresh_db):
    """0023 on a real 0022 database: two live reservations of one stand on one night
    (possible before the lock) become one, keeping the sit somebody used and saying in
    the other's notes what it was; the unique index then refuses a second one; going
    back down keeps every row."""
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0022_ai_checking")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            # 0001 builds today's ORM; restore the 0022 shape first.
            c.execute(text("DROP INDEX uq_sits_stand_night_live"))
            c.execute(text("ALTER TABLE sits DROP COLUMN reported_at"))
            estate_id = c.execute(text(
                "INSERT INTO estates (id,name,timezone) "
                "VALUES (gen_random_uuid(),'Existing estate','Europe/Madrid') RETURNING id"
            )).scalar_one()
            alice, bob = (c.execute(text(
                "INSERT INTO users (id,estate_id,email,password_hash,role) "
                "VALUES (gen_random_uuid(),:e,:m,'h','member') RETURNING id"
            ), {"e": estate_id, "m": m}).scalar_one() for m in ("alice@x.local", "bob@x.local"))
            ridge, oak, pine = (c.execute(text(
                "INSERT INTO stands (id,estate_id,name) VALUES (gen_random_uuid(),:e,:n) "
                "RETURNING id"
            ), {"e": estate_id, "n": n}).scalar_one() for n in ("Ridge", "Oak", "Pine"))

            def sit(stand, user, night, outcome="unreported", started=False, mins=0, notes=None):
                return c.execute(text(
                    "INSERT INTO sits (id,stand_id,user_id,night,claimed_at,started_at,"
                    "outcome,notes) VALUES (gen_random_uuid(),:s,:u,:n,"
                    "now() - make_interval(mins => :m),"
                    "CASE WHEN :st THEN now() ELSE NULL END,:o,:notes) RETURNING id"
                ), {"s": stand, "u": user, "n": night, "o": outcome, "st": started,
                    "m": mins, "notes": notes}).scalar_one()

            # Ridge, one night: Alice reserved first, Bob sat it and reported.
            first = sit(ridge, alice, "2026-09-20", mins=30)
            used = sit(ridge, bob, "2026-09-20", outcome="seen", started=True, mins=10)
            dropped = sit(ridge, alice, "2026-09-20", outcome="cancelled", mins=40)
            # Oak: neither reported; the started one is kept, the other's note stays.
            idle = sit(oak, alice, "2026-09-21", mins=30, notes="Bring the chair")
            sat = sit(oak, bob, "2026-09-21", started=True, mins=5)
            alone = sit(pine, alice, "2026-09-20")

        command.upgrade(cfg, "head")
        with eng.begin() as c:
            rows = {r[0]: r[1:] for r in c.execute(text(
                "SELECT id, outcome, notes, reported_at FROM sits")).all()}
            assert len(rows) == 6
            assert rows[used][:2] == ("seen", None)
            assert rows[sat][:2] == ("unreported", None)
            assert rows[alone][:2] == ("unreported", None)
            assert rows[dropped][0] == "cancelled" and rows[dropped][1] is None
            assert rows[first][0] == "cancelled"
            assert rows[first][1] == (
                "Cancelled by the upgrade: a second reservation of this stand that night. "
                "Nothing was reported."
            )
            assert rows[idle][0] == "cancelled"
            assert rows[idle][1].startswith("Bring the chair\nCancelled by the upgrade")
            assert all(r[2] is None for r in rows.values()), "old sits let the next report in"
            # One live reservation per stand and night from now on; cancelled ones are history.
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(text(
                    "INSERT INTO sits (id,stand_id,night,outcome) "
                    "VALUES (gen_random_uuid(),:s,'2026-09-20','unreported')"), {"s": ridge})
            c.execute(text(
                "INSERT INTO sits (id,stand_id,night,outcome) "
                "VALUES (gen_random_uuid(),:s,'2026-09-20','cancelled')"), {"s": ridge})
        with eng.connect() as c:
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            from app.core.db import Base

            diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
            assert [d for d in diff if "alembic_version" not in repr(d)] == []

        command.downgrade(cfg, "0022_ai_checking")
        assert "reported_at" not in _columns(eng, "sits")
        assert _index(eng, "sits", "uq_sits_stand_night_live") is None
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM sits")).scalar_one() == 7
            assert c.execute(text("SELECT outcome FROM sits WHERE id=:s"),
                             {"s": first}).scalar_one() == "cancelled"

        command.upgrade(cfg, "head")
        command.stamp(cfg, "0022_ai_checking")
        command.upgrade(cfg, "head")  # and again: a no-op, not an error
        assert "reported_at" in _columns(eng, "sits")
        assert _index(eng, "sits", "uq_sits_stand_night_live") == ["stand_id", "night"]
    finally:
        eng.dispose()


@requires_db
def test_camera_retired_upgrade_down_and_up_again(fresh_db):
    """0024 on a real 0023 database: every camera arrives not retired, its photos and
    nights untouched; going down drops only the column; up again is a no-op."""
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0023_sit_reports")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            # 0001 builds today's ORM; restore the 0023 shape first.
            c.execute(text("ALTER TABLE cameras DROP COLUMN retired_at"))
            estate_id = c.execute(text(
                "INSERT INTO estates (id,name,timezone) "
                "VALUES (gen_random_uuid(),'Existing estate','Europe/Madrid') RETURNING id"
            )).scalar_one()
            cams = [c.execute(text(
                "INSERT INTO cameras (id,estate_id,name,active,name_is_custom,import_failures) "
                "VALUES (gen_random_uuid(),:e,:n,:a,false,'{}') RETURNING id"
            ), {"e": estate_id, "n": n, "a": a}).scalar_one()
                for n, a in (("PL07", True), ("PL19", False))]
            c.execute(text(
                "INSERT INTO images (id,camera_id,captured_at,reviewed) "
                "VALUES (gen_random_uuid(),:c,now(),false)"), {"c": cams[0]})
            c.execute(text(
                "INSERT INTO camera_nights (id,camera_id,night,exposure_state,frames,"
                "empty_frames) VALUES (gen_random_uuid(),:c,'2026-09-20','CONFIRMED',1,0)"),
                {"c": cams[0]})

        command.upgrade(cfg, "0024_camera_retired")
        with eng.connect() as c:
            rows = c.execute(text(
                "SELECT name, active, retired_at FROM cameras ORDER BY name")).all()
            assert [tuple(r) for r in rows] == [("PL07", True, None), ("PL19", False, None)]
            assert c.execute(text("SELECT count(*) FROM images")).scalar_one() == 1
            assert c.execute(text("SELECT count(*) FROM camera_nights")).scalar_one() == 1
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            from app.core.db import Base

            diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
            assert [d for d in diff if "alembic_version" not in repr(d)] == []

        with eng.begin() as c:
            c.execute(text("UPDATE cameras SET retired_at = now() WHERE name = 'PL07'"))
        command.downgrade(cfg, "0023_sit_reports")
        assert "retired_at" not in _columns(eng, "cameras")
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM cameras")).scalar_one() == 2

        command.upgrade(cfg, "head")
        command.stamp(cfg, "0023_sit_reports")
        command.upgrade(cfg, "head")  # and again: a no-op, not an error
        assert "retired_at" in _columns(eng, "cameras")
    finally:
        eng.dispose()


@requires_db
def test_species_fixes_upgrade_down_and_up_again(fresh_db):
    """0025 on a real 0024 database: the classifier's old names become the app's
    ("Wild Boar" -> "Wild boar", "Rabbit" -> "Hare or rabbit", "Micromammal" -> "Mouse
    or rat"), a name somebody chose stays, hidden stays hidden, sightings are kept;
    a fix records who made it and outlives that login; down and up again is safe."""
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0024_camera_retired")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            # 0001 builds today's ORM; restore the 0024 shape first.
            c.execute(text("ALTER TABLE detections DROP COLUMN corrected_by"))
            c.execute(text("ALTER TABLE detections DROP COLUMN corrected_at"))
            for key, name, hidden in (
                ("wild_boar", "Wild Boar", False), ("red_deer", "Red Deer", False),
                ("lagomorph", "Rabbit", True), ("micromammal", "Micromammal", False),
                ("mustelid", "Mustelid", False), ("fox", "Fox", False),
                ("roe_deer", "Corzo", False), ("moose", "Moose", False),
            ):
                c.execute(text("INSERT INTO species (id, common_name, is_priority, huntable, "
                               "hidden) VALUES (:k, :n, false, true, :h)"),
                          {"k": key, "n": name, "h": hidden})
            estate = c.execute(text(
                "INSERT INTO estates (id,name,timezone) VALUES (gen_random_uuid(),'E',"
                "'Europe/Madrid') RETURNING id")).scalar_one()
            cam = c.execute(text(
                "INSERT INTO cameras (id,estate_id,name,name_is_custom,active,import_failures) "
                "VALUES (gen_random_uuid(),:e,'PL19',false,true,'{}') RETURNING id"),
                {"e": estate}).scalar_one()
            img = c.execute(text(
                "INSERT INTO images (id,camera_id,captured_at,reviewed,download_attempts,"
                "ai_attempts) VALUES (gen_random_uuid(),:c,now(),false,0,0) RETURNING id"),
                {"c": cam}).scalar_one()
            c.execute(text(
                "INSERT INTO detections (id,image_id,species_id,sex,sex_attempts,age_class) "
                "VALUES (gen_random_uuid(),:i,'lagomorph','unknown',0,'unknown')"), {"i": img})

        command.upgrade(cfg, "head")
        names = {}
        with eng.begin() as c:
            names = dict(c.execute(text("SELECT id, common_name FROM species")).all())
            assert names == {
                "wild_boar": "Wild boar", "red_deer": "Red deer", "lagomorph": "Hare or rabbit",
                "micromammal": "Mouse or rat", "mustelid": "Marten or weasel", "fox": "Fox",
                "roe_deer": "Corzo", "moose": "Moose",
            }
            assert c.execute(text("SELECT hidden FROM species WHERE id='lagomorph'")).scalar()
            assert c.execute(text("SELECT count(*) FROM detections")).scalar_one() == 1
            user = c.execute(text(
                "INSERT INTO users (id,estate_id,email,password_hash,role) "
                "VALUES (gen_random_uuid(),:e,'pedro@x.es','h','member') RETURNING id"),
                {"e": estate}).scalar_one()
            c.execute(text("UPDATE detections SET species_id='wild_boar', corrected_at=now(), "
                           "corrected_by=:u"), {"u": user})
            # A removed login leaves the fix, without a name.
            c.execute(text("DELETE FROM users WHERE id=:u"), {"u": user})
            fixed = c.execute(text("SELECT species_id, corrected_at IS NOT NULL, corrected_by "
                                   "FROM detections")).one()
            assert tuple(fixed) == ("wild_boar", True, None)
        with eng.connect() as c:
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            from app.core.db import Base

            diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
            assert [d for d in diff if "alembic_version" not in repr(d)] == []

        command.downgrade(cfg, "0024_camera_retired")
        assert "corrected_at" not in _columns(eng, "detections")
        with eng.connect() as c:
            back = dict(c.execute(text("SELECT id, common_name FROM species")).all())
            assert back["wild_boar"] == "Wild Boar" and back["lagomorph"] == "Rabbit"
            assert back["roe_deer"] == "Corzo"
            assert c.execute(text("SELECT species_id FROM detections")).scalar_one() == "wild_boar"

        command.upgrade(cfg, "head")
        command.stamp(cfg, "0024_camera_retired")
        command.upgrade(cfg, "head")  # and again: a no-op, not an error
        assert {"corrected_at", "corrected_by"} <= set(_columns(eng, "detections"))
        with eng.connect() as c:
            assert dict(c.execute(text("SELECT id, common_name FROM species")).all()) == names
    finally:
        eng.dispose()


@requires_db
def test_wind_time_and_camera_clock_upgrade_down_and_up_again(fresh_db):
    """0026 on a real 0025 database: sits reserved before it keep their verdict and
    say no time for it, cameras have no clock check yet, photos stored before it have
    no receipt time, nothing else moves; down drops only the four columns; up again
    is a no-op."""
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0025_species_fixes")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            # 0001 builds today's ORM; restore the 0025 shape first.
            c.execute(text("ALTER TABLE sits DROP COLUMN wind_at"))
            c.execute(text("ALTER TABLE cameras DROP COLUMN clock_ahead_min"))
            c.execute(text("ALTER TABLE cameras DROP COLUMN clock_ok_photos"))
            c.execute(text("ALTER TABLE images DROP COLUMN received_at"))
            estate = c.execute(text(
                "INSERT INTO estates (id,name,timezone) VALUES (gen_random_uuid(),'E',"
                "'Europe/Madrid') RETURNING id")).scalar_one()
            cam = c.execute(text(
                "INSERT INTO cameras (id,estate_id,name,name_is_custom,active,import_failures) "
                "VALUES (gen_random_uuid(),:e,'Suntek',false,true,'{}') RETURNING id"),
                {"e": estate}).scalar_one()
            c.execute(text(
                "INSERT INTO images (id,camera_id,captured_at,download_attempts,reviewed,"
                "ai_attempts) VALUES (gen_random_uuid(),:c,'2026-09-20 21:00+02',0,false,0)"),
                {"c": cam})
            stand = c.execute(text(
                "INSERT INTO stands (id,estate_id,name) VALUES (gen_random_uuid(),:e,'Puente') "
                "RETURNING id"), {"e": estate}).scalar_one()
            c.execute(text(
                "INSERT INTO sits (id,stand_id,night,outcome,wind_status,wind_text) "
                "VALUES (gen_random_uuid(),:s,'2026-09-20','seen','clean','Wind S 15 km/h')"),
                {"s": stand})

        command.upgrade(cfg, "0026_wind_time_and_camera_clock")
        with eng.connect() as c:
            sit = c.execute(text("SELECT outcome, wind_status, wind_text, wind_at FROM sits")).one()
            assert tuple(sit) == ("seen", "clean", "Wind S 15 km/h", None)
            cam = c.execute(text(
                "SELECT name, clock_ahead_min, clock_ok_photos FROM cameras")).one()
            assert tuple(cam) == ("Suntek", None, None)
            img = c.execute(text("SELECT captured_at IS NOT NULL, received_at FROM images")).one()
            assert tuple(img) == (True, None)
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            from app.core.db import Base

            diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
            assert [d for d in diff if "alembic_version" not in repr(d)] == []

        with eng.begin() as c:
            c.execute(text("UPDATE sits SET wind_at = now()"))
            c.execute(text("UPDATE cameras SET clock_ahead_min = 60, clock_ok_photos = 1"))
            c.execute(text("UPDATE images SET received_at = captured_at + interval '2 min'"))
        command.downgrade(cfg, "0025_species_fixes")
        assert "wind_at" not in _columns(eng, "sits")
        assert not {"clock_ahead_min", "clock_ok_photos"} & set(_columns(eng, "cameras"))
        assert "received_at" not in _columns(eng, "images")
        with eng.connect() as c:
            assert c.execute(text("SELECT wind_status FROM sits")).scalar_one() == "clean"
            assert c.execute(text("SELECT count(*) FROM cameras")).scalar_one() == 1
            assert c.execute(text("SELECT count(*) FROM images")).scalar_one() == 1

        command.upgrade(cfg, "head")
        command.stamp(cfg, "0025_species_fixes")
        command.upgrade(cfg, "head")  # and again: a no-op, not an error
        assert "wind_at" in _columns(eng, "sits")
        assert {"clock_ahead_min", "clock_ok_photos"} <= set(_columns(eng, "cameras"))
        assert "received_at" in _columns(eng, "images")
    finally:
        eng.dispose()


@requires_db
def test_camera_location_custom_upgrade_down_and_up_again(fresh_db):
    """0027 on a real 0026 database: a placed camera with no SPYPOINT id can only have
    been placed by hand, so it is marked custom; a SPYPOINT camera keeps following
    its own GPS, as it did; positions stay through down and up again."""
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0026_wind_time_and_camera_clock")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            # 0001 builds today's ORM; restore the 0026 shape first.
            for col in ("location_is_custom", "provider_lat", "provider_lon"):
                c.execute(text(f"ALTER TABLE cameras DROP COLUMN {col}"))
            estate = c.execute(text(
                "INSERT INTO estates (id,name,timezone) VALUES (gen_random_uuid(),'E',"
                "'Europe/Madrid') RETURNING id")).scalar_one()
            for name, spy, lat, lon in (("UBox charca", None, 39.09, -1.36),
                                        ("PL19", "sp-19", 39.1, -1.35),
                                        ("FTP loma", None, None, None)):
                c.execute(text(
                    "INSERT INTO cameras (id,estate_id,name,spypoint_id,lat,lon,name_is_custom,"
                    "active,import_failures) VALUES (gen_random_uuid(),:e,:n,:s,:lat,:lon,"
                    "false,true,'{}')"), {"e": estate, "n": name, "s": spy, "lat": lat, "lon": lon})

        command.upgrade(cfg, "0027_camera_location_custom")
        with eng.connect() as c:
            rows = c.execute(text("SELECT name, lat, lon, location_is_custom, provider_lat "
                                  "FROM cameras ORDER BY name")).all()
            assert [tuple(r) for r in rows] == [
                ("FTP loma", None, None, False, None),
                ("PL19", 39.1, -1.35, False, None),
                ("UBox charca", 39.09, -1.36, True, None),
            ]
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            from app.core.db import Base

            diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
            assert [d for d in diff if "alembic_version" not in repr(d)] == []

        command.downgrade(cfg, "0026_wind_time_and_camera_clock")
        assert "location_is_custom" not in _columns(eng, "cameras")
        with eng.connect() as c:
            assert c.execute(text(
                "SELECT lat FROM cameras WHERE name='UBox charca'")).scalar_one() == 39.09

        command.upgrade(cfg, "head")
        command.stamp(cfg, "0026_wind_time_and_camera_clock")
        command.upgrade(cfg, "head")  # and again: a no-op, not an error
        assert {"location_is_custom", "provider_lat", "provider_lon"} <= set(
            _columns(eng, "cameras"))
    finally:
        eng.dispose()


@requires_db
def test_quiet_alerts_and_plan_push_upgrade_down_and_up_again(fresh_db):
    """0029 on a real 0027 database: everyone's alert choices and past alerts are
    kept, nobody has quiet hours or the plan push until they turn them on, and the
    alerts survive going down and up again."""
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "0027_camera_location_custom")
    eng = create_engine(fresh_db)
    try:
        with eng.begin() as c:
            # 0001 builds today's ORM; restore the 0027 shape first.
            for col in ("quiet_start", "quiet_end", "plan_push"):
                c.execute(text(f"ALTER TABLE notification_prefs DROP COLUMN {col}"))
            c.execute(text("ALTER TABLE notifications DROP COLUMN detail"))
            estate = c.execute(text(
                "INSERT INTO estates (id,name,timezone) VALUES (gen_random_uuid(),'E',"
                "'Europe/Madrid') RETURNING id")).scalar_one()
            user = c.execute(text(
                "INSERT INTO users (id,estate_id,email,password_hash,role) "
                "VALUES (gen_random_uuid(),:e,'ana@x.local','h','member') RETURNING id"
            ), {"e": estate}).scalar_one()
            c.execute(text(
                "INSERT INTO notification_prefs (user_id,enabled,species_ids,muted_camera_ids) "
                "VALUES (:u,true,'[\"wild_boar\"]'::jsonb,'[]'::jsonb)"), {"u": user})
            c.execute(text(
                "INSERT INTO notifications (id,user_id,kind,title,body,push_status,created_at) "
                "VALUES (gen_random_uuid(),:u,'sighting','Wild boar at PL19','1 visit at 22:14.',"
                "'sent',now())"), {"u": user})

        command.upgrade(cfg, "0029_quiet_alerts_and_plan_push")
        with eng.connect() as c:
            assert tuple(c.execute(text(
                "SELECT enabled, species_ids, quiet_start, quiet_end, plan_push "
                "FROM notification_prefs")).one()) == (True, ["wild_boar"], None, None, False)
            assert tuple(c.execute(text(
                "SELECT title, push_status, detail FROM notifications")).one()) == (
                "Wild boar at PL19", "sent", None)
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            from app.core.db import Base

            diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
            assert [d for d in diff if "alembic_version" not in repr(d)] == []
        with eng.begin() as c:
            c.execute(text("UPDATE notification_prefs SET quiet_start='23:00', "
                           "quiet_end='07:00', plan_push=true"))
            c.execute(text("UPDATE notifications SET detail='{\"visits\": 1}'::jsonb"))

        command.downgrade(cfg, "0027_camera_location_custom")
        assert "plan_push" not in _columns(eng, "notification_prefs")
        assert "detail" not in _columns(eng, "notifications")
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM notifications")).scalar_one() == 1

        command.upgrade(cfg, "head")
        command.stamp(cfg, "0027_camera_location_custom")
        command.upgrade(cfg, "head")  # and again: a no-op, not an error
        assert {"quiet_start", "quiet_end", "plan_push"} <= set(
            _columns(eng, "notification_prefs"))
        assert "detail" in _columns(eng, "notifications")
    finally:
        eng.dispose()
