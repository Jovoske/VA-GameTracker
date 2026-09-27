"""Admission limits and real Postgres gallery/ingestion integration."""
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image as PillowImage
from sqlalchemy import func, select, text

from app.core.crypto import encrypt
from app.health import camera_health
from app.ingestion import logins
from app.ingestion import ubox_sync as sync
from app.ingestion.ubox import UboxDevice, UboxError, UboxEvent, UboxPageLimitError
from app.media import resolve
from app.models import Camera, CameraAccount, Estate, Image, SyncLog, User

from .conftest import requires_db

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


def test_interval_handles_unordered_and_late_arrivals():
    budget = sync.ImportBudget([NOW + timedelta(seconds=120), NOW], 60, 500, "UTC")
    assert budget.reason(NOW + timedelta(seconds=59)) == "interval_skipped"
    assert budget.reason(NOW + timedelta(seconds=61)) == "interval_skipped"
    assert budget.reason(NOW + timedelta(seconds=60)) is None
    budget.record(NOW + timedelta(seconds=60))
    assert budget.reason(NOW + timedelta(seconds=60)) == "interval_skipped"
    assert budget.reason(NOW - timedelta(seconds=30)) == "interval_skipped"


def test_daily_limit_resets_at_estate_midnight_and_interval_crosses_it():
    before = datetime(2026, 9, 16, 21, 59, 50, tzinfo=UTC)  # Madrid 23:59:50
    budget = sync.ImportBudget([before], 60, 1, "Europe/Madrid")
    assert budget.reason(before - timedelta(hours=1)) == "daily_limit_skipped"
    assert budget.reason(before + timedelta(seconds=20)) == "interval_skipped"
    assert budget.reason(before + timedelta(seconds=60)) is None


def test_dst_repeated_hour_shares_daily_allowance():
    first = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    second = first + timedelta(hours=1)
    budget = sync.ImportBudget([first], 60, 1, "Europe/Madrid")
    assert budget.reason(second) == "daily_limit_skipped"


def jpeg(color="red"):
    stream = BytesIO()
    PillowImage.new("RGB", (24, 12), color).save(stream, format="JPEG")
    return stream.getvalue()


@pytest.mark.parametrize("data", [b"", b"<html>Expired URL</html>", jpeg()[:60]])
def test_invalid_snapshots_are_not_gallery_files(data):
    with pytest.raises(UboxError):
        sync._jpeg(data)


def test_jpeg_dimensions():
    assert sync._jpeg(jpeg()) == (24, 12)


def test_saturated_period_splits_into_complete_ordered_windows():
    class BusyCamera:
        calls = 0

        def list_events(self, uid, start, end, page_size):
            self.calls += 1
            if end - start > timedelta(hours=6):
                raise UboxPageLimitError("too many pages")
            return [UboxEvent(f"{uid}:{start.timestamp()}", uid, start, "https://example.com/1")]

    client = BusyCamera()
    windows = list(sync._event_windows(client, "busy", NOW - timedelta(days=1), NOW))
    assert len(windows) == 4 and client.calls == 7
    assert [w[0].captured_at for w in windows] == [
        NOW - timedelta(hours=hours) for hours in (24, 18, 12, 6)
    ]


def test_saturated_minute_raises_instead_of_silently_losing_events():
    class BusyCamera:
        def list_events(self, *args, **kwargs):
            raise UboxPageLimitError("too many pages")

    with pytest.raises(UboxPageLimitError):
        list(sync._event_windows(BusyCamera(), "busy", NOW, NOW + timedelta(minutes=1)))


class FakeClient:
    events = []
    downloads = []
    windows = []
    payloads = {}
    devices = [UboxDevice("cam-1", "UBox orchard", battery_pct=82, online=True)]
    fail_listing = False
    signins = 0
    token = None
    token_valid_hours = None

    def __init__(self, username, password):
        assert password == "example-password"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def login(self):
        FakeClient.signins += 1
        self.token, self.token_valid_hours = f"session-{FakeClient.signins}", 696

    def use_token(self, token):
        self.token = token

    def list_devices(self):
        return self.devices

    def list_events(self, uid, since, until, page_size=100):
        self.windows.append((since, until))
        if self.fail_listing:
            raise UboxError("Pagination was incomplete")
        return [e for e in self.events if e.device_uid == uid and since <= e.captured_at <= until]

    def download(self, url):
        self.downloads.append(url)
        color = "red" if url.endswith("1") else ("green" if url.endswith("4") else "blue")
        data = self.payloads.get(url, jpeg(color))
        if isinstance(data, Exception):
            raise data
        return data


def event(identifier, seconds=0, *, uid="cam-1", url=None):
    return UboxEvent(f"{uid}:{identifier}", uid, NOW + timedelta(seconds=seconds),
                     url if url is not None else f"https://example.com/{identifier}")


@pytest.fixture
def setup(db_session, monkeypatch, tmp_path):
    FakeClient.events, FakeClient.downloads, FakeClient.windows = [], [], []
    FakeClient.payloads = {}
    FakeClient.fail_listing = False
    FakeClient.signins = 0
    FakeClient.devices = [UboxDevice("cam-1", "UBox orchard", battery_pct=82, online=True)]
    monkeypatch.setattr(sync, "UboxClient", FakeClient)
    monkeypatch.setattr(sync.settings, "media_root", str(tmp_path / "media"))
    monkeypatch.setattr(sync, "enrich_image", lambda *args: None)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (NOW + timedelta(hours=1)).astimezone(tz or UTC)

    monkeypatch.setattr(sync, "datetime", Clock)
    estate = Estate(name="UBox test estate", timezone="Europe/Madrid")
    db_session.add(estate)
    db_session.flush()
    account = CameraAccount(estate_id=estate.id, username="ubox@example.com",
                            provider="ubox", password_enc=encrypt("example-password"))
    db_session.add(account)
    db_session.commit()
    return account


@requires_db
def test_sync_images_are_served_in_gallery_and_repeat_is_idempotent(db_session, setup):
    from app.api.routes_cameras import camera_images
    from app.api.routes_images import image_file
    from app.core.security import image_token

    FakeClient.events = [event("2", 120), event("1")]
    result = sync.sync_ubox_all(db_session)
    assert result["total"] == 2 and result["status"] == "ok"
    camera = db_session.scalar(select(Camera))
    assert camera.account_id == setup.id
    assert camera.ubox_uid == "cam-1" and camera.spypoint_id is None
    assert camera.battery_pct == 82 and camera.photo_limit is None
    assert camera.last_report_at and camera.last_sync_at
    # A real login: the photo endpoints look the person up, as every other one does.
    # An admin: until the AI has looked at them, fresh photos are theirs alone (R6BE-2).
    user = User(estate_id=setup.estate_id, email="owner@ubox.local", password_hash="x",
                role="admin")
    db_session.add(user)
    db_session.commit()
    gallery = camera_images(camera.id, limit=40, include_empty=False, user=user, db=db_session)
    assert len(gallery) == 2 and all(i["file_url"] for i in gallery)
    for image in db_session.scalars(select(Image)):
        assert image.width == 24 and image.height == 12
        assert Path(image.original_path).name.startswith("ubox_")
        assert ":" not in Path(image.original_path).name
        response = image_file(image.id, token=image_token(user),
                              download=False, creds=None, db=db_session)
        assert Path(response.path).read_bytes() in (jpeg("red"), jpeg("blue"))
    second = sync.sync_ubox_all(db_session)
    assert second["total"] == 0 and len(FakeClient.downloads) == 2
    assert db_session.scalar(select(func.count(Camera.id))) == 1
    assert db_session.scalar(select(func.count(Image.id))) == 2
    assert db_session.scalar(select(func.count(SyncLog.id))) == 2
    latest = db_session.scalar(select(SyncLog).order_by(SyncLog.finished_at.desc()))
    assert latest.details["provider"] == "ubox"


@requires_db
def test_limits_apply_before_download_across_syncs_and_initial_backfill(db_session, setup):
    setup.ubox_max_images_per_day = 2
    db_session.commit()
    FakeClient.events = [event("4", 240), event("2", 120), event("burst", 230), event("1")]
    result = sync.backfill_ubox_account(db_session, setup.id)
    assert result["downloaded"] == 2
    assert result["interval_skipped"] == 1 and result["daily_limit_skipped"] == 1
    assert len(FakeClient.downloads) == 2
    FakeClient.events += [event("late", 30), event("later", 360)]
    result = sync.sync_ubox_all(db_session)
    assert result["total"] == 0 and result["daily_limit_skipped"] >= 2
    assert len(FakeClient.downloads) == 2
    assert len(FakeClient.windows) >= 7  # automatic initial history is split by day


@requires_db
def test_duplicate_content_no_image_and_bad_download_are_not_blank_tiles(db_session, setup):
    FakeClient.events = [event("1"), event("same", 120), event("empty", 240, url=""),
                         event("bad", 360)]
    FakeClient.payloads = {"https://example.com/same": jpeg("red"),
                           "https://example.com/bad": b"<html>expired</html>"}
    result = sync.sync_ubox_all(db_session)
    assert result["downloaded"] == 1 and result["duplicate"] == 1
    assert result["no_image"] == 1 and result["failed"] == 1
    # One dead snapshot is a warning, not a failed login (E-08): the login counts as
    # fetched, and the camera holds its place at the snapshot to try it again.
    assert result["status"] == "partial"
    assert result["accounts"][0]["error"] == (
        "1 photo wouldn't download. It is tried again on the next fetch.")
    assert db_session.scalar(select(func.count(Image.id))) == 1
    camera = db_session.scalar(select(Camera))
    assert camera.last_sync_at == NOW + timedelta(seconds=360)
    assert camera.import_failures["cam-1:bad"][0] == 1
    assert setup.last_sync_at == NOW + timedelta(hours=1)
    assert setup.last_error is None and setup.last_ok_at is not None


@requires_db
def test_expired_full_image_falls_back_to_thumbnail(db_session, setup):
    item = event("full")
    item.fallback_image_url = "https://example.com/thumb"
    FakeClient.events = [item]
    FakeClient.payloads[item.image_url] = UboxError("expired")
    assert sync.sync_ubox_all(db_session)["total"] == 1
    assert FakeClient.downloads == [item.image_url, item.fallback_image_url]


@requires_db
def test_broken_snapshot_batch_stops_after_five_attempts(db_session, setup):
    FakeClient.events = [event(f"bad-{i}", i * 60) for i in range(30)]
    FakeClient.payloads = {e.image_url: UboxError("expired") for e in FakeClient.events}
    result = sync.sync_ubox_all(db_session)
    assert result["failed"] == 5 and len(FakeClient.downloads) == 5
    assert result["status"] == "partial"


@requires_db
def test_expired_history_does_not_starve_current_gallery(db_session, setup):
    FakeClient.events = [event(f"bad-{i}", -5 * 86400 + i * 60) for i in range(30)]
    FakeClient.payloads = {e.image_url: UboxError("expired") for e in FakeClient.events}
    FakeClient.events.append(event("1"))
    result = sync.sync_ubox_all(db_session)
    assert result["total"] == 1 and result["failed"] == 5
    assert db_session.scalar(select(Image)).captured_at == NOW
    # The next pass keeps the recent photo and retries only a bounded historical set.
    again = sync.sync_ubox_all(db_session)
    assert again["total"] == 0 and again["failed"] == 5


@requires_db
def test_enrichment_sql_error_does_not_poison_image(db_session, setup, monkeypatch):
    monkeypatch.setattr(sync, "enrich_image", lambda db, _: db.execute(text("SELECT 1/0")))
    FakeClient.events = [event("1")]
    assert sync.sync_ubox_all(db_session)["total"] == 1
    assert db_session.scalar(select(Image)) is not None


@requires_db
def test_pagination_failure_does_not_advance_watermark(db_session, setup):
    original = NOW - timedelta(hours=3)
    camera = Camera(estate_id=setup.estate_id, account_id=setup.id, ubox_uid="cam-1",
                    name="Orchard", last_sync_at=original)
    setup.last_sync_at = original
    db_session.add(camera)
    db_session.commit()
    FakeClient.fail_listing = True
    result = sync.sync_ubox_all(db_session)
    assert result["status"] == "error" and camera.last_sync_at == original
    assert setup.last_sync_at == original
    assert FakeClient.windows[0][0] == original - timedelta(hours=2)


@requires_db
def test_spypoint_accounts_are_not_sent_to_ubox_and_vice_versa(db_session, setup, monkeypatch):
    from app.ingestion.sync import _accounts

    monkeypatch.setattr(sync.settings, "spypoint_username", "")
    monkeypatch.setattr(sync.settings, "spypoint_password", "")
    account = CameraAccount(estate_id=setup.estate_id, provider="spypoint",
                            username="spypoint@example.com", password_enc=encrypt("other"))
    db_session.add(account)
    db_session.commit()
    assert [a.id for a in sync._ubox_accounts(db_session)] == [setup.id]
    assert [a["id"] for a in _accounts(db_session)] == [account.id]


@requires_db
def test_camera_cannot_be_rehomed_across_estates(db_session, setup):
    other = Estate(name="Other estate", timezone="UTC")
    db_session.add(other)
    db_session.flush()
    camera = Camera(estate_id=other.id, ubox_uid="cam-1", name="Other owner's camera")
    db_session.add(camera)
    db_session.commit()
    assert sync.sync_ubox_all(db_session)["status"] == "error"
    assert camera.estate_id == other.id and camera.account_id is None


@requires_db
def test_unchanged_snapshots_do_not_move_existing_capture_times(db_session, setup):
    FakeClient.events = [event("1")]
    sync.sync_ubox_all(db_session)
    image = db_session.scalar(select(Image))
    before = image.captured_at
    sync.backfill_ubox_account(db_session, setup.id)
    assert image.captured_at == before


@requires_db
def test_ubox_enters_normal_classification_and_animals_gallery(db_session, setup, monkeypatch):
    from app.ai import checking, species
    from app.api.routes_species import species_images, spotted
    from app.notifications import dispatch

    FakeClient.events = [event("1")]
    sync.sync_ubox_all(db_session)
    boxes = [{"confidence": 0.95, "bbox": [0.1, 0.1, 0.9, 0.9]}]
    monkeypatch.setattr(checking, "load_models", lambda: None)
    monkeypatch.setattr(checking, "detect", lambda _: boxes)
    monkeypatch.setattr(species, "classify_crop", lambda *_: ("fox", "Fox", 0.97))
    notified = []
    monkeypatch.setattr(dispatch, "dispatch_new_sightings", lambda db: notified.append(True))
    result = checking.check_photos(db_session)
    assert (result["animal"], result["by_species"]) == (1, {"fox": 1})
    assert notified == [True]
    user = User(id=setup.id, estate_id=setup.estate_id)
    animals = spotted(_=user, db=db_session)
    assert len(animals) == 1 and animals[0]["id"] == "fox"
    gallery = species_images("fox", limit=200, label=None, _=user, db=db_session)
    assert len(gallery) == 1 and gallery[0]["file_url"].endswith("/file")
    image = db_session.scalar(select(Image))
    assert str(image.id) in gallery[0]["file_url"] and Path(resolve(image.original_path)).is_file()
    # Stored under MEDIA_ROOT, not absolute: moving the media folder moves nothing else.
    assert not Path(image.original_path).is_absolute()


@requires_db
def test_failed_camera_commit_cleans_files_and_allows_next_camera(db_session, setup, monkeypatch):
    FakeClient.devices.append(UboxDevice("cam-2", "Second camera", online=True))
    FakeClient.events = [event("1"), event("2", uid="cam-2")]
    original_commit = db_session.commit
    commits = 0

    def fail_first_camera_commit():
        nonlocal commits
        commits += 1
        if commits == 2:  # first commit is the durable running SyncLog
            raise RuntimeError("simulated commit failure")
        original_commit()

    monkeypatch.setattr(db_session, "commit", fail_first_camera_commit)
    result = sync.sync_ubox_all(db_session)
    # One camera's photos came in and the other's did not: partial, not a failure.
    assert result["status"] == "partial" and result["total"] == 1
    assert db_session.scalar(select(Camera)).ubox_uid == "cam-2"
    assert db_session.scalar(select(func.count(Image.id))) == 1
    assert len(list(Path(sync.settings.media_root).rglob("*.jpg"))) == 1
    assert db_session.scalar(select(SyncLog)).status == "partial"
    assert result["accounts"][0]["error"].startswith("1 of 2 cameras failed.")


@requires_db
def test_concurrent_syncs_share_one_persisted_camera_allowance(db_session, setup, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import sessionmaker

    setup.ubox_max_images_per_day = 1
    db_session.commit()
    FakeClient.events = [event("1"), event("2", 120)]
    barrier = Barrier(2)
    monkeypatch.setattr(FakeClient, "login", lambda _: barrier.wait(timeout=10))
    factory = sessionmaker(bind=db_session.get_bind())

    def work(_):
        with factory() as session:
            return sync.sync_ubox_all(session)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, range(2)))
    assert all(r["status"] == "ok" for r in results)
    assert sum(r["total"] for r in results) == 1
    assert db_session.scalar(select(func.count(Camera.id))) == 1
    assert db_session.scalar(select(func.count(Image.id))) == 1
    assert len(FakeClient.downloads) == 1


@requires_db
def test_a_long_outage_is_caught_up_not_left_as_a_hole(db_session, setup):
    """E-06: three days without a fetch; the next one reads back to where it stopped."""
    stopped = NOW - timedelta(days=3)
    db_session.add(Camera(estate_id=setup.estate_id, account_id=setup.id, ubox_uid="cam-1",
                          name="Orchard", last_sync_at=stopped))
    setup.last_sync_at = stopped
    db_session.commit()
    FakeClient.events = [event("during", -2 * 86400), event("1")]
    result = sync.sync_ubox_all(db_session)
    assert result["downloaded"] == 2
    assert min(start for start, _ in FakeClient.windows) == stopped - timedelta(hours=2)


@requires_db
def test_catch_up_stops_at_what_ubox_still_lists(db_session, setup):
    stopped = NOW - timedelta(days=20)
    db_session.add(Camera(estate_id=setup.estate_id, account_id=setup.id, ubox_uid="cam-1",
                          name="Orchard", last_sync_at=stopped))
    setup.last_sync_at = stopped
    db_session.commit()
    sync.sync_ubox_all(db_session)
    until = NOW + timedelta(hours=1)
    assert min(start for start, _ in FakeClient.windows) == until - sync.CATCH_UP


@requires_db
def test_a_dead_snapshot_is_tried_three_times_then_let_go(db_session, setup):
    """E-08: it holds the camera's place while it may still come, then stops doing so."""
    FakeClient.events = [event("1", 60), event("bad")]
    FakeClient.payloads = {"https://example.com/bad": UboxError("expired")}
    for attempt in (1, 2, 3):
        result = sync.sync_ubox_all(db_session)
        assert result["failed"] == 1 and result["status"] == "partial"
        camera = db_session.scalar(select(Camera))
        assert camera.import_failures["cam-1:bad"][0] == attempt
        # Said as it is: tried again, or, on the last try, let go.
        assert result["accounts"][0]["error"] == (
            "1 photo wouldn't download. It is tried again on the next fetch." if attempt < 3
            else "1 photo wouldn't download. It was tried 3 times, so it is left out.")
    assert camera.last_sync_at == NOW + timedelta(hours=1)  # no longer held back
    fourth = sync.sync_ubox_all(db_session)
    assert fourth["failed"] == 0 and fourth["given_up"] == 1 and fourth["status"] == "ok"
    assert FakeClient.downloads.count("https://example.com/bad") == 3
    assert setup.last_error is None


@requires_db
@pytest.mark.parametrize(("error", "words"), [
    (UboxError("UBox rejected the account or password"),
     "UBox refused the password. Re-enter it."),
    (UboxError("Unable to reach UBox for login"),
     "Couldn't reach UBox. It tries again on the next fetch."),
    (UboxError("UBox login failed (HTTP 503)"),
     "UBox isn't answering properly right now. It tries again on the next fetch."),
])
def test_a_login_problem_is_said_in_words_not_a_class_name(
    db_session, setup, monkeypatch, error, words,
):
    """E-18: and it is kept on the login, where Settings shows it."""
    def refuse(self):
        raise error

    monkeypatch.setattr(FakeClient, "login", refuse)
    result = sync.sync_ubox_all(db_session)
    assert result["status"] == "error"
    assert result["accounts"][0]["error"] == words
    db_session.refresh(setup)
    assert setup.last_error == words and setup.last_ok_at is None


@requires_db
def test_an_unreadable_ubox_password_asks_to_be_re_entered(db_session, setup, monkeypatch):
    setup.password_enc = "not-a-token-this-server-can-read"
    db_session.commit()
    result = sync.sync_ubox_all(db_session)
    assert result["accounts"][0]["error"] == "The saved password can't be read. Re-enter it."


@requires_db
def test_a_login_keeps_its_ubox_sign_in_between_fetches(db_session, setup, monkeypatch):
    """E-21: UBox gives a sign-in for weeks; it is kept, not renewed every 15 minutes."""
    for _ in range(3):
        sync.sync_ubox_all(db_session)
    assert FakeClient.signins == 1
    db_session.refresh(setup)
    assert logins.saved_session(db_session, setup) == "session-1"

    def refuse(self):
        raise UboxError("UBox rejected the account or password")

    def lapsed(self):
        if self.token == "session-1":
            raise UboxError("UBox authentication expired after retry; reconnect the account")
        return self.devices

    # UBox let it lapse and the password was changed: said so, and forgotten.
    monkeypatch.setattr(FakeClient, "list_devices", lapsed)
    monkeypatch.setattr(FakeClient, "login", refuse)
    result = sync.sync_ubox_all(db_session)
    assert result["accounts"][0]["error"] == "UBox refused the password. Re-enter it."
    db_session.refresh(setup)
    assert setup.session_enc is None


@requires_db
def test_one_ubox_camera_that_cannot_be_read_says_so_on_its_card(db_session, setup, monkeypatch):
    FakeClient.devices.append(UboxDevice("cam-2", "Second camera", online=True))
    real = FakeClient.list_events

    def second_fails(self, uid, since, until, page_size=100):
        if uid == "cam-2":
            raise UboxError("UBox request failed (HTTP 502)")
        return real(self, uid, since, until, page_size)

    sync.sync_ubox_all(db_session)  # both come in once
    monkeypatch.setattr(FakeClient, "list_events", second_fails)
    result = sync.sync_ubox_all(db_session)
    assert result["status"] == "partial"
    cams = {c.ubox_uid: c for c in db_session.scalars(select(Camera))}
    assert cams["cam-1"].fetch_error is None
    assert cams["cam-2"].fetch_error == (
        "UBox isn't answering properly right now. It tries again on the next fetch.")
    states = logins.camera_logins(db_session, list(cams.values()))
    health = camera_health(cams["cam-2"], login=states[cams["cam-2"].id])
    assert health["status"] == "not_syncing" and health["login"]["camera"] is True
    assert camera_health(cams["cam-1"], login=states[cams["cam-1"].id])["status"] != "not_syncing"
