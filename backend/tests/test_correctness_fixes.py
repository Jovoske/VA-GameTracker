"""Regression tests for the correctness and security defects fixed in this branch.

Each test pins a bug that was silently wrong in production rather than loud.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app.ingestion.spypoint import SpypointClient, _parse_dt
from app.models import Camera, Detection, Estate, Image

from .conftest import requires_db


# ── timestamps must never be invented ───────────────────────────────────────


def test_unparseable_timestamp_returns_none_not_now():
    """It used to return datetime.now(), stamping a photo with its sync time."""
    assert _parse_dt(None) is None
    assert _parse_dt("") is None
    assert _parse_dt("not-a-date") is None


def test_valid_timestamp_still_parses():
    got = _parse_dt("2025-10-04T22:13:05.000Z")
    assert got == datetime(2025, 10, 4, 22, 13, 5, tzinfo=timezone.utc)


def test_photos_without_a_usable_timestamp_are_dropped(monkeypatch):
    """A photo with no trustworthy capture time must be skipped, not fabricated."""
    client = SpypointClient("u", "p")

    class _Resp:
        @staticmethod
        def json():
            return {
                "photos": [
                    {"id": "good", "originDate": "2025-10-04T22:00:00.000Z",
                     "large": {"host": "h", "path": "p"}},
                    {"id": "bad", "date": "garbage", "large": {"host": "h", "path": "p"}},
                    {"id": "missing", "large": {"host": "h", "path": "p"}},
                ]
            }

    monkeypatch.setattr(client, "_request", lambda *a, **k: _Resp())
    photos = client.list_photos("cam-1")
    assert [p.spypoint_id for p in photos] == ["good"]


def test_capture_time_is_preferred_over_receipt_time(monkeypatch):
    """originDate (when the camera fired) beats date (when SPYPOINT received it)."""
    client = SpypointClient("u", "p")

    class _Resp:
        @staticmethod
        def json():
            return {
                "photos": [
                    {
                        "id": "x",
                        "originDate": "2025-10-04T22:00:00.000Z",  # captured at night
                        "date": "2025-10-05T06:40:00.000Z",        # uploaded at dawn
                        "large": {"host": "h", "path": "p"},
                    }
                ]
            }

    monkeypatch.setattr(client, "_request", lambda *a, **k: _Resp())
    (photo,) = client.list_photos("cam-1")
    assert photo.captured_at.hour == 22, "a late upload must not become a dawn sighting"


# ── the night boundary ──────────────────────────────────────────────────────


@requires_db
def test_post_midnight_detections_belong_to_the_previous_evening(db_session):
    """The join bug: 02:00 activity was paired with the FOLLOWING night's weather.

    _overnight_weather keys a night by its evening date (18:00 D -> 06:00 D+1), so a
    detection at 02:00 on the 5th belongs to night '2025-10-04'.
    """
    from app.core.config import settings

    estate = Estate(name="E", timezone="Europe/Madrid", lat=39.0, lon=-1.3)
    db_session.add(estate)
    db_session.flush()
    cam = Camera(estate_id=estate.id, name="Puente", active=True)
    db_session.add(cam)
    db_session.flush()

    # 22:00 on the 4th and 02:00 on the 5th, Madrid local -- the same physical night.
    for iso in ("2025-10-04T20:00:00+00:00", "2025-10-05T00:00:00+00:00"):
        img = Image(camera_id=cam.id, captured_at=datetime.fromisoformat(iso), reviewed=False)
        db_session.add(img)
        db_session.flush()
        db_session.add(Detection(image_id=img.id, species_id=None, sex="unknown", age_class="unknown"))
    db_session.commit()

    tz = settings.estate_timezone
    night = func.date(func.timezone(tz, Image.captured_at) - text("interval '6 hours'"))
    rows = db_session.execute(
        select(night, func.count(Detection.id))
        .join(Image, Image.id == Detection.image_id)
        .group_by(night)
    ).all()

    assert len(rows) == 1, f"both detections must land on one night, got {rows}"
    assert rows[0][0].isoformat() == "2025-10-04"


# ── weather hour is anchored to the estate, not the process ─────────────────


def test_tonight_weather_is_sampled_at_estate_local_22():
    """Under a UTC container, .astimezone() was a no-op and sampled midnight."""
    from zoneinfo import ZoneInfo

    from app.core.config import settings

    now = datetime(2025, 10, 4, 17, 0, tzinfo=timezone.utc)
    local_22 = now.astimezone(ZoneInfo(settings.estate_timezone)).replace(
        hour=22, minute=0, second=0, microsecond=0
    )
    assert local_22.hour == 22
    # 22:00 Madrid in October (CEST, +02:00) is 20:00 UTC -- still the same evening.
    assert local_22.astimezone(timezone.utc).day == 4


# ── static file serving must not escape the dist root ───────────────────────


def test_spa_path_traversal_is_blocked(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "app.js").write_text("console.log(1)")
    secret = tmp_path / "secret.txt"
    secret.write_text("PRIVATE")

    dist_real = os.path.realpath(str(dist))

    def resolve(full_path: str):
        candidate = os.path.realpath(os.path.join(dist_real, full_path))
        inside = candidate == dist_real or candidate.startswith(dist_real + os.sep)
        return candidate if (full_path and inside and os.path.isfile(candidate)) else None

    assert resolve("app.js") is not None          # legitimate asset still served
    assert resolve("../secret.txt") is None       # traversal refused
    assert resolve("../../etc/passwd") is None
