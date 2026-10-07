"""Inbox progress, routing, credential validation and durable staging boundaries."""

import io
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

from app.api import routes_camera_accounts as routes
from app.ingestion import inbox
from app.ingestion.ftp_import import PACKAGE_NAME, read_package
from app.models import User

from .conftest import requires_db


def config(**values):
    return inbox.InboxConfig(
        host="mail.example.com", port=993, folder="INBOX", transport="imap_tls", **values
    )


def jpeg():
    stream = io.BytesIO()
    Image.new("RGB", (16, 16)).save(stream, "JPEG")
    return stream.getvalue()


@pytest.mark.parametrize("host", ["https://mail.example.com", "a\r\nUSER x", "localhost/", ""])
def test_host_rejects_urls_and_commands(host):
    with pytest.raises(ValidationError):
        config().model_copy(update={}).model_validate({**config().model_dump(), "host": host})


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.3", "169.254.169.254", "::1"])
def test_private_destinations_never_connect(monkeypatch, ip):
    monkeypatch.setattr(inbox.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", (ip, 993))])
    with pytest.raises(inbox.InboxError, match="publicly"):
        inbox.public_address("mail.example.com", 993)


def test_sender_does_not_allow_two_cameras_to_share_an_inbox():
    assert config(sender="one@example.com").key() == config(sender="two@example.com").key()
    different = config().model_copy(update={"folder": "camera-two"})
    assert different.key() != config().key()


@pytest.mark.parametrize(
    "provider,transport", [("suntek_email", "ftp"), ("suntek_ftp", "imap_tls")]
)
def test_protocol_must_match_provider(provider, transport):
    with pytest.raises(ValueError):
        config().model_copy(update={"transport": transport}).for_provider(provider)


def test_cloud_does_not_accept_inbox_configuration():
    with pytest.raises(ValidationError):
        routes.AddAccountBody(
            provider="nordic", username="test@example.com", password="p", connection=config()
        )


def test_inbox_needs_camera_name_and_connection():
    for data in ({}, {"label": "Camera"}, {"connection": config()}):
        with pytest.raises(ValidationError):
            routes.AddAccountBody(provider="suntek_email", username="owner", password="p", **data)


def test_member_cannot_make_custom_server_connections():
    db = Mock()
    with pytest.raises(HTTPException) as exc:
        routes.add_account(
            routes.AddAccountBody(
                provider="suntek_email",
                username="owner",
                password="p",
                label="Camera",
                connection=config(),
            ),
            User(id=uuid.uuid4(), estate_id=uuid.uuid4(), role="member"),
            db,
        )
    assert exc.value.status_code == 403
    db.add.assert_not_called()


def test_rejected_inbox_never_saves_credentials(monkeypatch):
    monkeypatch.setattr(
        routes, "verify_inbox", Mock(side_effect=inbox.InboxAuthError("Rejected login"))
    )
    db = Mock()
    db.scalar.return_value = None
    with pytest.raises(HTTPException) as exc:
        routes.add_account(
            routes.AddAccountBody(
                provider="suntek_email",
                username="owner",
                password="secret",
                label="Camera",
                connection=config(),
            ),
            User(id=uuid.uuid4(), estate_id=uuid.uuid4(), role="admin"),
            db,
        )
    assert exc.value.status_code == 400
    assert "secret" not in exc.value.detail
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_staged_photo_works_with_real_importer_and_replay(tmp_path):
    now = datetime.now(UTC)
    inbox.stage(tmp_path, "mail:1:4:1", jpeg(), "camera.jpg", now)
    inbox.stage(tmp_path, "mail:1:4:1", jpeg(), "camera.jpg", now)
    packages = list((tmp_path / "ready").iterdir())
    assert len(packages) == 1
    assert PACKAGE_NAME.fullmatch(packages[0].name)
    photo = read_package(packages[0], "Europe/Helsinki")
    assert photo.received_at == now


def test_staged_package_is_claimed_by_import_worker(tmp_path, monkeypatch):
    from contextlib import nullcontext

    from app.ingestion import ftp_import

    persisted = Mock(return_value=ftp_import.ImportResult("image-id", "imported", "photo.jpg"))
    monkeypatch.setattr(ftp_import, "_persist_photo", persisted)
    inbox.stage(tmp_path, "mail:1:4:1", jpeg(), "camera.jpg", datetime.now(UTC))
    result = ftp_import.run_once(
        tmp_path,
        uuid.uuid4(),
        session_factory=lambda: nullcontext(Mock()),
        media_root=tmp_path / "media",
        enrich=False,
    )
    assert result == {"imported": 1, "duplicate": 0, "failed": 0, "deferred": 0}
    persisted.assert_called_once()
    # A replay after UID reset finds its audit manifest; no second queue entry.
    inbox.stage(tmp_path, "mail:1:4:1", jpeg(), "camera.jpg", datetime.now(UTC))
    assert list((tmp_path / "ready").iterdir()) == []


def test_directory_listing_is_bounded_before_buffering(monkeypatch):
    client = inbox._PinnedFTP()
    monkeypatch.setattr(client, "sendcmd", lambda command: "200 OK")

    def listing(command, callback):
        for index in range(10001):
            callback(f"type=file;size=10; {index}.jpg")

    monkeypatch.setattr(client, "retrlines", listing)
    with pytest.raises(inbox.InboxError, match="10,000"):
        list(client.mlsd(facts=["type", "size"]))


class Mailbox:
    def __init__(self, epoch=b"10"):
        self.epoch = epoch
        self.calls = []

    def response(self, key):
        return key, [self.epoch]

    def uid(self, *args):
        self.calls.append(args)
        if args[0] == "search":
            return "OK", [b"4 5"]
        if args[2] == "(RFC822.SIZE)":
            return "OK", [b"1 (RFC822.SIZE 4000)"]
        msg = EmailMessage()
        msg["From"] = "camera@example.com"
        msg.set_content("Camera photo")
        msg.add_attachment(jpeg(), maintype="image", subtype="jpeg", filename="camera.jpg")
        return "OK", [
            (b'1 (INTERNALDATE "06-Oct-2026 10:00:00 +0000" BODY[] {4000}', msg.as_bytes()),
            b")",
        ]


def test_mail_continues_by_uid_and_does_not_mark_seen():
    client, publish, checkpoint = Mailbox(), Mock(), Mock()
    inbox.poll_mail(client, config(), {"epoch": "10", "uid": 4}, publish, checkpoint)
    assert publish.call_count == 1
    checkpoint.assert_called_once_with({"epoch": "10", "uid": 5})
    assert all(call[0] != "store" for call in client.calls)
    assert any("BODY.PEEK[]" in str(call) for call in client.calls)


def test_uidvalidity_change_restarts_without_skipping():
    publish = Mock()
    inbox.poll_mail(Mailbox(b"11"), config(), {"epoch": "10", "uid": 100}, publish, Mock())
    assert publish.call_count == 2


def test_staging_failure_does_not_advance_mail_cursor():
    checkpoint = Mock()
    with pytest.raises(OSError):
        inbox.poll_mail(Mailbox(), config(), {}, Mock(side_effect=OSError("disk full")), checkpoint)
    checkpoint.assert_not_called()


def test_sender_filter_advances_without_importing_wrong_camera():
    publish, checkpoint = Mock(), Mock()
    inbox.poll_mail(Mailbox(), config(sender="different@example.com"), {}, publish, checkpoint)
    publish.assert_not_called()
    assert checkpoint.call_count == 2


class FTP:
    def __init__(self, count=1, modified="20261006100000", incomplete=False):
        self.data = jpeg()
        self.modified = modified
        self.count = count
        self.incomplete = incomplete
        self.downloads = []

    def mlsd(self, **kwargs):
        for i in range(self.count):
            yield (
                f"{i:03d}.jpg",
                {"type": "file", "size": str(len(self.data)), "modify": self.modified},
            )

    def retrbinary(self, command, callback):
        self.downloads.append(command)
        callback(self.data[:-2] if self.incomplete else self.data)

    def size(self, name):
        return len(self.data)


def test_ftp_cursor_rotates_across_more_than_one_batch():
    client = FTP(count=60)
    cursor = {}

    def checkpoint(value):
        cursor.clear()
        cursor.update(value)

    publish = Mock()
    inbox.poll_ftp(client, config(), cursor, publish, checkpoint)
    assert len(client.downloads) == 50
    inbox.poll_ftp(client, config(), cursor, publish, checkpoint)
    assert len(client.downloads) == 60
    inbox.poll_ftp(client, config(), cursor, publish, checkpoint)
    assert len(client.downloads) == 60


def test_ftp_overwritten_filename_is_downloaded_again():
    client, cursor = FTP(), {}

    def checkpoint(value):
        cursor.clear()
        cursor.update(value)

    inbox.poll_ftp(client, config(), cursor, Mock(), checkpoint)
    client.modified = "20261006110000"
    inbox.poll_ftp(client, config(), cursor, Mock(), checkpoint)
    assert len(client.downloads) == 2


def test_partial_ftp_upload_never_advances_cursor():
    publish, checkpoint = Mock(), Mock()
    with pytest.raises(inbox.InboxError, match="progress"):
        inbox.poll_ftp(FTP(incomplete=True), config(), {}, publish, checkpoint)
    publish.assert_not_called()
    checkpoint.assert_not_called()


def test_ftps_passive_data_pins_control_peer(monkeypatch):
    monkeypatch.setattr(inbox.ftplib.FTP, "makepasv", lambda _: ("10.0.0.1", 44000))
    client = inbox._PinnedFTPS()
    client.sock = Mock()
    client.sock.getpeername.return_value = ("8.8.8.8", 21)
    assert client.makepasv() == ("8.8.8.8", 44000)


@requires_db
def test_saved_inbox_encrypts_password_links_one_camera_and_imports(
    db_session, monkeypatch, tmp_path
):
    db = db_session
    from contextlib import contextmanager

    from sqlalchemy import select

    from app.core.config import settings
    from app.core.crypto import decrypt
    from app.ingestion import inbox_sync
    from app.models import Camera, CameraAccount, Image

    from .test_camera_accounts import _seed

    user = _seed(db)
    user.role = "admin"
    db.commit()
    monkeypatch.setattr(routes, "verify_inbox", lambda *args: None)
    monkeypatch.setattr(settings, "media_root", str(tmp_path / "media"))
    body = routes.AddAccountBody(
        provider="suntek_email",
        username="owner@example.com",
        password="private-password",
        label="Clearing",
        connection=config(),
    )
    added = routes.add_account(body, user, db)
    account = db.get(CameraAccount, uuid.UUID(added["id"]))
    assert decrypt(account.password_enc) == "private-password"
    assert "private-password" not in str(account.connection_config)
    camera = db.scalar(select(Camera).where(Camera.account_id == account.id))
    assert camera.estate_id == user.estate_id and camera.name == "Clearing"
    with pytest.raises(HTTPException) as exc:
        routes.add_account(body, user, db)
    assert exc.value.status_code == 400

    @contextmanager
    def connection(*args):
        yield Mailbox()

    monkeypatch.setattr(inbox_sync, "connect", connection)
    original = inbox_sync.run_once
    monkeypatch.setattr(inbox_sync, "run_once", lambda *a, **kw: original(*a, **kw, enrich=False))
    first = inbox_sync.sync_inbox_all(db, account.id)
    assert first["status"] == "ok" and first["total"] == 1  # identical attachments deduplicate
    again = inbox_sync.sync_inbox_all(db, account.id)
    assert again["status"] == "ok" and again["total"] == 0
    db.refresh(account)
    assert account.input_cursor == {"epoch": "10", "uid": 5}
    assert db.scalar(select(Image).where(Image.camera_id == camera.id)) is not None
    routes.remove_account(account.id, user, db)
    db.refresh(camera)
    assert not camera.active and camera.account_id is None
    assert db.scalar(select(Image).where(Image.camera_id == camera.id)) is not None
