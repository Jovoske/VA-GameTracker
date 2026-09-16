"""Mailbox receiver against a fake IMAP client; no network, no Pillow."""

import email.policy
import imaplib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "receiver.py"
SPEC = importlib.util.spec_from_file_location("camera_mail_receiver", MODULE_PATH)
receiver = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = receiver
SPEC.loader.exec_module(receiver)

JPEG = b"\xff\xd8\xff\xe0" + b"camera bytes\r\n" * 4 + b"\xff\xd9"
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def make_message(*, attachments=(), sender="cam@example.com",
                 date="Tue, 16 Sep 2026 10:30:00 +0200", subject="HC801LTE photo"):
    message = EmailMessage(policy=email.policy.default)
    message["From"] = sender
    message["To"] = "spool@example.com"
    message["Subject"] = subject
    if date:
        message["Date"] = date
    message.set_content("Photo attached.")
    for name, data, subtype in attachments:
        message.add_attachment(data, maintype="image" if subtype in {"jpeg", "png"} else "text",
                               subtype=subtype, filename=name)
    return message.as_bytes()


class FakeIMAP:
    """Just enough of imaplib.IMAP4 for the receiver: UID SEARCH/FETCH/STORE."""

    error = imaplib.IMAP4.error

    def __init__(self, messages: dict[int, bytes], uidvalidity=42, fail_fetch=False):
        self.messages = messages
        self.uidvalidity = uidvalidity
        self.fail_fetch = fail_fetch
        self.seen: list[int] = []
        self.logged_in = False
        self.logged_out = False
        self.selected = None

    def login(self, user, password):
        assert (user, password) == ("spool@example.com", "app-password-16")
        self.logged_in = True

    def select(self, folder, readonly=False):
        self.selected = folder
        return "OK", [str(len(self.messages)).encode()]

    def response(self, code):
        assert code == "UIDVALIDITY"
        return code, [str(self.uidvalidity).encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            low = int(args[1].split()[1].split(":")[0])
            hits = sorted(u for u in self.messages if u >= low)
            if not hits and self.messages:
                hits = [max(self.messages)]  # IMAP "n:*" semantics
            return "OK", [" ".join(map(str, hits)).encode()]
        if command == "FETCH":
            if self.fail_fetch:
                raise imaplib.IMAP4.abort("connection dropped")
            uid = int(args[0])
            raw = self.messages[uid]
            return "OK", [(f"1 (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw), b")"]
        if command == "STORE":
            self.seen.append(int(args[0]))
            return "OK", [b""]
        raise AssertionError(command)

    def logout(self):
        self.logged_out = True


def settings_for(tmp_path, **overrides):
    values = dict(host="imap.example.com", username="spool@example.com",
                  password="app-password-16", spool_root=tmp_path)
    values.update(overrides)
    return receiver.Settings(**values)


def run(tmp_path, fake, **overrides):
    settings = settings_for(tmp_path, **overrides)
    spool = receiver.Spool(tmp_path)
    try:
        state = receiver.State(spool.root)
        counts = receiver.process_once(settings, spool, state, client_factory=lambda s: fake,
                                       now=lambda: NOW)
    finally:
        spool.close()
    return counts, receiver.State(tmp_path)


def ready_packages(tmp_path):
    return sorted((tmp_path / "ready").iterdir(), key=lambda p: p.stat().st_mtime_ns)


def test_publishes_jpeg_attachment_as_importer_package(tmp_path):
    fake = FakeIMAP({7: make_message(attachments=[("PICT0001.JPG", JPEG, "jpeg")])})
    counts, state = run(tmp_path, fake)

    assert counts == {"messages": 1, "published": 1, "skipped": 0, "errors": 0}
    packages = ready_packages(tmp_path)
    assert len(packages) == 1 and receiver.PACKAGE_NAME.fullmatch(packages[0].name)
    assert (packages[0] / "photo.jpg").read_bytes() == JPEG
    metadata = json.loads((packages[0] / "metadata.json").read_text())
    assert metadata["version"] == 1
    assert metadata["original_filename"] == "PICT0001.JPG"
    assert metadata["byte_count"] == len(JPEG)
    assert metadata["received_at"] == "2026-09-16T08:30:00+00:00"  # Date header, in UTC
    assert metadata["source"] == "mail" and metadata["mail_uid"] == 7
    assert state.last_uid == 7 and state.uidvalidity == 42
    assert fake.seen == [7] and fake.logged_in and fake.logged_out
    assert not list((tmp_path / receiver.STAGING).iterdir())


def test_every_jpeg_in_one_message_becomes_its_own_package(tmp_path):
    fake = FakeIMAP({1: make_message(attachments=[("a.jpg", JPEG, "jpeg"), (None, JPEG, "jpeg")])})
    counts, _ = run(tmp_path, fake)
    assert counts["published"] == 2
    names = sorted(json.loads((p / "metadata.json").read_text())["original_filename"]
                   for p in ready_packages(tmp_path))
    assert names == ["MAIL1_2.jpg", "a.jpg"]


def test_messages_without_a_usable_jpeg_are_skipped_but_progress_advances(tmp_path):
    fake = FakeIMAP({
        1: make_message(attachments=[("notes.txt", b"hello", "plain")]),
        2: make_message(attachments=[("cut.jpg", JPEG[:-2], "jpeg")]),  # no EOI marker
        3: make_message(attachments=[("big.jpg", JPEG, "jpeg")]),
    })
    counts, state = run(tmp_path, fake, max_upload_bytes=len(JPEG) - 1)
    assert counts == {"messages": 3, "published": 0, "skipped": 3, "errors": 0}
    assert state.last_uid == 3
    assert not ready_packages(tmp_path)


def test_from_filter_rejects_other_senders(tmp_path):
    fake = FakeIMAP({
        1: make_message(attachments=[("x.jpg", JPEG, "jpeg")],
                        sender="Someone <spam@evil.example>"),
        2: make_message(attachments=[("y.jpg", JPEG, "jpeg")], sender="Camera <cam@example.com>"),
    })
    counts, state = run(tmp_path, fake, from_filter="cam@example.com")
    assert counts["published"] == 1 and counts["skipped"] == 1 and state.last_uid == 2


def test_missing_or_absurd_date_falls_back_to_poll_time(tmp_path):
    fake = FakeIMAP({
        1: make_message(attachments=[("a.jpg", JPEG, "jpeg")], date=None),
        2: make_message(attachments=[("b.jpg", JPEG, "jpeg")],
                        date="Mon, 1 Jan 2091 00:00:00 +0000"),
    })
    run(tmp_path, fake)
    stamps = {json.loads((p / "metadata.json").read_text())["received_at"]
              for p in ready_packages(tmp_path)}
    assert stamps == {"2026-09-16T12:00:00+00:00"}


def test_second_poll_only_sees_new_uids(tmp_path):
    fake = FakeIMAP({5: make_message(attachments=[("a.jpg", JPEG, "jpeg")])})
    run(tmp_path, fake)
    counts, state = run(tmp_path, fake)  # "6:*" answers with uid 5 again; must be ignored
    assert counts["messages"] == 0 and state.last_uid == 5
    fake.messages[6] = make_message(attachments=[("b.jpg", JPEG, "jpeg")])
    counts, state = run(tmp_path, fake)
    assert counts["published"] == 1 and state.last_uid == 6


def test_uidvalidity_change_starts_over(tmp_path):
    run(tmp_path, FakeIMAP({9: make_message(attachments=[("a.jpg", JPEG, "jpeg")])}))
    counts, state = run(tmp_path, FakeIMAP({1: make_message(attachments=[("b.jpg", JPEG, "jpeg")])},
                                           uidvalidity=43))
    assert counts["published"] == 1 and state.uidvalidity == 43 and state.last_uid == 1


def test_transient_fetch_failure_raises_and_keeps_state(tmp_path):
    fake = FakeIMAP({3: make_message(attachments=[("a.jpg", JPEG, "jpeg")])}, fail_fetch=True)
    with pytest.raises(imaplib.IMAP4.error):
        run(tmp_path, fake)
    assert receiver.State(tmp_path).last_uid == 0
    assert not ready_packages(tmp_path)
    assert fake.logged_out


def test_publish_failure_leaves_no_partial_package(tmp_path, monkeypatch):
    fake = FakeIMAP({3: make_message(attachments=[("a.jpg", JPEG, "jpeg")])})
    monkeypatch.setattr(receiver.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        run(tmp_path, fake)
    assert not ready_packages(tmp_path)
    assert not list((tmp_path / receiver.STAGING).iterdir())
    assert receiver.State(tmp_path).last_uid == 0


@pytest.mark.parametrize("raw, expected", [
    ("PICT0001.JPG", "PICT0001.JPG"),
    ("../../etc/passwd.jpg", "passwd.jpg"),
    ("C:\\cam\\IMG_20260916_101500.jpeg", "IMG_20260916_101500.jpeg"),
    ("photo", "photo.jpg"),
    ("bad\x00name.jpg", "badname.jpg"),
    ("weird name?.JPG", "weird_name.jpg"),
    ("", "MAIL7_1.jpg"),
    (None, "MAIL7_1.jpg"),
    ("...", "MAIL7_1.jpg"),
])
def test_sanitize_filename(raw, expected):
    assert receiver.sanitize_filename(raw, "MAIL7_1.jpg") == expected


def test_spool_is_exclusive_and_cleans_its_own_stale_staging(tmp_path):
    stale = tmp_path / receiver.STAGING / ("a" * 32)
    stale.mkdir(parents=True)
    (stale / "photo.jpg").write_bytes(JPEG)
    foreign = tmp_path / "staging" / ("b" * 32)  # the FTP receiver's directory: never touched
    foreign.mkdir(parents=True)
    first = receiver.Spool(tmp_path)
    try:
        assert not stale.exists() and foreign.exists()
        with pytest.raises(RuntimeError):
            receiver.Spool(tmp_path)
    finally:
        first.close()
    receiver.Spool(tmp_path).close()


def test_settings_from_env(monkeypatch, tmp_path):
    for key in ("MAIL_IMAP_HOST", "MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_SPOOL_ROOT"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError):
        receiver.Settings.from_env()
    monkeypatch.setenv("MAIL_IMAP_HOST", "imap.gmail.com")
    monkeypatch.setenv("MAIL_USERNAME", "cam@gmail.com")
    monkeypatch.setenv("MAIL_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setenv("MAIL_SPOOL_ROOT", str(tmp_path))
    monkeypatch.setenv("MAIL_FROM_FILTER", "  Cam@Gmail.com ")
    settings = receiver.Settings.from_env()
    assert settings.port == 993 and settings.folder == "INBOX" and settings.poll_seconds == 60
    assert settings.from_filter == "cam@gmail.com"
    monkeypatch.setenv("MAIL_POLL_SECONDS", "1")
    with pytest.raises(ValueError):
        receiver.Settings.from_env()


def test_watch_once_reports_failure_as_exit_code(tmp_path):
    settings = settings_for(tmp_path, host="127.0.0.1", port=1)  # nothing listens there
    spool = receiver.Spool(tmp_path)
    try:
        assert receiver.watch(settings, spool, receiver.State(tmp_path), once=True) == 1
    finally:
        spool.close()
