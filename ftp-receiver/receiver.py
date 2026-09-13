"""Upload-only FTP bridge. Run one process/account per camera and spool.

pyftpdlib's on_file_received runs AFTER 226. DurableDTP closes and publishes
the upload BEFORE calling its close implementation, so storage failures cannot
be acknowledged as successful uploads. Keep the pinned dependency and tests.
"""

from __future__ import annotations

import errno
import ipaddress
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import DTPHandler, FTPHandler
from pyftpdlib.ioloop import IOLoop
from pyftpdlib.servers import FTPServer

LOG = logging.getLogger("camera_ftp")
MIB = 1024 * 1024
FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,119}\.(?:jpg|jpeg)", re.I)


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    spool_root: Path
    bind: str = "127.0.0.1"
    port: int = 2121
    public_ip: str | None = None
    max_upload_bytes: int = 20 * MIB
    max_spool_bytes: int = 2 * 1024 * MIB
    max_queue_files: int = 1000
    min_free_bytes: int = 100 * MIB
    passive_start: int = 50000
    passive_end: int = 50009

    @classmethod
    def from_env(cls) -> Settings:
        username = os.environ.get("FTP_USERNAME", "")
        password = os.environ.get("FTP_PASSWORD", "")
        root = os.environ.get("FTP_SPOOL_ROOT", "")
        if not username or len(password) < 13 or not root:
            raise ValueError(
                "Set FTP_USERNAME, FTP_PASSWORD (at least 13 characters), and FTP_SPOOL_ROOT"
            )
        if any(char in username + password for char in "\r\n\x00"):
            raise ValueError("FTP credentials must not contain newlines or null bytes")
        result = cls(
            username=username,
            password=password,
            spool_root=Path(root).resolve(),
            bind=os.environ.get("FTP_BIND", "127.0.0.1"),
            port=int(os.environ.get("FTP_PORT", "2121")),
            public_ip=os.environ.get("FTP_PUBLIC_IP") or None,
            max_upload_bytes=int(os.environ.get("FTP_MAX_UPLOAD_BYTES", str(20 * MIB))),
            max_spool_bytes=int(os.environ.get("FTP_MAX_SPOOL_BYTES", str(2 * 1024 * MIB))),
            max_queue_files=int(os.environ.get("FTP_MAX_QUEUE_FILES", "1000")),
            min_free_bytes=int(os.environ.get("FTP_MIN_FREE_BYTES", str(100 * MIB))),
        )
        if not 1 <= result.port <= 65535:
            raise ValueError("FTP_PORT must be between 1 and 65535")
        if result.public_ip is not None:
            ipaddress.IPv4Address(result.public_ip)
        if not 1 <= result.max_upload_bytes <= 20 * MIB:
            raise ValueError("FTP_MAX_UPLOAD_BYTES must be between 1 and 20971520")
        if (
            result.max_spool_bytes < result.max_upload_bytes + 8192
            or result.max_queue_files < 1
            or result.min_free_bytes < 0
        ):
            raise ValueError("Invalid FTP spool capacity settings")
        return result


def sync_directory(path: Path) -> None:
    """Directory fsync is available on the Linux deployment target."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class Spool:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.spool_root.resolve()
        self.active: dict[str, Upload] = {}
        self.lock_file = None
        missing = []
        ancestor = self.root
        while not ancestor.exists():
            missing.append(ancestor)
            ancestor = ancestor.parent
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock()
        try:
            for directory in ("staging", "ready", "ftp-home"):
                path = self.root / directory
                if path.is_symlink():
                    raise ValueError("Spool directories must not be symbolic links")
                path.mkdir(exist_ok=True)
            # Only this receiver owns staging; never remove ready/processing.
            for stale in (self.root / "staging").iterdir():
                if (
                    stale.is_dir()
                    and not stale.is_symlink()
                    and re.fullmatch(r"[a-f0-9]{32}", stale.name)
                ):
                    shutil.rmtree(stale)
            sync_directory(self.root)
            for created in missing:
                sync_directory(created.parent)
        except Exception:
            self.close()
            raise

    def _lock(self) -> None:
        self.lock_file = (self.root / ".receiver.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self.lock_file.seek(0)
                if self.lock_file.read(1) == b"":
                    self.lock_file.write(b"0")
                    self.lock_file.flush()
                self.lock_file.seek(0)
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close()
            self.lock_file = None
            raise RuntimeError("Another receiver already owns this spool") from None

    def close(self) -> None:
        for upload in list(self.active.values()):
            upload.discard()
        if self.lock_file is not None:
            self.lock_file.close()
            self.lock_file = None

    def begin(self, original_filename: str) -> Upload:
        # Conservative reservation accounts for full-sized concurrent uploads.
        used = 0
        queued = 0
        active_dirs = {upload.directory for upload in self.active.values()}
        for directory, child_dirs, files in os.walk(self.root, followlinks=False):
            path = Path(directory)
            child_dirs[:] = [
                name
                for name in child_dirs
                if path / name not in active_dirs and not (path / name).is_symlink()
            ]
            if "photo.jpg" in files:
                queued += 1
            for name in files:
                try:
                    used += (path / name).stat(follow_symlinks=False).st_size
                except FileNotFoundError:
                    pass  # importer completed an item during this scan
        reservation = (len(self.active) + 1) * (self.settings.max_upload_bytes + 8192)
        if (
            queued + len(self.active) >= self.settings.max_queue_files
            or used + reservation > self.settings.max_spool_bytes
        ):
            raise OSError("Upload queue capacity reached")
        if shutil.disk_usage(self.root).free < self.settings.min_free_bytes + reservation:
            raise OSError("Insufficient free space")
        upload = Upload(self, original_filename)
        self.active[upload.id] = upload
        return upload


class Upload:
    """A file-like bounded writer and one atomic queue record."""

    def __init__(self, spool: Spool, original_filename: str):
        self.spool = spool
        self.id = uuid4().hex
        self.directory = spool.root / "staging" / self.id
        self.directory.mkdir()
        try:
            self.file = (self.directory / "photo.jpg").open("xb")
        except Exception:
            self.directory.rmdir()
            raise
        self.original_filename = original_filename
        self.byte_count = 0
        self.header = b""
        self.tail = b""
        self.published = False
        self.name = str(self.directory / "photo.jpg")

    @property
    def closed(self) -> bool:
        return self.file.closed

    def write(self, chunk: bytes) -> int:
        if self.byte_count + len(chunk) > self.spool.settings.max_upload_bytes:
            raise OSError("Upload exceeds size limit")
        self.header = (self.header + chunk)[:3]
        if len(self.header) == 3 and self.header != b"\xff\xd8\xff":
            raise OSError("Only JPEG images are accepted")
        count = self.file.write(chunk)
        self.byte_count += count
        self.tail = (self.tail + chunk)[-2:]
        return count

    def close(self) -> None:
        self.file.close()

    def finish(self) -> None:
        if self.byte_count < 4 or self.header != b"\xff\xd8\xff" or self.tail != b"\xff\xd9":
            raise OSError("Incomplete JPEG image")
        self.file.flush()
        os.fsync(self.file.fileno())
        self.file.close()
        metadata = {
            "version": 1,
            "original_filename": self.original_filename,
            "received_at": datetime.now(UTC).isoformat(),
            "byte_count": self.byte_count,
        }
        with (self.directory / "metadata.json").open("x", encoding="utf-8") as file:
            json.dump(metadata, file, separators=(",", ":"))
            file.flush()
            os.fsync(file.fileno())
        sync_directory(self.directory)
        destination = self.spool.root / "ready" / self.id
        os.replace(self.directory, destination)
        self.published = True
        self.spool.active.pop(self.id, None)
        sync_directory(destination.parent)
        sync_directory(self.directory.parent)

    def discard(self) -> None:
        try:
            self.file.close()
        except OSError:
            LOG.exception("Unable to close partial upload %s", self.id)
        finally:
            if not self.published:
                shutil.rmtree(self.directory, ignore_errors=True)
            self.spool.active.pop(self.id, None)


class DurableDTP(DTPHandler):
    timeout = 90

    def enable_receiving(self, type, cmd):
        # This camera sends JPEGs under TYPE A too; never translate newlines.
        super().enable_receiving("i", cmd)

    def close(self):
        if not self._closed and isinstance(self.file_obj, Upload):
            upload = self.file_obj
            if self.receive and self.transfer_finished:
                try:
                    upload.finish()
                except Exception:
                    LOG.exception("Unable to commit camera upload %s", upload.id)
                    self.transfer_finished = False
                    self._resp = ("451 Upload could not be committed; retry later.", LOG.warning)
                    upload.discard()
            else:
                upload.discard()
        super().close()


class FixedPassiveDTP(FTPHandler.passive_dtp):
    def bind(self, address):
        if address[1] == 0 and 0 not in self.cmd_channel.passive_ports:
            # pyftpdlib otherwise silently leaves the configured firewall range
            # when all passive ports are occupied. Close and reject instead.
            self.close()
            raise OSError(errno.EADDRINUSE, "No configured passive port available")
        return super().bind(address)


def make_server(settings: Settings) -> FTPServer:
    spool = Spool(settings)
    authorizer = DummyAuthorizer()
    authorizer.add_user(
        settings.username, settings.password, str(spool.root / "ftp-home"), perm="ew"
    )
    allowed = {
        "USER",
        "PASS",
        "QUIT",
        "NOOP",
        "SYST",
        "FEAT",
        "HELP",
        "OPTS",
        "PWD",
        "XPWD",
        "TYPE",
        "STRU",
        "MODE",
        "PASV",
        "EPSV",
        "ABOR",
        "CWD",
        "XCWD",
        "ALLO",
        "STOR",
    }

    class CameraHandler(FTPHandler):
        dtp_handler = DurableDTP
        passive_dtp = FixedPassiveDTP
        passive_ports = range(settings.passive_start, settings.passive_end + 1)
        masquerade_address = settings.public_ip
        timeout = 120
        max_login_attempts = 3
        banner = "Camera upload receiver ready."
        proto_cmds = {key: value for key, value in FTPHandler.proto_cmds.items() if key in allowed}

        def pre_process_command(self, line, cmd, arg):
            if self.authenticated and cmd == "STOR":
                filename = arg[1:] if arg.startswith("/") else arg
                if not FILENAME.fullmatch(filename):
                    self.respond("550 Upload a JPEG filename in the root folder only.")
                    return
                if self._in_dtp_queue is not None or (
                    self.data_channel is not None and self.data_channel.file_obj is not None
                ):
                    self.respond("450 An upload is already in progress.")
                    return
            if self.authenticated and cmd in {"CWD", "XCWD"} and arg not in {"/", "."}:
                self.respond("550 Only the root folder is available.")
                return
            super().pre_process_command(line, cmd, arg)

        def ftp_STOR(self, file, mode="w"):
            try:
                upload = spool.begin(Path(file).name)
            except OSError:
                self.respond("452 Upload storage unavailable; retry later.")
                return
            try:
                if self.data_channel is not None:
                    self.respond("125 Data connection open; upload starting.")
                    self.data_channel.file_obj = upload
                    # Suntek firmware asks its modem for ASCII FTP mode even
                    # when uploading JPEGs. This receiver stores bytes exactly;
                    # never perform FTP's ASCII newline translation.
                    self.data_channel.enable_receiving("i", "STOR")
                else:
                    self.respond("150 Ready for upload data connection.")
                    self._in_dtp_queue = (upload, "STOR")
            except Exception:
                upload.discard()
                raise

        def on_disconnect(self):
            # Queued STOR with no established data socket also needs cleanup.
            for upload in list(spool.active.values()):
                if upload.closed:
                    upload.discard()

        def ftp_ABOR(self, line):
            queued = self._in_dtp_queue
            super().ftp_ABOR(line)
            if queued is not None:
                queued[0].discard()
                self._in_dtp_queue = None

        def _make_epasv(self, extmode=False):
            try:
                super()._make_epasv(extmode)
            except OSError:
                self.respond("425 No passive data port available; retry later.")

    CameraHandler.authorizer = authorizer
    try:
        server = FTPServer((settings.bind, settings.port), CameraHandler, ioloop=IOLoop())
    except Exception:
        spool.close()
        raise
    server.max_cons = 12  # includes passive listeners and data connections
    server.max_cons_per_ip = 6
    server.spool = spool
    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    server = make_server(settings)
    try:
        server.serve_forever()
    finally:
        server.close_all()
        server.spool.close()


if __name__ == "__main__":
    main()
