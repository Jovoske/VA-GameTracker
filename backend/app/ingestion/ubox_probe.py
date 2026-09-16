"""Operator-only, read-only UBox diagnostics; never run automatically on connect.

Run from backend: python -m app.ingestion.ubox_probe --output /safe/path/probe.json
The email and password are prompted without echo, or read from explicitly set
UBOX_EMAIL / UBOX_PASSWORD environment variables. No .env is loaded by this tool.
Only login, device/event listing and snapshot GET requests are made. It never
starts a stream, changes camera settings, subscribes or buys a cloud plan.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import io
import json
import os
import secrets
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image

from app.ingestion.ubox import UboxClient, UboxError, UboxEvent

_SAFE_TEXT = {
    "event_time", "latest_active_utc", "time_diff", "online_state", "battery", "signal",
    "model_num", "firmware_ver", "version", "type", "status", "code", "page", "pages",
    "total", "page_num", "token_valid_hours", "summer_time", "device_type", "ai_flag",
}


def scrub_fixture(value: Any, salt: bytes, key: str = "") -> Any:
    """Preserve response shape while removing every unrecognized string value.

    A per-run HMAC lets device/event identifiers match across captured responses
    without publishing reversible SIM numbers or enabling cross-run correlation.
    The random key is never saved. Unknown nested strings are redacted by default.
    """
    lowered = key.lower()
    if any(part in lowered for part in ("password", "pwd", "secret", "token")):
        if lowered != "token_valid_hours":
            return "[redacted]" if value not in (None, "") else value
    if (lowered in {"uid", "uuid", "kuid", "id", "account", "email", "device_user"}
            or lowered.endswith(("_uid", "_id"))
            or lowered.startswith(("icc_id", "imei", "imsi"))):
        if value in (None, ""):
            return value
        return "id_" + hmac.new(salt, str(value).encode(), hashlib.sha256).hexdigest()[:16]
    if isinstance(value, dict):
        return {str(k): scrub_fixture(v, salt, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_fixture(item, salt, key) for item in value]
    if isinstance(value, str):
        if not value:
            return ""
        if key in _SAFE_TEXT and len(value) < 80 and all(
            char.isalnum() or char in ".,:_+- " for char in value
        ):
            return value
        if "url" in lowered or lowered == "img" or value.startswith(("http:", "https:")):
            return "https://redacted.invalid/image"
        return "[redacted]"
    return value


class ProbeClient(UboxClient):
    def __init__(self, email: str, password: str, salt: bytes) -> None:
        super().__init__(email, password)
        self.salt = salt
        self.fixtures: dict[str, Any] = {}

    def _request(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = super()._request(path, body)
        self.fixtures.setdefault(path, {"code": 0, "data": scrub_fixture(data, self.salt)})
        return data


def _snapshot(client: UboxClient, url: str, detect: bool) -> dict[str, Any]:
    try:
        content = client.download(url)
        report = dict(client.last_download_metadata)
        with Image.open(io.BytesIO(content)) as image:
            report.update(width=image.width, height=image.height, image_format=image.format)
            image.verify()
        if detect:
            # Optional local inference, using the same detector as ingestion.
            from app.ai.detector import detect_animals

            with tempfile.TemporaryDirectory(prefix="ubox-probe-") as directory:
                path = Path(directory) / "snapshot.jpg"
                path.write_bytes(content)
                report["animal_detections"] = detect_animals(str(path))
        return {**report, "ok": True}
    except UboxError as exc:
        return {**client.last_download_metadata, "ok": False, "error": str(exc)}
    except Exception as exc:
        # Third-party errors sometimes contain request URLs or local paths.
        return {**client.last_download_metadata, "ok": False, "error_type": type(exc).__name__}


def run_probe(
    client: ProbeClient, *, detect: bool = False,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    client.login()
    now = datetime.now(UTC)
    report: dict[str, Any] = {
        "captured_at_utc": now.isoformat(), "source": "live operator probe",
        "token_valid_hours": client.token_valid_hours,
        "timezone_status": "UNVERIFIED: compare three UTC instants below with UBox Pro",
        "timestamp_assumption": "Unix seconds; time_diff=0, summer_time=0, time_revised=false",
        "devices": [],
    }
    rechecks: list[tuple[str, str]] = []
    for device in client.list_devices():
        device_report: dict[str, Any] = {
            "device": scrub_fixture(device.raw, client.salt), "periods": {}, "snapshots": {},
        }
        candidates: dict[str, UboxEvent] = {}
        for days in (1, 7):
            # Query daily so busy cameras do not exhaust a seven-day page budget.
            events: dict[str, UboxEvent] = {}
            for offset in range(days):
                until = now - timedelta(days=offset)
                for event in client.list_events(device.uid, until - timedelta(days=1), until):
                    events[event.event_id] = event
            selected = sorted(events.values(), key=lambda item: item.captured_at)
            candidates.update(events)
            ai_shapes = Counter(
                json.dumps(scrub_fixture(event.ai_result, client.salt), sort_keys=True)
                for event in selected
            )
            device_report["periods"][f"{days}_days"] = {
                "event_count": len(selected),
                "type_distribution": dict(Counter(str(event.type) for event in selected)),
                "ai_result_distribution": dict(ai_shapes),
                "events_with_snapshot_url": sum(bool(event.image_url) for event in selected),
                "sample_times": [{
                    "event_time": event.raw.get("event_time"),
                    "parsed_utc": event.captured_at.isoformat(),
                    "device_time_diff_s": device.time_diff_s,
                } for event in selected[:3]],
            }
        for field in ("img", "cloud_hd_image_url", "cloud_image_url"):
            url = next((event.raw.get(field) for event in candidates.values()
                        if isinstance(event.raw.get(field), str) and event.raw.get(field)), None)
            if url:
                result = _snapshot(client, url, detect)
                device_report["snapshots"][field] = result
                rechecks.append((f"device_{len(report['devices'])}_{field}", url))
            else:
                device_report["snapshots"][field] = {"available": False}
        report["devices"].append(device_report)
    report["fixtures"] = client.fixtures
    report["url_expiry_status"] = "UNVERIFIED unless optional delayed recheck was requested"
    report["retention_status"] = "Observed events only; absence does not establish retention"
    return report, rechecks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Scrubbed JSON report path")
    parser.add_argument("--detect", action="store_true", help="Also run local MegaDetector")
    parser.add_argument("--recheck-after-minutes", type=int, default=0, choices=(0, 60),
                        help="Keep signed URLs only in memory and retry them after one hour")
    args = parser.parse_args()
    email = os.environ.get("UBOX_EMAIL") or getpass.getpass("UBox email (hidden): ")
    password = os.environ.get("UBOX_PASSWORD") or getpass.getpass("UBox password: ")
    try:
        with ProbeClient(email, password, secrets.token_bytes(32)) as client:
            report, rechecks = run_probe(client, detect=args.detect)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            if args.recheck_after_minutes and rechecks:
                print("Initial report saved. Rechecking the same URLs after 60 minutes.")
                deadline = time.monotonic() + 3600
                while time.monotonic() < deadline:
                    time.sleep(min(30, max(0, deadline - time.monotonic())))
                report["one_hour_url_recheck"] = {
                    label: _snapshot(client, url, False) for label, url in rechecks
                }
                report["url_expiry_status"] = "Same original URLs retried after one hour"
                args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(json.dumps(report["one_hour_url_recheck"], indent=2))
    except UboxError as exc:
        print(f"Probe failed: {exc}")
        return 1
    print("Compare sample_times with UBox Pro before declaring timezone behavior verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
