"""No gaps in photo ingestion, and a broken camera login is visible (plan item 4).

Every provider is a fake: SPYPOINT lists photos newest first and pages backward on
its dateEnd cursor, as the real API does, so the tests exercise the real pager,
retry and bookkeeping against a real Postgres.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError

from app.core import crypto
from app.core.config import settings
from app.health import camera_health
from app.ingestion import fetch, logins, sync
from app.ingestion.spypoint import (
    SpypointAuthError,
    SpypointCamera,
    SpypointClient,
    SpypointError,
    SpypointPhoto,
    _capture_time,
)
from app.models import AppSetting, Camera, CameraAccount, Estate, Image, SyncLog, User

from .conftest import requires_db

NOW = datetime.now(UTC).replace(microsecond=0)


class FakeSpypoint:
    """One SPYPOINT for the whole test: logins, their cameras, their photos."""

    photos: dict[str, list[SpypointPhoto]] = {}
    cameras: dict[str, list[str]] = {}  # username -> camera ids
    login_errors: dict[str, Exception] = {}
    list_errors: dict[str, Exception] = {}
    dead_urls: set[str] = set()
    downloads: list[str] = []
    pages: list[tuple[str, str | None]] = []
    on_list = None

    def __init__(self, username, password, **_):
        self.username, self.password = username, password

    def login(self):
        if self.username in self.login_errors:
            raise self.login_errors[self.username]

    def list_cameras(self):
        return [SpypointCamera(cid, f"Cam {cid}", last_report_at=datetime.now(UTC))
                for cid in self.cameras.get(self.username, [])]

    def date_cursor(self, when):
        return when.isoformat()

    def list_photos(self, camera_id, limit=100, date_end=None):
        self.pages.append((camera_id, date_end))
        if FakeSpypoint.on_list:
            FakeSpypoint.on_list(camera_id, date_end)
        if camera_id in self.list_errors:
            raise self.list_errors[camera_id]
        rows = sorted(self.photos.get(camera_id, []), key=lambda p: p.captured_at, reverse=True)
        if date_end is not None:
            end = datetime.fromisoformat(date_end)
            rows = [p for p in rows if p.captured_at <= end]  # inclusive, as SPYPOINT is
        return rows[:limit]

    def download(self, url):
        self.downloads.append(url)
        if url in self.dead_urls:
            raise httpx.ReadTimeout("CDN timed out")
        return b"jpeg:" + url.encode()

    def close(self):
        pass


def shots(camera_id, count, newest, step=timedelta(minutes=10), prefix=None):
    prefix = prefix or camera_id
    return [SpypointPhoto(f"{prefix}-{i}", newest - i * step, url=f"https://cdn/{prefix}-{i}.jpg")
            for i in range(count)]


@pytest.fixture
def spypoint(db_session, monkeypatch, tmp_path):
    FakeSpypoint.photos, FakeSpypoint.cameras = {}, {"owner@example.com": []}
    FakeSpypoint.login_errors, FakeSpypoint.list_errors = {}, {}
    FakeSpypoint.dead_urls, FakeSpypoint.downloads, FakeSpypoint.pages = set(), [], []
    FakeSpypoint.on_list = None
    monkeypatch.setattr(sync, "SpypointClient", FakeSpypoint)
    monkeypatch.setattr(sync, "enrich_image", lambda db, image: None)
    monkeypatch.setattr(settings, "media_root", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "spypoint_username", "owner@example.com")
    monkeypatch.setattr(settings, "spypoint_password", "secret")
    estate = Estate(name="Piedras Lisas", timezone="Europe/Madrid")
    db_session.add(estate)
    db_session.commit()
    return estate


def guest(db, estate, username="marco@example.com", *, imported=True, label="Marco's cameras"):
    account = CameraAccount(
        estate_id=estate.id, username=username, provider="spypoint", label=label,
        password_enc=crypto.encrypt("guest-secret"),
        last_sync_at=NOW - timedelta(minutes=15) if imported else None,
    )
    db.add(account)
    db.commit()
    return account


def images(db, camera_id=None):
    q = select(Image)
    if camera_id is not None:
        q = q.join(Camera).where(Camera.spypoint_id == camera_id)
    return db.scalars(q.order_by(Image.captured_at.desc())).all()


# ── E-01: a failed download is retried, and rows with no file are repaired ──────


@requires_db
def test_failed_download_is_retried_on_the_next_fetch(db_session, spypoint):
    FakeSpypoint.cameras["owner@example.com"] = ["sp-1"]
    FakeSpypoint.photos["sp-1"] = shots("sp-1", 3, NOW - timedelta(hours=2))
    FakeSpypoint.dead_urls = {"https://cdn/sp-1-1.jpg"}

    first = sync.sync_all(db_session)
    assert first["total"] == 2  # only photos whose file is here count as come in
    lost = db_session.scalar(select(Image).where(Image.spypoint_photo_id == "sp-1-1"))
    assert lost.original_path is None and lost.download_attempts == 1

    FakeSpypoint.dead_urls = set()  # the CDN recovers
    second = sync.sync_all(db_session)
    db_session.refresh(lost)
    assert second["total"] == 1
    assert lost.original_path and lost.file_hash
    with open(lost.original_path, "rb") as f:
        assert f.read() == b"jpeg:https://cdn/sp-1-1.jpg"
    assert db_session.scalar(select(func.count(Image.id))) == 3  # no duplicate rows


@requires_db
def test_repair_pass_fetches_files_the_listing_no_longer_shows(db_session, spypoint):
    FakeSpypoint.cameras["owner@example.com"] = ["sp-1"]
    FakeSpypoint.photos["sp-1"] = shots("sp-1", 2, NOW - timedelta(hours=1))
    sync.sync_all(db_session)
    camera = db_session.scalar(select(Camera))
    old = Image(camera_id=camera.id, spypoint_photo_id="old-1", download_attempts=2,
                captured_at=NOW - timedelta(days=10), cdn_url="https://cdn/old-1.jpg",
                processed_at=NOW - timedelta(days=9))
    capped = Image(camera_id=camera.id, spypoint_photo_id="old-2", download_attempts=5,
                   captured_at=NOW - timedelta(days=10), cdn_url="https://cdn/old-2.jpg")
    db_session.add_all([old, capped])
    db_session.commit()

    sync.sync_all(db_session)
    db_session.refresh(old)
    db_session.refresh(capped)
    assert old.original_path is not None
    # Passed over by the detector for having no file: it gets looked at now.
    assert old.processed_at is None
    assert "https://cdn/old-2.jpg" not in FakeSpypoint.downloads  # given up after 5 tries
    assert capped.original_path is None


@requires_db
def test_a_photo_whose_file_never_came_stops_blinding_its_night(db_session, spypoint):
    from app.ai import empty_filter

    FakeSpypoint.cameras["owner@example.com"] = ["sp-1"]
    camera = Camera(estate_id=spypoint.id, spypoint_id="sp-1", name="Charca")
    db_session.add(camera)
    db_session.flush()
    fresh = Image(camera_id=camera.id, spypoint_photo_id="a", captured_at=NOW,
                  cdn_url="https://cdn/a.jpg")
    stale = Image(camera_id=camera.id, spypoint_photo_id="b", captured_at=NOW,
                  cdn_url="https://cdn/b.jpg", created_at=NOW - timedelta(hours=30))
    db_session.add_all([fresh, stale])
    db_session.commit()
    assert empty_filter.scan_unprocessed(db_session)["scanned"] == 1
    assert stale.processed_at is not None and stale.is_empty_frame is None
    assert fresh.processed_at is None  # still being retried by the fetch


# ── E-02: an outage leaves no hole ──────────────────────────────────────────────


@requires_db
def test_fetch_after_an_outage_pages_back_to_photos_already_listed(db_session, spypoint):
    FakeSpypoint.cameras["owner@example.com"] = ["sp-1"]
    listed_to = NOW - timedelta(days=3)
    history = shots("sp-1", 300, listed_to - timedelta(days=3), prefix="old")
    outage = shots("sp-1", 250, NOW - timedelta(minutes=5), step=timedelta(minutes=17))
    FakeSpypoint.photos["sp-1"] = history + outage
    db_session.add(Camera(estate_id=spypoint.id, spypoint_id="sp-1", name="Charca",
                          photos_listed_to=listed_to))
    db_session.commit()

    result = sync.sync_all(db_session)
    stored = {i.spypoint_photo_id for i in images(db_session)}
    assert {p.spypoint_id for p in outage} <= stored  # the newest 100 used to be all
    pages = [p for p in FakeSpypoint.pages if p[0] == "sp-1"]
    assert len(pages) == 3  # and it stopped once it met what it had already listed
    # Page 3 reached into what was listed before; page 4 was never asked for.
    assert max(int(s.split("-")[1]) for s in stored if s.startswith("old-")) < 100
    camera = db_session.scalar(select(Camera))
    assert camera.photos_listed_to == outage[0].captured_at
    assert result["cameras"][0]["complete"] is True


@requires_db
def test_the_page_cap_bounds_a_fetch_and_does_not_claim_what_it_missed(
    db_session, spypoint, monkeypatch,
):
    FakeSpypoint.cameras["owner@example.com"] = ["sp-1"]
    FakeSpypoint.photos["sp-1"] = shots("sp-1", 500, NOW - timedelta(minutes=5),
                                        step=timedelta(minutes=5))
    listed_to = NOW - timedelta(days=5)
    db_session.add(Camera(estate_id=spypoint.id, spypoint_id="sp-1", name="Charca",
                          photos_listed_to=listed_to))
    db_session.commit()
    monkeypatch.setattr(sync, "MAX_PAGES", 2)
    result = sync.sync_all(db_session)
    assert result["cameras"][0]["complete"] is False
    # Only a complete listing moves the mark, so the next fetch looks again.
    assert db_session.scalar(select(Camera)).photos_listed_to == listed_to
    assert db_session.scalar(select(func.count(Image.id))) == 199  # dateEnd is inclusive


# ── E-04 / E-17: one error never costs the rest ─────────────────────────────────


@requires_db
def test_a_login_removed_mid_run_costs_only_its_own_cameras(db_session, spypoint):
    """The audit's proof: a guest removes their login while the run is between
    accounts. The owner's photos, the other guest's and the sync log all survive."""
    from app.api.routes_camera_accounts import remove_account

    marco = guest(db_session, spypoint)
    ana = guest(db_session, spypoint, "ana@example.com", label="Ana")
    FakeSpypoint.cameras.update({"owner@example.com": ["sp-1"],
                                 "marco@example.com": ["sp-2"], "ana@example.com": ["sp-3"]})
    for cid in ("sp-1", "sp-2", "sp-3"):
        FakeSpypoint.photos[cid] = shots(cid, 2, NOW - timedelta(hours=1))
    owner = User(estate_id=spypoint.id, email="admin@x.local", password_hash="x", role="admin")
    db_session.add(owner)
    db_session.commit()
    others = create_engine(db_session.get_bind().url)
    from sqlalchemy.orm import Session

    def remove_marco(camera_id, date_end):
        if camera_id == "sp-1" and date_end is None:
            with Session(others) as s:
                remove_account(marco.id, s.get(User, owner.id), s)

    FakeSpypoint.on_list = remove_marco
    try:
        result = sync.sync_all(db_session)
    finally:
        others.dispose()
    assert {i.spypoint_photo_id for i in images(db_session)} == {
        "sp-1-0", "sp-1-1", "sp-3-0", "sp-3-1"}
    assert result["status"] == "partial"
    assert db_session.scalar(select(SyncLog)).status == "partial"
    assert db_session.get(CameraAccount, ana.id).last_error is None


@requires_db
def test_a_camera_is_not_locked_for_the_whole_fetch(db_session, spypoint):
    """Renaming a camera while the fetch is on its second page does not wait."""
    FakeSpypoint.cameras["owner@example.com"] = ["sp-1"]
    FakeSpypoint.photos["sp-1"] = shots("sp-1", 150, NOW - timedelta(minutes=5))
    others = create_engine(db_session.get_bind().url)
    locked: list[bool] = []

    def try_lock(camera_id, date_end):
        if date_end is None:
            return
        with others.begin() as c:
            c.execute(text("SET LOCAL lock_timeout = '500ms'"))
            locked.append(c.execute(text(
                "SELECT id FROM cameras WHERE spypoint_id='sp-1' FOR UPDATE")).first() is not None)

    FakeSpypoint.on_list = try_lock
    try:
        sync.sync_all(db_session)
    finally:
        others.dispose()
    assert locked and all(locked)


# ── E-13: a login added while the pipeline was busy still gets its history ──────


@requires_db
def test_a_new_login_picked_up_by_the_routine_fetch_gets_its_history(db_session, spypoint):
    marco = guest(db_session, spypoint, imported=False)
    FakeSpypoint.cameras["marco@example.com"] = ["sp-9"]
    FakeSpypoint.photos["sp-9"] = shots("sp-9", 400, NOW - timedelta(hours=1),
                                        step=timedelta(hours=1))
    sync.sync_all(db_session)
    assert len(images(db_session, "sp-9")) == 400  # not the newest 100
    db_session.refresh(marco)
    assert marco.last_sync_at is not None


@requires_db
def test_backfill_account_keeps_going_past_a_camera_that_fails(db_session, spypoint):
    marco = guest(db_session, spypoint, imported=False)
    FakeSpypoint.cameras["marco@example.com"] = ["sp-8", "sp-9"]
    FakeSpypoint.photos["sp-9"] = shots("sp-9", 3, NOW - timedelta(hours=1))
    FakeSpypoint.list_errors["sp-8"] = SpypointError("POST /photo/all -> HTTP 502", 502)
    result = sync.backfill_account(db_session, str(marco.id))
    assert result["status"] == "partial"
    assert len(images(db_session, "sp-9")) == 3
    db_session.refresh(marco)
    assert marco.last_sync_at is None  # the next fetch imports the one that failed
    assert marco.reported_cameras == 2


# ── E-03: a camera clock that is obviously wrong is not believed ────────────────


@pytest.mark.parametrize(("origin", "expected"), [
    ("1970-01-01T00:00:00.000Z", "date"),       # reset after a battery swap
    ("2020-07-18T00:12:00.000Z", "date"),       # a year off
    ("2027-03-01T21:00:00.000Z", "date"),       # running ahead
    ("2026-09-25T21:40:00.000Z", "origin"),     # a late upload is still believed
    ("2026-09-26T00:00:00.000Z", "origin"),     # an hour or two either way is a zone mix-up
])
def test_capture_time_falls_back_to_receipt_on_an_impossible_clock(origin, expected):
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Madrid")
    photo = {"id": "x", "originDate": origin, "date": "2026-09-26T19:05:00.000Z"}
    got = _capture_time(photo, tz)
    from app.ingestion.spypoint import _parse_dt

    assert got == _parse_dt(photo["date" if expected == "date" else "originDate"], tz)


# ── E-07: rotating JWT_SECRET no longer silently drops guest logins ─────────────


@requires_db
def test_rotating_the_secret_with_the_old_one_kept_rewrites_passwords(
    db_session, spypoint, monkeypatch,
):
    monkeypatch.setattr(settings, "credentials_key", "")
    monkeypatch.setattr(settings, "jwt_secret", "old-secret")
    marco = guest(db_session, spypoint)
    FakeSpypoint.cameras["marco@example.com"] = ["sp-2"]
    monkeypatch.setattr(settings, "jwt_secret", "new-secret")
    monkeypatch.setattr(settings, "previous_jwt_secret", "old-secret")
    result = sync.sync_all(db_session)
    assert [a["status"] for a in result["accounts"]] == ["ok", "ok"]
    db_session.refresh(marco)
    assert crypto.is_current(marco.password_enc)  # saved again under the new key
    monkeypatch.setattr(settings, "previous_jwt_secret", "")
    assert crypto.decrypt(marco.password_enc) == "guest-secret"


@requires_db
def test_a_credentials_key_set_before_rotation_keeps_logins_working(
    db_session, spypoint, monkeypatch,
):
    monkeypatch.setattr(settings, "jwt_secret", "old-secret")
    monkeypatch.setattr(settings, "credentials_key", "")
    marco = guest(db_session, spypoint)
    monkeypatch.setattr(settings, "credentials_key", "kept-apart")
    sync.sync_all(db_session)  # one fetch saves it again under CREDENTIALS_KEY
    monkeypatch.setattr(settings, "jwt_secret", "rotated")
    db_session.refresh(marco)
    assert crypto.decrypt(marco.password_enc) == "guest-secret"


@requires_db
def test_an_unreadable_password_is_reported_not_dropped(db_session, spypoint, monkeypatch):
    from app.api.routes_camera_accounts import list_accounts

    monkeypatch.setattr(settings, "credentials_key", "")
    monkeypatch.setattr(settings, "previous_jwt_secret", "")
    monkeypatch.setattr(settings, "jwt_secret", "old-secret")
    marco = guest(db_session, spypoint)
    monkeypatch.setattr(settings, "jwt_secret", "new-secret")
    result = sync.sync_all(db_session)
    words = "The saved password can't be read. Re-enter it."
    assert result["accounts"][1] == {"account_id": str(marco.id), "label": "Marco's cameras",
                                     "status": "error", "error": words}
    assert result["status"] == "partial" and result["accounts_failed"] == 1
    member = User(estate_id=spypoint.id, email="m@x.local", password_hash="x", role="member")
    db_session.add(member)
    db_session.commit()
    row = next(r for r in list_accounts(member, db_session) if r["id"] == str(marco.id))
    assert row["status"]["state"] == "failing" and row["status"]["error"] == words


# ── E-22: one login is one login ────────────────────────────────────────────────


@pytest.fixture
def verified(monkeypatch):
    from app.api import routes_camera_accounts as accounts

    class Provider:
        cameras = 3

        def __init__(self, *_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def login(self):
            pass

        def list_cameras(self):
            return [object()] * self.cameras

        list_devices = list_cameras

        def close(self):
            pass

    monkeypatch.setattr(accounts, "SpypointClient", Provider)
    monkeypatch.setattr(accounts, "UboxClient", Provider)
    monkeypatch.setattr("app.api.routes_cameras._pipeline_busy", lambda: True)
    return Provider


def _member(db, estate, role="member"):
    user = User(estate_id=estate.id, email=f"{uuid.uuid4().hex[:8]}@x.local",
                password_hash="x", role=role)
    db.add(user)
    db.commit()
    return user


@requires_db
def test_the_same_login_in_another_case_or_the_main_login_is_refused(
    db_session, spypoint, verified,
):
    from app.api.routes_camera_accounts import AddAccountBody, add_account

    user = _member(db_session, spypoint)
    add_account(AddAccountBody(username="julle@example.com", password="p"),
                BackgroundTasks(), user, db_session)
    for username, words in (
        ("Julle@Example.com", "That SPYPOINT login is already added"),
        ("OWNER@example.com", "This login is already connected as the estate's main account"),
    ):
        with pytest.raises(HTTPException) as exc:
            add_account(AddAccountBody(username=username, password="p"),
                        BackgroundTasks(), user, db_session)
        assert exc.value.detail == words
    # And the database says so too, should two phones add it at the same moment.
    db_session.add(CameraAccount(estate_id=spypoint.id, username="JULLE@example.com",
                                 provider="spypoint", password_enc="x"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@requires_db
def test_a_guest_copy_of_the_main_login_is_not_fetched_twice(db_session, spypoint):
    copy = guest(db_session, spypoint, "Owner@Example.com", label="Owner again")
    FakeSpypoint.cameras["owner@example.com"] = ["sp-1"]
    FakeSpypoint.cameras["Owner@Example.com"] = ["sp-1"]
    result = sync.sync_all(db_session)
    assert result["accounts"][1]["error"] == sync.DUPLICATE_OF_PRIMARY
    assert db_session.scalar(select(Camera)).account_id is None  # still the main login's
    db_session.refresh(copy)
    assert copy.last_error == sync.DUPLICATE_OF_PRIMARY


# ── E-05: a broken login is visible everywhere a hunter looks ───────────────────


@requires_db
def test_a_refused_main_login_says_so_in_settings_cards_and_alerts(
    db_session, spypoint, monkeypatch,
):
    from app.api.routes_camera_accounts import list_accounts
    from app.forecasting import alerts, model

    monkeypatch.setattr(model, "_tonight_conditions", lambda now: {"moon_phase": "New Moon"})
    guest(db_session, spypoint)
    FakeSpypoint.cameras.update({"owner@example.com": ["sp-1", "sp-2"],
                                 "marco@example.com": ["sp-3"]})
    FakeSpypoint.photos["sp-3"] = shots("sp-3", 2, NOW - timedelta(hours=1))
    sync.sync_all(db_session)  # everything works first
    FakeSpypoint.login_errors["owner@example.com"] = SpypointAuthError(
        "login refused: HTTP 401", 401)
    result = sync.sync_all(db_session)

    words = "SPYPOINT refused the password. Re-enter it."
    assert result["status"] == "partial"  # Marco's still worked
    assert result["accounts"][0] == {"account_id": None, "label": "Main SPYPOINT login",
                                     "status": "error", "error": words}
    assert db_session.scalar(select(SyncLog).order_by(SyncLog.started_at.desc())).error == (
        f"Main SPYPOINT login: {words}")
    assert logins.primary_status(db_session)["last_error"] == words

    rows = list_accounts(_member(db_session, spypoint, "admin"), db_session)
    assert rows[0]["id"] == "primary" and rows[0]["cameras"] == 2
    assert rows[0]["status"]["state"] == "failing" and rows[0]["status"]["error"] == words
    assert not rows[0]["can_remove"]
    assert rows[1]["status"]["state"] == "ok"

    cams = db_session.scalars(select(Camera).order_by(Camera.spypoint_id)).all()
    states = logins.camera_logins(db_session, cams)
    health = [camera_health(c, login=states.get(c.id)) for c in cams]
    assert [h["status"] for h in health] == ["not_syncing", "not_syncing", "ok"]
    assert health[0]["detail"] == "Photos not coming in. The camera login needs attention."
    assert health[0]["login"] == {"label": "Main SPYPOINT login", "error": words}

    feed = alerts.compute_alerts(db_session)
    login_alerts = [a for a in feed if a["type"] == "camera"]
    assert [a["title"] for a in login_alerts] == ["Main SPYPOINT login: photos not coming in"]
    assert "Cam sp-1, Cam sp-2" in login_alerts[0]["text"]
    assert words in login_alerts[0]["text"]
    assert not any("battery" in a["text"] for a in feed)


@requires_db
def test_a_login_with_no_good_fetch_for_hours_counts_as_stopped(db_session, spypoint):
    marco = guest(db_session, spypoint)
    camera = Camera(estate_id=spypoint.id, spypoint_id="sp-3", account_id=marco.id,
                    name="Pinar", last_report_at=NOW - timedelta(hours=1))
    db_session.add(camera)
    logins.record(db_session, marco, cameras=1, now=NOW - timedelta(hours=3))
    db_session.commit()
    state = logins.camera_logins(db_session, [camera], NOW)[camera.id]
    assert state["state"] == "stale"
    health = camera_health(camera, NOW, state)
    assert health["status"] == "not_syncing"
    # No login error: the fetch has stopped, and the login is not blamed for it.
    assert health["detail"] == "Photos not coming in. No photo fetch has worked for over 2 hours."
    assert health["login"]["error"] is None
    fresh = logins.freshness(db_session, now=NOW)
    assert fresh["problem"] == "stopped" and fresh["last_fetch_ok_at"] == NOW - timedelta(hours=3)


@requires_db
def test_tonight_says_when_the_photos_behind_it_are_old(db_session, spypoint, monkeypatch):
    from app.forecasting import model

    monkeypatch.setattr(model, "_tonight_conditions", lambda now: {"moon_phase": "New Moon"})
    guest(db_session, spypoint)
    FakeSpypoint.cameras.update({"owner@example.com": ["sp-1"], "marco@example.com": ["sp-3"]})
    FakeSpypoint.photos["sp-3"] = shots("sp-3", 2, NOW - timedelta(hours=5))
    FakeSpypoint.list_errors["sp-3"] = SpypointError("POST /photo/all -> HTTP 503", 503)
    sync.sync_all(db_session)
    plan = model.forecast_tonight(db_session)
    assert plan["freshness"]["problem"] == "login"
    assert plan["freshness"]["logins"] == ["Marco's cameras"]
    assert plan["freshness"]["last_fetch_ok_at"] is not None


# ── E-23: a removed login's cameras are "not connected", not "check battery" ────


@requires_db
def test_removing_a_login_disconnects_its_cameras_until_a_login_lists_them(
    db_session, spypoint, monkeypatch,
):
    from app.api.routes_camera_accounts import remove_account
    from app.forecasting import alerts, model

    monkeypatch.setattr(model, "_tonight_conditions", lambda now: {"moon_phase": "New Moon"})
    marco = guest(db_session, spypoint)
    FakeSpypoint.cameras.update({"owner@example.com": [], "marco@example.com": ["sp-3"]})
    FakeSpypoint.photos["sp-3"] = shots("sp-3", 2, NOW - timedelta(days=3))
    sync.sync_all(db_session)
    camera = db_session.scalar(select(Camera))
    camera.last_report_at = NOW - timedelta(days=3)
    db_session.commit()

    remove_account(marco.id, _member(db_session, spypoint, "admin"), db_session)
    db_session.refresh(camera)
    assert camera.active is False and len(images(db_session)) == 2  # photos stay
    health = camera_health(camera)
    assert health["status"] == "disconnected" and not health["producing"]
    assert not any(camera.name in a["title"] for a in alerts.compute_alerts(db_session))
    assert model.forecast_tonight(db_session)["alerts"] == []

    # The owner adds the camera to the main login: it is connected again.
    FakeSpypoint.cameras["owner@example.com"] = ["sp-3"]
    sync.sync_all(db_session)
    db_session.refresh(camera)
    assert camera.active is True


@requires_db
def test_a_camera_no_login_lists_is_disconnected_only_after_a_complete_run(
    db_session, spypoint,
):
    marco = guest(db_session, spypoint)
    db_session.add(Camera(estate_id=spypoint.id, spypoint_id="sp-gone", name="Orphan"))
    db_session.commit()
    FakeSpypoint.cameras.update({"owner@example.com": ["sp-1"], "marco@example.com": ["sp-3"]})
    FakeSpypoint.login_errors["marco@example.com"] = SpypointAuthError("refused", 401)
    sync.sync_all(db_session)
    orphan = db_session.scalar(select(Camera).where(Camera.spypoint_id == "sp-gone"))
    assert orphan.active is True  # Marco's login didn't answer: it may be his
    del FakeSpypoint.login_errors["marco@example.com"]
    sync.sync_all(db_session)
    db_session.refresh(orphan)
    assert orphan.active is False
    assert db_session.get(CameraAccount, marco.id).last_error is None


# ── C-08 / I-30 / E-10: the Check button's line is the truth ────────────────────


@pytest.mark.parametrize(("results", "status", "downloaded", "problems"), [
    ({"spypoint": {"status": "ok", "total": 7},
      "ubox": {"status": "error", "total": 0, "accounts": [
          {"label": "Ana's UBox", "status": "error",
           "error": "UBox refused the password. Re-enter it."}]}},
     "partial", 7, [{"label": "Ana's UBox", "error": "UBox refused the password. Re-enter it."}]),
    ({"spypoint": {"status": "skipped"}, "ubox": {"status": "skipped"}}, "skipped", 0, []),
    ({"spypoint": {"status": "ok", "total": 0}, "ubox": {"status": "skipped"}}, "ok", 0, []),
    ({"spypoint": {"status": "error", "total": 0, "reason": "no estate seeded"},
      "ubox": {"status": "skipped"}}, "error", 0,
     [{"label": "SPYPOINT", "error": "no estate seeded"}]),
])
def test_the_run_summary_names_what_went_wrong(results, status, downloaded, problems):
    assert fetch.summarize(results) == {
        "status": status, "downloaded": downloaded, "problems": problems}


@requires_db
def test_one_provider_crashing_never_stops_the_other(db_session, spypoint, monkeypatch):
    from app.ingestion import ubox_sync

    def crash(db):
        raise RuntimeError("database went away")

    monkeypatch.setattr(sync, "sync_all", crash)
    monkeypatch.setattr(ubox_sync, "sync_ubox_all", lambda db: {
        "status": "ok", "total": 3, "accounts": []})
    for name in ("app.ai.empty_filter", "app.ai.species", "app.forecasting.exposure"):
        monkeypatch.setitem(__import__("sys").modules, name, SimpleNamespace(
            scan_unprocessed=lambda db: {}, classify_unclassified=lambda db: {},
            recompute_camera_nights=lambda db: {}))
    fetch.run_fetch(db_session)
    row = fetch.latest_run(db_session)
    assert (row.status, row.images_downloaded) == ("partial", 3)
    assert row.details["stage"] == "done" and row.finished_at is not None
    assert row.details["problems"][0]["label"] == "SPYPOINT"
    assert "RuntimeError" in row.details["problems"][0]["error"]


@requires_db
def test_sync_status_reports_the_count_while_the_detector_is_still_looking(
    db_session, spypoint, monkeypatch, tmp_path,
):
    from app.api import routes_cameras

    lock = tmp_path / "pipeline.lock"
    monkeypatch.setattr(routes_cameras, "_lock_path", lambda: lock)
    viewer = _member(db_session, spypoint, "viewer")
    db_session.add(SyncLog(status="ok", started_at=NOW - timedelta(hours=1),
                           images_downloaded=9, details={"provider": "pipeline",
                                                         "stage": "done", "problems": []}))
    db_session.commit()
    lock.write_text("api 0")
    assert routes_cameras.sync_status(viewer, db_session)["status"] == "running"

    problems = [{"label": "Marco's cameras", "error": "SPYPOINT refused the password."}]
    row = SyncLog(status="partial", started_at=datetime.now(UTC), images_downloaded=4,
                  details={"provider": "pipeline", "stage": "identifying",
                           "problems": problems})
    db_session.add(row)
    db_session.commit()
    now = routes_cameras.sync_status(viewer, db_session)
    assert now["status"] == "identifying" and now["result"] == "partial"
    assert now["images_downloaded"] == 4 and now["problems"] == problems

    lock.unlink()
    done = routes_cameras.sync_status(viewer, db_session)
    assert done["status"] == "partial" and done["problems"] == problems
    # A provider row written later does not hide the run's summary.
    db_session.add(SyncLog(status="ok", started_at=datetime.now(UTC) + timedelta(seconds=1),
                           details={"provider": "ubox"}))
    db_session.commit()
    assert routes_cameras.sync_status(viewer, db_session)["status"] == "partial"


# ── E-20 / re-entering a password ───────────────────────────────────────────────


@requires_db
def test_a_new_login_shows_its_cameras_while_its_first_import_runs(
    db_session, spypoint, verified,
):
    from app.api.routes_camera_accounts import AddAccountBody, add_account, list_accounts

    user = _member(db_session, spypoint)
    add_account(AddAccountBody(username="new@example.com", password="p"),
                BackgroundTasks(), user, db_session)
    row = next(r for r in list_accounts(user, db_session) if r["username"] == "new@example.com")
    assert row["cameras"] == 3 and row["importing"] is True


@requires_db
def test_re_entering_a_password_checks_it_and_clears_the_problem(
    db_session, spypoint, verified, monkeypatch,
):
    from app.api import routes_camera_accounts as accounts

    owner = _member(db_session, spypoint)
    marco = guest(db_session, spypoint)
    marco.owner_user_id = owner.id
    logins.record(db_session, marco, error="SPYPOINT refused the password. Re-enter it.")
    db_session.commit()
    with pytest.raises(HTTPException) as exc:
        accounts.replace_password(marco.id, accounts.PasswordBody(password="new"),
                                  _member(db_session, spypoint), db_session)
    assert exc.value.status_code == 403

    def refuse(self):
        raise SpypointError("login refused: HTTP 401", 401)

    monkeypatch.setattr(verified, "login", refuse)
    with pytest.raises(HTTPException) as exc:
        accounts.replace_password(marco.id, accounts.PasswordBody(password="typo"),
                                  owner, db_session)
    assert exc.value.status_code == 400
    assert crypto.decrypt(db_session.get(CameraAccount, marco.id).password_enc) == "guest-secret"

    monkeypatch.setattr(verified, "login", lambda self: None)
    result = accounts.replace_password(marco.id, accounts.PasswordBody(password="new-one"),
                                       owner, db_session)
    assert result["cameras"] == 3
    db_session.refresh(marco)
    assert crypto.decrypt(marco.password_enc) == "new-one"
    assert marco.last_error is None and marco.last_ok_at is not None


# ── E-15 / H-22: a camera that only sends photos is not "offline" ───────────────


@pytest.mark.parametrize(("hours", "status", "producing"), [
    (40, "ok", True), (24 * 8, "quiet", False),
])
def test_a_suntek_camera_is_judged_by_a_week_not_36_hours(hours, status, producing):
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    suntek = Camera(name="Suntek", active=True, last_report_at=now - timedelta(hours=hours))
    health = camera_health(suntek, now)
    assert (health["status"], health["producing"]) == (status, producing)
    if status == "quiet":
        assert health["detail"] == "No photos since 19 Sep"
    spypoint = Camera(name="PL14", spypoint_id="sp", active=True,
                      last_report_at=now - timedelta(hours=hours))
    assert camera_health(spypoint, now)["status"] == "offline"


# ── E-21: SPYPOINT's "busy" is waited out once; UBox sees one phone ─────────────


def test_spypoint_retry_after_is_honoured_once(monkeypatch):
    from app.ingestion import spypoint as sp

    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"token": "t"})
        if len(calls) == 2:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json=[])

    slept = []
    monkeypatch.setattr(sp.time, "sleep", slept.append)
    client = SpypointClient("u", "p")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert client.list_cameras() == []
    assert slept == [2.0] and len(calls) == 3


def test_ubox_signs_in_as_the_same_phone_every_time():
    from app.ingestion.ubox import device_token

    assert device_token("Ana@Example.com") == device_token("ana@example.com")
    assert device_token("ana@example.com") != device_token("marco@example.com")
    assert len(device_token("ana@example.com")) == 30


@requires_db
def test_the_main_login_record_starts_afresh_when_the_login_changes(db_session, monkeypatch):
    monkeypatch.setattr(settings, "spypoint_username", "old@example.com")
    monkeypatch.setattr(settings, "spypoint_password", "x")
    logins.record(db_session, None, error="SPYPOINT refused the password. Re-enter it.")
    db_session.commit()
    monkeypatch.setattr(settings, "spypoint_username", "new@example.com")
    assert logins.primary_status(db_session)["last_error"] is None
    assert db_session.get(AppSetting, logins.PRIMARY_KEY) is not None


@requires_db
def test_a_full_disk_costs_a_photo_its_file_for_now_not_the_camera(
    db_session, spypoint, monkeypatch,
):
    import errno

    FakeSpypoint.cameras["owner@example.com"] = ["sp-1"]
    FakeSpypoint.photos["sp-1"] = shots("sp-1", 3, NOW - timedelta(hours=1))
    real = sync._store_file

    def full(estate_id, camera, image, data):
        if image.spypoint_photo_id == "sp-1-1":
            raise OSError(errno.ENOSPC, "No space left on device")
        real(estate_id, camera, image, data)

    monkeypatch.setattr(sync, "_store_file", full)
    result = sync.sync_all(db_session)
    assert result["status"] == "ok" and result["total"] == 2
    kept = {i.spypoint_photo_id: (i.original_path is not None, i.download_attempts)
            for i in images(db_session)}
    assert kept == {"sp-1-0": (True, 0), "sp-1-1": (False, 1), "sp-1-2": (True, 0)}
    monkeypatch.setattr(sync, "_store_file", real)
    sync.sync_all(db_session)  # space again: the next fetch fills it in
    assert all(i.original_path for i in images(db_session))
