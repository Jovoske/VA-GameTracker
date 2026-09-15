"""Real loopback FTP exchanges, never binds a public address."""

import concurrent.futures
import ftplib
import importlib.util
import io
import json
import socket
import struct
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

MODULE_PATH = Path(__file__).parents[1] / "receiver.py"
SPEC = importlib.util.spec_from_file_location("camera_receiver", MODULE_PATH)
receiver = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = receiver
SPEC.loader.exec_module(receiver)


@pytest.fixture
def jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "green").save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def running(tmp_path):
    resources = []

    def start(**overrides):
        settings = receiver.Settings(
            username="trailcamera",
            password="test-only-password-long",
            spool_root=tmp_path / str(len(resources)),
            port=0,
            passive_start=overrides.pop("passive_start", 0),
            passive_end=overrides.pop("passive_end", 0),
            min_free_bytes=0,
            **overrides,
        )
        server = receiver.make_server(settings)
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"timeout": 0.01, "handle_exit": False}, daemon=True
        )
        thread.start()
        resources.append((server, thread))
        return server

    yield start
    for server, thread in resources:
        server.close_all()
        thread.join(timeout=3)
        server.spool.close()
        assert not thread.is_alive()


def client(server):
    ftp = ftplib.FTP()
    ftp.connect("127.0.0.1", server.socket.getsockname()[1], timeout=3)
    ftp.login("trailcamera", "test-only-password-long")
    return ftp


def ready(server):
    return list((server.spool.root / "ready").iterdir())


def wait_clean(server):
    deadline = time.monotonic() + 2
    while server.spool.active and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not server.spool.active
    assert not list((server.spool.root / "staging").iterdir())


def test_upload_is_published_before_226(running, jpeg):
    server = running()
    with client(server) as ftp:
        assert ftp.pwd() == "/"
        ftp.cwd("/")
        assert ftp.storbinary("STOR /PICT.JPG", io.BytesIO(jpeg)).startswith("226")
        entries = ready(server)
        assert len(entries) == 1
        assert (entries[0] / "photo.jpg").read_bytes() == jpeg
        data = json.loads((entries[0] / "metadata.json").read_text())
        assert data["version"] == 1
        assert data["original_filename"] == "PICT.JPG"
        assert data["byte_count"] == len(jpeg)
        assert datetime.fromisoformat(data["received_at"]).utcoffset().total_seconds() == 0
    wait_clean(server)


def test_same_filename_concurrent_uploads_never_overwrite(running, jpeg):
    server = running()
    payloads = [jpeg, jpeg[:-2] + b"different-payload" + jpeg[-2:]]
    barrier = threading.Barrier(2)

    def send(payload):
        with client(server) as ftp:
            barrier.wait(timeout=2)
            ftp.storbinary("STOR PICT.JPG", io.BytesIO(payload), blocksize=64)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(send, payloads))
    entries = ready(server)
    assert len(entries) == 2
    assert {(entry / "photo.jpg").read_bytes() for entry in entries} == set(payloads)
    wait_clean(server)


@pytest.mark.parametrize("queued", [False, True])
def test_camera_ascii_mode_preserves_jpeg_bytes(running, jpeg, queued):
    server = running()
    # A valid JPEG comment segment containing CRLF must remain byte-for-byte.
    comment = b"camera\r\ncomment\r\n"
    payload = jpeg[:2] + b"\xff\xfe" + struct.pack(">H", len(comment) + 2) + comment + jpeg[2:]
    with client(server) as ftp:
        ftp.voidcmd("TYPE A")
        if queued:
            host, port = ftp.makepasv()
            assert ftp.sendcmd("STOR PICT.JPG").startswith("150")
            data = socket.create_connection((host, port), timeout=3)
        else:
            data = ftp.transfercmd("STOR PICT.JPG")
        data.sendall(payload)
        data.close()
        assert ftp.voidresp().startswith("226")
    assert (ready(server)[0] / "photo.jpg").read_bytes() == payload
    wait_clean(server)


@pytest.mark.parametrize(
    "command",
    [
        "STOR ../PICT.JPG",
        "STOR sub/PICT.JPG",
        "STOR /ready/PICT.JPG",
        "STOR PICT.bin",
        "STOR firmware.rar",
        "STOR photo.jpg:stream",
        "STOR \\PICT.JPG",
        "RETR PICT.JPG",
        "DELE PICT.JPG",
        "MKD sub",
        "RMD sub",
        "RNFR PICT.JPG",
        "APPE PICT.JPG",
        "REST 10",
        "STOU PICT.JPG",
        "LIST",
        "CWD ..",
        "CWD ready",
        "PORT 127,0,0,1,1,1",
        "EPRT |1|127.0.0.1|22|",
    ],
)
def test_disallowed_commands_and_paths(running, command):
    server = running()
    with client(server) as ftp:
        ftp.voidcmd("TYPE I")
        with pytest.raises(ftplib.error_perm):
            ftp.sendcmd(command)
    assert not ready(server)
    wait_clean(server)


def test_wrong_password_and_anonymous_rejected(running):
    server = running()
    for username, password in [
        ("trailcamera", "incorrect"),
        ("anonymous", "email@example.invalid"),
    ]:
        with ftplib.FTP() as ftp:
            ftp.connect("127.0.0.1", server.socket.getsockname()[1], timeout=6)
            with pytest.raises(ftplib.error_perm, match="530"):
                ftp.login(username, password)


def test_interrupted_socket_upload_is_not_published(running, jpeg):
    server = running()
    with client(server) as ftp:
        ftp.voidcmd("TYPE I")
        data = ftp.transfercmd("STOR PICT.JPG")
        data.sendall(jpeg[:100])
        linger = struct.pack("hh" if sys.platform == "win32" else "ii", 1, 0)
        data.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
        data.close()
        with pytest.raises(ftplib.error_temp):
            ftp.voidresp()
    assert not ready(server)
    wait_clean(server)


def test_oversize_never_publishes_and_cleans_partial(running, jpeg):
    server = running(max_upload_bytes=128)
    with client(server) as ftp:
        with pytest.raises((ftplib.error_temp, OSError)):
            ftp.storbinary("STOR PICT.JPG", io.BytesIO(jpeg))
    assert not ready(server)
    wait_clean(server)


def test_invalid_content_and_truncated_clean_fin_rejected(running, jpeg):
    server = running()
    for data in [b"not an image", jpeg[:-2], b""]:
        with client(server) as ftp:
            with pytest.raises((ftplib.error_temp, OSError)):
                ftp.storbinary("STOR PICT.JPG", io.BytesIO(data))
    assert not ready(server)
    wait_clean(server)


def test_publish_failure_does_not_return_success(running, jpeg, monkeypatch):
    server = running()

    def fail_replace(*args):
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(receiver.os, "replace", fail_replace)
    with client(server) as ftp:
        with pytest.raises(ftplib.error_temp, match="451"):
            ftp.storbinary("STOR PICT.JPG", io.BytesIO(jpeg))
    assert not ready(server)
    wait_clean(server)


def test_file_fsync_failure_does_not_return_success(running, jpeg, monkeypatch):
    server = running()

    def fail_sync(*args):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(receiver.os, "fsync", fail_sync)
    with client(server) as ftp:
        with pytest.raises(ftplib.error_temp, match="451"):
            ftp.storbinary("STOR PICT.JPG", io.BytesIO(jpeg))
    assert not ready(server)
    wait_clean(server)


def test_post_rename_sync_failure_returns_error_but_preserves_complete_item(
    running, jpeg, monkeypatch
):
    server = running()

    def fail_ready_sync(path):
        if path.name == "ready":
            raise OSError("simulated directory sync failure")

    monkeypatch.setattr(receiver, "sync_directory", fail_ready_sync)
    with client(server) as ftp:
        with pytest.raises(ftplib.error_temp, match="451"):
            ftp.storbinary("STOR PICT.JPG", io.BytesIO(jpeg))
    assert len(ready(server)) == 1
    assert (ready(server)[0] / "photo.jpg").read_bytes() == jpeg
    wait_clean(server)


def test_queue_budget_rejects_next_upload(running, jpeg):
    server = running(max_queue_files=1)
    with client(server) as ftp:
        ftp.storbinary("STOR PICT.JPG", io.BytesIO(jpeg))
        with pytest.raises(ftplib.error_temp, match="452"):
            ftp.storbinary("STOR PICT.JPG", io.BytesIO(jpeg))
    assert len(ready(server)) == 1
    wait_clean(server)


def test_second_receiver_cannot_share_spool(running):
    server = running()
    with pytest.raises(RuntimeError, match="already owns"):
        receiver.Spool(server.spool.settings)


def test_pending_stor_abort_cleans_and_allows_retry(running, jpeg):
    server = running()
    with client(server) as ftp:
        ftp.voidcmd("TYPE I")
        ftp.sendcmd("PASV")
        assert ftp.sendcmd("STOR PICT.JPG").startswith("150")
        assert ftp.sendcmd("ABOR").startswith("225")
        wait_clean(server)
        ftp.storbinary("STOR PICT.JPG", io.BytesIO(jpeg))
    assert len(ready(server)) == 1


def test_pending_stor_disconnect_cleans_partial(running):
    server = running()
    ftp = client(server)
    ftp.sendcmd("PASV")
    assert ftp.sendcmd("STOR PICT.JPG").startswith("150")
    ftp.close()
    wait_clean(server)


def test_passive_range_exhaustion_does_not_open_random_port(running):
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        server = running(passive_start=port, passive_end=port)
        with client(server) as ftp:
            with pytest.raises(ftplib.error_temp, match="425"):
                ftp.sendcmd("PASV")
            assert ftp.sendcmd("NOOP").startswith("200")
