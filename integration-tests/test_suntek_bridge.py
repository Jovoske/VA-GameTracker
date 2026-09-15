"""Actual FTP -> completed package -> importer JPEG/time parser, without a database."""
import ftplib
import importlib.util
import io
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
spec = importlib.util.spec_from_file_location("bridge_receiver", ROOT / "ftp-receiver/receiver.py")
receiver = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = receiver
spec.loader.exec_module(receiver)
from app.ingestion.ftp_import import read_package  # noqa: E402


@pytest.mark.parametrize("transfer_type", ["I", "A"])
def test_camera_upload_preserves_pixels_exif_and_filename(tmp_path, transfer_type):
    exif = Image.Exif()
    exif[36867] = "2026:09:13 10:15:00"
    exif[36881] = "+02:00"
    # JPEG comment explicitly exercises CRLF preservation under TYPE A.
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "green").save(
        buffer, format="JPEG", exif=exif, comment=b"camera\r\nphoto\r\n"
    )
    payload = buffer.getvalue()
    server = receiver.make_server(receiver.Settings(
        username="camera-test", password="test-only-long-password", spool_root=tmp_path,
        port=0, passive_start=0, passive_end=0, min_free_bytes=0,
    ))
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"timeout": 0.01, "handle_exit": False}, daemon=True)
    thread.start()
    try:
        with ftplib.FTP() as ftp:
            ftp.connect("127.0.0.1", server.socket.getsockname()[1], timeout=5)
            ftp.login("camera-test", "test-only-long-password")
            ftp.cwd("/")
            ftp.voidcmd(f"TYPE {transfer_type}")
            with ftp.transfercmd("STOR PICT_20260913_1015.jpg") as channel:
                channel.sendall(payload)
            assert ftp.voidresp().startswith("226")
        packages = list((tmp_path / "ready").iterdir())
        assert len(packages) == 1
        photo = read_package(packages[0], "Europe/Madrid")
        assert photo.data == payload
        assert (photo.width, photo.height) == (16, 16)
        assert photo.original_filename == "PICT_20260913_1015.jpg"
        assert photo.captured_at == datetime(2026, 9, 13, 8, 15, tzinfo=UTC)
        assert photo.timestamp_source == "exif_with_offset"
    finally:
        server.close_all()
        thread.join(timeout=3)
        server.spool.close()
        assert not thread.is_alive()
