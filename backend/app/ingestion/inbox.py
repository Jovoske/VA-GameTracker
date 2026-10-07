"""Read-only, per-camera IMAP and FTP/FTPS inboxes.

Connections pin a public IP while retaining the hostname for TLS verification.
Neither transport deletes files/messages; progress advances only after durable staging.
"""

from __future__ import annotations

import ftplib
import hashlib
import imaplib
import ipaddress
import json
import re
import socket
import ssl
from contextlib import contextmanager
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROVIDERS = {"suntek_email", "suntek_ftp"}
MAX_PHOTO = 20 * 1024 * 1024
MAX_MAIL = 32 * 1024 * 1024
BATCH = 50


class InboxError(Exception):
    """Safe, actionable text; never include server replies or credentials."""


class InboxAuthError(InboxError):
    pass


class InboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    folder: str = Field(min_length=1, max_length=512)
    transport: str
    sender: str = Field(default="", max_length=254)
    timezone: str = "Europe/Helsinki"

    @field_validator("host")
    @classmethod
    def hostname(cls, value):
        value = value.lower().rstrip(".")
        if not value or any(c in value for c in "/\\@:?# \r\n\x00"):
            raise ValueError("Enter a server hostname, without a URL or port")
        return value.encode("idna").decode("ascii")

    @field_validator("folder", "sender")
    @classmethod
    def no_commands(cls, value):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Control characters are not allowed")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Enter a valid timezone, for example Europe/Helsinki") from exc
        return value

    def for_provider(self, provider: str) -> InboxConfig:
        allowed = {"imap_tls"} if provider == "suntek_email" else {"ftp", "ftps"}
        if self.transport not in allowed:
            raise ValueError("Choose a transport matching the camera connection")
        if provider == "suntek_ftp" and not self.folder.startswith("/"):
            raise ValueError("Use an absolute FTP folder starting with /")
        if provider == "suntek_ftp" and self.sender:
            raise ValueError("Sender filtering is only available for email")
        if self.sender and (
            len(getaddresses([self.sender])) != 1
            or getaddresses([self.sender])[0][1] != self.sender
            or "@" not in self.sender
        ):
            raise ValueError("Enter one exact camera sender email address")
        return self

    def key(self) -> str:
        # One mailbox/folder per camera, even if a different sender filter is supplied.
        folder = self.folder
        if self.transport != "imap_tls":
            folder = "/" + "/".join(p for p in folder.split("/") if p not in ("", "."))
            if ".." in folder.split("/") or "\\" in folder:
                raise ValueError("Use an absolute FTP folder without parent segments")
        elif folder.upper() == "INBOX":
            folder = "INBOX"
        return hashlib.sha256(json.dumps([self.host, self.port, folder]).encode()).hexdigest()


def public_address(host: str, port: int) -> str:
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise InboxError("Use a publicly reachable mail or FTP server")
    return addresses[0][4][0]


class _PinnedFTP(ftplib.FTP):
    def mlsd(self, path="", facts=()):
        # ftplib's default implementation buffers the entire directory before yielding.
        if facts:
            self.sendcmd("OPTS MLST " + ";".join(facts) + ";")
        lines = []

        def collect(line):
            if len(lines) >= 10000:
                raise InboxError("The FTP folder has over 10,000 entries. Archive older files.")
            lines.append(line)

        self.retrlines("MLSD" + (" " + path if path else ""), collect)
        for line in lines:
            facts_text, _, name = line.partition(" ")
            facts_map = {}
            for fact in facts_text.rstrip(";").split(";"):
                key, _, value = fact.partition("=")
                facts_map[key.lower()] = value
            yield name, facts_map

    def makepasv(self):
        _, port = super().makepasv()
        return self.sock.getpeername()[0], port


class _PinnedFTPS(ftplib.FTP_TLS, _PinnedFTP):
    pass


class _PinnedIMAP(imaplib.IMAP4_SSL):
    def _create_socket(self, timeout):
        raw = socket.create_connection((public_address(self.host, self.port), self.port), timeout)
        try:
            return self.ssl_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


@contextmanager
def connect(config: InboxConfig, username: str, password: str):
    client = None
    try:
        if config.transport == "imap_tls":
            client = _PinnedIMAP(
                config.host, config.port, ssl_context=ssl.create_default_context(), timeout=30
            )
            try:
                client.login(username, password)
            except imaplib.IMAP4.error:
                raise InboxAuthError(
                    "The mailbox refused the login. Re-enter its password or app password."
                ) from None
            # Quote mailbox names so spaces and non-ASCII names don't become commands.
            folder = '"' + config.folder.replace("\\", "\\\\").replace('"', '\\"') + '"'
            status, _ = client.select(folder, readonly=True)
            if status != "OK":
                raise InboxError("The mailbox folder could not be opened. Check its name.")
        else:
            client = (
                _PinnedFTPS(context=ssl.create_default_context(), timeout=30)
                if config.transport == "ftps"
                else _PinnedFTP(timeout=30)
            )
            client.connect(public_address(config.host, config.port), config.port)
            client.host = config.host  # Original hostname for TLS SNI and certificate validation.
            try:
                client.login(username, password)
            except ftplib.error_perm:
                raise InboxAuthError(
                    "The FTP server refused the login. Re-enter its password."
                ) from None
            if config.transport == "ftps":
                client.prot_p()
            client.trust_server_pasv_ipv4_address = False
            client.cwd(config.folder)
        yield client
    except InboxError:
        raise
    except (OSError, EOFError, UnicodeError, ValueError, imaplib.IMAP4.error, ftplib.Error):
        raise InboxError(
            "Could not read the camera inbox. Check the server, folder, transport and access "
            "permissions."
        ) from None
    finally:
        if client is not None:
            try:
                if config.transport == "imap_tls":
                    client.logout()
                else:
                    client.close()
            except (OSError, EOFError, imaplib.IMAP4.error):
                pass


def stage(spool: Path, identity: str, data: bytes, filename: str, received: datetime):
    from app.ingestion.ftp_import import _atomic_write, _json_write, _move_package

    if not data or len(data) > MAX_PHOTO:
        raise InboxError("A camera photo exceeds the 20 MB import limit")
    key = hashlib.sha256(identity.encode()).hexdigest()[:32]
    ready = spool / "ready" / key
    if ready.exists() or (spool / "processed" / key).exists() or (spool / "failed" / key).exists():
        return
    package = spool / "staging" / key
    package.mkdir(parents=True, exist_ok=True)
    _atomic_write(package / "photo.jpg", data)
    _json_write(
        package / "metadata.json",
        {
            "version": 1,
            "original_filename": re.split(r"[/\\]", filename)[-1][:250],
            "received_at": received.isoformat(),
            "byte_count": len(data),
        },
    )
    ready.parent.mkdir(parents=True, exist_ok=True)
    _move_package(package, ready)


def poll_mail(client, config: InboxConfig, cursor: dict, publish, checkpoint):
    _, validity = client.response("UIDVALIDITY")
    if not validity or not validity[0]:
        raise InboxError("The mailbox did not provide stable message identifiers")
    epoch = validity[0].decode("ascii")
    last = int(cursor.get("uid", 0)) if cursor.get("epoch") == epoch else 0
    status, data = client.uid("search", None, "UID", f"{last + 1}:*")
    if status != "OK":
        raise InboxError("The mailbox could not list camera messages")
    ids = sorted(int(uid) for uid in (data[0] or b"").split() if int(uid) > last)
    for uid in ids[:BATCH]:
        status, sizes = client.uid("fetch", str(uid), "(RFC822.SIZE)")
        size = re.search(rb"RFC822.SIZE (\d+)", b" ".join(x for x in sizes if isinstance(x, bytes)))
        if status != "OK" or not size or int(size[1]) > MAX_MAIL:
            raise InboxError(
                "A mailbox message could not be read or exceeds 32 MB. Move it out of this "
                "camera folder."
            )
        status, parts = client.uid("fetch", str(uid), "(INTERNALDATE BODY.PEEK[])")
        literal = next((p for p in parts if isinstance(p, tuple)), None)
        if status != "OK" or literal is None or len(literal[1]) > MAX_MAIL:
            raise InboxError("A camera message could not be downloaded")
        message = BytesParser(policy=policy.default).parsebytes(literal[1])
        senders = [address.lower() for _, address in getaddresses(message.get_all("From", []))]
        if not config.sender or config.sender.lower() in senders:
            internal = imaplib.Internaldate2tuple(literal[0])
            if internal is None:
                raise InboxError("The mailbox did not provide a message receipt time")
            import time

            received = datetime.fromtimestamp(time.mktime(internal), UTC)
            for index, part in enumerate(message.walk()):
                name = part.get_filename() or ""
                if part.get_content_type() == "image/jpeg" or name.lower().endswith(
                    (".jpg", ".jpeg")
                ):
                    publish(
                        f"mail:{epoch}:{uid}:{index}",
                        part.get_payload(decode=True) or b"",
                        name or f"photo-{index}.jpg",
                        received,
                    )
        checkpoint({"epoch": epoch, "uid": uid})


def ftp_files(client) -> list[tuple[str, dict]]:
    try:
        rows = []
        for name, facts in client.mlsd(facts=["type", "size", "modify"]):
            rows.append((name, facts))
            if len(rows) > 10000:
                raise InboxError(
                    "The FTP folder has over 10,000 entries. Archive older files into another "
                    "folder."
                )
    except ftplib.error_perm as exc:
        # Don't silently downgrade a permissions failure to an empty folder.
        if not str(exc).startswith(("500", "501", "502", "504")):
            raise
        raise InboxError(
            "This FTP server must support MLSD directory listings. Enable MLSD or use an email "
            "inbox."
        ) from None
    return sorted(
        (name, facts)
        for name, facts in rows
        if facts.get("type") == "file" and name.lower().endswith((".jpg", ".jpeg"))
    )


def poll_ftp(client, config: InboxConfig, cursor: dict, publish, checkpoint):
    rows = ftp_files(client)
    names = {name for name, _ in rows}
    seen = {name: value for name, value in cursor.get("seen", {}).items() if name in names}
    offset = int(cursor.get("offset", 0)) % max(len(rows), 1)
    for index in range(min(len(rows), BATCH)):
        name, facts = rows[(offset + index) % len(rows)]
        if any(c in name for c in "/\\\r\n\x00") or name in (".", ".."):
            raise InboxError("The FTP folder contains an unsupported filename")
        signature = [facts.get("size"), facts.get("modify")]
        if all(signature) and seen.get(name) == signature:
            continue
        if not facts.get("size", "").isdigit() or int(facts["size"]) > MAX_PHOTO:
            raise InboxError("An FTP photo has no readable size or exceeds 20 MB")
        data = bytearray()

        def collect(chunk, data=data):
            if len(data) + len(chunk) > MAX_PHOTO:
                raise InboxError("An FTP photo exceeds 20 MB")
            data.extend(chunk)

        client.retrbinary("RETR " + name, collect)
        # An upload still in progress must be retried rather than checkpointed.
        if len(data) != int(facts["size"]) or client.size(name) != len(data):
            raise InboxError(
                "A camera upload is still in progress. It will be retried on the next check."
            )
        if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
            raise InboxError("An FTP photo is incomplete. It will be retried on the next check.")
        received = datetime.now(UTC)
        if facts.get("modify"):
            received = datetime.strptime(facts["modify"].split(".")[0], "%Y%m%d%H%M%S").replace(
                tzinfo=UTC
            )
        publish("ftp:" + name + ":" + hashlib.sha256(data).hexdigest(), bytes(data), name, received)
        seen[name] = signature
        checkpoint({"seen": dict(seen), "offset": (offset + index + 1) % max(len(rows), 1)})
    checkpoint({"seen": seen, "offset": (offset + min(len(rows), BATCH)) % max(len(rows), 1)})


def verify(provider: str, username: str, password: str, config: InboxConfig):
    config.for_provider(provider)
    config.key()
    with connect(config, username, password) as client:
        if provider == "suntek_ftp":
            ftp_files(client)
