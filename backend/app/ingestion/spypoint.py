"""SPYPOINT cloud API client — ported and hardened from the legacy integration.

The endpoints and the host/path photo-URL reconstruction are the genuinely
hard-won knowledge preserved from the old app; everything else (typed DTOs,
401 re-auth, metadata extraction, image download) is new.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

SPYPOINT_API = "https://restapi.spypoint.com/api/v3"


class SpypointError(Exception):
    pass


@dataclass
class SpypointCamera:
    spypoint_id: str
    name: str
    battery_pct: int | None = None
    signal_pct: int | None = None
    lat: float | None = None
    lng: float | None = None
    model: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpypointPhoto:
    spypoint_id: str
    captured_at: datetime
    url: str
    tags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def _to_int(*values: Any) -> int | None:
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return int(v)
    return None


def _extract_signal(signal: Any) -> int | None:
    """SPYPOINT signal: int, {percentage}, or {bar, processed:{percentage}}."""
    if isinstance(signal, (int, float)):
        return int(signal)
    if isinstance(signal, dict):
        processed = signal.get("processed")
        if isinstance(processed, dict):
            pct = _to_int(processed.get("percentage"))
            if pct is not None:
                return pct
        pct = _to_int(signal.get("percentage"))
        if pct is not None:
            return pct
        bar = _to_int(signal.get("bar"))
        if bar is not None:
            return min(100, bar * 20)  # 0..5 bars -> 0..100
    return None


def _extract_battery(status: dict) -> int | None:
    """Active battery %: powerSources[active].percentage → batteries[active] → fallbacks."""
    active = status.get("activePowerSource")
    sources = status.get("powerSources")
    if isinstance(sources, list) and sources:
        idx = active if isinstance(active, int) and 0 <= active < len(sources) else 0
        pct = _to_int((sources[idx] or {}).get("percentage"))
        if pct is not None:
            return pct
    batteries = status.get("batteries")
    if isinstance(batteries, list) and batteries:
        if isinstance(active, int) and 0 <= active < len(batteries):
            return _to_int(batteries[active])
        return _to_int(max(batteries))
    return _to_int(status.get("batteryPercentage"), status.get("battery"))


def _extract_coords(cam: dict) -> tuple[float | None, float | None]:
    """Coordinates may be a list of {position:[lng,lat]} / {latitude,longitude} entries."""
    coords = cam.get("coordinates") or []
    if isinstance(coords, list) and coords:
        first = coords[0]
        if isinstance(first, dict):
            pos = first.get("position")
            if isinstance(pos, list) and len(pos) == 2:
                return float(pos[1]), float(pos[0])  # [lng, lat]
            lat = first.get("latitude")
            lng = first.get("longitude")
            if lat is not None and lng is not None:
                return float(lat), float(lng)
    return None, None


def _parse_dt(value: Any) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _extract_tags(photo: dict) -> list[str]:
    tags = photo.get("tags")
    if isinstance(tags, list):
        return [str(t) for t in tags]
    tag = photo.get("tag")
    if isinstance(tag, str) and tag:
        return [tag]
    return []


class SpypointClient:
    def __init__(self, username: str, password: str, timeout: float = 30.0) -> None:
        self._username = username
        self._password = password
        self._token: str | None = None
        self._client = httpx.Client(timeout=timeout)

    # ── auth ────────────────────────────────────────────────
    def login(self) -> str:
        if not self._username or not self._password:
            raise SpypointError("SPYPOINT credentials are not configured")
        resp = self._client.post(
            f"{SPYPOINT_API}/user/login",
            json={"username": self._username, "password": self._password},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise SpypointError(f"login failed: HTTP {resp.status_code}")
        token = resp.json().get("token")
        if not token:
            raise SpypointError("login response missing token")
        self._token = token
        return token

    def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            self.login()
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }

    def _request(self, method: str, path: str, *, json: Any = None) -> httpx.Response:
        url = f"{SPYPOINT_API}{path}"
        resp = self._client.request(method, url, json=json, headers=self._auth_headers())
        if resp.status_code == 401:  # token expired → re-auth once
            log.info("spypoint.reauth")
            self._token = None
            resp = self._client.request(method, url, json=json, headers=self._auth_headers())
        if resp.status_code >= 400:
            raise SpypointError(f"{method} {path} -> HTTP {resp.status_code}")
        return resp

    # ── cameras ─────────────────────────────────────────────
    def list_cameras(self) -> list[SpypointCamera]:
        data = self._request("GET", "/camera/all").json()
        if not isinstance(data, list):
            data = data.get("cameras", []) if isinstance(data, dict) else []
        return [self._parse_camera(c) for c in data]

    @staticmethod
    def _parse_camera(cam: dict) -> SpypointCamera:
        cid = str(cam.get("id") or cam.get("_id") or "")
        config = cam.get("config") or {}
        status = cam.get("status") or {}
        name = config.get("name") or cam.get("name") or cid
        battery = _extract_battery(status)
        signal = _extract_signal(status.get("signal"))
        lat, lng = _extract_coords(status if status.get("coordinates") else cam)
        model = status.get("model") or config.get("model") or cam.get("model")
        return SpypointCamera(
            spypoint_id=cid, name=name, battery_pct=battery, signal_pct=signal,
            lat=lat, lng=lng, model=model, raw=cam,
        )

    # ── photos ──────────────────────────────────────────────
    def list_photos(
        self, camera_id: str, *, limit: int = 100, date_end: str | None = None
    ) -> list[SpypointPhoto]:
        body = {
            "camera": [camera_id],
            "dateEnd": date_end or "2100-01-01T00:00:00.000Z",
            "favorite": False,
            "hd": False,
            "limit": limit,
        }
        data = self._request("POST", "/photo/all", json=body).json()
        photos = data.get("photos", []) if isinstance(data, dict) else []
        result = []
        for p in photos:
            pid = str(p.get("id") or p.get("_id") or "")
            result.append(
                SpypointPhoto(
                    spypoint_id=pid,
                    captured_at=_parse_dt(p.get("date") or p.get("originDate") or p.get("createdAt")),
                    url=self.photo_url(p),
                    tags=_extract_tags(p),
                    raw=p,
                )
            )
        return result

    @staticmethod
    def photo_url(photo: dict) -> str:
        for key in ("large", "medium", "small"):
            obj = photo.get(key) or {}
            if obj.get("host") and obj.get("path"):
                return f"https://{obj['host']}/{obj['path']}"
        return photo.get("url") or photo.get("originUrl") or ""

    def download(self, url: str) -> bytes:
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.content

    def close(self) -> None:
        self._client.close()
