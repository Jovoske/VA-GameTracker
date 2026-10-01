"""No gaps in photo ingestion, and a broken camera login is visible (plan item 4).

Every provider is a fake: SPYPOINT lists photos newest first and pages backward on
its dateEnd cursor, as the real API does, so the tests exercise the real pager,
retry and bookkeeping against a real Postgres.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError

from app import i18n
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
from app.models import (
    AppSetting,
    Camera,
    CameraAccount,
    CameraNight,
    Estate,
    Image,
    SyncLog,
    User,
)

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
    signins: list[str] = []
    issued: list[str] = []
    expired: set[str] = set()  # sign-ins SPYPOINT no longer takes

    def __init__(self, username, password, **_):
        self.username, self.password = username, password
        self.token = None

    @classmethod
    def sign_everyone_out(cls):
        cls.expired.update(cls.issued)

    def login(self):
        if self.username in self.login_errors:
            raise self.login_errors[self.username]
        self.signins.append(self.username)
        self.token = f"session-{self.username}-{len(self.signins)}"
        self.issued.append(self.token)

    def use_token(self, token):
        self.token = token

    def list_cameras(self):
        if self.token is None or self.token in self.expired:
            self.login()  # as SpypointClient._request signs in again on a 401
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


def fake_spypoint(monkeypatch, tmp_path):
    """SPYPOINT is FakeSpypoint, with nothing listed yet; the main login is owner@."""
    FakeSpypoint.photos, FakeSpypoint.cameras = {}, {"owner@example.com": []}
    FakeSpypoint.login_errors, FakeSpypoint.list_errors = {}, {}
    FakeSpypoint.dead_urls, FakeSpypoint.downloads, FakeSpypoint.pages = set(), [], []
    FakeSpypoint.on_list = None
    FakeSpypoint.signins, FakeSpypoint.issued, FakeSpypoint.expired = [], [], set()
    monkeypatch.setattr(sync, "SpypointClient", FakeSpypoint)
    monkeypatch.setattr(sync, "enrich_image", lambda db, image: None)
    monkeypatch.setattr(settings, "media_root", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "spypoint_username", "owner@example.com")
    monkeypatch.setattr(settings, "spypoint_password", "secret")


@pytest.fixture
def spypoint(db_session, monkeypatch, tmp_path):
    fake_spypoint(monkeypatch, tmp_path)
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
    from app.media import resolve

    with open(resolve(lost.original_path), "rb") as f:
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
    from app.ai import checking

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
    assert checking.check_photos(db_session)["no_file"] == 1
    assert stale.processed_at is not None and stale.is_empty_frame is None
    assert fresh.processed_at is None  # still being retried by the fetch


@requires_db
def test_a_photo_the_fetch_gave_up_on_is_let_through_at_once(db_session, spypoint):
    from app.ai import checking

    camera = Camera(estate_id=spypoint.id, spypoint_id="sp-1", name="Charca")
    db_session.add(camera)
    db_session.flush()
    given_up = Image(camera_id=camera.id, spypoint_photo_id="b", captured_at=NOW,
                     cdn_url="https://cdn/b.jpg", created_at=NOW - timedelta(hours=7),
                     download_attempts=sync.MAX_DOWNLOAD_ATTEMPTS)
    no_link = Image(camera_id=camera.id, spypoint_photo_id="c", captured_at=NOW)
    retrying = Image(camera_id=camera.id, spypoint_photo_id="d", captured_at=NOW,
                     cdn_url="https://cdn/d.jpg", download_attempts=2)
    db_session.add_all([given_up, no_link, retrying])
    db_session.commit()
    assert checking.check_photos(db_session)["no_file"] == 2
    assert given_up.processed_at is not None and no_link.processed_at is not None
    assert retrying.processed_at is None  # the fetch is still trying for its file


@requires_db
def test_a_cdn_down_for_hours_loses_no_photo_and_makes_no_empty_night(db_session, spypoint):
    """Final review E2E-1: five fetches (an hour and a quarter) of a dead CDN used the
    photo's five tries; SPYPOINT went on listing it with a fresh link, and it was never
    fetched again. Let through with no file, its night read as watched, nothing in it."""
    from app.ai import checking
    from app.forecasting.exposure import night_expr, recompute_camera_nights

    FakeSpypoint.cameras["owner@example.com"] = ["sp-1"]
    FakeSpypoint.photos["sp-1"] = [SpypointPhoto("only", NOW - timedelta(hours=3),
                                                 url="https://cdn/only.jpg")]
    FakeSpypoint.dead_urls = {"https://cdn/only.jpg"}
    for _ in range(sync.MAX_DOWNLOAD_ATTEMPTS + 3):
        sync.sync_all(db_session)
    photo = db_session.scalar(select(Image).where(Image.spypoint_photo_id == "only"))
    assert photo.original_path is None
    assert photo.download_attempts > sync.MAX_DOWNLOAD_ATTEMPTS

    # The AI pass stops waiting for it, and its night is not one watched and empty.
    assert checking.check_photos(db_session)["no_file"] == 1
    recompute_camera_nights(db_session)
    night = db_session.scalar(select(night_expr()).where(Image.id == photo.id))
    state = db_session.scalar(select(CameraNight.exposure_state).where(CameraNight.night == night))
    assert state == "UNPROCESSED"
    assert checking.lost_count(db_session) == 1

    # The CDN comes back and the next fetch lists it again: it comes in after all.
    FakeSpypoint.dead_urls = set()
    sync.sync_all(db_session)
    db_session.refresh(photo)
    assert photo.original_path is not None
    assert photo.processed_at is None  # sent back to be checked for animals
    assert checking.lost_count(db_session) == 0


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
def test_an_outage_longer_than_the_page_cap_is_closed_by_the_next_fetches(
    db_session, spypoint, monkeypatch,
):
    monkeypatch.setattr(sync, "MAX_PAGES", 3)  # stands for 20 pages of 100
    FakeSpypoint.cameras["owner@example.com"] = ["sp-1"]
    listed_to = NOW - timedelta(days=11)
    history = shots("sp-1", 100, listed_to, step=timedelta(hours=2), prefix="old")
    outage = shots("sp-1", 500, NOW - timedelta(minutes=5), step=timedelta(minutes=30))
    FakeSpypoint.photos["sp-1"] = history + outage
    db_session.add(Camera(estate_id=spypoint.id, spypoint_id="sp-1", name="Charca",
                          photos_listed_to=listed_to))
    db_session.commit()
    camera = db_session.scalar(select(Camera))

    first = sync.sync_all(db_session)["cameras"][0]
    db_session.refresh(camera)
    assert (first["pages"], first["complete"]) == (3, False)
    assert db_session.scalar(select(func.count(Image.id))) == 298  # dateEnd is inclusive
    # What the cap left is kept as the camera's gap; the mark is the newest listed.
    assert camera.photos_listed_to == outage[0].captured_at
    assert camera.photos_gap_from == listed_to - sync.OVERLAP
    assert camera.photos_gap_to == outage[297].captured_at

    runs = []
    for _ in range(3):
        FakeSpypoint.pages.clear()
        result = sync.sync_all(db_session)["cameras"][0]
        runs.append((len(FakeSpypoint.pages), result["complete"]))
    # New photos first (one page), then on through the gap with what is left of the
    # cap, until it is closed; after that a fetch reads one page again.
    assert runs == [(3, False), (2, True), (1, True)]
    stored = set(db_session.scalars(select(Image.spypoint_photo_id)))
    assert {p.spypoint_id for p in outage} <= stored
    db_session.refresh(camera)
    assert camera.photos_gap_from is None and camera.photos_gap_to is None


@requires_db
def test_a_fetch_cut_short_by_an_error_leaves_its_gap_for_the_next(db_session, spypoint):
    FakeSpypoint.cameras["owner@example.com"] = ["sp-1", "sp-2"]
    FakeSpypoint.photos["sp-1"] = shots("sp-1", 300, NOW - timedelta(minutes=5),
                                        step=timedelta(minutes=30))
    FakeSpypoint.photos["sp-2"] = shots("sp-2", 2, NOW - timedelta(hours=1))

    def drop_third_page(camera_id, date_end):
        if len(FakeSpypoint.pages) == 3:
            raise SpypointError("POST /photo/all -> HTTP 502", 502)

    FakeSpypoint.on_list = drop_third_page
    result = sync.sync_all(db_session)
    assert result["status"] == "partial" and len(images(db_session, "sp-1")) == 199
    camera = db_session.scalar(select(Camera).where(Camera.spypoint_id == "sp-1"))
    assert camera.photos_gap_to == FakeSpypoint.photos["sp-1"][198].captured_at
    # Its login works: the camera itself says its photos didn't come.
    assert camera.fetch_error == (
        "SPYPOINT isn't answering properly right now. It tries again on the next fetch.")
    health = camera_health(camera, login=logins.camera_logins(db_session, [camera])[camera.id])
    assert health["status"] == "not_syncing" and health["login"]["camera"] is True

    FakeSpypoint.on_list = None
    sync.sync_all(db_session)
    db_session.refresh(camera)
    assert len(images(db_session, "sp-1")) == 300
    assert camera.photos_gap_to is None and camera.fetch_error is None
    assert camera_health(camera)["status"] == "ok"


@requires_db
def test_a_camera_fetched_before_the_upgrade_reads_one_page_not_the_whole_cap(
    db_session, spypoint, monkeypatch,
):
    """Right after 0020 a camera has no mark yet: it pages back to its newest stored
    photo, not two months, so a busy one doesn't read the whole cap every fetch."""
    monkeypatch.setattr(sync, "MAX_PAGES", 4)
    FakeSpypoint.cameras["owner@example.com"] = ["sp-1"]
    FakeSpypoint.photos["sp-1"] = shots("sp-1", 500, NOW - timedelta(minutes=5),
                                        step=timedelta(minutes=86))
    camera = Camera(estate_id=spypoint.id, spypoint_id="sp-1", name="Charca")
    db_session.add(camera)
    db_session.commit()
    for p in FakeSpypoint.photos["sp-1"]:
        db_session.add(Image(camera_id=camera.id, spypoint_photo_id=p.spypoint_id,
                             captured_at=p.captured_at, original_path="/x.jpg", cdn_url=p.url))
    db_session.commit()
    runs = []
    for _ in range(2):
        FakeSpypoint.pages.clear()
        result = sync.sync_all(db_session)
        runs.append((len(FakeSpypoint.pages), result["cameras"][0]["complete"], result["total"]))
    assert runs == [(1, True, 0), (1, True, 0)]
    db_session.refresh(camera)
    assert camera.photos_listed_to == FakeSpypoint.photos["sp-1"][0].captured_at


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
    assert marco.reported_cameras == 2
    # Tried: the next fetch is a routine one, and the camera that failed says so.
    assert marco.last_sync_at is not None
    failed = db_session.scalar(select(Camera).where(Camera.spypoint_id == "sp-8"))
    assert failed is None  # its first page never came, so there is no card to mark


@requires_db
def test_a_new_login_with_one_failing_camera_is_not_imported_again_every_fetch(
    db_session, spypoint,
):
    from app.api.routes_camera_accounts import list_accounts

    marco = guest(db_session, spypoint, imported=False)
    FakeSpypoint.cameras.update({"owner@example.com": [],
                                 "marco@example.com": ["sp-good", "sp-bad"]})
    FakeSpypoint.photos["sp-good"] = shots("sp-good", 600, NOW - timedelta(minutes=5),
                                           step=timedelta(hours=2))  # 50 days
    FakeSpypoint.photos["sp-bad"] = shots("sp-bad", 3, NOW - timedelta(hours=1))
    sync.sync_all(db_session)  # sp-bad comes in once, then its listing starts failing
    FakeSpypoint.list_errors["sp-bad"] = SpypointError("POST /photo/all -> HTTP 500", 500)
    per_run = []
    for _ in range(2):
        FakeSpypoint.pages.clear()
        sync.sync_all(db_session)
        per_run.append(sum(1 for p in FakeSpypoint.pages if p[0] == "sp-good"))
    assert per_run == [1, 1]  # a routine page, not the two months again
    row = next(r for r in list_accounts(_member(db_session, spypoint, "admin"), db_session)
               if r["id"] == str(marco.id))
    assert row["importing"] is False and row["status"]["state"] == "ok"
    assert row["status"]["cameras_failing"] == 1
    assert row["status"]["camera_error"].startswith("SPYPOINT isn't answering properly")
    bad = db_session.scalar(select(Camera).where(Camera.spypoint_id == "sp-bad"))
    health = camera_health(bad, login=logins.camera_logins(db_session, [bad])[bad.id])
    assert health["status"] == "not_syncing" and not health["producing"]
    assert health["login"] == {"label": "Marco's cameras", "camera": True,
                               "error": bad.fetch_error}
    assert bad.fetch_error.startswith("SPYPOINT isn't answering properly")


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
                user, db_session)
    for username, words in (
        ("Julle@Example.com", "That SPYPOINT login is already added"),
        ("OWNER@example.com", "This login is already connected as the estate's main account"),
    ):
        with pytest.raises(HTTPException) as exc:
            add_account(AddAccountBody(username=username, password="p"),
                        user, db_session)
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


@requires_db
def test_a_copy_of_the_main_login_left_from_before_hands_its_cameras_back(
    db_session, spypoint,
):
    """A copy added before copies were refused still owns the main cameras: the main
    login takes them back on its first fetch, the copy's problem is not theirs, and
    removing the copy never switches them off."""
    from app.api.routes_camera_accounts import remove_account

    copy = guest(db_session, spypoint, "Owner@Example.com", label="Owner again")
    camera = Camera(estate_id=spypoint.id, spypoint_id="sp-1", name="PL14",
                    account_id=copy.id, last_report_at=NOW)
    db_session.add_all([camera, Camera(estate_id=spypoint.id, spypoint_id="sp-gone",
                                       name="Orphan", account_id=None)])
    db_session.commit()
    # Before any fetch: the main login is who fetches it.
    logins.record(db_session, None, cameras=1)
    logins.record(db_session, copy, error=sync.DUPLICATE_OF_PRIMARY)
    db_session.commit()
    assert logins.camera_logins(db_session, [camera])[camera.id]["label"] == "Main SPYPOINT login"

    FakeSpypoint.cameras["owner@example.com"] = ["sp-1"]
    FakeSpypoint.photos["sp-1"] = shots("sp-1", 3, NOW - timedelta(minutes=30))
    assert sync.sync_all(db_session)["total"] == 3
    db_session.refresh(camera)
    assert camera.account_id is None
    health = camera_health(camera, login=logins.camera_logins(db_session, [camera])[camera.id])
    assert health["status"] == "ok" and health["producing"]
    # The copy doesn't stop a camera no login lists from being switched off.
    orphan = db_session.scalar(select(Camera).where(Camera.spypoint_id == "sp-gone"))
    assert orphan.active is False

    # A camera still linked to the copy when it is removed stays on, with the main login.
    camera.account_id = copy.id
    db_session.commit()
    remove_account(copy.id, _member(db_session, spypoint, "admin"), db_session)
    db_session.refresh(camera)
    assert camera.active is True and camera.account_id is None


@requires_db
def test_a_camera_two_logins_list_belongs_to_the_first(db_session, spypoint):
    marco = guest(db_session, spypoint)
    FakeSpypoint.cameras.update({"owner@example.com": ["sp-1"],
                                 "marco@example.com": ["sp-1", "sp-2"]})
    sync.sync_all(db_session)
    owners = dict(db_session.execute(select(Camera.spypoint_id, Camera.account_id)).all())
    assert owners == {"sp-1": None, "sp-2": marco.id}
    # Marco's login breaking doesn't make the shared camera look stopped.
    FakeSpypoint.sign_everyone_out()
    FakeSpypoint.login_errors["marco@example.com"] = SpypointAuthError("refused", 401)
    sync.sync_all(db_session)
    cams = db_session.scalars(select(Camera).order_by(Camera.spypoint_id)).all()
    states = logins.camera_logins(db_session, cams)
    assert [camera_health(c, login=states.get(c.id))["status"] for c in cams] == [
        "ok", "not_syncing"]


# ── E-21: a login is not signed in afresh every 15 minutes ──────────────────────


@requires_db
def test_a_login_keeps_its_sign_in_between_fetches(db_session, spypoint, verified):
    from app.api import routes_camera_accounts as accounts

    marco = guest(db_session, spypoint)
    marco.owner_user_id = _member(db_session, spypoint).id
    FakeSpypoint.cameras.update({"owner@example.com": ["sp-1"], "marco@example.com": ["sp-2"]})
    for _ in range(3):
        sync.sync_all(db_session)
    assert sorted(FakeSpypoint.signins) == ["marco@example.com", "owner@example.com"]
    db_session.refresh(marco)
    assert marco.session_enc and "session-" not in marco.session_enc  # sealed
    assert logins.saved_session(db_session, None) == "session-owner@example.com-1"

    # SPYPOINT lets the sign-in lapse: the login signs in again, once, and keeps it.
    FakeSpypoint.sign_everyone_out()
    sync.sync_all(db_session)
    sync.sync_all(db_session)
    assert len(FakeSpypoint.signins) == 4

    # A new password starts a new sign-in.
    accounts.replace_password(marco.id, accounts.PasswordBody(password="new"),
                              db_session.get(User, marco.owner_user_id), db_session)
    assert logins.saved_session(db_session, db_session.get(CameraAccount, marco.id)) is None

    # One that can't be read (the key changed) is simply signed in afresh.
    marco = db_session.get(CameraAccount, marco.id)
    marco.session_enc = "not-a-sealed-token"
    db_session.commit()
    assert logins.saved_session(db_session, marco) is None


def test_a_kept_sign_in_runs_out_before_ubox_refuses_it(monkeypatch):
    kept = {}

    class Account:
        session_enc = None

    account = Account()
    logins.keep_session(None, account, "tok", valid_hours=2)
    kept["fresh"] = logins.saved_session(None, account)
    logins.keep_session(None, account, "tok", valid_hours=1)  # an hour early: gone now
    kept["lapsed"] = logins.saved_session(None, account)
    assert kept == {"fresh": "tok", "lapsed": None}


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
    # Later SPYPOINT signs the main login out and refuses its password.
    FakeSpypoint.sign_everyone_out()
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

    # Said once in each place: the line above the plan names the login and the way
    # to Settings, the plan's "Cameras not sending" card its cameras. The alerts
    # under them don't say it a third time (J-12).
    fresh = logins.freshness(db_session, now=NOW)
    assert fresh["problem"] == "login" and fresh["logins"] == ["Main SPYPOINT login"]
    feed = alerts.compute_alerts(db_session)
    assert not any(a["type"] == "camera" for a in feed)
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


@requires_db
def test_a_long_job_holding_the_pipeline_is_busy_not_stopped(
    db_session, spypoint, monkeypatch,
):
    from app.forecasting import alerts, model

    monkeypatch.setattr(model, "_tonight_conditions", lambda now: {"moon_phase": "New Moon"})
    cameras = []
    for n, username in enumerate(("marco@example.com", "ana@example.com", "leo@example.com")):
        account = guest(db_session, spypoint, username, label=username.split("@")[0])
        logins.record(db_session, account, cameras=1, now=NOW - timedelta(hours=3))
        cameras.append(Camera(estate_id=spypoint.id, spypoint_id=f"sp-{n}", name=f"Cam {n}",
                              account_id=account.id, last_report_at=NOW - timedelta(hours=1)))
    db_session.add_all(cameras)
    db_session.commit()
    # The AI pass after a big import took the pipeline 2 h 30 min ago, before the
    # logins were due to be called stopped.
    monkeypatch.setattr(logins, "pipeline_busy_since", lambda now=None: NOW - timedelta(hours=2.5))
    states = logins.camera_logins(db_session, cameras, NOW)
    assert {s["state"] for s in states.values()} == {"busy"}
    assert camera_health(cameras[0], NOW, states[cameras[0].id])["status"] == "ok"
    assert logins.freshness(db_session, now=NOW)["problem"] is None

    # No job explains it: stopped, said once for the estate above the plan, not once
    # per login, and not again in the alerts (J-12).
    monkeypatch.setattr(logins, "pipeline_busy_since", lambda now=None: None)
    assert logins.freshness(db_session, now=NOW)["problem"] == "stopped"
    plan = model.forecast_tonight(db_session)
    assert plan["freshness"]["problem"] == "stopped"
    assert {a["camera"] for a in plan["alerts"]} == {"Cam 0", "Cam 1", "Cam 2"}
    assert not [a for a in alerts.compute_alerts(db_session) if a["type"] == "camera"]
    # A job that only began after they had stopped doesn't excuse them.
    busy = datetime.now(UTC) - timedelta(minutes=10)
    monkeypatch.setattr(logins, "pipeline_busy_since", lambda now=None: busy)
    assert logins.camera_logins(db_session, cameras)[cameras[0].id]["state"] == "stale"


def test_the_pipeline_lock_says_when_a_job_began():
    import json
    import os
    import socket

    from app import jobs

    assert logins.pipeline_busy_since() is None
    lock = jobs.lock_path("pipeline")
    lock.parent.mkdir(parents=True, exist_ok=True)
    began = datetime.now(UTC) - timedelta(minutes=20)
    lock.write_text(json.dumps({"owner": "sync", "pid": os.getpid(), "host": socket.gethostname(),
                                "started": began.timestamp(), "token": "t"}))
    # Started 20 minutes ago, heartbeat fresh: a long job, still going.
    assert abs(logins.pipeline_busy_since() - began) < timedelta(seconds=1)
    beat = datetime.now(UTC) - timedelta(minutes=15)
    os.utime(lock, (beat.timestamp(), beat.timestamp()))
    assert logins.pipeline_busy_since() is None  # no heartbeat for 15 min: it died


@pytest.mark.parametrize(("exc", "words"), [
    (SpypointError("GET /camera/all -> HTTP 404", 404),
     "SPYPOINT refused the request. It tries again on the next fetch."),
    (SpypointError("login response missing token"),
     "SPYPOINT sent something the app can't read. It tries again on the next fetch."),
    (SpypointAuthError("login refused: HTTP 401", 401),
     "SPYPOINT refused the password. Re-enter it."),
])
def test_login_errors_are_words_without_the_request_behind_them(exc, words):
    assert logins.login_error(exc, "spypoint") == words


@pytest.mark.parametrize(("error", "asks"), [
    ("SPYPOINT refused the password. Re-enter it.", True),
    ("UBox signed this login out. Re-enter the password.", True),
    ("The saved password can't be read. Re-enter it.", True),
    ("Couldn't reach SPYPOINT. It tries again on the next fetch.", False),
    ("SPYPOINT is turning requests away for now. It tries again on the next fetch.", False),
    (sync.DUPLICATE_OF_PRIMARY, False),
    (None, False),
])
def test_only_a_password_problem_asks_for_the_password(error, asks):
    assert logins.asks_for_password(error) is asks


@requires_db
def test_re_entering_a_password_while_the_provider_is_unreachable_says_so(
    db_session, spypoint, verified, monkeypatch,
):
    from app.api import routes_camera_accounts as accounts

    admin = _member(db_session, spypoint, "admin")
    marco = guest(db_session, spypoint)
    logins.record(db_session, marco,
                  error="Couldn't reach SPYPOINT. It tries again on the next fetch.")
    db_session.commit()
    row = next(r for r in accounts.list_accounts(admin, db_session) if r["id"] == str(marco.id))
    assert row["status"]["password_problem"] is False  # a new password wouldn't help

    for failure in (httpx.ConnectTimeout("timed out"), httpx.ProxyError("proxy"),
                    SpypointError("login failed: HTTP 503", 503)):
        def unreachable(self, failure=failure):
            raise failure

        monkeypatch.setattr(verified, "login", unreachable)
        with pytest.raises(HTTPException) as exc:
            accounts.replace_password(marco.id, accounts.PasswordBody(password="new"),
                                      admin, db_session)
        assert exc.value.status_code == 503
        assert exc.value.detail == (
            "Couldn't reach SPYPOINT to check the password. Try again in a few minutes.")
    assert crypto.decrypt(db_session.get(CameraAccount, marco.id).password_enc) == "guest-secret"

    def refused(self):
        raise SpypointAuthError("login refused: HTTP 401", 401)

    monkeypatch.setattr(verified, "login", refused)
    with pytest.raises(HTTPException) as exc:
        accounts.add_account(accounts.AddAccountBody(username="new@example.com", password="x"),
                             admin, db_session)
    assert exc.value.status_code == 400
    assert exc.value.detail == (
        "SPYPOINT refused that email and password. Check them in the SPYPOINT app.")

    monkeypatch.setattr(accounts, "UboxClient", _UnreachableUbox)
    with pytest.raises(HTTPException) as exc:
        accounts.add_account(accounts.AddAccountBody(username="ana@example.com", password="x",
                                                     provider="ubox"),
                             admin, db_session)
    assert exc.value.status_code == 503 and "Couldn't reach UBox" in exc.value.detail


class _UnreachableUbox:
    def __init__(self, *_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def login(self):
        from app.ingestion.ubox import UboxError

        raise UboxError("Unable to reach UBox for login")


@requires_db
def test_a_disconnected_camera_keeps_its_photo_filter(db_session, spypoint):
    from app.api.routes_photos import filters
    from app.models import Detection, Species

    user = _member(db_session, spypoint, "viewer")
    kept = Camera(estate_id=spypoint.id, spypoint_id="sp-1", name="Old feeder", active=False)
    bare = Camera(estate_id=spypoint.id, spypoint_id="sp-2", name="Never used", active=False)
    live = Camera(estate_id=spypoint.id, spypoint_id="sp-3", name="Charca")
    db_session.add_all([kept, bare, live])
    db_session.flush()
    if db_session.get(Species, "wild_boar") is None:
        db_session.add(Species(id="wild_boar", common_name="Wild boar"))
    photo = Image(camera_id=kept.id, captured_at=NOW, original_path="/x.jpg",
                  processed_at=NOW, is_empty_frame=False)
    db_session.add(photo)
    db_session.flush()
    db_session.add(Detection(image_id=photo.id, species_id="wild_boar", species_conf=0.9))
    db_session.commit()
    chips = {c["name"]: c for c in filters(user, db_session)["cameras"]}
    assert set(chips) == {"Old feeder", "Charca"}
    assert chips["Old feeder"]["connected"] is False and chips["Old feeder"]["count"] == 1
    assert chips["Charca"]["connected"] is True


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
def test_a_camera_no_login_lists_is_disconnected_once_its_own_login_answers(
    db_session, spypoint,
):
    """E-23: a camera left by a login removed before this change (no login on it)
    is switched off as soon as the main login answers without it, even while a
    guest's login is failing; a camera of that guest's stays until the guest answers."""
    marco = guest(db_session, spypoint)
    db_session.add_all([
        Camera(estate_id=spypoint.id, spypoint_id="sp-gone", name="Orphan"),
        Camera(estate_id=spypoint.id, spypoint_id="sp-4", name="Marco's old one",
               account_id=marco.id),
    ])
    db_session.commit()
    FakeSpypoint.cameras.update({"owner@example.com": ["sp-1"], "marco@example.com": ["sp-3"]})
    FakeSpypoint.login_errors["marco@example.com"] = SpypointAuthError("refused", 401)
    sync.sync_all(db_session)
    orphan = db_session.scalar(select(Camera).where(Camera.spypoint_id == "sp-gone"))
    marcos = db_session.scalar(select(Camera).where(Camera.spypoint_id == "sp-4"))
    assert orphan.active is False
    assert marcos.active is True  # Marco's login didn't answer: it may still list it
    del FakeSpypoint.login_errors["marco@example.com"]
    sync.sync_all(db_session)
    db_session.refresh(marcos)
    assert marcos.active is False
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
    monkeypatch.setattr(fetch, "check_and_recount", lambda db: ({}, None))
    fetch.run_fetch(db_session)
    row = fetch.latest_run(db_session)
    assert (row.status, row.images_downloaded) == ("partial", 3)
    assert row.details["stage"] == "done" and row.finished_at is not None
    assert row.details["problems"][0]["label"] == "SPYPOINT"
    assert "RuntimeError" in row.details["problems"][0]["error"]


@requires_db
def test_sync_status_reports_the_count_while_the_detector_is_still_looking(
    db_session, spypoint,
):
    from app import jobs
    from app.api import routes_cameras

    viewer = _member(db_session, spypoint, "viewer")
    db_session.add(SyncLog(status="ok", started_at=NOW - timedelta(hours=1),
                           images_downloaded=9, details={"provider": "pipeline",
                                                         "stage": "done", "problems": []}))
    db_session.commit()
    lock = jobs.try_acquire("pipeline", "sync")
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

    lock.release()
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
                user, db_session)
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


# ── 28 Sep 2026: the fetch as the server runs it ────────────────────────────────
#
# On the server every SPYPOINT fetch said "The SPYPOINT fetch failed (IntegrityError)"
# and 0 photos. Its main login had no record yet (app_settings 'spypoint_primary_login');
# after the cameras, record() added one and keep_session() added a second, as the
# server's sessions don't autoflush and db.get() doesn't see a row only added. The
# commit broke pk_app_settings, outside every per-camera try, and nothing ever made the
# row, so each fetch failed the same way. These tests use a session as the server
# makes one (app.core.db.server_sessions).


class _Said:
    """A stand-in for a module's log: what it was told, as (level, event, fields)."""

    def __init__(self):
        self.lines: list[tuple[str, str, dict]] = []

    def __getattr__(self, level):
        return lambda event, **fields: self.lines.append((level, event, fields))

    def errors(self):
        return [(event, fields) for level, event, fields in self.lines if level == "error"]


def _server_session(bind):
    from app.core.db import server_sessions

    return server_sessions(bind)()


@pytest.fixture
def server_db(db_session):
    s = _server_session(db_session.get_bind())
    try:
        yield s
    finally:
        s.close()


def _still_running(db) -> int:
    return db.scalar(select(func.count(SyncLog.id)).where(SyncLog.status == "running"))


@requires_db
def test_the_first_fetch_on_the_servers_session_keeps_the_main_logins_record(
    db_session, spypoint, server_db,
):
    marco = guest(db_session, spypoint)
    FakeSpypoint.cameras.update({"owner@example.com": ["sp-1", "sp-2"],
                                 "marco@example.com": ["sp-3"]})
    for cid in ("sp-2", "sp-3"):
        FakeSpypoint.photos[cid] = shots(cid, 2, NOW - timedelta(hours=1))
    assert server_db.get(AppSetting, logins.PRIMARY_KEY) is None  # as on the server

    row, results = fetch.fetch_photos(server_db)
    assert results["spypoint"]["status"] == "ok", results["spypoint"]
    assert (row.status, row.images_downloaded, row.error) == ("ok", 4, None)
    status = logins.primary_status(db_session)
    assert status["last_error"] is None and status["reported_cameras"] == 2
    assert status["last_ok_at"] is not None
    assert logins.saved_session(db_session, None) == "session-owner@example.com-1"
    db_session.refresh(marco)
    assert marco.last_ok_at is not None  # the login after the main one was fetched
    assert _still_running(db_session) == 0

    # The next fetch uses the kept sign-in, and its record is updated, not added again.
    row, results = fetch.fetch_photos(server_db)
    assert results["spypoint"]["status"] == "ok" and row.status == "ok"
    assert FakeSpypoint.signins.count("owner@example.com") == 1
    assert db_session.scalar(select(func.count()).select_from(AppSetting).where(
        AppSetting.key == logins.PRIMARY_KEY)) == 1


@requires_db
def test_two_runs_making_the_main_logins_record_at_once_both_keep_it(db_session, spypoint):
    """Both find no record and both write one (a Check pressed as a stale lock is taken
    over): the second waits for the first on the key and then updates its row, where
    it used to fail on pk_app_settings as the first committed."""
    import threading
    import time

    first, second = (_server_session(db_session.get_bind()) for _ in range(2))
    down = i18n.stored("login.spypoint_down")
    outcome: list = []

    def other_run():
        try:
            logins.record(second, None, error=down)
            second.commit()
            outcome.append("saved")
        except Exception as exc:  # what the test is about: it must not happen
            second.rollback()
            outcome.append(exc)

    try:
        logins.record(first, None, cameras=2)  # written, not committed yet
        run = threading.Thread(target=other_run)
        run.start()
        waiting = text("SELECT count(*) FROM pg_stat_activity WHERE datname = "
                       "current_database() AND wait_event_type = 'Lock'")
        for _ in range(100):  # the second run's INSERT waits on the first's key
            seen = db_session.execute(waiting).scalar()
            db_session.rollback()  # pg_stat_activity is read once per transaction
            if seen or not run.is_alive():
                break
            time.sleep(0.05)
        first.commit()
        run.join(timeout=10)
    finally:
        first.close()
        second.close()
    assert outcome == ["saved"]
    assert logins.primary_status(db_session)["last_error"] == down


@requires_db
def test_a_login_whose_record_cannot_be_saved_costs_only_that_login(
    db_session, spypoint, server_db, monkeypatch,
):
    """The main login's record written as it was on the server (added, then added
    again): its bookkeeping fails, and nothing else. Its photos, the guest login after
    it and the run's summary are kept, and the summary names the rule that broke."""

    def added_twice(db, row, value):  # _save_primary before the fix
        if row is None:
            db.add(AppSetting(key=logins.PRIMARY_KEY, value=value))
        else:
            row.value = value

    monkeypatch.setattr(logins, "_save_primary", added_twice)
    said = _Said()
    monkeypatch.setattr(logins, "log", said)
    marco = guest(db_session, spypoint)
    FakeSpypoint.cameras.update({"owner@example.com": ["sp-1"], "marco@example.com": ["sp-2"]})
    for cid in ("sp-1", "sp-2"):
        FakeSpypoint.photos[cid] = shots(cid, 2, NOW - timedelta(hours=1))

    row, results = fetch.fetch_photos(server_db)
    reason = "IntegrityError: pk_app_settings"
    spy = results["spypoint"]
    assert (spy["status"], spy["total"]) == ("partial", 4)
    main, other = spy["accounts"]
    assert (main["status"], main["not_saved"]) == ("partial", reason)
    assert main["error"] == i18n.stored("sync.login_not_saved", error=reason)
    assert (other["status"], other["error"]) == ("ok", None)
    db_session.refresh(marco)
    assert marco.last_ok_at is not None
    assert len(images(db_session)) == 4
    assert (row.status, row.images_downloaded) == ("partial", 4)
    assert row.details["problems"] == [{"label": logins.PRIMARY_LABEL, "error": main["error"]}]
    assert _still_running(db_session) == 0
    [(event, fields)] = said.errors()
    assert (event, fields["reason"], fields["account"]) == (
        "spypoint.login_not_saved", reason, "owner@example.com")
    assert "pk_app_settings" in fields["error"] and fields["exc_info"] is True
    for lang in i18n.LANGUAGES:  # read in each language, the rule's name kept
        assert f"({reason})" in i18n.localize(main["error"], lang)


@requires_db
def test_a_refused_write_is_named_by_the_rule_it_broke(db_session, spypoint, monkeypatch):
    from app.core.db import error_name

    def refused(sql, **params):
        try:
            with db_session.begin_nested():
                db_session.execute(text(sql), params)
        except IntegrityError as exc:
            return error_name(exc)
        raise AssertionError(f"the database took {sql}")

    twice = "INSERT INTO app_settings (key, value) VALUES ('k', '{}'), ('k', '{}')"
    assert refused(twice) == "IntegrityError: pk_app_settings"
    assert refused("INSERT INTO app_settings (key, value) VALUES ('k', NULL)") == (
        "IntegrityError: app_settings.value")
    assert refused(
        "INSERT INTO camera_accounts (id, estate_id, provider, username, password_enc,"
        " active) VALUES (gen_random_uuid(), :estate, 'ftp', 'x', 'y', true)",
        estate=spypoint.id) == "IntegrityError: ck_camera_accounts_provider_valid"
    assert error_name(RuntimeError("database went away")) == "RuntimeError"

    # A provider's run that raises one: the reason kept and shown names the rule, and
    # the log has it with where it was raised.
    monkeypatch.setattr(sync, "sync_all", lambda db: db.execute(text(twice)))
    said = _Said()
    monkeypatch.setattr(fetch, "log", said)
    row, results = fetch.fetch_photos(db_session)
    reason = "IntegrityError: pk_app_settings"
    assert results["spypoint"]["reason"] == i18n.stored(
        "fetch.provider_failed", provider="SPYPOINT", error=reason)
    assert row.error == (
        "SPYPOINT: The SPYPOINT fetch failed (IntegrityError: pk_app_settings). "
        "It tries again on the next one.")
    [(event, fields)] = said.errors()
    assert (event, fields["provider"], fields["reason"]) == (
        "fetch.provider_failed", "spypoint", reason)
    assert "pk_app_settings" in fields["error"] and fields["exc_info"] is True
    for lang in i18n.LANGUAGES:
        assert f"({reason})" in i18n.localize(results["spypoint"]["reason"], lang)


@requires_db
def test_a_server_upgraded_to_this_version_fetches_on_its_first_run(
    fresh_db, monkeypatch, tmp_path,
):
    """As on the server: a database migrated long ago (the snapshot of one at 0030),
    with the rows a server has but no record of the main login yet, upgraded to this
    version and fetched as the server fetches. Cam1 stopped checking in on Saturday and
    sent only empty frames; Cam2 has photos whose file never came after 5 tries; a
    removed person's login is now the admin's; a UBox and a Suntek camera sit beside
    them."""
    from alembic import command

    from . import schema_snapshot
    from .conftest import alembic_config

    fake_spypoint(monkeypatch, tmp_path)
    schema_snapshot.load(fresh_db)
    eng = create_engine(fresh_db)
    ids = {k: uuid.uuid4() for k in ("estate", "admin", "marco", "cam1", "cam2", "cam3")}
    saturday = NOW - timedelta(days=2)
    try:
        with eng.begin() as c:
            c.execute(text("INSERT INTO estates (id, name, timezone) "
                           "VALUES (:estate, 'Piedras Lisas', 'Europe/Madrid')"), ids)
            c.execute(text("INSERT INTO users (id, estate_id, email, password_hash, role) "
                           "VALUES (:admin, :estate, 'admin@estate.local', 'x', 'admin')"), ids)
            c.execute(text(
                "INSERT INTO camera_accounts (id, estate_id, owner_user_id, former_owner,"
                " label, provider, username, password_enc, active, last_sync_at)"
                " VALUES (:marco, :estate, :admin, 'Marco', 'Marco''s cameras', 'spypoint',"
                " 'marco@example.com', :pw, true, :synced)"),
                {**ids, "pw": crypto.encrypt("guest-secret"),
                 "synced": NOW - timedelta(days=1)})
            cameras = [("cam1", "sp-cam1", None, "Cam1", saturday),
                       ("cam2", "sp-cam2", None, "Cam2", NOW - timedelta(hours=1)),
                       ("cam3", "sp-cam3", ids["marco"], "Marco's", NOW)]
            for key, sid, account, name, report in cameras:
                c.execute(text(
                    "INSERT INTO cameras (id, estate_id, account_id, spypoint_id, name,"
                    " provider_name, active, last_report_at, last_sync_at)"
                    " VALUES (:id, :estate, :account, :sid, :name, :name, true, :report,"
                    " :report)"), {"id": ids[key], "estate": ids["estate"],
                                   "account": account, "sid": sid, "name": name,
                                   "report": report})
            c.execute(text(
                "INSERT INTO cameras (id, estate_id, ubox_uid, name, active) VALUES"
                " (gen_random_uuid(), :estate, 'ub-1', 'UBox orchard', true),"
                " (gen_random_uuid(), :estate, NULL, 'Suntek gate', true)"), ids)
            photo = ("INSERT INTO images (id, camera_id, spypoint_photo_id, captured_at,"
                     " original_path, cdn_url, download_attempts, reviewed, is_empty_frame)"
                     " VALUES (gen_random_uuid(), :camera, :pid, :at, :path, :url, :tries,"
                     " false, :empty)")
            for i in range(69):  # Cam1: empty frames, the newest 8 days ago
                c.execute(text(photo), {"camera": ids["cam1"], "pid": f"c1-{i}",
                                        "at": NOW - timedelta(days=8, hours=i),
                                        "path": f"old/c1-{i}.jpg", "url": None,
                                        "tries": 0, "empty": True})
            for i in range(3):  # Cam2: given up on after 5 tries, listed again today
                c.execute(text(photo), {"camera": ids["cam2"], "pid": f"sp-cam2-{i + 1}",
                                        "at": NOW - timedelta(days=1, minutes=10 * (i + 1)),
                                        "path": None, "url": "https://cdn/expired.jpg",
                                        "tries": 5, "empty": None})
            c.execute(text("INSERT INTO sync_log (id, status, started_at, finished_at,"
                           " images_downloaded, details) VALUES (gen_random_uuid(), 'ok',"
                           " :at, :at, 0, '{\"provider\": \"spypoint\"}')"),
                      {"at": NOW - timedelta(days=1)})
        command.upgrade(alembic_config(fresh_db), "head")

        FakeSpypoint.cameras.update({"owner@example.com": ["sp-cam1", "sp-cam2"],
                                     "marco@example.com": ["sp-cam3"]})
        FakeSpypoint.photos["sp-cam2"] = [
            SpypointPhoto("sp-cam2-0", NOW - timedelta(hours=2), url="https://cdn/c2-0.jpg"),
            *[SpypointPhoto(f"sp-cam2-{i}", NOW - timedelta(days=1, minutes=10 * i),
                            url=f"https://cdn/c2-{i}.jpg") for i in (1, 2, 3)],
        ]
        FakeSpypoint.photos["sp-cam3"] = shots("sp-cam3", 2, NOW - timedelta(hours=3))
        db = _server_session(eng)
        try:
            assert db.get(AppSetting, logins.PRIMARY_KEY) is None
            row, results = fetch.fetch_photos(db)
            assert results["spypoint"]["status"] == "ok", results["spypoint"]
            assert (row.status, row.images_downloaded, row.error) == ("ok", 6, None)
            assert logins.primary_status(db)["reported_cameras"] == 2
            assert logins.saved_session(db, None) == "session-owner@example.com-1"
            marco = db.get(CameraAccount, ids["marco"])
            db.refresh(marco)
            assert marco.last_ok_at is not None and marco.last_error is None
            got = {i.spypoint_photo_id for i in db.scalars(select(Image).where(
                Image.camera_id == ids["cam2"], Image.original_path.isnot(None)))}
            assert got == {"sp-cam2-0", "sp-cam2-1", "sp-cam2-2", "sp-cam2-3"}
            assert _still_running(db) == 0
            # Cam1's card says what SPYPOINT says: no check-in since Saturday.
            cam1 = db.get(Camera, ids["cam1"])
            db.refresh(cam1)
            assert cam1.active and cam1.fetch_error is None
            row, results = fetch.fetch_photos(db)  # and the next one
            assert results["spypoint"]["status"] == "ok" and row.status == "ok"
        finally:
            db.close()
    finally:
        eng.dispose()
