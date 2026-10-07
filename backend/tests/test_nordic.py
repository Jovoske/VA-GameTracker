"""Synthetic tests of the contract observed in Nordic's public web-app bundle.

These verify request shapes and failure behavior, not a live vendor account.
"""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.ingestion import nordic
from app.ingestion.nordic import NordicAuthError, NordicClient, NordicError

SINCE = datetime(2026, 10, 5, tzinfo=UTC)
UNTIL = SINCE + timedelta(days=1)


def client_for(handler, public_handler=None):
    client = NordicClient("synthetic@example.test", "synthetic-password")
    client._client.close()
    client._public_client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    client._public_client = httpx.Client(
        transport=httpx.MockTransport(public_handler or handler), trust_env=False,
    )
    return client


@pytest.fixture(autouse=True)
def configured_client(monkeypatch):
    monkeypatch.setattr(nordic.settings, "nordic_client_secret", "synthetic-client-setting")


def authorize(request):
    if request.url.path == "/oauth/authorize":
        return httpx.Response(200, json={"expires_at": "2030-01-01T00:00:00Z"}, headers={
            "set-cookie": "session=synthetic-cookie; Path=/; Secure; HttpOnly",
        })
    if request.url.path == "/api/user/me":
        return httpx.Response(200, json={"roles": ["ROLE_USER"]})
    return None


def photo(identifier="one", *, date=None, url="https://images.example.test/photo.jpg"):
    return {"idString": identifier, "shortCode": "short-camera", "url": url,
            "thumbnailUrl": "https://images.example.test/thumb.jpg", "tags": [],
            "dateEpoch": SINCE.timestamp() + 3600 if date is None else date}


def test_login_shape_cookie_session_roundtrip_and_expiry():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        assert request.url.host == "api.nordicgamekeeper.com"
        assert "authorization" not in request.headers
        assert request.headers["x-app-id"]
        if request.url.path == "/oauth/authorize":
            assert json.loads(request.content) == {
                "username": "synthetic@example.test", "password": "synthetic-password",
                "client_id": "webApp", "client_secret": "synthetic-client-setting",
                "grant_type": "password", "rememberMe": True,
            }
        else:
            assert request.headers["cookie"] == "session=synthetic-cookie"
        return authorize(request) or httpx.Response(200, json={"content": []})

    with client_for(handler) as client:
        token = client.login()
        assert client.token_valid_hours > 0
        assert "synthetic-password" not in token
        assert "synthetic-client-setting" not in token
    with client_for(handler) as restored:
        restored.use_token(token)
        assert restored.list_cameras() == []
    assert calls == ["/oauth/authorize", "/api/user/me", "/api/camera/mine"]


def test_cameras_use_observed_metadata_fields_and_preserve_zero():
    def handler(request):
        return authorize(request) or httpx.Response(200, json={"content": [{
            "id": "camera-id", "shortCode": "short-camera", "displayName": "Test woodland",
            "latitude": 60.5, "longitude": 24.5,
            "status": {"batteryPercentage": 0, "signalPercentage": 80,
                       "cameraModel": "APEX PRO", "created": SINCE.timestamp()},
        }]})

    with client_for(handler) as client:
        camera, = client.list_cameras()
    assert camera.nordic_id == "camera-id" and camera.name == "Test woodland"
    assert camera.battery_pct == 0 and camera.signal_pct == 80
    assert camera.model == "APEX PRO" and camera.last_report_at == SINCE
    assert (camera.lat, camera.lng) == (60.5, 24.5)


def test_media_paging_filters_dates_and_skips_videos():
    pages = []

    def handler(request):
        auth = authorize(request)
        if auth:
            return auth
        assert request.url.path == "/api/camera/camera-id/media"
        assert request.url.params["size"] == "36"
        assert set(request.url.params) == {"page", "size"}
        page = int(request.url.params["page"])
        pages.append(page)
        if page == 0:
            rows = [photo("future", date=UNTIL.timestamp() + 1),
                    photo("video", url="https://images.example.test/clip.mp4")]
        else:
            rows = [photo(), photo("old", date=SINCE.timestamp() - 1)]
        return httpx.Response(200, json={"content": rows, "last": page == 1})

    with client_for(handler) as client:
        image, = client.list_photos("camera-id", SINCE, UNTIL)
    assert pages == [0, 1]
    assert image.photo_id == "one" and image.camera_id == "camera-id"
    assert image.captured_at == SINCE + timedelta(hours=1)
    assert image.url.endswith("/photo.jpg")


def test_newest_first_scan_stops_before_since_without_reading_entire_history():
    pages = []

    def handler(request):
        auth = authorize(request)
        if auth:
            return auth
        pages.append(int(request.url.params["page"]))
        assert len(pages) <= 2
        rows = [photo(), photo("older", date=SINCE.timestamp() - 1)] if len(pages) == 1 else [
            photo("much-older", date=SINCE.timestamp() - 2),
        ]
        return httpx.Response(200, json={
            "content": rows, "last": False,
        })

    with client_for(handler) as client:
        assert len(client.list_photos("camera-id", SINCE, UNTIL)) == 1
    assert pages == [0, 1]


def test_equal_since_timestamp_spanning_pages_is_not_skipped():
    def handler(request):
        auth = authorize(request)
        if auth:
            return auth
        page = int(request.url.params["page"])
        return httpx.Response(200, json={
            "content": [photo(str(page), date=SINCE.timestamp())], "last": page == 2,
        })

    with client_for(handler) as client:
        images = client.list_photos("camera-id", SINCE, UNTIL)
    assert [image.photo_id for image in images] == ["0", "1", "2"]


def test_media_ordering_violation_fails_instead_of_advancing_sync():
    payload = {"content": [photo(), photo("newer", date=UNTIL.timestamp())], "last": True}
    with client_for(lambda r: authorize(r) or httpx.Response(200, json=payload)) as client:
        with pytest.raises(NordicError, match="ordering"):
            client.list_photos("camera-id", SINCE, UNTIL)


@pytest.mark.parametrize("payload", [
    {}, {"content": []}, {"content": [], "last": False},
    {"content": [photo(date="untrusted")], "last": True},
    {"content": [photo(date=1791158400000)], "last": True},
    {"content": [{"url": "https://images.example.test/photo.jpg"}], "last": True},
])
def test_unknown_media_contract_fails_without_returning_partial_results(payload):
    with client_for(lambda r: authorize(r) or httpx.Response(200, json=payload)) as client:
        with pytest.raises(NordicError):
            client.list_photos("camera-id", SINCE, UNTIL)


def test_page_bound_fails_without_partial_results(monkeypatch):
    monkeypatch.setattr(nordic, "MAX_PAGES", 2)

    def handler(request):
        return authorize(request) or httpx.Response(200, json={
            "content": [photo(request.url.params["page"])], "last": False,
        })

    with client_for(handler) as client, pytest.raises(NordicError, match="page limit"):
        client.list_photos("camera-id", SINCE, UNTIL)


def test_repeated_page_is_not_mistaken_for_sync_completion():
    payload = {"content": [photo()], "last": False}
    with client_for(lambda r: authorize(r) or httpx.Response(200, json=payload)) as client:
        with pytest.raises(NordicError, match="repeated"):
            client.list_photos("camera-id", SINCE, UNTIL)


def test_authentication_retry_is_bounded_and_errors_do_not_echo_vendor_secrets():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return authorize(request) or httpx.Response(403, text="private email and password")

    with client_for(handler) as client, pytest.raises(NordicAuthError) as error:
        client.list_cameras()
    assert calls.count("/oauth/authorize") == 2
    assert "private" not in str(error.value)


def test_login_requires_cookies_and_successful_me_check():
    with client_for(lambda _: httpx.Response(200, json={"expires_at": 1900000000})) as client:
        with pytest.raises(NordicAuthError, match="cookie"):
            client.login()


def test_runtime_public_configuration_is_bounded_and_not_executed(monkeypatch):
    monkeypatch.setattr(nordic.settings, "nordic_client_secret", "")
    paths = []

    def public(request):
        paths.append(request.url.path)
        assert request.url.host == "account.nordicgamekeeper.com"
        assert "cookie" not in request.headers and "authorization" not in request.headers
        if request.url.path == "/":
            return httpx.Response(200, text='<script src="/assets/index-synthetic.js"></script>')
        return httpx.Response(200, text=(
            'throw new Error("must not execute");'
            'client_id:"webApp",client_secret:"synthetic-client-setting",grant_type:"password"'
        ))

    with client_for(authorize, public) as client:
        assert client.login()
    assert paths == ["/", "/assets/index-synthetic.js"]


@pytest.mark.parametrize("html", [
    '<script src="https://other.example/index.js"></script>',
    '<script src="//other.example/assets/index-ab.js"></script>',
    '<script src="/assets/index-a.js"></script><script src="/assets/index-b.js"></script>',
])
def test_public_configuration_rejects_external_or_ambiguous_bundles(html):
    with pytest.raises(NordicError):
        nordic._web_bundle_path(html)


def test_download_pins_public_address_preserves_sni_and_never_sends_session(monkeypatch):
    monkeypatch.setattr(nordic, "_public_address", lambda _: "93.184.216.34")

    def public(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "images.example.test"
        assert request.extensions["sni_hostname"] == "images.example.test"
        assert "cookie" not in request.headers
        assert "authorization" not in request.headers
        assert "x-app-id" not in request.headers
        return httpx.Response(200, content=b"synthetic image bytes")

    with client_for(authorize, public) as client:
        client.login()
        assert client.download("https://images.example.test/image.jpg") == b"synthetic image bytes"


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "::1", "169.254.169.254"])
def test_media_dns_rejects_private_addresses(monkeypatch, address):
    monkeypatch.setattr(nordic.socket, "getaddrinfo", lambda *a, **kw: [
        (None, None, None, None, (address, 443)),
    ])
    with pytest.raises(NordicError, match="public address"):
        nordic._public_address("images.example.test")


@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"location": "https://127.0.0.1/internal"}),
    httpx.Response(200, headers={"content-length": str(nordic.MAX_IMAGE_BYTES + 1)}),
])
def test_download_rejects_redirects_and_oversize(monkeypatch, response):
    monkeypatch.setattr(nordic, "_public_address", lambda _: "93.184.216.34")
    with client_for(authorize, lambda _: response) as client, pytest.raises(NordicError):
        client.download("https://images.example.test/image.jpg")


def test_saved_session_cannot_scope_cookies_to_another_host():
    with client_for(authorize) as client:
        token = json.loads(client.login())
        token["cookies"][0]["domain"] = ".example.test"
        with pytest.raises(NordicAuthError):
            client.use_token(json.dumps(token))


def test_network_failure_is_temporary_and_does_not_echo_request():
    def handler(request):
        raise httpx.ConnectError("private details", request=request)

    with client_for(handler) as client, pytest.raises(NordicError) as error:
        client.login()
    assert error.value.status == 503
    assert "private" not in str(error.value)
