"""Import completed, locally staged FTP photos into the normal image pipeline.

The receiver atomically publishes ready/<uuid>/{photo.jpg,metadata.json}. A spool
belongs to one camera, bound by the operator's --camera-id, never by upload data.
Each package is claimed by rename and remains replayable until its DB commit.
Processing packages are never reclaimed automatically: stop workers and use the
explicit recover command after a crash. No detector or cloud AI is invoked here.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import signal
import stat
import tempfile
import threading
import uuid
import warnings
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image as PillowImage

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
PACKAGE_NAME = re.compile(r"(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\Z")
FILENAME_DATE = re.compile(r"(?:IMG_|SUNTEK_)?(\d{8})[_-]?(\d{6})(?:[_-]\d{1,6})?", re.I)
SUNTEK_FTP_DATE = re.compile(r"PICT_(\d{8})_(\d{4})", re.I)


class InvalidPackage(ValueError):
    """A package fails the completed-photo contract."""


@dataclass(frozen=True)
class Photo:
    data: bytes
    sha256: str
    width: int
    height: int
    original_filename: str
    received_at: datetime
    captured_at: datetime
    timestamp_source: str
    timestamp_notes: tuple[str, ...]


@dataclass(frozen=True)
class ImportResult:
    image_id: str
    status: str
    original_path: str


def _logger():
    from app.core.logging import get_logger

    return get_logger(__name__)


def _directory(path: Path, *, create: bool = False) -> Path:
    if create:
        missing = []
        ancestor = path
        while not ancestor.exists():
            missing.append(ancestor)
            ancestor = ancestor.parent
        path.mkdir(parents=True, exist_ok=True)
        for created in reversed(missing):
            _fsync_directory(created.parent)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink() or (
        getattr(info, "st_file_attributes", 0) & 0x400  # Windows reparse point
    ):
        raise InvalidPackage(f"Not a regular directory: {path.name}")
    return path


def _read_regular(path: Path, maximum: int) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink() or (
        getattr(info, "st_file_attributes", 0) & 0x400
    ):
        raise InvalidPackage(f"Not a regular file: {path.name}")
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise InvalidPackage(f"Not a regular file: {path.name}")
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise InvalidPackage(f"{path.name} exceeds the {maximum}-byte limit")
    return data


def _aware_local(value: datetime, tz: ZoneInfo) -> datetime:
    """Reject missing/repeated DST wall times rather than guessing an hour."""
    candidates = set()
    for fold in (0, 1):
        candidate = value.replace(tzinfo=tz, fold=fold).astimezone(UTC)
        if candidate.astimezone(tz).replace(tzinfo=None) == value:
            candidates.add(candidate)
    if len(candidates) != 1:
        raise ValueError("ambiguous or nonexistent local time; no UTC offset available")
    return candidates.pop()


def _timestamp(exif: dict, filename: str, received: datetime, tz: ZoneInfo):
    notes = []

    def plausible(value):
        if value.year < 2000 or value > received + timedelta(days=1):
            raise ValueError("capture time is implausible relative to receipt")
        return value.astimezone(UTC)

    original = exif.get(36867)
    if original:
        try:
            when = datetime.strptime(str(original).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
            offset = exif.get(36881)
            if offset:
                offset = str(offset).strip("\x00 ")
                if not re.fullmatch(r"[+-]\d{2}:\d{2}", offset):
                    raise ValueError("invalid EXIF OffsetTimeOriginal")
                if int(offset[1:3]) > 23 or int(offset[4:6]) > 59:
                    raise ValueError("invalid EXIF UTC offset hours/minutes")
                when = datetime.fromisoformat(when.isoformat() + offset)
                return plausible(when), "exif_with_offset", tuple(notes)
            return plausible(_aware_local(when, tz)), "exif_camera_timezone", tuple(notes)
        except (ValueError, TypeError, OverflowError) as exc:
            notes.append(f"EXIF time ignored: {exc}")

    stem = Path(filename).stem
    minute_match = SUNTEK_FTP_DATE.fullmatch(stem)
    match = minute_match or FILENAME_DATE.fullmatch(stem)
    if match:
        try:
            value = "".join(match.groups()) + ("00" if minute_match else "")
            when = datetime.strptime(value, "%Y%m%d%H%M%S")
            source = "filename_camera_timezone"
            if minute_match:
                source = "filename_camera_timezone_minute_precision"
                notes.append("Firmware FTP filename records minutes only; seconds set to 00")
            return plausible(_aware_local(when, tz)), source, tuple(notes)
        except (ValueError, OverflowError) as exc:
            notes.append(f"Filename time ignored: {exc}")
    notes.append("No reliable capture timestamp; using receiver receipt time")
    return received, "received_at_fallback", tuple(notes)


def read_package(
    package: Path, timezone_name: str, *, max_bytes: int = MAX_BYTES, max_pixels: int = MAX_PIXELS
) -> Photo:
    """Read bounded input and decode the entire JPEG, without modifying it."""
    if max_bytes < 1 or max_pixels < 1:
        raise ValueError("Size limits must be positive")
    _directory(package)
    tz = ZoneInfo(timezone_name)
    try:
        manifest = json.loads(_read_regular(package / "metadata.json", 8192))
    except (ValueError, UnicodeError) as exc:
        raise InvalidPackage("Invalid metadata.json") from exc
    if not isinstance(manifest, dict) or type(manifest.get("version")) is not int or (
        manifest["version"] != 1
    ):
        raise InvalidPackage("Unsupported manifest version")
    filename = manifest.get("original_filename")
    if not isinstance(filename, str) or not 1 <= len(filename) <= 255 or (
        any(c in filename for c in "/\\\x00") or any(ord(c) < 32 for c in filename)
    ) or Path(filename).suffix.lower() not in {".jpg", ".jpeg"}:
        raise InvalidPackage("original_filename must be a JPEG basename")
    try:
        received = datetime.fromisoformat(manifest["received_at"].replace("Z", "+00:00"))
        if received.tzinfo is None or received.utcoffset() is None:
            raise ValueError("receipt timestamp has no UTC offset")
        received = received.astimezone(UTC)
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError) as exc:
        raise InvalidPackage("received_at must be an ISO timestamp with a UTC offset") from exc
    data = _read_regular(package / "photo.jpg", max_bytes)
    if "byte_count" in manifest and (
        type(manifest["byte_count"]) is not int or manifest["byte_count"] != len(data)
    ):
        raise InvalidPackage("byte_count does not match the completed file")
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise InvalidPackage("Not a complete JPEG (missing SOI/EOI)")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PillowImage.DecompressionBombWarning)
            with PillowImage.open(io.BytesIO(data)) as image:
                if image.format != "JPEG":
                    raise InvalidPackage("Only JPEG images are accepted")
                width, height = image.size
                if width * height > max_pixels or min(width, height) < 1:
                    raise InvalidPackage(f"Image exceeds the {max_pixels}-pixel limit")
                image.verify()
            with PillowImage.open(io.BytesIO(data)) as image:
                image.load()  # verify() alone does not decode JPEG's compressed pixels
                raw_exif = image.getexif()
                exif = dict(raw_exif)
                try:
                    exif.update(raw_exif.get_ifd(34665))  # Exif sub-IFD
                except (KeyError, ValueError, TypeError, OSError):
                    pass
    except (OSError, ValueError, SyntaxError, PillowImage.DecompressionBombError,
            PillowImage.DecompressionBombWarning) as exc:
        raise InvalidPackage(f"Invalid or oversized JPEG: {exc}") from exc
    captured, source, notes = _timestamp(exif, filename, received, tz)
    return Photo(data, hashlib.sha256(data).hexdigest(), width, height, filename,
                 received, captured, source, notes)


def _fsync_directory(path: Path):
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _atomic_write(path: Path, data: bytes):
    _directory(path.parent, create=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".ftp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _json_write(path: Path, value: dict):
    _atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode())


def advisory_lock_key(camera_id: uuid.UUID, file_hash: str) -> int:
    key = f"gamesense:ftp:{camera_id.hex}:{file_hash}".encode("ascii")
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big", signed=True)


def _persist_photo(db, camera_id: uuid.UUID, photo: Photo, media_root: Path, *, enrich: bool):
    from sqlalchemy import select, text

    from app.models import Camera, Image

    if db.get_bind().dialect.name != "postgresql":
        raise RuntimeError("FTP ingestion requires PostgreSQL advisory transaction locks")
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise ValueError(f"Camera {camera_id} does not exist; register it first")
    if camera.spypoint_id is not None:
        raise ValueError("Use a dedicated FTP camera registered with the register command")
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
               {"key": advisory_lock_key(camera_id, photo.sha256)})
    existing = db.scalar(select(Image).where(
        Image.camera_id == camera_id, Image.file_hash == photo.sha256
    ))
    if existing is not None:
        if not existing.original_path or not Path(existing.original_path).is_file():
            raise RuntimeError("Duplicate image has no media file; retained package needs repair")
        stored = _read_regular(Path(existing.original_path), len(photo.data))
        if hashlib.sha256(stored).hexdigest() != photo.sha256:
            raise RuntimeError("Duplicate image media hash mismatch; retained package needs repair")
        result = ImportResult(str(existing.id), "duplicate", existing.original_path)
        db.commit()
        return result

    destination = media_root / str(camera.estate_id) / str(camera_id) / (
        photo.captured_at.strftime("%Y-%m-%d")
    ) / f"ftp_{photo.sha256}.jpg"
    _atomic_write(destination, photo.data)
    row = Image(camera_id=camera_id, captured_at=photo.captured_at,
                original_path=str(destination), file_hash=photo.sha256,
                width=photo.width, height=photo.height)
    db.add(row)
    db.flush()
    provenance = {
        "version": 1, "source": "ftp", "image_id": str(row.id), "camera_id": str(camera_id),
        "sha256": photo.sha256, "original_filename": photo.original_filename,
        "received_at": photo.received_at.isoformat(), "captured_at": photo.captured_at.isoformat(),
        "timestamp_source": photo.timestamp_source, "timestamp_notes": photo.timestamp_notes,
    }
    _json_write(destination.with_suffix(".ftp.json"), provenance)
    if enrich:
        from app.enrichment.enrich import enrich_image

        try:
            with db.begin_nested():
                enrich_image(db, row)
        except Exception as exc:
            _logger().warning("ftp.enrichment_failed", image=str(row.id), error=str(exc))
    camera.last_sync_at = datetime.now(UTC)
    camera.last_report_at = max(camera.last_report_at or photo.received_at, photo.received_at)
    result = ImportResult(str(row.id), "imported", str(destination))
    db.commit()  # source package still exists; crash after commit is harmless on retry
    _logger().info("ftp.imported", image=result.image_id, camera=str(camera_id),
                   timestamp_source=photo.timestamp_source, timestamp_notes=photo.timestamp_notes)
    return result


def _layout(spool: Path):
    _directory(spool, create=True)
    return {name: _directory(spool / name, create=True)
            for name in ("ready", "processing", "failed", "processed")}


def _packages(folder: Path):
    return sorted((p for p in folder.iterdir() if PACKAGE_NAME.fullmatch(p.name)),
                  key=lambda p: p.name)


def _move_package(source: Path, destination: Path):
    source.rename(destination)
    _fsync_directory(destination.parent)
    _fsync_directory(source.parent)


def _transient_db_failure(exc: Exception) -> bool:
    from sqlalchemy.exc import DBAPIError, OperationalError
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    return isinstance(exc, OperationalError | PoolTimeout) or (
        isinstance(exc, DBAPIError) and exc.connection_invalidated
    )


def run_once(
    spool: str | Path, camera_id: uuid.UUID | str, *, timezone_name: str | None = None,
    session_factory=None, media_root: str | Path | None = None, max_bytes: int = MAX_BYTES,
    max_pixels: int = MAX_PIXELS, limit: int = 100, enrich: bool = True,
) -> dict:
    """Claim at most limit complete packages; failed work requires explicit retry.

    session_factory must yield a fresh Session context manager per package. The
    function never takes ownership of an existing caller transaction.
    """
    from app.core.config import settings

    if limit < 1:
        raise ValueError("limit must be positive")
    if max_bytes < 1 or max_pixels < 1:
        raise ValueError("Size limits must be positive")
    camera_id = uuid.UUID(str(camera_id))
    timezone_name = timezone_name or settings.estate_timezone
    ZoneInfo(timezone_name)  # fail configuration errors before claiming packages
    if session_factory is None:
        from app.core.db import SessionLocal

        session_factory = SessionLocal
    paths = _layout(Path(spool).absolute())
    media_root = Path(media_root or settings.media_root).absolute()
    summary = {"imported": 0, "duplicate": 0, "failed": 0, "deferred": 0}
    for candidate in _packages(paths["ready"])[:limit]:
        claimed = paths["processing"] / candidate.name
        try:
            _directory(candidate)
            _move_package(candidate, claimed)  # only one worker can claim this package
        except FileNotFoundError:
            continue
        try:
            photo = read_package(claimed, timezone_name, max_bytes=max_bytes, max_pixels=max_pixels)
            if photo.timestamp_source == "received_at_fallback":
                _logger().warning("ftp.capture_time_fallback", package=claimed.name,
                                  received_at=photo.received_at.isoformat(),
                                  notes=photo.timestamp_notes)
            with session_factory() as db:
                result = _persist_photo(db, camera_id, photo, media_root, enrich=enrich)
            _json_write(claimed / "result.json", {
                **asdict(result), "camera_id": str(camera_id), "sha256": photo.sha256,
                "captured_at": photo.captured_at.isoformat(),
                "timestamp_source": photo.timestamp_source,
                "timestamp_notes": photo.timestamp_notes,
            })
            finished = paths["processed"] / claimed.name
            _move_package(claimed, finished)
            summary[result.status] += 1
            try:
                (finished / "photo.jpg").unlink()  # media + DB are durable; retain audit manifest
                _fsync_directory(finished)
            except OSError as exc:
                _logger().warning("ftp.processed_cleanup_failed",
                                  package=finished.name, error=str(exc))
        except Exception as exc:
            if _transient_db_failure(exc) and claimed.exists():
                # The Session context has rolled back/closed before returning the
                # package. An uncertain commit is safe: the next pass deduplicates.
                _move_package(claimed, paths["ready"] / claimed.name)
                summary["deferred"] += 1
                _logger().warning("ftp.database_unavailable", package=claimed.name, error=str(exc))
                break  # avoid hammering an unavailable database with the rest of the batch
            summary["failed"] += 1
            _logger().error("ftp.import_failed", package=claimed.name, error=str(exc))
            if claimed.exists():
                try:
                    _json_write(claimed / "error.json", {"error": str(exc),
                                "failed_at": datetime.now(UTC).isoformat()})
                finally:
                    _move_package(claimed, paths["failed"] / claimed.name)
    return summary


def requeue(spool: str | Path, source: str, *, workers_stopped: bool = False) -> int:
    """Replay failed work, or explicitly recover processing after workers stop."""
    if source not in {"failed", "processing"}:
        raise ValueError("Only failed or processing packages can be requeued")
    if source == "processing" and not workers_stopped:
        raise ValueError("Stop ALL import workers before recovery; pass --workers-stopped")
    paths = _layout(Path(spool).absolute())
    count = 0
    for package in _packages(paths[source]):
        _directory(package)
        destination = paths["ready"] / package.name
        if destination.exists():
            raise FileExistsError(f"Ready package already exists: {package.name}")
        try:
            _move_package(package, destination)
            count += 1
        except FileNotFoundError:
            continue
    return count


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Import one bounded batch; schedule with cron/systemd")
    run.add_argument("--camera-id", type=uuid.UUID, required=True)
    run.add_argument("--spool", type=Path, required=True)
    run.add_argument("--timezone", help="Camera clock timezone; defaults to ESTATE_TIMEZONE")
    run.add_argument("--limit", type=int, default=100)
    run.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    run.add_argument("--skip-enrichment", action="store_true",
                     help="Skip weather/astronomy lookups")
    run.add_argument("--watch", action="store_true", help="Keep processing batches until stopped")
    run.add_argument("--interval", type=float, default=30, help="Seconds between batches (>=1)")
    commands.add_parser("list", help="List estate and camera IDs for operator configuration")
    register = commands.add_parser("register", help="Register a new FTP camera; prints its UUID")
    register.add_argument("--estate-id", type=uuid.UUID, required=True)
    register.add_argument("--name", required=True)
    register.add_argument("--model", default="Suntek HC801LTE")
    for name in ("retry", "recover"):
        command = commands.add_parser(name)
        command.add_argument("--spool", type=Path, required=True)
        if name == "recover":
            command.add_argument("--workers-stopped", action="store_true", required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        if not 1 <= args.interval <= 86400:
            parser.error("--interval must be between 1 and 86400 seconds")
        stopped = threading.Event()
        if args.watch:
            for signum in (signal.SIGTERM, signal.SIGINT):
                signal.signal(signum, lambda _signum, _frame: stopped.set())
        while True:
            result = run_once(args.spool, args.camera_id, timezone_name=args.timezone,
                              limit=args.limit, max_bytes=args.max_bytes,
                              enrich=not args.skip_enrichment)
            print(json.dumps(result), flush=True)
            if not args.watch:
                return 1 if result["failed"] or result["deferred"] else 0
            if stopped.wait(args.interval):
                return 0
    if args.command in {"retry", "recover"}:
        count = requeue(args.spool, "failed" if args.command == "retry" else "processing",
                        workers_stopped=getattr(args, "workers_stopped", False))
        print(json.dumps({"requeued": count}))
        return 0
    from app.core.db import SessionLocal
    from app.models import Camera, Estate

    if args.command == "list":
        from sqlalchemy import select

        with SessionLocal() as db:
            print(json.dumps({
                "estates": [{"id": str(e.id), "name": e.name, "timezone": e.timezone}
                            for e in db.scalars(select(Estate).order_by(Estate.name))],
                "cameras": [{"id": str(c.id), "estate_id": str(c.estate_id), "name": c.name,
                             "ftp_eligible": c.spypoint_id is None}
                            for c in db.scalars(select(Camera).order_by(Camera.name))],
            }, indent=2))
        return 0
    if not args.name.strip():
        parser.error("Camera name must not be empty")
    with SessionLocal() as db:
        if db.get(Estate, args.estate_id) is None:
            parser.error("Estate does not exist; pass the app's existing estate UUID")
        camera = Camera(estate_id=args.estate_id, name=args.name.strip(), model=args.model)
        db.add(camera)
        db.commit()
        print(camera.id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
