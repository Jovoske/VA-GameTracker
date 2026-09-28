"""Read-only UBIA cloud client; protocol based on JEMcats/ubox_camera_api.

The community proxy exposes device_list as GET, but its upstream call is POST
with x-ubia-auth-usertoken. Real-account snapshot access and timestamp semantics
still require the operator probe in ``ubox_probe``; fixtures are synthetic.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
import math
import socket
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.logging import get_logger
from app.i18n import stored

log = get_logger(__name__)
UBOX_API = "https://portal.ubianet.com"
MAX_PAGES = 100
MAX_IMAGE_BYTES = 20 * 1024 * 1024
_quiet_request: ContextVar[bool] = ContextVar("ubox_quiet_request", default=False)


class _CredentialSafeHttpLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # httpx's INFO request log includes signed image URLs. Suppress only this
        # client's active requests in the current thread/context, not other clients.
        return not _quiet_request.get()


for _logger_name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
    logging.getLogger(_logger_name).addFilter(_CredentialSafeHttpLogs())


@contextmanager
def _private_request():
    state = _quiet_request.set(True)
    try:
        yield
    finally:
        _quiet_request.reset(state)


def device_token(email: str) -> str:
    """The same 30-character device token for a login on every sign-in.

    A fresh random one each fetch (every 15 minutes) looked like a new phone signing
    in every time, which invites UBox to throttle or lock the login.
    """
    digest = hashlib.sha256(f"gamesense-ubox:{email.strip().lower()}".encode()).digest()
    return base64.b32encode(digest).decode().lower()[:30]


# A 429 or 5xx is waited out once when UBox says how long (Retry-After), up to this
# long; any longer and the fetch gives up until its next run.
RETRY_AFTER_MAX_S = 30


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds to wait before one more try, when UBox is busy and says how long."""
    if response.status_code != 429 and response.status_code < 500:
        return None
    try:
        seconds = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return seconds if 0 <= seconds <= RETRY_AFTER_MAX_S else None


class UboxError(Exception):
    """An intentionally credential-free error, safe to show in account/sync UI."""


class UboxPageLimitError(UboxError):
    """The caller should split the requested time interval and retry each half."""


@dataclass
class UboxDevice:
    uid: str
    name: str
    model: str | None = None
    battery_pct: int | None = None
    charging: bool | None = None
    signal: int | None = None  # Vendor scale is unknown; do not label it percent.
    online: bool | None = None
    firmware: str | None = None
    time_diff_s: int | None = None
    last_active_at: datetime | None = None
    has_cloud: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class UboxEvent:
    event_id: str
    device_uid: str
    captured_at: datetime
    image_url: str = field(repr=False)
    type: str | int | None = None
    ai_result: Any = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    fallback_image_url: str = field(default="", repr=False)


def hash_password(password: str) -> str:
    digest = hmac.new(b"", password.encode("utf-8"), hashlib.sha1).digest()
    # LoginViewModel.loginV3 / HttpClient.get_replace_str also replace '+' and '/'.
    # The older community script omitted those two substitutions.
    return base64.b64encode(digest).decode("ascii").translate(str.maketrans("+/=", "-_,"))


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
        return int(number) if math.isfinite(number) and number.is_integer() else None
    except (TypeError, ValueError, OverflowError):
        return None


def _boolean(value: Any) -> bool | None:
    if value in (True, 1, "1", "true"):
        return True
    if value in (False, 0, "0", "false"):
        return False
    return None


def parse_timestamp(value: Any) -> datetime | None:
    """Accept Unix seconds or explicitly zoned ISO times, never invent an offset.

    In particular, time_diff is not subtracted from a Unix timestamp. Cloud-list
    requests disable time revision and request UTC. This is an explicit protocol
    assumption to compare against three app events during the operator probe.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, str | int | float):
            try:
                seconds = float(value)
            except ValueError:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                return parsed.astimezone(UTC) if parsed.utcoffset() is not None else None
            if not math.isfinite(seconds) or seconds <= 0:
                return None
            # Community records specify Unix seconds, not milliseconds.
            return datetime.fromtimestamp(seconds, UTC)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _https_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 8192:
        return ""
    try:
        url = httpx.URL(value)
        if url.scheme != "https" or not url.host or url.userinfo or url.port not in (None, 443):
            return ""
        return str(url)
    except (httpx.InvalidURL, ValueError):
        return ""


def _public_address(host: str) -> str:
    """Resolve once, reject private answers, and return the address to connect to."""
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips = [ipaddress.ip_address(entry[4][0]) for entry in addresses]
    except (OSError, ValueError):
        raise UboxError(stored("ubox.err.host_unresolved")) from None
    if not ips or any(not address.is_global or address.is_multicast for address in ips):
        raise UboxError(stored("ubox.err.host_public"))
    return str(ips[0])


class UboxClient:
    def __init__(
        self, email: str, password: str, timeout: float = 20.0, *, app: str = "uboxpro",
    ) -> None:
        if app not in ("ubox", "uboxpro"):
            raise ValueError("Unsupported UBox app identifier")
        self._email = email
        self._password = password
        self._app = app
        self._token: str | None = None
        self.token_valid_hours: int | None = None
        self.last_download_metadata: dict[str, Any] = {}
        # No environment proxies, redirects, or API authentication on image GETs.
        self._client = httpx.Client(
            timeout=timeout, follow_redirects=False, trust_env=False,
            headers={"User-Agent": "GameSense-UBox/1.0", "Accept": "application/json"},
        )

    def __enter__(self) -> UboxClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @property
    def token(self) -> str | None:
        """The sign-in in use, kept by the fetch for next time (logins.keep_session)."""
        return self._token

    def use_token(self, token: str) -> None:
        """Carry on with a sign-in kept from an earlier fetch instead of signing in;
        UBox saying it has expired signs in afresh (_request)."""
        self._token = token

    def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        response = self._client.post(url, **kwargs)
        wait = _retry_after(response)
        if wait is not None:  # busy: wait as long as asked, once, then try again
            log.info("ubox.retry_after", status=response.status_code, seconds=wait)
            time.sleep(wait)
            response = self._client.post(url, **kwargs)
        return response

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            raise UboxError(stored("ubox.err.bad_json")) from None
        if not isinstance(payload, dict):
            raise UboxError(stored("ubox.err.unexpected"))
        return payload

    @staticmethod
    def _data(payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("code") not in (0, "0"):
            # Vendor text can echo credentials; never include it in errors/logs.
            if str(payload.get("code")) == "20002":
                raise UboxError(stored("ubox.err.unknown_account"))
            if str(payload.get("code")) == "20005":
                raise UboxError(stored("ubox.err.rejected_password"))
            raise UboxError(stored("ubox.err.rejected_request"))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise UboxError(stored("ubox.err.no_data"))
        return data

    def login(self) -> str:
        if not self._email or not self._password:
            raise UboxError(stored("ubox.err.need_login"))
        self._token = None
        try:
            with _private_request():
                response = self._post(f"{UBOX_API}/api/v3/login", json={
                    "account": self._email,
                    "password": hash_password(self._password),
                "lang": "en", "app": self._app, "device_type": 2,
                    "device_token": device_token(self._email),
                })
        except httpx.HTTPError:
            raise UboxError(stored("ubox.err.unreachable_login")) from None
        if response.status_code != 200:
            raise UboxError(stored("ubox.err.login_http", status=response.status_code))
        data = self._data(self._payload(response))
        token = data.get("Token")
        if not isinstance(token, str) or not token:
            raise UboxError(stored("ubox.err.no_token"))
        self._token = token
        self.token_valid_hours = _integer(data.get("token_valid_hours"))
        return token

    @staticmethod
    def _expired(payload: dict[str, Any]) -> bool:
        # No verified vendor numeric expiry code is available in the reference.
        # Recognize explicit token messages/codes, without logging vendor strings.
        code = str(payload.get("code", "")).lower()
        message = str(payload.get("msg", "")).lower()
        return code in ("401", "token_expired", "invalid_token") or (
            "token" in message and any(word in message for word in ("expired", "invalid"))
        )

    def _request(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(2):
            if self._token is None:
                self.login()
            try:
                with _private_request():
                    response = self._post(
                        f"{UBOX_API}{path}", json={**(body or {}), "token": self._token},
                        headers={"x-ubia-auth-usertoken": self._token or ""},
                    )
            except httpx.HTTPError:
                raise UboxError(stored("ubox.err.unreachable")) from None
            payload = self._payload(response) if response.status_code == 200 else {}
            if response.status_code == 401 or self._expired(payload):
                self._token = None
                if attempt == 0:
                    log.info("ubox.reauth")
                    continue
                raise UboxError(stored("ubox.err.auth_expired"))
            if response.status_code != 200:
                raise UboxError(stored("ubox.err.request_http", status=response.status_code))
            return self._data(payload)
        raise UboxError(stored("ubox.err.auth_failed"))

    def list_devices(self) -> list[UboxDevice]:
        data = self._request("/api/v2/user/device_list")
        if not isinstance(data.get("items"), list) or not isinstance(data.get("infos"), list):
            raise UboxError(stored("ubox.err.no_devices"))
        merged: dict[str, dict[str, Any]] = {}
        for item in [*data["items"], *data["infos"]]:
            if not isinstance(item, dict) or not item.get("device_uid"):
                raise UboxError(stored("ubox.err.device_no_id"))
            uid = str(item["device_uid"])
            merged[uid] = {**merged.get(uid, {}), **item}
        return [self._parse_device(item) for item in merged.values()]

    @staticmethod
    def _parse_device(item: dict[str, Any]) -> UboxDevice:
        dynamic = item.get("dynamic_info")
        dynamic = dynamic if isinstance(dynamic, dict) else {}
        values = {**item, **dynamic}
        battery = _integer(values.get("battery"))
        online = values.get("online_state")
        return UboxDevice(
            uid=str(item["device_uid"]), name=str(item.get("device_name") or "UBox camera"),
            model=str(item["model_num"]) if item.get("model_num") is not None else None,
            battery_pct=battery if battery is not None and 0 <= battery <= 100 else None,
            charging=_boolean(values.get("is_battery_charging")),
            signal=_integer(values.get("signal")),
            online=str(online) == "2" if online is not None else None,
            firmware=values.get("firmware_ver") if isinstance(values.get("firmware_ver"), str)
            else None,
            time_diff_s=_integer(item.get("time_diff")),
            last_active_at=parse_timestamp(values.get("latest_active_utc")),
            has_cloud=_boolean(item.get("has_cloud_storage")), raw=item,
        )

    @staticmethod
    def _parse_event(item: dict[str, Any], device_uid: str) -> UboxEvent | None:
        if str(item.get("device_uid") or device_uid) != device_uid:
            return None
        captured_at = parse_timestamp(item.get("event_time"))
        if captured_at is None:
            return None
        identifier = item.get("id")
        if identifier in (None, ""):
            identifier = item.get("uuid") or item["event_time"]
        # Pro's img was not a usable HTTPS URL in the live probe. Its signed
        # cloud_hd_image_url was; older responses may also have full img URLs.
        full = _https_url(item.get("cloud_hd_image_url")) or _https_url(item.get("img"))
        thumbnail = _https_url(item.get("cloud_image_url"))
        return UboxEvent(
            event_id=f"{device_uid}:{identifier}", device_uid=device_uid,
            captured_at=captured_at, image_url=full or thumbnail,
            type=item.get("type"), ai_result=item.get("ai_result"), raw=item,
            fallback_image_url=thumbnail if full and thumbnail != full else "",
        )

    def _cloud_page(
        self, device_uid: str, since: datetime, until: datetime, page: int, page_size: int,
    ) -> dict[str, Any]:
        return self._request("/api/user/cloud_list", {
            "device_uid": [device_uid],
            "timestamp": [int(since.timestamp()), int(until.timestamp())],
            "page": page, "page_num": page_size,
            "time_diff": 0, "summer_time": 0, "time_revised": False,
        })

    def list_events(
        self, device_uid: str, since: datetime, until: datetime, page_size: int = 100,
    ) -> list[UboxEvent]:
        if since.utcoffset() is None or until.utcoffset() is None:
            raise UboxError(stored("ubox.err.naive_dates"))
        if since >= until or not 1 <= page_size <= 100:
            raise UboxError(stored("ubox.err.bad_range"))
        events: dict[str, UboxEvent] = {}
        seen_pages: set[str] = set()
        expected_pages = 0
        expected_total = 0
        received = 0
        for page in range(1, MAX_PAGES + 1):
            if page > 1:
                time.sleep(0.5)
            data = self._cloud_page(device_uid, since, until, page, page_size)
            items = data.get("list")
            if not isinstance(items, list):
                raise UboxError(stored("ubox.err.no_events"))
            count = data.get("count")
            count = count if isinstance(count, dict) else {}
            pages = _integer(count.get("pages"))
            expected_pages = max(expected_pages, pages or 0)
            expected_total = max(expected_total, _integer(count.get("total")) or 0)
            if expected_pages > MAX_PAGES:
                raise UboxPageLimitError(stored("ubox.err.page_limit"))
            if not items:
                empty_result = page == 1 and expected_pages <= 1 and expected_total == 0
                if not empty_result and (page <= expected_pages or received < expected_total):
                    raise UboxError(stored("ubox.err.incomplete_page"))
                break
            if any(not isinstance(item, dict) for item in items):
                raise UboxError(stored("ubox.err.bad_event"))
            # IDs/timestamps are stable when expiring signed image URLs change.
            signature = repr([(i.get("id"), i.get("uuid"), i.get("event_time")) for i in items])
            if signature in seen_pages:
                raise UboxError(stored("ubox.err.repeated_page"))
            seen_pages.add(signature)
            received += len(items)
            for item in items:
                event = self._parse_event(item, device_uid)
                if event is None:
                    raise UboxError(stored("ubox.err.bad_event_fields"))
                elif since <= event.captured_at <= until:
                    events[event.event_id] = event
            if pages is not None and page >= pages:
                if received < expected_total:
                    raise UboxError(stored("ubox.err.fewer_events"))
                break
        else:
            raise UboxPageLimitError(stored("ubox.err.page_limit"))
        return sorted(events.values(), key=lambda event: (event.captured_at, event.event_id))

    def download(self, url: str) -> bytes:
        self.last_download_metadata = {}
        checked = _https_url(url)
        if not checked:
            raise UboxError(stored("ubox.err.https_only"))
        original = httpx.URL(checked)
        address = _public_address(original.host)
        # Pin the checked IP so a DNS rebind cannot reach the private network.
        # Host + SNI preserve the original server's TLS certificate verification.
        target = original.copy_with(host=address)
        try:
            with _private_request(), self._client.stream(
                "GET", target,
                headers={"Host": original.host, "Accept": "image/*", "Connection": "close"},
                extensions={"sni_hostname": original.host},
            ) as response:
                self.last_download_metadata = {
                    "http_status": response.status_code,
                    "content_type": response.headers.get("content-type", "").split(";", 1)[0],
                }
                if response.status_code != 200:
                    raise UboxError(stored("ubox.err.download_http", status=response.status_code))
                length = _integer(response.headers.get("content-length"))
                if length is not None and length > MAX_IMAGE_BYTES:
                    raise UboxError(stored("ubox.err.too_big"))
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_IMAGE_BYTES:
                        raise UboxError(stored("ubox.err.too_big"))
                if not content:
                    raise UboxError(stored("ubox.err.empty_image"))
                self.last_download_metadata["file_bytes"] = len(content)
                return bytes(content)
        except httpx.HTTPError:
            raise UboxError(stored("ubox.err.download_failed")) from None
