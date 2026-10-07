"""Nordic photo failures must be retryable without duplicate or invented sightings."""
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from io import BytesIO
from unittest.mock import MagicMock, Mock

import pytest
from PIL import Image as PillowImage
from sqlalchemy import select

from app.core.crypto import encrypt
from app.ingestion import nordic_sync as sync
from app.ingestion.nordic import NordicAuthError, NordicCamera, NordicError, NordicPhoto
from app.models import Camera, CameraAccount, Estate, Image

from .conftest import requires_db

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


def jpeg():
    stream = BytesIO()
    PillowImage.new("RGB", (24, 12), "green").save(stream, format="JPEG")
    return stream.getvalue()


def photo(identifier="frame-1", camera="cam-1", age=1):
    return NordicPhoto(identifier, camera, NOW - timedelta(hours=age),
                       "https://media.example.test/" + identifier + ".jpg")


@pytest.mark.parametrize("data", [b"", b"<html>Login required</html>", jpeg()[:70]])
def test_non_photos_are_rejected(data):
    with pytest.raises(NordicError):
        sync._jpeg(data)


def test_jpeg_is_decoded_before_saving():
    assert sync._jpeg(jpeg()) == (24, 12)


def test_photo_identity_is_scoped_and_unambiguous():
    assert sync.photo_key(photo("1", "a")) != sync.photo_key(photo("1", "b"))
    assert sync.photo_key(photo("a:b", "c")) != sync.photo_key(photo("b", "c:a"))


def test_saved_session_reused_and_reauthenticated_only_after_auth_failure(monkeypatch):
    monkeypatch.setattr(sync.logins, "saved_session", lambda *_: "encrypted-cookie-jar")
    client = Mock()
    client.list_cameras.return_value = [NordicCamera("cam-1", "Pond")]
    assert sync._devices(Mock(), client, Mock())[0].name == "Pond"
    client.login.assert_not_called()
    client.use_token.assert_called_once_with("encrypted-cookie-jar")
    client.list_cameras.side_effect = [NordicAuthError("expired"), []]
    assert sync._devices(Mock(), client, Mock()) == []
    client.login.assert_called_once()
    client.reset_mock()
    client.list_cameras.side_effect = NordicError("temporarily unavailable", 503)
    with pytest.raises(NordicError):
        sync._devices(Mock(), client, Mock())
    client.login.assert_not_called()


def camera_case(monkeypatch):
    db = Mock()
    db.begin_nested.side_effect = lambda: nullcontext()
    camera = Camera(id=uuid.uuid4(), name="Pond", estate_id=uuid.uuid4(),
                    nordic_id="cam-1", last_sync_at=NOW - timedelta(days=2))
    monkeypatch.setattr(sync, "upsert_camera", lambda *_: camera)
    monkeypatch.setattr(sync.jobs, "lock_lost", lambda: False)
    account = CameraAccount(id=uuid.uuid4(), estate_id=camera.estate_id)
    device = NordicCamera("cam-1", "Pond")
    client = Mock()
    return db, camera, account, device, client


def test_failed_photo_holds_cursor_and_successful_retry_advances(monkeypatch):
    db, camera, account, device, client = camera_case(monkeypatch)
    failed = photo("failure", age=4)
    client.list_photos.return_value = [failed, photo("success", age=1)]
    monkeypatch.setattr(sync, "_ingest_photo",
                        lambda _db, _cl, _cam, p, _paths:
                        "failed" if p.photo_id == "failure" else "downloaded")
    result = sync._sync_camera(db, client, account, device, NOW, [])
    assert result["failed"] == 1 and result["downloaded"] == 1
    assert camera.last_sync_at == failed.captured_at
    assert camera.fetch_error
    monkeypatch.setattr(sync, "_ingest_photo", lambda *_: "downloaded")
    sync._sync_camera(db, client, account, device, NOW, [])
    assert camera.last_sync_at == NOW and camera.fetch_error is None


def test_incomplete_listing_never_advances_cursor(monkeypatch):
    db, camera, account, device, client = camera_case(monkeypatch)
    before = camera.last_sync_at
    client.list_photos.side_effect = NordicError("page cap reached")
    with pytest.raises(NordicError):
        sync._sync_camera(db, client, account, device, NOW, [])
    assert camera.last_sync_at == before


def test_failed_historical_backfill_remains_due_on_normal_fetch(monkeypatch):
    db, camera, account, device, client = camera_case(monkeypatch)
    camera.last_sync_at = NOW
    historical = photo(age=20 * 24)
    client.list_photos.return_value = [historical]
    monkeypatch.setattr(sync, "_ingest_photo", lambda *_: "failed")
    sync._sync_camera(db, client, account, device, NOW, [], days=30)
    assert camera.last_sync_at == historical.captured_at
    sync._sync_camera(db, client, account, device, NOW, [])
    assert client.list_photos.call_args.args[1] <= historical.captured_at


def test_cross_camera_response_is_not_imported(monkeypatch):
    db, _camera, account, device, client = camera_case(monkeypatch)
    client.list_photos.return_value = [photo(camera="another-camera")]
    ingest = Mock()
    monkeypatch.setattr(sync, "_ingest_photo", ingest)
    with pytest.raises(NordicError, match="different camera"):
        sync._sync_camera(db, client, account, device, NOW, [])
    ingest.assert_not_called()


def test_download_outage_bounds_attempts_without_losing_remaining_window(monkeypatch):
    db, camera, account, device, client = camera_case(monkeypatch)
    before = camera.last_sync_at
    client.list_photos.return_value = [photo(str(i), age=i + 1) for i in range(20)]
    ingest = Mock(return_value="failed")
    monkeypatch.setattr(sync, "_ingest_photo", ingest)
    sync._sync_camera(db, client, account, device, NOW, [])
    assert ingest.call_count == 5
    assert camera.last_sync_at == before


def test_interruption_inside_last_camera_is_reported(monkeypatch):
    db, camera, account, device, client = camera_case(monkeypatch)
    before = camera.last_sync_at
    client.list_photos.return_value = [photo()]
    monkeypatch.setattr(sync.jobs, "lock_lost", lambda: True)
    ingest = Mock()
    monkeypatch.setattr(sync, "_ingest_photo", ingest)
    result = sync._sync_camera(db, client, account, device, NOW, [])
    assert result["interrupted"] is True
    assert camera.last_sync_at == before and camera.fetch_error
    ingest.assert_not_called()


def test_foreign_estate_camera_is_refused():
    db = Mock()
    db.scalar.return_value = Camera(estate_id=uuid.uuid4(), nordic_id="cam-1", name="Pond")
    with pytest.raises(NordicError, match="another estate"):
        sync.upsert_camera(db, uuid.uuid4(), NordicCamera("cam-1", "Pond"), uuid.uuid4())
    db.add.assert_not_called()


def test_provider_metadata_preserves_custom_name_location_and_retirement():
    db = Mock()
    camera = Camera(estate_id=uuid.uuid4(), nordic_id="cam-1", name="Estate name",
                    name_is_custom=True, lat=40, lon=-2, location_is_custom=True,
                    retired_at=NOW)
    db.scalar.return_value = camera
    result = sync.upsert_camera(db, camera.estate_id,
                                NordicCamera("cam-1", "Provider name", lat=50, lng=10),
                                uuid.uuid4())
    assert result.name == "Estate name" and result.provider_name == "Provider name"
    assert (result.lat, result.lon) == (40, -2)
    assert (result.provider_lat, result.provider_lon) == (50, 10)
    assert result.retired_at == NOW


def test_interrupted_import_keeps_every_camera_the_account_listed(monkeypatch):
    account = CameraAccount(id=uuid.uuid4(), estate_id=uuid.uuid4(), provider="nordic",
                            username="owner@example.test", label="Owner")
    db = Mock()
    db.scalars.return_value.all.return_value = [account]
    db.get.return_value = Estate(id=account.estate_id, name="Test")
    db.begin_nested.side_effect = lambda: nullcontext()
    client = MagicMock()
    client.__enter__.return_value = client
    client.token = "cookie-session"
    monkeypatch.setattr(sync, "NordicClient", lambda *_: client)
    monkeypatch.setattr(sync, "_devices", lambda *_:
                        [NordicCamera("first", "First"), NordicCamera("second", "Second")])
    monkeypatch.setattr(sync, "_sync_camera", lambda *_args, **_kwargs:
                        {"seen": 0, "downloaded": 0, "duplicate": 0, "failed": 0})
    monkeypatch.setattr(sync.jobs, "lock_lost", Mock(side_effect=[False, False, True]))
    monkeypatch.setattr(sync.logins, "read_password", lambda *_: "fixture-password")
    monkeypatch.setattr(sync.logins, "bookkeeping", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(sync.logins, "record", Mock())
    monkeypatch.setattr(sync.logins, "keep_session", Mock())
    disconnect = Mock()
    monkeypatch.setattr(sync.logins, "disconnect_unlisted", disconnect)
    result = sync.sync_nordic_all(db)
    assert result["status"] == "partial"
    assert disconnect.call_args.kwargs["listed"] == {"first", "second"}


@requires_db
def test_retry_enters_gallery_once_with_original_capture_time(db_session, monkeypatch, tmp_path):
    db = db_session
    monkeypatch.setattr(sync.settings, "media_root", str(tmp_path))
    monkeypatch.setattr(sync, "enrich_image", lambda *_: None)
    estate = Estate(name="Nordic test", timezone="UTC")
    db.add(estate)
    db.flush()
    account = CameraAccount(estate_id=estate.id, username="nordic@example.test", provider="nordic",
                            password_enc=encrypt("fixture-password"))
    db.add(account)
    db.flush()
    camera = sync.upsert_camera(db, estate.id, NordicCamera("cam-1", "Pond"), account.id)
    event = photo()
    client = Mock()
    client.download.side_effect = [NordicError("temporarily unavailable", 503), jpeg()]
    assert sync._ingest_photo(db, client, camera, event, []) == "failed"
    db.commit()
    row = db.scalar(select(Image).where(Image.camera_id == camera.id))
    assert row.original_path is None and row.download_attempts == 1
    assert row.captured_at == event.captured_at
    assert sync._ingest_photo(db, client, camera, event, []) == "downloaded"
    db.commit()
    assert sync._ingest_photo(db, client, camera, event, []) == "duplicate"
    db.commit()
    assert len(list(db.scalars(select(Image).where(Image.camera_id == camera.id)))) == 1
    assert client.download.call_count == 2
    assert row.captured_at == event.captured_at and row.original_path
