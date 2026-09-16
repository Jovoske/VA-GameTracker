"""Camera email -> mail receiver package -> importer JPEG/time parser, without a database."""
import email.policy
import importlib.util
import io
import sys
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
spec = importlib.util.spec_from_file_location(
    "bridge_mail_receiver", ROOT / "mail-receiver/receiver.py"
)
receiver = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = receiver
spec.loader.exec_module(receiver)
from app.ingestion.ftp_import import read_package  # noqa: E402


class OneMessageIMAP:
    error = Exception

    def __init__(self, raw):
        self.raw = raw

    def login(self, *_):
        pass

    def select(self, *_, **__):
        return "OK", [b"1"]

    def response(self, _):
        return "UIDVALIDITY", [b"7"]

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b"1"]
        if command == "FETCH":
            return "OK", [(b"1 (UID 1 BODY[] {0}", self.raw), b")"]
        return "OK", [b""]

    def logout(self):
        pass


def test_emailed_photo_keeps_pixels_exif_and_filename(tmp_path):
    exif = Image.Exif()
    exif[36867] = "2026:09:16 10:15:00"
    exif[36881] = "+02:00"
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "green").save(buffer, format="JPEG", exif=exif,
                                             comment=b"camera\r\nphoto\r\n")
    payload = buffer.getvalue()

    message = EmailMessage(policy=email.policy.default)
    message["From"] = "camera@example.com"
    message["To"] = "spool@example.com"
    message["Subject"] = "Suntek photo"
    message["Date"] = "Tue, 16 Sep 2026 10:16:30 +0200"
    message.set_content("see attachment")
    message.add_attachment(payload, maintype="image", subtype="jpeg",
                           filename="PICT_20260916_1015.jpg")

    settings = receiver.Settings(host="x", username="u", password="p", spool_root=tmp_path)
    spool = receiver.Spool(tmp_path)
    try:
        counts = receiver.process_once(settings, spool, receiver.State(tmp_path),
                                       client_factory=lambda s: OneMessageIMAP(message.as_bytes()))
    finally:
        spool.close()
    assert counts["published"] == 1

    packages = list((tmp_path / "ready").iterdir())
    assert len(packages) == 1
    photo = read_package(packages[0], "Europe/Madrid")
    assert photo.data == payload
    assert (photo.width, photo.height) == (16, 16)
    assert photo.original_filename == "PICT_20260916_1015.jpg"
    assert photo.received_at == datetime(2026, 9, 16, 8, 16, 30, tzinfo=UTC)
    assert photo.captured_at == datetime(2026, 9, 16, 8, 15, tzinfo=UTC)
    assert photo.timestamp_source == "exif_with_offset"
