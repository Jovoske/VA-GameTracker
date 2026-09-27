"""Safe deploys (plan item 3): the server says truthfully whether it works, what it
runs and how its own upkeep went, keeps its photos findable when the media folder
moves, never fills its disk with photos, and a deploy holds every job off while the
code and the schema change.

Each test is a rule the owner would notice: a deploy rolled back because /api/health
said the database was down (H-07); "App version" saying which commit runs and why an
update didn't go in, not "Up to date" from a check that never ran (D-22); "Last
backup 2 days ago" in red (H-10); a photo that still opens after the media folder
moved to D: (H-21); no photo fetch on a nearly full disk (H-18); a quoted .env value
read the same by every part of the server (H-15); a plan run that waited through a
deploy starting again on the new code (H-09).
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PImage
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import jobs, media, ops
from app.core.config import settings
from app.core.security import create_access_token
from app.models import Camera, Estate, Image, User
from app.version import __version__, read_commit

from .conftest import requires_db

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(db_session):
    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def estate(db_session):
    e = Estate(name="Piedras Lisas", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db_session.add(e)
    db_session.commit()
    return e


def _user(db, estate, role="admin"):
    u = User(estate_id=estate.id, email=f"{role}-{uuid.uuid4().hex[:6]}@estate.local",
             password_hash="x", role=role)
    db.add(u)
    db.commit()
    return u, {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


def _write_status(name: str, value, *, bom: bool = False) -> None:
    path = jobs.data_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, str) else json.dumps(value)
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + raw.encode("utf-8"))


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── /api/health and /api/ready tell the truth (H-07) ───────────────────────────


@requires_db
def test_health_is_ok_only_with_the_database_and_names_the_version(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] is True
    assert body["version"] == __version__ and body["version"] != "0.1.0"
    assert body["commit"] == read_commit()


def test_health_is_503_when_the_database_is_down():
    from app.core.db import get_db
    from app.main import app

    # Nothing listens on port 1: the deploy must read this as "not healthy".
    down = sessionmaker(bind=create_engine(
        "postgresql+psycopg://nobody@127.0.0.1:1/none?connect_timeout=2"))()
    app.dependency_overrides[get_db] = lambda: down
    try:
        with TestClient(app) as c:
            r = c.get("/api/health")
            assert r.status_code == 503
            assert r.json()["status"] == "down" and r.json()["database"] is False
            ready = c.get("/api/ready")
            assert ready.status_code == 503 and ready.json()["checks"]["database"] is False
    finally:
        app.dependency_overrides.clear()
        down.close()


def test_the_api_says_its_own_version():
    from app.main import app

    assert app.version == __version__


@requires_db
def test_ready_wants_the_schema_at_the_codes_head_and_no_redis_unless_it_is_used(
    client, db_session, monkeypatch,
):
    from app.api import routes_health

    head = routes_health.code_head()
    assert head and head[:4].isdigit()
    # create_all, never migrated: no alembic_version, so not ready.
    r = client.get("/api/ready")
    assert r.status_code == 503 and r.json()["checks"] == {"database": True, "schema": False}
    db_session.execute(text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"))
    db_session.execute(text("INSERT INTO alembic_version VALUES ('0001_initial')"))
    db_session.commit()
    body = client.get("/api/ready").json()
    assert body["checks"]["schema"] is False and body["schema"] == "0001_initial"
    db_session.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": head})
    db_session.commit()
    r = client.get("/api/ready")
    # The native server has no Redis and no Celery: it is not asked about.
    assert r.status_code == 200 and r.json()["checks"] == {"database": True, "schema": True}
    # Where a broker is configured (the Docker stack), Redis down is not ready.
    monkeypatch.setattr(routes_health, "_broker_in_use", lambda: True)
    monkeypatch.setattr(routes_health, "_redis", lambda: False)
    r = client.get("/api/ready")
    assert r.status_code == 503 and r.json()["checks"]["redis"] is False


def test_a_broker_counts_as_in_use_only_when_redis_is_configured(monkeypatch):
    from app.api import routes_health
    from app.core.config import Settings

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(routes_health, "settings", Settings(_env_file=None))
    assert routes_health._broker_in_use() is False
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setattr(routes_health, "settings", Settings(_env_file=None))
    assert routes_health._broker_in_use() is True


# ── the commit this process runs, read without git (for the deploy's check) ─────


def _repo(tmp_path, head: str) -> Path:
    git = tmp_path / "repo" / ".git"
    git.mkdir(parents=True)
    (git / "HEAD").write_text(head)
    return git


def test_the_commit_is_read_from_a_loose_ref_a_packed_ref_or_a_detached_head(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv("GAMESENSE_COMMIT", raising=False)
    a, b = "a" * 40, "b" * 40
    git = _repo(tmp_path, "ref: refs/heads/main\n")
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "refs" / "heads" / "main").write_text(a + "\n")
    assert read_commit(git.parent) == a
    (git / "refs" / "heads" / "main").unlink()
    (git / "packed-refs").write_text(f"# pack-refs with: peeled\n{b} refs/heads/main\n")
    assert read_commit(git.parent) == b
    (git / "HEAD").write_text(a)
    assert read_commit(git.parent) == a
    monkeypatch.setenv("GAMESENSE_COMMIT", b)
    assert read_commit(git.parent) == b


def test_the_commit_of_a_worktree_is_found_through_its_gitdir(tmp_path, monkeypatch):
    monkeypatch.delenv("GAMESENSE_COMMIT", raising=False)
    common = tmp_path / "main" / ".git"
    (common / "refs" / "heads").mkdir(parents=True)
    (common / "refs" / "heads" / "lane").write_text("c" * 40)
    wt_git = common / "worktrees" / "lane"
    wt_git.mkdir(parents=True)
    (wt_git / "HEAD").write_text("ref: refs/heads/lane\n")
    (wt_git / "commondir").write_text("../..\n")
    checkout = tmp_path / "lane"
    checkout.mkdir()
    (checkout / ".git").write_text(f"gitdir: {wt_git}\n")
    assert read_commit(checkout) == "c" * 40
    assert read_commit(tmp_path / "nowhere") is None


# ── .env read the same everywhere (H-15) ──────────────────────────────────────


def test_serve_reads_env_as_pydantic_does_quotes_and_notes_are_not_the_value(
    tmp_path, monkeypatch,
):
    import importlib.util

    spec = importlib.util.spec_from_file_location("serve_under_test", BACKEND / "serve.py")
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    env = tmp_path / ".env"
    env.write_text('ESTATE_TIMEZONE="Europe/Madrid"\n'
                   "SPYPOINT_PASSWORD=abc#123 # my note\n"
                   "GS_TEST_KEPT=from-file\n", encoding="utf-8")
    for key in ("ESTATE_TIMEZONE", "SPYPOINT_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GS_TEST_KEPT", "from-environment")
    serve.load_env(env)
    assert os.environ["ESTATE_TIMEZONE"] == "Europe/Madrid"
    assert os.environ["SPYPOINT_PASSWORD"] == "abc#123"
    assert os.environ["GS_TEST_KEPT"] == "from-environment"  # the environment wins
    # What alembic and the FTP importer read, through pydantic-settings alone.
    from app.core.config import Settings

    for key in ("ESTATE_TIMEZONE", "SPYPOINT_PASSWORD"):
        monkeypatch.delenv(key)
    alone = Settings(_env_file=str(env))
    assert (alone.estate_timezone, alone.spypoint_password) == ("Europe/Madrid", "abc#123")


def test_the_pipeline_loads_env_the_same_way():
    source = (BACKEND / "pipeline.py").read_text(encoding="utf-8")
    assert "load_dotenv(" in source and "setdefault" not in source
    assert "python-dotenv" in (BACKEND / "requirements.txt").read_text()


# ── what the server's upkeep did, for Settings (D-22, H-10) ────────────────────


def test_no_status_file_means_the_task_never_ran_here():
    assert ops.deploy() is None and ops.backup() is None and ops.restore_check() is None


def test_the_deploy_status_says_what_runs_and_why_an_update_did_not_go_in():
    now = datetime(2026, 9, 27, 20, 0, tzinfo=UTC)
    _write_status(ops.DEPLOY_FILE, {
        "checked_at": _iso(now - timedelta(minutes=4)), "source": "deploy",
        "running": "a" * 40, "running_subject": "Wind by the hour",
        "running_since": _iso(now - timedelta(days=2)), "waiting_for_tests": 2,
        "state": "failed",
        "failed": {"commit": "b" * 40, "subject": "New map", "step": "build",
                   "reason": "The app's screens didn't build.", "at": _iso(now),
                   "attempts": 2, "gave_up": False, "rolled_back": True},
    }, bom=True)  # Windows PowerShell 5.1 may write a byte-order mark
    d = ops.deploy(now)
    assert d["late"] is False and d["source"] == "deploy" and d["waiting_for_tests"] == 2
    assert d["running"] == "a" * 40 and d["running_since"] == now - timedelta(days=2)
    assert d["failed"]["step"] == "build" and d["failed"]["attempts"] == 2
    assert d["failed"]["rolled_back"] is True and d["failed"]["gave_up"] is False
    # Three missed runs of a 10-minute task: it has stopped.
    assert ops.deploy(now + timedelta(minutes=40))["late"] is True


def test_a_backup_is_late_after_36_hours_and_a_failed_night_keeps_the_last_good_one():
    now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    _write_status(ops.BACKUP_FILE, {
        "finished_at": _iso(now - timedelta(hours=9)), "ok": True,
        "target": r"D:\GameSense-Backup", "dump_mb": 412.5, "photos_on_server": 120,
        "photos_in_backup": 121, "target_free_gb": 800.1,
    })
    b = ops.backup(now)
    assert b["ok"] and not b["late"] and b["dump_mb"] == 412.5
    assert (b["photos_on_server"], b["photos_in_backup"]) == (120, 121)
    assert ops.backup(now + timedelta(hours=30))["late"] is True
    _write_status(ops.BACKUP_FILE, {
        "finished_at": _iso(now), "ok": False, "error": "D: is not there.",
        "last_ok_at": _iso(now - timedelta(hours=40)),
    })
    b = ops.backup(now)
    assert b["ok"] is False and b["late"] is True and b["error"] == "D: is not there."
    assert b["last_ok_at"] == now - timedelta(hours=40)
    _write_status(ops.BACKUP_FILE, "{half a file")
    b = ops.backup(now)
    assert b["ok"] is False and b["late"] is True and "can't be read" in b["error"]


@requires_db
def test_settings_shows_the_deploy_backup_and_restore_check_to_admins_only(
    client, db_session, estate,
):
    now = datetime.now(UTC)
    _write_status(ops.DEPLOY_FILE, {"checked_at": _iso(now), "source": "main",
                                    "running": "d" * 40, "state": "current"})
    _write_status(ops.BACKUP_FILE, {"finished_at": _iso(now - timedelta(hours=50)), "ok": True})
    _write_status(ops.RESTORE_FILE, {"finished_at": _iso(now - timedelta(days=2)), "ok": True,
                                     "photos_checked": 20, "photos_found": 20})
    _, admin = _user(db_session, estate)
    _, viewer = _user(db_session, estate, "viewer")
    v = client.get("/api/admin/version", headers=admin).json()
    assert v["version"] == __version__ and v["deploy"]["source"] == "main"
    assert v["deploy"]["running"] == "d" * 40 and v["deploy"]["failed"] is None
    s = client.get("/api/admin/status", headers=admin).json()
    assert s["backup"]["late"] is True and s["backup"]["ok"] is True
    assert s["restore_check"]["ok"] is True and s["restore_check"]["photos_found"] == 20
    assert client.get("/api/admin/version", headers=viewer).status_code == 403
    assert client.get("/api/admin/status", headers=viewer).status_code == 403
    # An app copy from before: it shows the error line, never "Up to date".
    old = client.get("/api/admin/version/check", headers=admin).json()
    assert old["update_available"] is False and "Reload the app" in old["error"]


# ── photos findable when the media folder moves (H-21) ────────────────────────


def test_paths_are_stored_under_media_root_and_found_wherever_it_is(tmp_path, monkeypatch):
    root = tmp_path / "media"
    monkeypatch.setattr(settings, "media_root", str(root))
    estate_id, camera_id = uuid.uuid4(), uuid.uuid4()
    photo = root / str(estate_id) / str(camera_id) / "2026-09-01" / "sp-1.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"jpeg")
    rel = media.stored(photo)
    assert rel == f"{estate_id}/{camera_id}/2026-09-01/sp-1.jpg"
    assert media.resolve(rel) == str(photo)
    # Outside the media folder (a hand-made test row): kept as given.
    assert media.stored("/elsewhere/x.jpg") == "/elsewhere/x.jpg"
    # An absolute path from before, where the file still is: as it says.
    assert media.resolve(str(photo)) == str(photo)
    # The folder moved to D:, the old absolute path is gone: found under the new root.
    old = f"C:\\GameSense\\data\\media\\{estate_id}\\{camera_id}\\2026-09-01\\sp-1.jpg"
    assert media.resolve(old) == str(photo)
    thumb = root / "thumbs" / "ab" / "abc.webp"
    thumb.parent.mkdir(parents=True)
    thumb.write_bytes(b"webp")
    assert media.resolve("/data/media/thumbs/ab/abc.webp") == str(thumb)
    # Nowhere at all: the likeliest place, so the caller's "missing" check says so.
    assert media.resolve("/gone/for/good.jpg") == "/gone/for/good.jpg"
    assert media.resolve(None) is None and media.resolve("") is None


@requires_db
def test_a_photo_stored_before_the_media_folder_moved_still_opens(
    client, db_session, estate, tmp_path, monkeypatch,
):
    new_root = tmp_path / "D" / "GameSense-media"
    monkeypatch.setattr(settings, "media_root", str(new_root))
    cam = Camera(estate_id=estate.id, name="Charca", lat=39.09, lon=-1.36)
    db_session.add(cam)
    db_session.commit()
    at = datetime(2026, 9, 20, 21, 0, tzinfo=UTC)
    moved = new_root / str(estate.id) / str(cam.id) / "2026-09-20" / "sp-9.jpg"
    moved.parent.mkdir(parents=True)
    PImage.new("RGB", (64, 48), (90, 120, 60)).save(moved, "JPEG")
    # Written when the photos lived on C:, as every importer wrote them then.
    old = f"C:\\GameSense\\data\\media\\{estate.id}\\{cam.id}\\2026-09-20\\sp-9.jpg"
    img = Image(camera_id=cam.id, captured_at=at, original_path=old, is_empty_frame=False)
    db_session.add(img)
    db_session.commit()
    _, admin = _user(db_session, estate)
    r = client.get(f"/api/images/{img.id}/file", headers=admin)
    assert r.status_code == 200 and r.content == moved.read_bytes()
    r = client.get(f"/api/images/{img.id}/thumb", headers=admin)
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    db_session.refresh(img)
    assert img.thumbnail_path == f"thumbs/{str(img.id)[:2]}/{img.id}.webp"


@requires_db
def test_the_ubox_cleanup_knows_a_file_by_either_kind_of_path(db_session, estate, tmp_path,
                                                             monkeypatch):
    from sqlalchemy import select

    monkeypatch.setattr(settings, "media_root", str(tmp_path / "media"))
    cam = Camera(estate_id=estate.id, name="UBox", lat=39.09, lon=-1.36)
    db_session.add(cam)
    db_session.commit()
    path = tmp_path / "media" / str(estate.id) / str(cam.id) / "2026-09-20" / "ubox_1.jpg"
    for stored in (media.stored(path), str(path)):
        img = Image(camera_id=cam.id, captured_at=datetime.now(UTC), original_path=stored)
        db_session.add(img)
        db_session.commit()
        assert db_session.scalar(select(Image.id).where(
            media.same_file(Image.original_path, path))) == img.id
        db_session.delete(img)
        db_session.commit()


# ── no photo fetch on a nearly full disk (H-18) ───────────────────────────────


@requires_db
def test_a_nearly_full_disk_stops_the_download_and_says_why(db_session, monkeypatch):
    from app.ingestion import fetch, sync, ubox_sync

    called = []
    monkeypatch.setattr(sync, "sync_all", lambda db: called.append("spypoint") or {})
    monkeypatch.setattr(ubox_sync, "sync_ubox_all", lambda db: called.append("ubox") or {})
    monkeypatch.setattr(ops, "disk_free", lambda path=None: 3 * 1024**3)
    row, results = fetch.fetch_photos(db_session)
    assert called == []
    assert row.status == "error" and row.images_downloaded == 0
    assert row.details["problems"] == [{
        "label": "Server disk",
        "error": "Nearly full (3.0 GB free). The photos wait on the cameras and come in "
                 "once there is room."}]
    monkeypatch.setattr(ops, "disk_free", lambda path=None: 50 * 1024**3)
    monkeypatch.setattr(sync, "sync_all", lambda db: called.append("spypoint")
                        or {"status": "ok", "total": 0})
    monkeypatch.setattr(ubox_sync, "sync_ubox_all", lambda db: called.append("ubox")
                        or {"status": "skipped", "total": 0})
    row, _ = fetch.fetch_photos(db_session)
    assert called == ["spypoint", "ubox"] and row.status == "ok"


@requires_db
@pytest.mark.parametrize("provider", ["spypoint", "ubox"])
def test_a_new_login_and_the_history_pull_wait_for_room_too(
    db_session, estate, monkeypatch, provider,
):
    """A new login's first import and "Get older photos" are the biggest downloads of
    all: on a nearly full disk they download nothing either, and the Check button and
    Settings say why (R7BE-5). The photos already in are still checked."""
    import pipeline
    from app.ingestion import fetch, sync, ubox_sync
    from app.models import CameraAccount

    pulled, checked = [], []
    for module, name in ((sync, "backfill_all"), (sync, "backfill_account"),
                         (ubox_sync, "backfill_ubox_account")):
        monkeypatch.setattr(module, name, lambda *a, _n=name, **kw: pulled.append(_n) or {})
    monkeypatch.setattr(fetch, "check_and_recount",
                        lambda db: checked.append(True) or ({"ai": {}}, None))
    monkeypatch.setattr(pipeline, "plan_catch_up", lambda db: None)
    monkeypatch.setattr(ops, "disk_free", lambda path=None: 2 * 1024**3)
    login = CameraAccount(estate_id=estate.id, provider=provider, username="guest",
                          password_enc="x")
    db_session.add(login)
    db_session.commit()
    for mode, args in (("backfill", ["13"]), ("login", [str(login.id)])):
        assert pipeline._run(mode, args, db_session) == 0
        row = fetch.latest_run(db_session)
        assert row.status == "error" and row.images_downloaded == 0
        assert row.details["stage"] == "done" and row.finished_at is not None
        assert row.details["problems"] == [{
            "label": "Server disk",
            "error": "Nearly full (2.0 GB free). The photos wait on the cameras and come in "
                     "once there is room."}]
    assert pulled == [] and checked == [True, True]
    # With room, they download as before.
    monkeypatch.setattr(ops, "disk_free", lambda path=None: 50 * 1024**3)
    pipeline._run("backfill", ["13"], db_session)
    pipeline._run("login", [str(login.id)], db_session)
    first = "backfill_ubox_account" if provider == "ubox" else "backfill_account"
    assert pulled == ["backfill_all", first]


def test_a_test_database_is_named_in_any_form_of_dsn():
    """The laptop DSN in the README has no query string: the test databases must still
    be databases of their own, not the server's postgres one (R7BE-8)."""
    from .conftest import alembic_config, dsn_for

    laptop = "postgresql+psycopg://postgres:postgres@localhost:5432/"
    assert dsn_for("gs_x", laptop + "postgres") == laptop + "gs_x"
    ci = "postgresql+psycopg://postgres:p%40ss@localhost/{}?sslmode=disable"
    assert dsn_for("gs_x", ci.format("postgres")) == ci.format("gs_x")
    from sqlalchemy.engine import make_url

    socket = dsn_for("gs_x", "postgresql+psycopg://postgres@/postgres?host=/tmp&port=55432")
    url = make_url(socket)
    assert url.database == "gs_x" and dict(url.query) == {"host": "/tmp", "port": "55432"}
    # alembic's config reads % as an interpolation: the DSN must come back as it went in.
    assert alembic_config(socket).get_main_option("sqlalchemy.url") == socket


# ── a deploy holds every job off (H-09) ───────────────────────────────────────


class _Closes:
    """A deploy's end of the pipe: open until `close()`."""

    def __init__(self):
        self._r, self._w = os.pipe()
        self.stream = io.TextIOWrapper(os.fdopen(self._r, "rb"))

    def close(self):
        os.close(self._w)


def test_hold_takes_every_jobs_lock_until_the_deploy_is_done(capsys):
    import pipeline

    end = _Closes()
    out: list[int] = []
    t = threading.Thread(target=lambda: out.append(pipeline.hold(end.stream)))
    t.start()
    deadline = time.monotonic() + 5
    while jobs.holder("notify") is None and time.monotonic() < deadline:
        time.sleep(0.02)
    for name in pipeline.DEPLOY_LOCKS:
        assert jobs.holder(name).owner == "deploy"
    # While it holds them, a scheduled sync gives way and the deploy reads as busy.
    assert jobs.try_acquire("pipeline", "sync") is None
    assert pipeline.main(["busy"]) == pipeline.BUSY_EXIT
    end.close()
    t.join(5)
    assert out == [0] and all(jobs.holder(n) is None for n in pipeline.DEPLOY_LOCKS)
    printed = capsys.readouterr().out
    assert printed.splitlines()[0] == "held" and "released" in printed


def test_hold_is_refused_while_a_job_runs_and_holds_nothing(capsys):
    import pipeline

    sex = jobs.try_acquire("sexpass", "sex")
    assert pipeline.hold(io.StringIO("")) == pipeline.BUSY_EXIT
    assert "busy: sex" in capsys.readouterr().out
    assert jobs.holder("pipeline") is None and jobs.holder("notify") is None
    sex.release()


def test_hold_lets_go_after_its_limit_if_the_deploy_never_says(monkeypatch):
    import pipeline

    monkeypatch.setattr(pipeline, "HOLD_MAX_SECONDS", 0.2)
    end = _Closes()
    assert pipeline.hold(end.stream) == 0
    assert jobs.holder("pipeline") is None
    end.close()


@pytest.fixture
def runner(monkeypatch):
    import pipeline

    ran: list = []
    monkeypatch.setattr(pipeline, "configure_logging", lambda **kw: None)
    monkeypatch.setattr(pipeline, "_run", lambda mode, args, db: ran.append((mode, args)) or 0)
    monkeypatch.setattr(pipeline, "POLL_SECONDS", 0.05)
    monkeypatch.setattr(pipeline, "WAIT_SECONDS", 3)
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _NullSession())
    return pipeline, ran


class _NullSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_run_that_waited_through_a_deploy_starts_again_on_the_new_code(runner, monkeypatch):
    pipeline, ran = runner
    commits = iter(["old", "new"])
    monkeypatch.setattr(pipeline, "read_commit", lambda: next(commits))
    again: list = []
    monkeypatch.setattr(pipeline, "again", lambda argv: again.append(argv) or 0)
    deploy = jobs.try_acquire("pipeline", "deploy")
    threading.Timer(0.3, deploy.release).start()
    assert pipeline.main(["plan"]) == 0
    assert again == [["plan"]] and ran == []
    assert jobs.holder("pipeline") is None  # given back before starting over


def test_a_run_that_waited_on_the_same_code_just_runs(runner, monkeypatch):
    pipeline, ran = runner
    monkeypatch.setattr(pipeline, "read_commit", lambda: "same")
    monkeypatch.setattr(pipeline, "again", lambda argv: pytest.fail("no restart"))
    sync = jobs.try_acquire("pipeline", "sync")
    threading.Timer(0.3, sync.release).start()
    assert pipeline.main(["score"]) == 0 and ran == [("score", [])]


@requires_db
def test_the_check_button_during_a_deploy_says_the_server_is_updating(
    client, db_session, estate, spawned,
):
    _, member = _user(db_session, estate, "member")
    deploy = jobs.try_acquire("pipeline", "deploy")
    try:
        r = client.post("/api/cameras/sync", headers=member).json()
        assert r["status"] == "queued" and "installing an update" in r["note"]
        assert spawned == [("sync", "queued")]
    finally:
        deploy.release()


@requires_db
def test_the_stag_and_hind_pass_during_a_deploy_is_not_called_running(
    client, db_session, estate, monkeypatch, spawned,
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    _, admin = _user(db_session, estate)
    deploy = jobs.try_acquire("sexpass", "deploy")
    try:
        r = client.post("/api/admin/sex-pass", headers=admin).json()
        assert r["status"] == "busy" and "installing an update" in r["note"]
        assert client.get("/api/admin/status", headers=admin).json()["sex_pass"]["running"] is False
        assert spawned == []
    finally:
        deploy.release()


# ── the restore rehearsal (H-10) ──────────────────────────────────────────────


@pytest.fixture
def restored_db(admin_engine):
    """A second database, for the restored copy (fresh_db is the live one here)."""
    from app.core.db import Base

    from .conftest import dsn_for

    name = f"gs_restored_{uuid.uuid4().hex[:10]}"
    with admin_engine.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    dsn = dsn_for(name)
    eng = create_engine(dsn)
    Base.metadata.create_all(eng)
    eng.dispose()
    try:
        yield dsn
    finally:
        with admin_engine.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@requires_db
def test_the_restore_check_compares_the_copy_and_finds_its_photos_in_the_backup(
    db_session, restored_db, estate, tmp_path,
):
    from app import backup_check

    live_url = db_session.get_bind().url.render_as_string(hide_password=False)
    restored = create_engine(restored_db)
    backup = tmp_path / "D" / "GameSense-Backup" / "media"
    cam = Camera(estate_id=estate.id, name="Charca", lat=39.09, lon=-1.36)
    db_session.add(cam)
    db_session.commit()
    rel = f"{estate.id}/{cam.id}/2026-09-20/sp-1.jpg"
    old = f"C:\\GameSense\\data\\media\\{estate.id}\\{cam.id}\\2026-09-20\\sp-2.jpg"
    at = datetime(2026, 9, 20, 21, 0, tzinfo=UTC)
    for path in (rel, old):
        db_session.add(Image(camera_id=cam.id, captured_at=at, original_path=path))
    db_session.commit()
    # The restored copy: the estate, the camera and the two photos, as last night had them.
    with sessionmaker(bind=restored)() as copy:
        copy.add(Estate(id=estate.id, name=estate.name, timezone=estate.timezone,
                        lat=estate.lat, lon=estate.lon))
        copy.flush()
        copy.add(Camera(id=cam.id, estate_id=estate.id, name=cam.name, lat=cam.lat, lon=cam.lon))
        copy.flush()
        for path in (rel, old):
            copy.add(Image(camera_id=cam.id, captured_at=at, original_path=path))
        copy.commit()
    (backup / str(estate.id) / str(cam.id) / "2026-09-20").mkdir(parents=True)
    (backup / rel).write_bytes(b"jpeg")
    result = backup_check.verify(live_url, restored_db, backup)
    # One photo's file is not in the backup: that is the finding.
    assert result["ok"] is False and result["photos_checked"] == 2
    assert result["photos_found"] == 1 and "1 of 2 photos" in result["error"]
    assert result["tables"]["images"] == {"live": 2, "restored": 2}
    (backup / str(estate.id) / str(cam.id) / "2026-09-20" / "sp-2.jpg").write_bytes(b"jpeg")
    result = backup_check.verify(live_url, restored_db, backup)
    assert result["ok"] is True and result["photos_found"] == 2 and result["error"] is None
    out = backup_check.record(result, str(tmp_path / "gamesense-20260927-030000.dump"))
    assert out["dump"] == "gamesense-20260927-030000.dump"
    r = ops.restore_check()
    assert r["ok"] is True and r["late"] is False and r["photos_found"] == 2
    restored.dispose()


@requires_db
def test_an_empty_restore_is_no_restore(db_session, restored_db, estate):
    from app import backup_check

    live_url = db_session.get_bind().url.render_as_string(hide_password=False)
    cam = Camera(estate_id=estate.id, name="Charca", lat=39.09, lon=-1.36)
    db_session.add(cam)
    db_session.commit()
    db_session.add(Image(camera_id=cam.id, captured_at=datetime.now(UTC), original_path="x.jpg"))
    db_session.commit()
    result = backup_check.verify(live_url, restored_db, "/nowhere")
    assert result["ok"] is False and "no rows in images" in result["error"]


def test_a_restore_that_failed_is_recorded_as_such(capsys):
    from app import backup_check

    assert backup_check.main(["--restored-db", "x", "--media", "/m", "--dump", "d.dump",
                              "--error", "pg_restore failed (see restore-check.log)."]) == 1
    r = ops.restore_check()
    assert r["ok"] is False and r["error"] == "pg_restore failed (see restore-check.log)."


# ── the deploy scripts themselves (K-09, H-04, H-05, H-09) ─────────────────────

DEPLOY = BACKEND.parent / "deploy"


def test_the_update_deploys_in_the_safe_order():
    """update.ps1's steps, in the order they run: the job locks first, the code, the
    packages and the build (nothing live yet), the backup, the migration, only then
    the new screens and the restart, and the commit counts as deployed only once the
    new version answered. The helpers are defined above the steps, so the steps are
    found by what only the step itself says."""
    script = (DEPLOY / "update.ps1").read_text()
    steps = ["$held = Start-Hold", "git reset --hard $target", "Note 'pip install'",
             'serve.py" check', "vite.js", "-Fc -f $dump", 'alembic.exe" upgrade head',
             'robocopy "$app\\frontend\\dist" $web', "\nRestart-GameSense\n",
             "Test-Healthy $target $HealthSeconds", "Write-TextFile $shaFile $target",
             "Stop-Hold\n$status.state = 'current'"]
    at = [script.index(step) for step in steps]
    assert at == sorted(at), [s for s, a, b in zip(steps, at, sorted(at), strict=True) if a != b]


def test_the_update_takes_tested_commits_and_keeps_its_timing():
    script = (DEPLOY / "update.ps1").read_text()
    # The deploy branch CI moves, main only while there is none; never main because
    # GitHub didn't answer.
    assert "ls-remote origin 'refs/heads/deploy'" in script
    assert script.index("$status.state = 'offline'") < script.index("$status.source = 'main'")
    # Every 10 minutes at any hour (owner's decision): no evening pause.
    assert not any(word in script.lower() for word in ("sunset", "freeze", "quiet hours"))
    # A failed health check puts the old commit, screens and service back.
    fail = script[script.index("function Fail("):script.index("function Try-Twice")]
    for undo in ("git reset --hard $good", "robocopy $webPrev $web", "Restart-GameSense"):
        assert undo in fail, undo


TASKS = ("GameSense-Update", "GameSense-Sync", "GameSense-Notify", "GameSense-Sex",
         "GameSense-Plan", "GameSense-Score", "GameSense-Backup", "GameSense-RestoreCheck")


def test_every_task_keeps_its_errors_in_a_file_of_its_own():
    """cmd.exe keeps a `2>>` redirect open, and shut to other writers, until the job
    ends: with one file for every task, a task starting while another ran never
    started at all (review R7BE-1). Each writes logs\\task-<job>.err.log, named after
    what it runs, and update.ps1 and backup.ps1 roll those over."""
    import re

    script = (DEPLOY / "register-tasks.ps1").read_text()
    for task in TASKS:
        assert f"'{task}'" in script, task
    assert "(Every 10) 120" in script  # the update: every 10 minutes, any hour
    runs = re.findall(r"\((?:Pipeline|Script)-Action '([^']+)'\)", script)
    jobs_run = [Path(r).stem for r in runs]
    assert len(jobs_run) == len(TASKS) and len(set(jobs_run)) == len(jobs_run), jobs_run
    for action in ("function Pipeline-Action", "function Script-Action"):
        body = script[script.index(action):script.index("\n}", script.index(action))]
        assert '1>NUL 2>>`"$(Task-Errors' in body, action
    assert 'function Task-Errors([string]$Job) { return "$logs\\task-$Job.err.log" }' in script
    assert "tasks-stderr.log" not in script
    for rolls in ("update.ps1", "backup.ps1"):
        assert "Limit-TaskLogs $logs" in (DEPLOY / rolls).read_text(), rolls


def test_the_jobs_log_no_line_per_http_request():
    """stderr is what a task's error file keeps: httpx's INFO line for every photo
    download (a signed address each) buried the reason a job died (R7BE-7)."""
    import logging

    from app.core.logging import configure_logging

    configure_logging()
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING, name


def _pwsh() -> str | None:
    import shutil

    return os.environ.get("GS_PWSH") or shutil.which("pwsh")


@pytest.mark.skipif(_pwsh() is None, reason="PowerShell (pwsh) is not installed here")
def test_the_deploy_scripts_parse():
    """Every script parses as PowerShell (CI's runners have pwsh). Db01 runs Windows
    PowerShell 5.1, so the scripts also keep to what it knows (lib.ps1's header)."""
    import subprocess

    scripts = sorted(DEPLOY.glob("*.ps1"))
    files = ", ".join(f"'{f}'" for f in scripts)
    parser = "[System.Management.Automation.Language.Parser]"
    check = (f"$bad = 0; foreach ($f in @({files})) {{ $e = $null; "
             f"[void]{parser}::ParseFile($f, [ref]$null, [ref]$e); "
             "foreach ($x in $e) { Write-Output \"${f}: $x\"; $bad++ } }; exit $bad")
    run = subprocess.run([_pwsh(), "-NoProfile", "-NonInteractive", "-Command", check],
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    for f in scripts:
        lines = f.read_text().splitlines()
        code = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
        for newer in ("??", "?.", "&&", "||", "-Parallel", "ConvertFrom-Json -AsHashtable"):
            assert newer not in code, f"{f.name}: {newer} is not in PowerShell 5.1"


# ── the deploy scripts, run (with pwsh; Windows-only commands stood in for) ───────

needs_pwsh = pytest.mark.skipif(_pwsh() is None, reason="PowerShell (pwsh) is not installed here")


def _ps(tmp_path: Path, body: str, timeout: int = 120):
    """Run `body` as a PowerShell script; (exit code, output)."""
    import subprocess

    script = tmp_path / f"run-{uuid.uuid4().hex[:6]}.ps1"
    script.write_text(body, encoding="utf-8")
    run = subprocess.run([_pwsh(), "-NoProfile", "-NonInteractive", "-File", str(script)],
                         capture_output=True, text=True, timeout=timeout)
    return run.returncode, run.stdout + run.stderr


def _shim(path: Path, target: str, env: str = "") -> None:
    """A stand-in for a Windows tool: `target` with the arguments' \\ turned into /
    (the scripts build Windows paths, which reach a native tool as they are)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\n" + env +
                    'args=(); for a in "$@"; do args+=("${a//\\\\//}"); done\n'
                    f'exec {target} "${{args[@]}}"\n')
    path.chmod(0o755)


def _server(tmp_path: Path, **env: str) -> Path:
    """A fake C:\\GameSense: its .env, a data folder, and the photo folder."""
    root = tmp_path / "GameSense"
    backend = root / "app" / "backend"
    backend.mkdir(parents=True)
    (root / "data" / "models").mkdir(parents=True)
    values = {"DATABASE_URL": "postgresql+psycopg://gs:pw@localhost:5432/gamesense",
              "MODELS_ROOT": str(root / "data" / "models"),
              "MEDIA_ROOT": str(root / "data" / "media"),
              "BACKUP_DIR": str(tmp_path / "D" / "GameSense-Backup"), **env}
    (backend / ".env").write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    return root


@needs_pwsh
def test_every_task_is_registered_with_its_own_error_file_and_its_start(tmp_path):
    """register-tasks.ps1 run for real, Task Scheduler stood in for: eight tasks, no
    two writing the same error file, none running twice at once, the update every 10
    minutes from midnight (the owner's timing) and the others a minute or two apart."""
    root = _server(tmp_path)
    for f in (root / "venv" / "Scripts" / "python.exe", root / "app" / "backend" / "pipeline.py"):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("")
    code, out = _ps(tmp_path, f"""
$global:tasks = @()
function global:New-ScheduledTaskAction {{ [CmdletBinding()]
    param($Execute, $WorkingDirectory, $Argument)
    [pscustomobject]@{{ Execute = $Execute; Argument = $Argument }} }}
function global:New-ScheduledTaskTrigger {{ [CmdletBinding()] param([switch]$Once, [switch]$Daily,
    [switch]$Weekly, $At, $RepetitionInterval, $DaysOfWeek)
    $every = $null; if ($RepetitionInterval) {{ $every = $RepetitionInterval.TotalMinutes }}
    [pscustomobject]@{{ At = ([datetime]$At).ToString('HH:mm'); Every = $every }} }}
function global:New-ScheduledTaskPrincipal {{ [CmdletBinding()]
    param($UserId, $LogonType, $RunLevel) 'SYSTEM' }}
function global:New-ScheduledTaskSettingsSet {{ [CmdletBinding()] param([switch]$StartWhenAvailable,
    $MultipleInstances, [switch]$DontStopIfGoingOnBatteries, [switch]$AllowStartIfOnBatteries,
    $ExecutionTimeLimit) [pscustomobject]@{{ Multiple = "$MultipleInstances" }} }}
function global:Get-ScheduledTask {{ [CmdletBinding()] param($TaskName) $null }}
function global:Register-ScheduledTask {{ [CmdletBinding()] param($TaskName, $Action, $Trigger,
    $Principal, $Settings, $Description)
    $global:tasks += [pscustomobject]@{{ Name = $TaskName; Execute = $Action.Execute;
        Argument = $Action.Argument; At = $Trigger.At; Every = $Trigger.Every;
        Multiple = $Settings.Multiple }} }}
& '{DEPLOY / "register-tasks.ps1"}' -Root '{root}' *> $null
'TASKS=' + ($global:tasks | ConvertTo-Json -Compress)
""")
    assert code == 0, out
    import re

    tasks = {t["Name"]: t for t in json.loads(out.split("TASKS=", 1)[1].strip())}
    assert sorted(tasks) == sorted(TASKS)
    errors = {}
    for name, t in tasks.items():
        assert t["Execute"] == "cmd.exe" and t["Multiple"] == "IgnoreNew", t
        m = re.search(r' 1>NUL 2>>"([^"]+)"', t["Argument"])
        assert m, t["Argument"]
        errors[name] = m.group(1)
    assert len(set(errors.values())) == len(errors), errors
    assert errors["GameSense-Sync"].endswith("task-sync.err.log")
    assert errors["GameSense-Backup"].endswith("task-backup.err.log")
    starts = {n: (t["At"], t["Every"]) for n, t in tasks.items()}
    assert starts == {
        "GameSense-Update": ("00:00", 10), "GameSense-Sync": ("00:01", 15),
        "GameSense-Notify": ("00:02", 15), "GameSense-Sex": ("00:04", 60),
        "GameSense-Plan": ("17:00", None), "GameSense-Score": ("11:00", None),
        "GameSense-Backup": ("03:07", None), "GameSense-RestoreCheck": ("04:37", None),
    }


def _backup_run(tmp_path: Path, root: Path, during: str = "") -> tuple[int, dict, str]:
    """backup.ps1 with robocopy stood in for: it copies the photo folder (thumbnails
    left out), then runs `during`, which happens while the copy is still going."""
    dump = tmp_path / "pg_stub"
    dump.write_text('#!/bin/bash\nwhile [ $# -gt 0 ]; do [ "$1" = "-f" ] && echo dump > "$2"; '
                    "shift; done\nexit 0\n")
    dump.chmod(0o755)
    env = root / "app" / "backend" / ".env"
    env.write_text(env.read_text() + f"PGDUMP={dump}\nPGRESTORE={dump}\n")
    code, out = _ps(tmp_path, f"""
function global:robocopy {{
    $src = $args[0]; $dst = $args[1]
    New-Item -ItemType Directory -Force $dst | Out-Null
    Get-ChildItem -Force $src | Where-Object Name -ne 'thumbs' |
        Copy-Item -Recurse -Force -Destination $dst
    {during}
    $global:LASTEXITCODE = 1
}}
& '{DEPLOY / "backup.ps1"}' -Root '{root}'
exit $LASTEXITCODE
""")
    status = json.loads((root / "data" / "backup-status.json").read_text(encoding="utf-8-sig"))
    return code, status, out


def _photos(root: Path, *names: str) -> Path:
    night = root / "data" / "media" / "estate-1" / "camera-1" / "2026-09-27"
    night.mkdir(parents=True, exist_ok=True)
    for name in names:
        (night / name).write_bytes(b"jpeg")
    thumbs = root / "data" / "media" / "thumbs" / "ab"
    thumbs.mkdir(parents=True, exist_ok=True)
    (thumbs / "ab12.webp").write_bytes(b"webp")
    return night


@needs_pwsh
def test_a_photo_that_arrives_during_the_backup_is_the_next_nights(tmp_path):
    """The 03:00 fetch writes a photo (and the .tmp of one still downloading) into a
    folder the copy has already walked: the night's backup is still good (R7BE-2)."""
    root = _server(tmp_path)
    night = _photos(root, "sp-1.jpg", "sp-2.jpg")
    code, status, out = _backup_run(tmp_path, root, during=(
        f"Set-Content -Path '{night / 'sp-3.jpg'}' -Value 'jpeg'; "
        f"Set-Content -Path '{night / 'tmpab12.tmp'}' -Value 'partial'"))
    assert code == 0, out
    assert status["ok"] is True and status["error"] is None, status
    assert (status["photos_on_server"], status["photos_in_backup"]) == (2, 2)
    assert status["last_ok_at"] == status["finished_at"]


@needs_pwsh
def test_a_photo_missing_from_the_backup_fails_the_night(tmp_path):
    root = _server(tmp_path)
    _photos(root, "sp-1.jpg", "sp-2.jpg")
    copied = tmp_path / "D" / "GameSense-Backup" / "media" / "estate-1" / "camera-1" / "2026-09-27"
    code, status, out = _backup_run(tmp_path, root, during=(
        f"Remove-Item -Force '{copied / 'sp-2.jpg'}'"))
    assert code == 1, out
    assert status["ok"] is False and status["last_ok_at"] is None
    assert status["error"] == ("1 of the server's 2 photos aren't in the backup "
                               "(see backup-media.log).")


@needs_pwsh
def test_no_photo_folder_is_a_failed_backup_not_a_good_one(tmp_path):
    """MEDIA_ROOT pointing where there is nothing (moved, or set only in the service's
    environment): no photo was backed up, so it is not a good backup (R7BE-3)."""
    moved = tmp_path / "media-moved"
    root = _server(tmp_path, MEDIA_ROOT=str(moved))
    code, status, out = _backup_run(tmp_path, root)
    assert code == 1, out
    assert status["ok"] is False and status["photos_on_server"] is None
    assert status["error"] == f"The photo folder {moved} isn't there, so no photos were backed up."
    assert status["dump"]  # the database was still backed up


def _git_server(tmp_path: Path) -> tuple[Path, str, str]:
    """A fake server whose app is a clone at B, B deployed, and origin's deploy branch
    at A, older (CI made it at its first green commit after main had put B live)."""
    import subprocess

    def git(*args, cwd):
        return subprocess.run(["git", "-c", "user.email=t@x", "-c", "user.name=t",
                               "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True,
                              capture_output=True, text=True).stdout.strip()

    src = tmp_path / "src"
    (src / "backend").mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=src)
    (src / "backend" / "x.py").write_text("A = 1\n")
    git("add", "-A", cwd=src)
    git("commit", "-qm", "A: start", cwd=src)
    a = git("rev-parse", "HEAD", cwd=src)
    (src / "backend" / "x.py").write_text("A = 2\n")
    git("commit", "-qam", "B: on main", cwd=src)
    b = git("rev-parse", "HEAD", cwd=src)
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    git("push", "-q", str(origin), "main", f"{a}:refs/heads/deploy", cwd=src)
    root = tmp_path / "GameSense"
    git("clone", "-q", str(origin), str(root / "app"), cwd=tmp_path)
    (root / "data").mkdir(parents=True)
    (root / "data" / "deployed.sha").write_text(b)
    (root / "app" / "backend" / ".env").write_text(f"MODELS_ROOT={root / 'data' / 'models'}\n")
    _shim(root / "tools" / "git" / "cmd" / "git.exe", "git")
    # pipeline.py busy: nothing runs.
    (root / "venv" / "Scripts").mkdir(parents=True)
    (root / "venv" / "Scripts" / "python.exe").write_text("#!/bin/bash\nexit 0\n")
    (root / "venv" / "Scripts" / "python.exe").chmod(0o755)
    return root, a, b


@needs_pwsh
def test_a_deploy_branch_behind_what_runs_is_waited_for_not_deployed(tmp_path):
    """Deploys only go forward: CI making the branch at a commit older than the one
    main already put live must not roll the server back to it (R7BE-4)."""
    import subprocess

    root, a, b = _git_server(tmp_path)
    for _ in range(2):
        code, out = _ps(tmp_path, f"& '{DEPLOY / 'update.ps1'}' -Root '{root}'\nexit $LASTEXITCODE")
        assert code == 0, out
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root / "app", check=True,
                          capture_output=True, text=True).stdout.strip()
    assert head == b
    status = json.loads((root / "data" / "deploy-status.json").read_text(encoding="utf-8-sig"))
    assert status["state"] == "current" and status["source"] == "deploy"
    assert status["running"] == b and status["behind"] == a and status["failed"] is None
    assert status["waiting_for_tests"] == 0
    log = (root / "logs" / "update.log").read_text()
    assert log.count("wait: ") == 1 and "update: " not in log  # said once, nothing deployed


@needs_pwsh
def test_the_restore_test_needs_room_on_the_database_disk(tmp_path):
    """A restore writes a second copy of the database on the live one's disk; with no
    room for it, the test fails in words and nothing is restored (R7BE-6)."""
    calls = tmp_path / "psql-calls.log"
    psql = tmp_path / "psql_stub"
    psql.write_text(f'#!/bin/bash\necho "$@" >> {calls}\n'
                    'case "$*" in *pg_database_size*) echo 1099511627776000;; esac\nexit 0\n')
    psql.chmod(0o755)
    root = _server(tmp_path, PSQL=str(psql), PGRESTORE=str(psql))
    dumps = tmp_path / "D" / "GameSense-Backup" / "db"
    dumps.mkdir(parents=True)
    (dumps / "gamesense-20260927-030700.dump").write_bytes(b"dump")
    _shim(root / "venv" / "Scripts" / "python.exe", os.sys.executable,
          env=f"export PYTHONPATH={BACKEND}\n")
    code, out = _ps(tmp_path,
                    f"& '{DEPLOY / 'restore-check.ps1'}' -Root '{root}'\nexit $LASTEXITCODE")
    assert code == 1, out
    result = json.loads((root / "data" / "restore-check.json").read_text(encoding="utf-8-sig"))
    assert result["ok"] is False
    assert result["error"].startswith("Not enough room on the server's disk to test the restore")
    assert "Nothing was restored." in result["error"]
    assert "CREATE DATABASE" not in calls.read_text()
