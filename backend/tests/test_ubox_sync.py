"""Admission limits and real Postgres gallery/ingestion integration."""
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image as PillowImage
from sqlalchemy import func, select, text

from app.core.crypto import encrypt
from app.ingestion import ubox_sync as sync
from app.ingestion.ubox import UboxDevice, UboxError, UboxEvent, UboxPageLimitError
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

    def __init__(self, username, password):
        assert password == "example-password"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def login(self):
        pass

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
    from app.core.security import create_access_token

    FakeClient.events = [event("2", 120), event("1")]
    result = sync.sync_ubox_all(db_session)
    assert result["total"] == 2 and result["status"] == "ok"
    camera = db_session.scalar(select(Camera))
    assert camera.account_id == setup.id
    assert camera.ubox_uid == "cam-1" and camera.spypoint_id is None
    assert camera.battery_pct == 82 and camera.photo_limit is None
    assert camera.last_report_at and camera.last_sync_at
    user = User(id=setup.id, estate_id=setup.estate_id)
    gallery = camera_images(camera.id, limit=40, include_empty=False, user=user, db=db_session)
    assert len(gallery) == 2 and all(i["file_url"] for i in gallery)
    for image in db_session.scalars(select(Image)):
        assert image.width == 24 and image.height == 12
        assert Path(image.original_path).name.startswith("ubox_")
        assert ":" not in Path(image.original_path).name
        response = image_file(image.id, token=create_access_token(str(user.id)),
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
    assert result["no_image"] == 1 and result["failed"] == 1 and result["status"] == "error"
    assert db_session.scalar(select(func.count(Image.id))) == 1
    assert db_session.scalar(select(Camera)).last_sync_at is None
    assert setup.last_sync_at is None


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
    assert result["status"] == "error"


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
    from app.ai import empty_filter, species
    from app.api.routes_species import species_images, spotted
    from app.notifications import dispatch

    FakeClient.events = [event("1")]
    sync.sync_ubox_all(db_session)
    boxes = [{"confidence": 0.95, "bbox": [0.1, 0.1, 0.9, 0.9]}]
    monkeypatch.setattr(empty_filter, "detect_animals", lambda _: boxes)
    monkeypatch.setattr(species, "detect_animals", lambda _: boxes)
    monkeypatch.setattr(species, "classify_crop", lambda *_: ("fox", "Fox", 0.97))
    notified = []
    monkeypatch.setattr(dispatch, "dispatch_new_sightings", lambda db: notified.append(True))
    assert empty_filter.scan_unprocessed(db_session)["animal"] == 1
    assert species.classify_unclassified(db_session)["by_species"] == {"fox": 1}
    assert notified == [True]
    user = User(id=setup.id, estate_id=setup.estate_id)
    animals = spotted(_=user, db=db_session)
    assert len(animals) == 1 and animals[0]["id"] == "fox"
    gallery = species_images("fox", limit=200, label=None, _=user, db=db_session)
    assert len(gallery) == 1 and gallery[0]["file_url"].endswith("/file")
    image = db_session.scalar(select(Image))
    assert str(image.id) in gallery[0]["file_url"] and Path(image.original_path).is_file()


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
    assert result["status"] == "error" and result["total"] == 1
    assert db_session.scalar(select(Camera)).ubox_uid == "cam-2"
    assert db_session.scalar(select(func.count(Image.id))) == 1
    assert len(list(Path(sync.settings.media_root).rglob("*.jpg"))) == 1
    assert db_session.scalar(select(SyncLog)).status == "error"


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
