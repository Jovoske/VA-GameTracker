"""JPEG validation and replay tests run offline; PostgreSQL tests use fresh_db."""
from __future__ import annotations

import hashlib
import io
import json
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime

import pytest
from PIL import Image as PillowImage

from app.ingestion import ftp_import as ftp
from tests.conftest import requires_db

RECEIVED = "2026-09-13T12:00:00+00:00"


def jpeg(exif=None, size=(24, 12)):
    out = io.BytesIO()
    image = PillowImage.new("RGB", size, "green")
    options = {}
    if exif:
        tags = PillowImage.Exif()
        tags[34665] = exif  # EXIF IFD, as emitted by cameras rather than only top-level tags
        options["exif"] = tags
    image.save(out, format="JPEG", **options)
    return out.getvalue()


def package(tmp_path, *, state="ready", name="PICT0001.JPG", data=None, manifest=None):
    directory = tmp_path / state / uuid.uuid4().hex
    directory.mkdir(parents=True)
    data = jpeg() if data is None else data
    values = {"version": 1, "original_filename": name, "received_at": RECEIVED,
              "byte_count": len(data)}
    values.update(manifest or {})
    (directory / "photo.jpg").write_bytes(data)
    (directory / "metadata.json").write_text(json.dumps(values), encoding="utf-8")
    return directory


def run(spool, monkeypatch, persist, *, camera=None, **kwargs):
    monkeypatch.setattr(ftp, "_persist_photo", persist)
    return ftp.run_once(spool, camera or uuid.uuid4(), timezone_name="Europe/Amsterdam",
                        session_factory=lambda: nullcontext(object()),
                        media_root=spool / "media", **kwargs)


def test_full_decode_dimensions_hash_and_explicit_receipt_fallback(tmp_path):
    p = package(tmp_path)
    result = ftp.read_package(p, "Europe/Amsterdam")
    assert (result.width, result.height) == (24, 12)
    assert result.sha256 == hashlib.sha256(result.data).hexdigest()
    assert result.captured_at == datetime.fromisoformat(RECEIVED)
    assert result.timestamp_source == "received_at_fallback"
    assert "receipt time" in result.timestamp_notes[0]


@pytest.mark.parametrize(("exif", "expected", "source"), [
    ({36867: "2026:09:12 19:20:21", 36881: "+03:00"}, "2026-09-12T16:20:21+00:00",
     "exif_with_offset"),
    ({36867: "2026:09:12 19:20:21"}, "2026-09-12T17:20:21+00:00", "exif_camera_timezone"),
])
def test_exif_capture_time_and_offset(tmp_path, exif, expected, source):
    result = ftp.read_package(package(tmp_path, data=jpeg(exif)), "Europe/Amsterdam")
    assert result.captured_at == datetime.fromisoformat(expected)
    assert result.timestamp_source == source


@pytest.mark.parametrize("name", ["20260912_192021.JPG", "IMG_20260912192021_001.jpg"])
def test_unambiguous_filename_date(tmp_path, name):
    result = ftp.read_package(package(tmp_path, name=name), "Europe/Amsterdam")
    assert result.captured_at == datetime(2026, 9, 12, 17, 20, 21, tzinfo=UTC)
    assert result.timestamp_source == "filename_camera_timezone"


def test_actual_suntek_firmware_ftp_filename_has_minute_precision(tmp_path):
    result = ftp.read_package(package(tmp_path, name="PICT_20260912_1920.jpg"), "Europe/Amsterdam")
    assert result.captured_at == datetime(2026, 9, 12, 17, 20, tzinfo=UTC)
    assert result.timestamp_source == "filename_camera_timezone_minute_precision"
    assert "seconds set to 00" in result.timestamp_notes[0]


@pytest.mark.parametrize("clock", ["2026:03:29 02:30:00", "2025:10:26 02:30:00"])
def test_dst_nonexistent_or_ambiguous_time_is_not_guessed(tmp_path, clock):
    result = ftp.read_package(package(tmp_path, data=jpeg({36867: clock})), "Europe/Amsterdam")
    assert result.timestamp_source == "received_at_fallback"
    assert any("ambiguous or nonexistent" in note for note in result.timestamp_notes)


def test_corrupt_or_future_exif_can_fall_back_to_filename(tmp_path):
    result = ftp.read_package(package(tmp_path, name="20260912_120000.jpg",
                                     data=jpeg({36867: "2099:01:01 00:00:00"})), "UTC")
    assert result.timestamp_source == "filename_camera_timezone"
    assert "implausible" in result.timestamp_notes[0]


@pytest.mark.parametrize("manifest", [
    {"version": True}, {"version": 2}, {"byte_count": -1}, {"byte_count": True},
    {"received_at": "2026-09-13T12:00:00"}, {"received_at": None},
    {"original_filename": "../../bad.jpg"}, {"original_filename": "x\\bad.jpg"},
    {"original_filename": "hidden.txt"}, {"original_filename": "bad\n.jpg"},
])
def test_reject_invalid_manifest(tmp_path, manifest):
    with pytest.raises(ftp.InvalidPackage):
        ftp.read_package(package(tmp_path, manifest=manifest), "UTC")


@pytest.mark.parametrize("content", [b"not an image", b"\xff\xd8garbage\xff\xd9"])
def test_reject_non_jpeg_even_with_matching_markers(tmp_path, content):
    with pytest.raises(ftp.InvalidPackage):
        ftp.read_package(package(tmp_path, data=content), "UTC")


def test_reject_truncated_jpeg_and_decompression_bomb(tmp_path):
    with pytest.raises(ftp.InvalidPackage, match="complete JPEG"):
        ftp.read_package(package(tmp_path, data=jpeg()[:-2]), "UTC")
    with pytest.raises(ftp.InvalidPackage, match="pixel limit"):
        ftp.read_package(package(tmp_path), "UTC", max_pixels=100)
    with pytest.raises(ftp.InvalidPackage, match="byte limit"):
        ftp.read_package(package(tmp_path), "UTC", max_bytes=100)


def test_complete_packages_only_and_camera_id_from_operator(tmp_path, monkeypatch):
    camera = uuid.uuid4()
    p = package(tmp_path, manifest={"camera_id": str(uuid.uuid4())})
    incoming = package(tmp_path, state="incoming")
    abandoned = package(tmp_path, state="processing")
    called = []

    def persist(db, bound_camera, photo, media_root, *, enrich):
        called.append(bound_camera)
        assert (tmp_path / "processing" / p.name / "photo.jpg").exists()
        return ftp.ImportResult(str(uuid.uuid4()), "imported", str(media_root / "photo.jpg"))

    assert run(tmp_path, monkeypatch, persist, camera=camera) == {
        "imported": 1, "duplicate": 0, "failed": 0, "deferred": 0,
    }
    assert called == [camera]
    assert (incoming / "photo.jpg").exists()
    assert (abandoned / "photo.jpg").exists()
    processed = tmp_path / "processed" / p.name
    assert not (processed / "photo.jpg").exists()
    receipt = json.loads((processed / "result.json").read_text())
    assert receipt["timestamp_source"] == "received_at_fallback"
    assert receipt["camera_id"] == str(camera)


def test_failed_import_keeps_photo_and_explicit_retry_succeeds(tmp_path, monkeypatch):
    p = package(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("database unavailable")

    assert run(tmp_path, monkeypatch, fail)["failed"] == 1
    failed = tmp_path / "failed" / p.name
    assert (failed / "photo.jpg").exists()
    assert "database unavailable" in (failed / "error.json").read_text()
    assert run(tmp_path, monkeypatch, fail)["failed"] == 0  # failures never spin on their own
    assert ftp.requeue(tmp_path, "failed") == 1
    def success(*args, **kwargs):
        return ftp.ImportResult(str(uuid.uuid4()), "imported", "/media/photo.jpg")

    assert run(tmp_path, monkeypatch, success)["imported"] == 1


def test_database_outage_returns_to_ready_and_retries_next_batch(tmp_path, monkeypatch):
    from sqlalchemy.exc import OperationalError

    p = package(tmp_path)
    package(tmp_path)

    def offline(*args, **kwargs):
        raise OperationalError("connect", {}, OSError("connection refused"))

    assert run(tmp_path, monkeypatch, offline) == {
        "imported": 0, "duplicate": 0, "failed": 0, "deferred": 1,
    }
    assert (p / "photo.jpg").exists()
    assert len(list((tmp_path / "ready").iterdir())) == 2
    assert not list((tmp_path / "failed").iterdir())

    def recovered(*args, **kwargs):
        return ftp.ImportResult(str(uuid.uuid4()), "imported", "/media/photo.jpg")

    assert run(tmp_path, monkeypatch, recovered)["imported"] == 2


def test_post_commit_receipt_failure_replays_as_duplicate(tmp_path, monkeypatch):
    p = package(tmp_path)
    committed = set()

    def persist(db, camera, photo, root, *, enrich):
        status = "duplicate" if photo.sha256 in committed else "imported"
        committed.add(photo.sha256)
        return ftp.ImportResult(str(uuid.uuid4()), status, "/media/photo.jpg")

    original = ftp._json_write

    def fail_receipt(path, data):
        if path.name == "result.json":
            raise OSError("disk full after database commit")
        original(path, data)

    monkeypatch.setattr(ftp, "_json_write", fail_receipt)
    assert run(tmp_path, monkeypatch, persist)["failed"] == 1
    assert (tmp_path / "failed" / p.name / "photo.jpg").exists()
    monkeypatch.setattr(ftp, "_json_write", original)
    ftp.requeue(tmp_path, "failed")
    assert run(tmp_path, monkeypatch, persist)["duplicate"] == 1


def test_invalid_jpeg_never_reaches_database(tmp_path, monkeypatch):
    package(tmp_path, data=b"broken upload")

    def persist(*args, **kwargs):
        pytest.fail("A malformed upload reached persistence")

    assert run(tmp_path, monkeypatch, persist)["failed"] == 1


def test_recover_requires_stopped_workers_and_never_reclaims_automatically(tmp_path):
    p = package(tmp_path, state="processing")
    with pytest.raises(ValueError, match="Stop ALL"):
        ftp.requeue(tmp_path, "processing")
    assert (p / "photo.jpg").exists()
    assert ftp.requeue(tmp_path, "processing", workers_stopped=True) == 1
    assert (tmp_path / "ready" / p.name / "photo.jpg").exists()


def test_media_atomic_write_fails_without_replacing_valid_file(tmp_path, monkeypatch):
    destination = tmp_path / "media" / "photo.jpg"
    destination.parent.mkdir()
    destination.write_bytes(b"previous bytes")

    def fail_replace(*args):
        raise OSError("failed media write")

    monkeypatch.setattr(ftp.os, "replace", fail_replace)
    with pytest.raises(OSError):
        ftp._atomic_write(destination, jpeg())
    assert destination.read_bytes() == b"previous bytes"
    assert not list(destination.parent.glob(".ftp-*"))


def test_advisory_key_is_stable_signed_bigint_and_camera_scoped():
    camera = uuid.UUID("9cbecbc6-bd1b-43ea-a6a0-fd4a78a91cd7")
    key = ftp.advisory_lock_key(camera, "a" * 64)
    assert key == ftp.advisory_lock_key(uuid.UUID(str(camera)), "a" * 64)
    assert -(2**63) <= key < 2**63
    assert key != ftp.advisory_lock_key(uuid.uuid4(), "a" * 64)
    assert key != ftp.advisory_lock_key(camera, "b" * 64)


def test_one_shot_cli_reports_database_outage_as_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(ftp, "run_once", lambda *a, **k: {
        "imported": 0, "duplicate": 0, "failed": 0, "deferred": 1,
    })
    assert ftp.main(["run", "--spool", str(tmp_path), "--camera-id", str(uuid.uuid4())]) == 1


def test_invalid_size_configuration_does_not_claim_a_photo(tmp_path):
    p = package(tmp_path)
    with pytest.raises(ValueError, match="Size limits"):
        ftp.run_once(tmp_path, uuid.uuid4(), max_bytes=0)
    assert (p / "photo.jpg").exists()


def seed_camera(db):
    from app.models import Camera, Estate

    estate = Estate(name="Test estate", timezone="Europe/Amsterdam")
    db.add(estate)
    db.flush()
    camera = Camera(name="Suntek test", estate_id=estate.id, model="HC801LTE")
    db.add(camera)
    db.commit()
    return camera.id


@requires_db
def test_postgres_import_dedupe_and_provenance(tmp_path, db_session):
    from sqlalchemy import func, select
    from sqlalchemy.orm import sessionmaker

    from app.models import Image

    camera = seed_camera(db_session)
    package(tmp_path)
    package(tmp_path)  # same bytes, different package IDs
    result = ftp.run_once(tmp_path, camera, timezone_name="Europe/Amsterdam",
                          session_factory=sessionmaker(bind=db_session.get_bind()),
                          media_root=tmp_path / "media", enrich=False)
    assert result == {"imported": 1, "duplicate": 1, "failed": 0, "deferred": 0}
    assert db_session.scalar(select(func.count()).select_from(Image)) == 1
    row = db_session.scalar(select(Image))
    assert row.spypoint_photo_id is None and row.processed_at is None
    assert (row.width, row.height) == (24, 12)
    from pathlib import Path

    assert Path(row.original_path).read_bytes() == jpeg()
    sidecar = json.loads(Path(row.original_path).with_suffix(".ftp.json").read_text())
    assert sidecar["timestamp_source"] == "received_at_fallback"


@requires_db
def test_postgres_enrichment_failure_does_not_poison_import(tmp_path, db_session, monkeypatch):
    from sqlalchemy import select, text
    from sqlalchemy.orm import sessionmaker

    from app.enrichment import enrich
    from app.models import Image

    def fail_enrichment(db, image):
        db.execute(text("SELECT 1 / 0"))  # requires rollback to savepoint, not just except

    monkeypatch.setattr(enrich, "enrich_image", fail_enrichment)
    camera = seed_camera(db_session)
    package(tmp_path)
    result = ftp.run_once(tmp_path, camera, timezone_name="UTC",
                          session_factory=sessionmaker(bind=db_session.get_bind()),
                          media_root=tmp_path / "media")
    assert result["imported"] == 1
    assert db_session.scalar(select(Image)) is not None


@requires_db
def test_postgres_failed_commit_preserves_replayable_photo(tmp_path, db_session):
    from sqlalchemy import select
    from sqlalchemy.orm import Session, sessionmaker

    from app.models import Image

    class FailCommitSession(Session):
        def commit(self):
            raise RuntimeError("simulated commit failure")

    camera = seed_camera(db_session)
    p = package(tmp_path)
    result = ftp.run_once(tmp_path, camera, timezone_name="UTC",
                          session_factory=sessionmaker(bind=db_session.get_bind(),
                                                       class_=FailCommitSession),
                          media_root=tmp_path / "media", enrich=False)
    assert result["failed"] == 1
    assert (tmp_path / "failed" / p.name / "photo.jpg").exists()
    assert db_session.scalar(select(Image)) is None
    ftp.requeue(tmp_path, "failed")
    result = ftp.run_once(tmp_path, camera, timezone_name="UTC",
                          session_factory=sessionmaker(bind=db_session.get_bind()),
                          media_root=tmp_path / "media", enrich=False)
    assert result["imported"] == 1


@requires_db
def test_postgres_concurrent_duplicate_packages_create_one_image(tmp_path, db_session, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy import func, select
    from sqlalchemy.orm import sessionmaker

    from app.models import Image

    camera = seed_camera(db_session)
    spools = [tmp_path / "a", tmp_path / "b"]
    for spool in spools:
        package(spool)
    original = ftp._persist_photo
    barrier = Barrier(2)

    def synchronized(*args, **kwargs):
        barrier.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(ftp, "_persist_photo", synchronized)
    factory = sessionmaker(bind=db_session.get_bind())

    def ingest(spool):
        return ftp.run_once(spool, camera, timezone_name="UTC", session_factory=factory,
                            media_root=tmp_path / "media", enrich=False)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(ingest, spools))
    assert sum(r["imported"] for r in results) == 1
    assert sum(r["duplicate"] for r in results) == 1
    assert db_session.scalar(select(func.count()).select_from(Image)) == 1
