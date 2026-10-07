"""Read-only Nordic cloud client based on the vendor's public web-app source.

The browser uses an HTTP cookie session, not a bearer token. ``token`` is our
serialized cookie jar for encrypted storage by GameSense. Contracts were read
from index-DPxt6J1B.js on 2026-10-06; live-account validation is still required.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import math
import re
import socket
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.cookiejar import Cookie
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings

NORDIC_API = "https://api.nordicgamekeeper.com"
NORDIC_WEB = "https://account.nordicgamekeeper.com"
MAX_PAGES = 100
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_BUNDLE_BYTES = 12 * 1024 * 1024
_quiet: ContextVar[bool] = ContextVar("nordic_private_request", default=False)


class _PrivateHttpLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _quiet.get()


for _name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
    logging.getLogger(_name).addFilter(_PrivateHttpLogs())


@contextmanager
def _private_request():
    state = _quiet.set(True)
    try:
        yield
    finally:
        _quiet.reset(state)


class NordicError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class NordicAuthError(NordicError):
    """The vendor rejected or could not establish the cookie session."""


@dataclass
class NordicCamera:
    nordic_id: str
    name: str
    battery_pct: int | None = None
    signal_pct: int | None = None
    lat: float | None = None
    lng: float | None = None
    model: str | None = None
    last_report_at: datetime | None = None


@dataclass
class NordicPhoto:
    photo_id: str
    camera_id: str
    captured_at: datetime
    url: str = field(repr=False)


def _timestamp(value: Any) -> datetime | None:
    try:
        if isinstance(value, int | float) and not isinstance(value, bool):
            if not math.isfinite(value) or not 0 < value < 10_000_000_000:
                return None
            return datetime.fromtimestamp(value, UTC)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _number(value: Any, minimum: float, maximum: float) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        if math.isfinite(value) and minimum <= value <= maximum:
            return float(value)
    return None


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise NordicError(f"Nordic returned an invalid {label}.")
    return value


def _https_url(value: Any) -> httpx.URL:
    try:
        url = httpx.URL(_required_string(value, "media URL"))
        if url.scheme == "https" and url.host and not url.userinfo and url.port in (None, 443):
            return url
    except (httpx.InvalidURL, ValueError):
        pass
    raise NordicError("Nordic media requires a valid HTTPS URL.")


def _public_address(host: str) -> str:
    try:
        addresses = [ipaddress.ip_address(item[4][0]) for item in
                     socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
    except (OSError, ValueError):
        raise NordicError("Nordic media host could not be resolved.") from None
    if not addresses or any(not ip.is_global or ip.is_multicast for ip in addresses):
        raise NordicError("Nordic media host must resolve to a public address.")
    return str(addresses[0])


def _read_bytes(response: httpx.Response, limit: int) -> bytes:
    if response.status_code != 200:
        raise NordicError("Nordic returned an unsuccessful response.", response.status_code)
    try:
        if int(response.headers.get("content-length", "0")) > limit:
            raise NordicError("Nordic response exceeds the size limit.")
    except ValueError:
        raise NordicError("Nordic returned an invalid content length.") from None
    result = bytearray()
    for part in response.iter_bytes():
        result.extend(part)
        if len(result) > limit:
            raise NordicError("Nordic response exceeds the size limit.")
    return bytes(result)


def _web_bundle_path(html: str) -> str:
    matches = re.findall(r'<script\b[^>]*\bsrc=["\'](/assets/index-[\w-]+\.js)["\']', html)
    if len(set(matches)) != 1:
        raise NordicError("Nordic web-app configuration changed; set NORDIC_CLIENT_SECRET.")
    return matches[0]


def _web_client_credential(bundle: str) -> str:
    # Parse only the observed password-grant literal. Never evaluate downloaded JS.
    matches = re.findall(
        r'client_id:"webApp",client_secret:"([A-Za-z0-9_-]{1,200})",grant_type:"password"',
        bundle,
    )
    if len(set(matches)) != 1:
        raise NordicError("Nordic web-app login changed; set NORDIC_CLIENT_SECRET.")
    return matches[0]


class NordicClient:
    def __init__(self, username: str, password: str, timeout: float = 30.0) -> None:
        self._username, self._password = username, password
        self._authenticated = False
        self._app_id = str(uuid.uuid4())
        self._expiry: datetime | None = None
        self.token_valid_hours: float | None = None
        self._client = httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False)
        # Public assets and media never share the API's cookies or credentials.
        self._public_client = httpx.Client(
            timeout=timeout, trust_env=False, follow_redirects=False,
        )

    def __enter__(self) -> NordicClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()
        self._public_client.close()

    @property
    def token(self) -> str | None:
        if not self._authenticated:
            return None
        cookies = []
        for cookie in self._client.cookies.jar:
            if cookie.domain.lstrip(".") not in (
                "api.nordicgamekeeper.com", "nordicgamekeeper.com",
            ):
                continue
            cookies.append({
                "name": cookie.name, "value": cookie.value, "domain": cookie.domain,
                "path": cookie.path, "expires": cookie.expires,
                "secure": cookie.secure, "domain_specified": cookie.domain_specified,
            })
        return json.dumps({"version": 1, "app_id": self._app_id, "cookies": cookies,
                           "expires_at": self._expiry.isoformat() if self._expiry else None})

    def use_token(self, token: str) -> None:
        try:
            if len(token) > 65536:
                raise ValueError
            data = json.loads(token)
            if data["version"] != 1 or not isinstance(data["cookies"], list):
                raise ValueError
            app_id = str(uuid.UUID(data["app_id"]))
            cookies = []
            for row in data["cookies"]:
                domain = row["domain"]
                if domain.lstrip(".") not in (
                    "api.nordicgamekeeper.com", "nordicgamekeeper.com",
                ) or not row["path"].startswith("/"):
                    raise ValueError
                for key in ("name", "value", "path"):
                    if not isinstance(row[key], str) or any(c in row[key] for c in "\r\n\x00"):
                        raise ValueError
                expires = row.get("expires")
                if expires is not None and not isinstance(expires, int):
                    raise ValueError
                cookies.append(Cookie(
                    0, row["name"], row["value"], None, False, domain,
                    bool(row.get("domain_specified", True)), domain.startswith("."),
                    row["path"], True, True, expires, expires is None, None, None, {}, False,
                ))
            if not cookies:
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError):
            raise NordicAuthError("Saved Nordic session is invalid; sign in again.") from None
        self._client.cookies.clear()
        for cookie in cookies:
            self._client.cookies.jar.set_cookie(cookie)
        self._app_id = app_id
        self._expiry = _timestamp(data.get("expires_at"))
        self._authenticated = True

    def _public_text(self, path: str, limit: int) -> str:
        try:
            with _private_request(), self._public_client.stream("GET", NORDIC_WEB + path) as r:
                return _read_bytes(r, limit).decode("utf-8")
        except httpx.HTTPError:
            raise NordicError(
                "Could not read Nordic's public web-app configuration.", 503,
            ) from None
        except UnicodeError:
            raise NordicError("Nordic's public web-app configuration is not valid text.") from None

    def _credential(self) -> str:
        configured = getattr(settings, "nordic_client_secret", "")
        if configured:
            return configured
        path = _web_bundle_path(self._public_text("/", 256 * 1024))
        return _web_client_credential(self._public_text(path, MAX_BUNDLE_BYTES))

    def _json(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            with _private_request(), self._client.stream(
                method, NORDIC_API + path,
                headers={"Content-Type": "application/json", "x-app-id": self._app_id},
                **kwargs,
            ) as response:
                if response.status_code in (401, 403):
                    raise NordicAuthError("Nordic rejected the account or session.",
                                          response.status_code)
                raw = _read_bytes(response, MAX_JSON_BYTES)
            result = json.loads(raw)
        except httpx.HTTPError:
            raise NordicError("Could not reach Nordic Gamekeeper.", 503) from None
        except ValueError:
            raise NordicError("Nordic returned an invalid JSON response.") from None
        if not isinstance(result, dict):
            raise NordicError("Nordic returned an unexpected response structure.")
        return result

    def login(self) -> str:
        if not self._username or not self._password:
            raise NordicAuthError("Enter the Nordic Gamekeeper email and password.")
        self._authenticated = False
        self._client.cookies.clear()
        result = self._json("POST", "/oauth/authorize", json={
            "username": self._username, "password": self._password,
            "client_id": "webApp", "client_secret": self._credential(),
            "grant_type": "password", "rememberMe": True,
        })
        if not list(self._client.cookies.jar):
            raise NordicAuthError("Nordic did not establish a cookie session.")
        # The vendor's UI verifies /me after authorization, too.
        self._json("GET", "/api/user/me")
        self._expiry = _timestamp(result.get("expires_at"))
        cookie_expiries = [c.expires for c in self._client.cookies.jar if c.expires]
        if cookie_expiries:
            cookie_expiry = _timestamp(min(cookie_expiries))
            if cookie_expiry and (self._expiry is None or cookie_expiry < self._expiry):
                self._expiry = cookie_expiry
        self.token_valid_hours = (
            max(0.0, (self._expiry - datetime.now(UTC)).total_seconds() / 3600)
            if self._expiry else None
        )
        self._authenticated = True
        return self.token or ""

    def _get(self, path: str, **kwargs: Any) -> dict:
        if not self._authenticated:
            self.login()
        for attempt in range(2):
            try:
                return self._json("GET", path, **kwargs)
            except NordicAuthError:
                self._authenticated = False
                if attempt:
                    raise
                self.login()
        raise NordicAuthError("Nordic authentication failed.")

    def list_cameras(self) -> list[NordicCamera]:
        payload = self._get("/api/camera/mine")
        rows = payload.get("content")
        if not isinstance(rows, list) or payload.get("last") is False:
            raise NordicError("Nordic camera list is incomplete or has changed format.")
        cameras = []
        for row in rows:
            if not isinstance(row, dict):
                raise NordicError("Nordic returned an invalid camera.")
            identifier = _required_string(row.get("id"), "camera ID")
            name = _required_string(row.get("displayName"), "camera name")
            status = row.get("status") or {}
            if not isinstance(status, dict):
                raise NordicError("Nordic returned an invalid camera status.")
            battery = _number(status.get("batteryPercentage"), 0, 100)
            signal = _number(status.get("signalPercentage"), 0, 100)
            cameras.append(NordicCamera(
                nordic_id=identifier, name=name,
                battery_pct=int(battery) if battery is not None else None,
                signal_pct=int(signal) if signal is not None else None,
                lat=_number(row.get("latitude"), -90, 90),
                lng=_number(row.get("longitude"), -180, 180),
                model=status.get("cameraModel") if isinstance(status.get("cameraModel"), str)
                else None,
                last_report_at=_timestamp(status.get("created")),
            ))
        return cameras

    def list_photos(self, camera_id: str, since: datetime, until: datetime) -> list[NordicPhoto]:
        if since.tzinfo is None or until.tzinfo is None or since > until:
            raise ValueError("Nordic photo bounds must be ordered, timezone-aware dates.")
        path = "/api/camera/" + quote(_required_string(camera_id, "camera ID"), safe="") + "/media"
        photos: dict[str, NordicPhoto] = {}
        seen_pages: set[tuple[str, ...]] = set()
        previous_date: datetime | None = None
        for page in range(MAX_PAGES):
            payload = self._get(path, params={"page": page, "size": 36})
            rows, last = payload.get("content"), payload.get("last")
            if not isinstance(rows, list) or not isinstance(last, bool) or (not rows and not last):
                raise NordicError("Nordic media page is incomplete or has changed format.")
            ids = []
            page_dates = []
            for row in rows:
                if not isinstance(row, dict):
                    raise NordicError("Nordic returned an invalid media record.")
                identifier = _required_string(row.get("idString"), "photo ID")
                ids.append(identifier)
                url = _https_url(row.get("url"))
                captured = _timestamp(row.get("dateEpoch"))
                if captured is None:
                    raise NordicError("Nordic photo has an invalid timestamp.")
                if previous_date is not None and captured > previous_date:
                    raise NordicError(
                        "Nordic media ordering changed; synchronization is incomplete.",
                    )
                previous_date = captured
                page_dates.append(captured)
                if url.path.lower().endswith((".mp4", ".mov")):
                    continue
                if since <= captured <= until:
                    photos[identifier] = NordicPhoto(identifier, camera_id, captured, str(url))
            signature = tuple(ids)
            if signature and signature in seen_pages:
                raise NordicError("Nordic repeated a media page; synchronization is incomplete.")
            seen_pages.add(signature)
            # Vendor camera cards request page=0,size=1 for "Latest image". Mirror
            # that newest-first contract, verifying monotonic dates as we scan.
            # Stop only strictly before since so equal-time page boundaries survive.
            if last or (page_dates and all(date < since for date in page_dates)):
                return list(photos.values())
        raise NordicError("Nordic media page limit reached; synchronization is incomplete.")

    def download(self, url: str) -> bytes:
        original = _https_url(url)
        address = _public_address(original.host)
        target = original.copy_with(host=address)
        try:
            with _private_request(), self._public_client.stream(
                "GET", target,
                headers={"Host": original.host, "Accept": "image/*", "Connection": "close"},
                extensions={"sni_hostname": original.host},
            ) as response:
                content = _read_bytes(response, MAX_IMAGE_BYTES)
        except httpx.HTTPError:
            raise NordicError("Could not download the Nordic photo.", 503) from None
        if not content:
            raise NordicError("Nordic returned an empty photo.")
        return content
