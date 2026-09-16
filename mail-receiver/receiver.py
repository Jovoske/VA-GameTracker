"""Mailbox bridge for the Suntek 4G camera: IMAP in, spool packages out.

The camera emails each photo (SMTP) to a dedicated mailbox. This process polls
that mailbox over IMAP, outbound only, and publishes every JPEG attachment as
ready/<hex>/{photo.jpg,metadata.json} in the same spool the FTP importer
(backend/app/ingestion/ftp_import.py) already watches. Nothing listens on a port,
so it works from behind a locked-down company network.

Standard library only. One process per mailbox and spool. Progress is tracked by
IMAP UID in <spool>/.mail-state.json, not by \\Seen flags, so a human opening
the mailbox cannot make a photo disappear from the import.
"""

from __future__ import annotations

import argparse
import email
import email.policy
import email.utils
import imaplib
import json
import logging
import os
import re
import shutil
import ssl
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from uuid import uuid4

LOG = logging.getLogger("camera_mail")
MIB = 1024 * 1024
PACKAGE_NAME = re.compile(r"[0-9a-f]{32}\Z")
STAGING = "staging-mail"
STATE_FILE = ".mail-state.json"
LOCK_FILE = ".mail-receiver.lock"


@dataclass(frozen=True)
class Settings:
    host: str
    username: str
    password: str
    spool_root: Path
    port: int = 993
    folder: str = "INBOX"
    poll_seconds: int = 60
    from_filter: str = ""
    mark_seen: bool = True
    max_upload_bytes: int = 20 * MIB
    max_messages_per_poll: int = 50

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ.get
        host, username, password = env("MAIL_IMAP_HOST", ""), env("MAIL_USERNAME", ""), env(
            "MAIL_PASSWORD", ""
        )
        root = env("MAIL_SPOOL_ROOT", "")
        if not host or not username or not password or not root:
            raise ValueError("Set MAIL_IMAP_HOST, MAIL_USERNAME, MAIL_PASSWORD and MAIL_SPOOL_ROOT")
        if any(c in username + password + host for c in "\r\n\x00"):
            raise ValueError("Mail settings must not contain newlines or null bytes")
        port = int(env("MAIL_IMAP_PORT", "993"))
        poll = int(env("MAIL_POLL_SECONDS", "60"))
        if not 1 <= port <= 65535 or poll < 5:
            raise ValueError("MAIL_IMAP_PORT out of range or MAIL_POLL_SECONDS below 5")
        limit = int(env("MAIL_MAX_UPLOAD_BYTES", str(20 * MIB)))
        if not 1 <= limit <= 20 * MIB:
            raise ValueError("MAIL_MAX_UPLOAD_BYTES must be between 1 and 20 MiB")
        return cls(
            host=host,
            username=username,
            password=password,
            spool_root=Path(root),
            port=port,
            folder=env("MAIL_FOLDER", "INBOX") or "INBOX",
            poll_seconds=poll,
            from_filter=env("MAIL_FROM_FILTER", "").strip().lower(),
            mark_seen=env("MAIL_MARK_SEEN", "1") not in {"0", "false", "no"},
            max_upload_bytes=limit,
        )


# ---- spool ------------------------------------------------------------------------------------


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Spool:
    """Owns <root>/staging-mail; publishes into <root>/ready like the FTP receiver."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock_file = None
        self._lock()
        try:
            for name in (STAGING, "ready"):
                path = self.root / name
                if path.is_symlink():
                    raise ValueError("Spool directories must not be symbolic links")
                path.mkdir(exist_ok=True)
            for stale in (self.root / STAGING).iterdir():
                if stale.is_dir() and not stale.is_symlink() and PACKAGE_NAME.fullmatch(stale.name):
                    shutil.rmtree(stale)
        except Exception:
            self.close()
            raise

    def _lock(self) -> None:
        self.lock_file = (self.root / LOCK_FILE).open("a+b")
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
            raise RuntimeError("Another mail receiver already owns this spool") from None

    def close(self) -> None:
        if self.lock_file is not None:
            self.lock_file.close()
            self.lock_file = None

    def publish(self, filename: str, data: bytes, received_at: datetime, extra: dict) -> Path:
        """Write staging-mail/<hex>/{photo.jpg,metadata.json}, fsync, rename into ready/."""
        package_id = uuid4().hex
        staging = self.root / STAGING / package_id
        staging.mkdir()
        try:
            with (staging / "photo.jpg").open("xb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            metadata = {
                "version": 1,
                "original_filename": filename,
                "received_at": received_at.astimezone(UTC).isoformat(),
                "byte_count": len(data),
                "source": "mail",
                **extra,
            }
            with (staging / "metadata.json").open("x", encoding="utf-8") as file:
                json.dump(metadata, file, separators=(",", ":"))
                file.flush()
                os.fsync(file.fileno())
            _fsync_directory(staging)
            destination = self.root / "ready" / package_id
            os.replace(staging, destination)
            _fsync_directory(destination.parent)
            return destination
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise


# ---- progress state --------------------------------------------------------------------------


class State:
    def __init__(self, root: Path):
        self.path = root / STATE_FILE
        self.uidvalidity: int | None = None
        self.last_uid = 0
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self.uidvalidity = int(raw["uidvalidity"])
                self.last_uid = int(raw["last_uid"])
            except (ValueError, KeyError, TypeError) as exc:
                LOG.warning("ignoring unreadable state file %s: %s", self.path, exc)

    def reset_for(self, uidvalidity: int) -> None:
        if self.uidvalidity != uidvalidity:
            if self.uidvalidity is not None:
                LOG.warning("mailbox UIDVALIDITY changed %s -> %s; starting over",
                            self.uidvalidity, uidvalidity)
            self.uidvalidity, self.last_uid = uidvalidity, 0
            self.save()

    def advance(self, uid: int) -> None:
        if uid > self.last_uid:
            self.last_uid = uid
            self.save()

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"uidvalidity": self.uidvalidity, "last_uid": self.last_uid}),
                       encoding="utf-8")
        os.replace(tmp, self.path)


# ---- message parsing --------------------------------------------------------------------------

_FILENAME_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,119}\.(?:jpg|jpeg)\Z", re.I)


def sanitize_filename(name: str | None, fallback: str) -> str:
    """Basename only, printable, JPEG suffix; otherwise a deterministic fallback."""
    if not name:
        return fallback
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    base = "".join(c for c in base if ord(c) >= 32)
    if _FILENAME_OK.fullmatch(base):
        return base
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(base).stem)[:100].strip("._")
    return f"{stem}.jpg" if stem else fallback


def jpeg_attachments(message: Message, *, max_bytes: int) -> list[tuple[str | None, bytes]]:
    """Every part that is a complete JPEG within the size limit, in document order."""
    found = []
    for part in message.walk():
        if part.is_multipart():
            continue
        name = part.get_filename()
        is_jpeg = part.get_content_type() == "image/jpeg" or (
            name is not None and name.lower().endswith((".jpg", ".jpeg"))
        )
        if not is_jpeg:
            continue
        try:
            data = part.get_payload(decode=True)
        except Exception as exc:  # malformed transfer encoding
            LOG.warning("attachment %r undecodable: %s", name, exc)
            continue
        if not data:
            continue
        if len(data) > max_bytes:
            LOG.warning("attachment %r skipped: %d bytes exceeds limit", name, len(data))
            continue
        if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
            LOG.warning("attachment %r skipped: not a complete JPEG", name)
            continue
        found.append((name, data))
    return found


def message_received_at(message: Message, now: datetime) -> datetime:
    """The camera's send time from the Date header, else the poll time."""
    for header in ("Date",):
        raw = message.get(header)
        if not raw:
            continue
        try:
            when = email.utils.parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            continue
        if when is None:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        when = when.astimezone(UTC)
        if datetime(2000, 1, 1, tzinfo=UTC) <= when <= now + timedelta(days=1):
            return when
    return now


def sender_matches(message: Message, from_filter: str) -> bool:
    if not from_filter:
        return True
    _, address = email.utils.parseaddr(message.get("From", ""))
    return from_filter in address.lower() or from_filter in message.get("From", "").lower()


# ---- IMAP ---------------------------------------------------------------------------------------


class Mailbox:
    """Thin wrapper so tests can substitute a fake IMAP client."""

    def __init__(self, settings: Settings, client_factory: Callable | None = None):
        self.settings = settings
        self._factory = client_factory or self._default_factory
        self.client = None

    @staticmethod
    def _default_factory(settings: Settings):
        context = ssl.create_default_context()
        return imaplib.IMAP4_SSL(settings.host, settings.port, ssl_context=context, timeout=60)

    def __enter__(self) -> Mailbox:
        client = self._factory(self.settings)
        try:
            client.login(self.settings.username, self.settings.password)
            typ, _ = client.select(self._quote(self.settings.folder), readonly=False)
            if typ != "OK":
                raise imaplib.IMAP4.error(f"cannot select folder {self.settings.folder!r}")
        except Exception:
            self._logout(client)
            raise
        self.client = client
        return self

    def __exit__(self, *exc) -> None:
        self._logout(self.client)
        self.client = None

    @staticmethod
    def _quote(folder: str) -> str:
        return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'

    @staticmethod
    def _logout(client) -> None:
        if client is None:
            return
        try:
            client.logout()
        except Exception:
            pass

    def uidvalidity(self) -> int:
        typ, data = self.client.response("UIDVALIDITY")
        if not data or data[0] is None:
            raise imaplib.IMAP4.error("server sent no UIDVALIDITY")
        return int(data[0])

    def uids_after(self, last_uid: int) -> list[int]:
        typ, data = self.client.uid("SEARCH", None, f"UID {last_uid + 1}:*")
        if typ != "OK":
            raise imaplib.IMAP4.error(f"UID SEARCH failed: {data!r}")
        raw = data[0] or b""
        if isinstance(raw, bytes):
            raw = raw.decode("ascii", "replace")
        # "n:*" always matches the highest UID even when it is below n; filter it out.
        return sorted(uid for uid in (int(x) for x in raw.split()) if uid > last_uid)

    def fetch(self, uid: int) -> bytes:
        typ, data = self.client.uid("FETCH", str(uid), "(BODY.PEEK[])")
        if typ != "OK":
            raise imaplib.IMAP4.error(f"UID FETCH {uid} failed: {data!r}")
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                if isinstance(item[1], bytes | bytearray):
                    return bytes(item[1])
        raise imaplib.IMAP4.error(f"UID FETCH {uid} returned no body")

    def mark_seen(self, uid: int) -> None:
        try:
            self.client.uid("STORE", str(uid), "+FLAGS.SILENT", "(\\Seen)")
        except Exception as exc:  # cosmetic; never affects the import
            LOG.debug("could not mark uid %s seen: %s", uid, exc)


# ---- one poll ----------------------------------------------------------------------------------


def process_once(
    settings: Settings,
    spool: Spool,
    state: State,
    *,
    client_factory: Callable | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    """Publish new messages' JPEGs. Transient IMAP/disk failures raise; bad mail is skipped."""
    counts = {"messages": 0, "published": 0, "skipped": 0, "errors": 0}
    with Mailbox(settings, client_factory) as box:
        state.reset_for(box.uidvalidity())
        uids = box.uids_after(state.last_uid)[: settings.max_messages_per_poll]
        for uid in uids:
            counts["messages"] += 1
            raw = box.fetch(uid)  # transient failure propagates; state not advanced
            try:
                message = email.message_from_bytes(raw, policy=email.policy.default)
                if not sender_matches(message, settings.from_filter):
                    LOG.info("uid %s skipped: sender %r does not match filter", uid,
                             message.get("From", ""))
                    counts["skipped"] += 1
                    state.advance(uid)
                    continue
                attachments = jpeg_attachments(message, max_bytes=settings.max_upload_bytes)
            except Exception as exc:  # unparsable message: log and move on, never wedge
                LOG.error("uid %s could not be parsed: %s", uid, exc)
                counts["errors"] += 1
                state.advance(uid)
                continue
            if not attachments:
                LOG.info("uid %s skipped: no JPEG attachment (subject %r)", uid,
                         str(message.get("Subject", ""))[:80])
                counts["skipped"] += 1
                state.advance(uid)
                continue
            received = message_received_at(message, now())
            for index, (name, data) in enumerate(attachments, start=1):
                filename = sanitize_filename(name, f"MAIL{uid}_{index}.jpg")
                extra = {
                    "mail_uid": uid,
                    "mail_part": index,
                    "mail_subject": str(message.get("Subject", ""))[:200],
                    "mail_from": str(message.get("From", ""))[:200],
                }
                package = spool.publish(filename, data, received, extra)  # disk failure propagates
                counts["published"] += 1
                LOG.info("uid %s part %d -> %s (%s, %d bytes)", uid, index, package.name,
                         filename, len(data))
            state.advance(uid)
            if settings.mark_seen:
                box.mark_seen(uid)
    return counts


def watch(settings: Settings, spool: Spool, state: State, *, once: bool = False,
          sleep: Callable[[float], None] = time.sleep) -> int:
    failures = 0
    while True:
        try:
            counts = process_once(settings, spool, state)
            failures = 0
            print(json.dumps(counts), flush=True)
        except (imaplib.IMAP4.error, OSError, ssl.SSLError) as exc:
            failures += 1
            LOG.error("poll failed (%d in a row): %s", failures, exc)
            if once:
                return 1
        if once:
            return 0
        sleep(min(settings.poll_seconds * (2 ** min(failures, 4)), 30 * 60)
              if failures else settings.poll_seconds)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="poll one time and exit")
    parser.add_argument("--log-level", default=os.environ.get("MAIL_LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    settings = Settings.from_env()
    spool = Spool(settings.spool_root)
    try:
        state = State(spool.root)
        LOG.info("polling %s@%s/%s every %ss into %s", settings.username, settings.host,
                 settings.folder, settings.poll_seconds, spool.root)
        return watch(settings, spool, state, once=args.once)
    finally:
        spool.close()


if __name__ == "__main__":
    sys.exit(main())
