"""Synthetic contract tests: no real UBox account or internet connection is used."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.ingestion import ubox
from app.ingestion.ubox import (
    UboxClient,
    UboxError,
    UboxPageLimitError,
    hash_password,
    parse_timestamp,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ubox"
SINCE = datetime(2026, 9, 16, tzinfo=UTC)
UNTIL = SINCE + timedelta(days=1)


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def client_for(handler):
    client = UboxClient("synthetic@example.test", "never-a-real-password")
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    client._token = "synthetic-token"
    return client


@pytest.mark.parametrize("password,expected", [
    ("password", "rgqoFHiJ6Aw9nYFzFVrPDHdIcrE,"),
    ("GameSense2026", "3zk0OTaRT7UlQmPh1BdcfKX9iBM,"),
    ("P@ssword!", "Detr52Q7Z-6ZKjsd0g7-JztK2VA,"),
    ("vector0", "jt_h-PG3e2Gc-txh626hqZixDAw,"),
])
def test_password_matches_node_crypto_vector(password, expected):
    # Node crypto.createHmac('sha1', ''), followed by the app's '+/=' substitutions.
    assert hash_password(password) == expected


@pytest.mark.parametrize("code,message", [
    (20002, "did not recognize this account"),
    (20005, "rejected the account or password"),
])
def test_login_errors_identify_known_vendor_failures_without_echoing_response(code, message):
    with client_for(lambda _: httpx.Response(200, json={
        "code": code, "msg": "private-email private-password",
    })) as client, pytest.raises(UboxError) as error:
        client.login()
    assert message in str(error.value)
    assert "private" not in str(error.value)


def test_pro_uses_signed_high_resolution_image_and_thumbnail_fallback():
    event = UboxClient._parse_event({
        "device_uid": "test-camera", "event_time": 1789570885, "id": "test-event",
        "img": "private-bucket/jpg/20260916_image.jpg",
        "cloud_hd_image_url": "https://images.example.test/high.jpg",
        "cloud_image_url": "https://images.example.test/preview.jpg",
    }, "test-camera")
    assert event.image_url == "https://images.example.test/high.jpg"
    assert event.fallback_image_url == "https://images.example.test/preview.jpg"


def test_redacted_live_pro_responses_parse_into_device_and_events():
    devices = fixture("live_device_list_redacted.json")
    events = fixture("live_cloud_list_redacted.json")

    def handler(request):
        return httpx.Response(200, json=devices if request.url.path.endswith("device_list")
                              else events)

    with client_for(handler) as client:
        device, = client.list_devices()
        assert device.model == "2592" and device.battery_pct == 85 and device.online
        assert device.has_cloud is True
        photos = client.list_events(device.uid, SINCE, UNTIL)
        assert len(photos) == 15
        assert all(p.image_url and p.device_uid == device.uid for p in photos)


def test_login_and_nested_device_fixture():
    def handler(request):
        assert request.method == "POST"
        body = json.loads(request.content)
        if request.url.path == "/api/v3/login":
            assert body["password"] == hash_password("never-a-real-password")
            assert body["app"] == "uboxpro"
            assert len(body["device_token"]) == 30
            return httpx.Response(200, json={"code": 0, "data": {
                "Token": "replacement-token", "token_valid_hours": 24,
            }})
        assert request.url.path == "/api/v2/user/device_list"
        assert request.headers["x-ubia-auth-usertoken"] == "replacement-token"
        assert body["token"] == "replacement-token"
        return httpx.Response(200, json=fixture("synthetic_device_list.json"))

    with client_for(handler) as client:
        client._token = None
        device, = client.list_devices()
        assert client.token_valid_hours == 24
    assert device.uid == "synthetic-camera"
    assert device.name == "Test woodland"
    assert device.battery_pct == 81
    assert device.charging is False
    assert device.signal == 1
    assert device.online is True
    assert device.has_cloud is True
    assert device.firmware is None
    assert device.time_diff_s == 7200
    assert device.last_active_at == datetime.fromtimestamp(1789556400, UTC)


def test_events_parse_images_timestamp_and_unique_identity():
    def handler(request):
        body = json.loads(request.content)
        assert body["device_uid"] == ["synthetic-camera"]
        assert body["timestamp"] == [int(SINCE.timestamp()), int(UNTIL.timestamp())]
        assert body["time_diff"] == 0
        assert body["time_revised"] is False
        return httpx.Response(200, json=fixture("synthetic_cloud_list.json"))

    with client_for(handler) as client:
        events = client.list_events("synthetic-camera", SINCE, UNTIL)
    assert len(events) == 3
    assert events[0].event_id == "synthetic-camera:41"
    assert events[0].captured_at == datetime.fromtimestamp(1789556400, UTC)
    assert "/full.jpg" in events[0].image_url
    assert "/thumb.jpg" in events[0].fallback_image_url
    assert events[1].event_id == "synthetic-camera:synthetic-event"
    assert events[1].image_url.endswith("thumb2.jpg")
    assert events[2].image_url == ""
    assert events[2].event_id == "synthetic-camera:1789556520"


@pytest.mark.parametrize("value", [None, "nonsense", "2026-09-16T12:00:00", True, 0,
                                        float("nan"), 1789556400000])
def test_untrusted_timestamps_are_rejected(value):
    assert parse_timestamp(value) is None


def test_aware_iso_and_epoch_have_same_instant():
    expected = datetime(2026, 9, 16, 10, tzinfo=UTC)
    assert parse_timestamp("2026-09-16T12:00:00+02:00") == expected
    assert parse_timestamp(expected.timestamp()) == expected


@pytest.mark.parametrize("expiry", [
    httpx.Response(401),
    httpx.Response(200, json={"code": 9876, "msg": "Token expired: secret"}),
])
def test_authentication_retries_once(expiry):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("login"):
            return httpx.Response(200, json={"code": 0, "data": {"Token": "new-token"}})
        return expiry

    with client_for(handler) as client, pytest.raises(UboxError, match="after retry") as error:
        client.list_devices()
    assert calls == ["/api/v2/user/device_list", "/api/v3/login", "/api/v2/user/device_list"]
    assert "secret" not in str(error.value)


def test_paging_without_server_count_stops_on_empty(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr(ubox.time, "sleep", sleeps.append)

    def handler(request):
        page = json.loads(request.content)["page"]
        calls.append(page)
        data = fixture("synthetic_cloud_list.json")
        del data["data"]["count"]
        if page == 2:
            data["data"]["list"] = []
        return httpx.Response(200, json=data)

    with client_for(handler) as client:
        assert len(client.list_events("synthetic-camera", SINCE, UNTIL)) == 3
    assert calls == [1, 2]
    assert sleeps == [0.5]


def test_empty_page_before_advertised_end_is_an_error(monkeypatch):
    monkeypatch.setattr(ubox.time, "sleep", lambda _: None)

    def handler(request):
        data = fixture("synthetic_cloud_list.json")
        data["data"]["count"] = {"pages": 9, "total": 25}
        if json.loads(request.content)["page"] == 2:
            data["data"]["list"] = []
        return httpx.Response(200, json=data)

    with client_for(handler) as client, pytest.raises(UboxError, match="incomplete"):
        client.list_events("synthetic-camera", SINCE, UNTIL)


def test_invalid_timestamp_fails_so_sync_does_not_advance_watermark():
    data = fixture("synthetic_cloud_list.json")
    data["data"]["list"][0]["event_time"] = "unknown"
    with client_for(lambda _: httpx.Response(200, json=data)) as client:
        with pytest.raises(UboxError, match="invalid timestamp"):
            client.list_events("synthetic-camera", SINCE, UNTIL)


def test_empty_first_page_with_zero_total_is_successful():
    data = {"code": 0, "data": {"count": {"pages": 1, "total": 0}, "list": []}}
    with client_for(lambda _: httpx.Response(200, json=data)) as client:
        assert client.list_events("synthetic-camera", SINCE, UNTIL) == []


def test_page_bound_raises_instead_of_returning_partial_results(monkeypatch):
    monkeypatch.setattr(ubox, "MAX_PAGES", 2)
    monkeypatch.setattr(ubox.time, "sleep", lambda _: None)

    def handler(request):
        data = fixture("synthetic_cloud_list.json")
        data["data"]["count"] = {"pages": 3, "total": 9}
        page = json.loads(request.content)["page"]
        for index, event in enumerate(data["data"]["list"]):
            event["id"] = 10 * page + index
        return httpx.Response(200, json=data)

    with client_for(handler) as client, pytest.raises(UboxPageLimitError, match="page limit"):
        client.list_events("synthetic-camera", SINCE, UNTIL)


def test_advertised_page_overflow_fails_immediately(monkeypatch):
    monkeypatch.setattr(ubox.time, "sleep", lambda _: pytest.fail("must split after first page"))
    data = fixture("synthetic_cloud_list.json")
    data["data"]["count"]["pages"] = ubox.MAX_PAGES + 1
    with client_for(lambda _: httpx.Response(200, json=data)) as client:
        with pytest.raises(UboxPageLimitError):
            client.list_events("synthetic-camera", SINCE, UNTIL)


def test_expired_token_is_replaced_before_successful_retry():
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(401)
        if request.url.path.endswith("login"):
            return httpx.Response(200, json={"code": 0, "data": {"Token": "new-token"}})
        assert request.headers["x-ubia-auth-usertoken"] == "new-token"
        assert json.loads(request.content)["token"] == "new-token"
        return httpx.Response(200, json=fixture("synthetic_device_list.json"))

    with client_for(handler) as client:
        assert len(client.list_devices()) == 1
    assert len(requests) == 3


def test_repeated_page_fails_instead_of_silently_losing_events(monkeypatch):
    monkeypatch.setattr(ubox.time, "sleep", lambda _: None)
    data = fixture("synthetic_cloud_list.json")
    data["data"]["count"]["pages"] = 9
    with client_for(lambda _: httpx.Response(200, json=data)) as client:
        with pytest.raises(UboxError, match="repeated"):
            client.list_events("synthetic-camera", SINCE, UNTIL)


def test_download_pins_public_ip_and_preserves_tls_host(monkeypatch):
    monkeypatch.setattr(ubox, "_public_address", lambda _: "93.184.216.34")

    def handler(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["Host"] == "images.example.test"
        assert request.extensions["sni_hostname"] == "images.example.test"
        assert "x-ubia-auth-usertoken" not in request.headers
        assert request.url.params["signature"] == "synthetic"
        return httpx.Response(200, content=b"test-image", headers={"Content-Type": "image/jpeg"})

    with client_for(handler) as client:
        content = client.download("https://images.example.test/a.jpg?signature=synthetic")
        assert content == b"test-image"
        assert client.last_download_metadata["file_bytes"] == 10


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_download_rejects_private_dns(monkeypatch, address):
    monkeypatch.setattr(ubox.socket, "getaddrinfo",
                        lambda *a, **kw: [(0, 0, 0, "", (address, 443))])
    with client_for(lambda _: pytest.fail("private hosts must not receive a request")) as client:
        with pytest.raises(UboxError, match="public HTTPS"):
            client.download("https://images.example.test/a.jpg")


@pytest.mark.parametrize("url", ["http://example.test/a", "https://user:pass@example.test/a",
                                     "https://example.test:444/a", "file:///etc/passwd"])
def test_download_rejects_unsafe_url(url):
    with client_for(lambda _: pytest.fail("unsafe URL must not receive a request")) as client:
        with pytest.raises(UboxError):
            client.download(url)


@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"Location": "http://localhost/secret"}),
    httpx.Response(200, headers={"Content-Length": str(ubox.MAX_IMAGE_BYTES + 1)}),
])
def test_download_rejects_redirects_and_oversized_content(monkeypatch, response):
    monkeypatch.setattr(ubox, "_public_address", lambda _: "93.184.216.34")
    with client_for(lambda _: response) as client, pytest.raises(UboxError):
        client.download("https://images.example.test/a.jpg")


def test_download_limits_stream_without_content_length(monkeypatch):
    monkeypatch.setattr(ubox, "_public_address", lambda _: "93.184.216.34")
    monkeypatch.setattr(ubox, "MAX_IMAGE_BYTES", 4)

    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            yield b"123"
            yield b"456"

    with client_for(lambda _: httpx.Response(200, stream=Chunks())) as client:
        with pytest.raises(UboxError, match="download limit"):
            client.download("https://images.example.test/a.jpg")


def test_vendor_errors_and_network_failures_never_expose_secrets():
    with client_for(lambda _: httpx.Response(200, json={
        "code": 999, "msg": "never-a-real-password synthetic-token",
    })) as client, pytest.raises(UboxError) as error:
        client.list_devices()
    assert "never-a-real-password" not in str(error.value)
    assert "synthetic-token" not in str(error.value)

    def broken(request):
        raise httpx.ConnectError("https://secret/token", request=request)

    with client_for(broken) as client, pytest.raises(UboxError) as error:
        client.list_devices()
    assert "secret" not in str(error.value)


def test_httpx_request_logs_do_not_expose_signed_urls(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(ubox, "_public_address", lambda _: "93.184.216.34")
    # Alembic's fileConfig disables existing loggers in the full test suite.
    monkeypatch.setattr(logging.getLogger("httpx"), "disabled", False)
    with client_for(lambda _: httpx.Response(200, content=b"photo")) as client:
        with caplog.at_level(logging.DEBUG, logger="httpx"):
            client.download("https://images.example.test/a.jpg?signature=secret-signature")
            logging.getLogger("httpx").info("Other clients still log normally")
    assert "secret-signature" not in caplog.text
    assert "Other clients still log normally" in caplog.text


def test_probe_fixture_scrubs_nested_secrets_and_consistently_hashes_ids():
    from app.ingestion.ubox_probe import scrub_fixture

    raw = {"device_uid": "private-device", "dynamic_info": {"device_uid": "private-device"},
           "device_pwd": "private-password", "card_info": {"icc_id": "01234567"},
           "device_name": "Private location", "img": "https://example.test?token=private-token",
           "cloud_image_url": "https://example.test/private-device", "account": "private-email",
           "event_time": 1789556400, "token_valid_hours": 24,
           "unknown_nested": {"text": "private-value"}}
    scrubbed = scrub_fixture(raw, b"test-salt")
    assert scrubbed["device_uid"] == scrubbed["dynamic_info"]["device_uid"]
    assert scrubbed["event_time"] == 1789556400
    assert scrubbed["token_valid_hours"] == 24
    assert "private" not in json.dumps(scrubbed)
