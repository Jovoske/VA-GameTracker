"""Turn newly classified detections into notifications.

Runs at the end of every classification pass (see app.ai.species), because that is
the first moment a photo has a species and so the first moment there is anything to
say. It keeps a watermark on detections.created_at rather than a flag on each row: the
classifier commits in batches and the watermark is one small write.

Two guards keep this an alert rather than a firehose:

  * photos captured more than NOTIFY_LOOKBACK_HOURS ago are never announced — a
    backfill is history, and thirteen months of it arriving as pushes would get the
    app muted in an afternoon;
  * one notification per species per run however many frames a sounder produced,
    and when one run has more than MAX_PER_USER species for a person it collapses
    into a single summary.
"""
from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import (
    AppSetting,
    Camera,
    Detection,
    Image,
    Notification,
    NotificationPref,
    Species,
)
from app.notifications import push

log = get_logger(__name__)

CURSOR_KEY = "notify_cursor"
MAX_PER_USER = 5
FEED_URL = "/animals"


def sighting_url(species_id: str, image_id: uuid.UUID | None) -> str:
    """Where a tap on one species' banner lands: that species' gallery, opened on
    the photo the notification is about. Nobody wants to be dropped at the top of
    the app and made to find the picture they were just told about."""
    query = urlencode({"species": species_id, **({"image": str(image_id)} if image_id else {})})
    return f"{FEED_URL}?{query}"


@dataclass
class SpeciesDigest:
    species_id: str
    name: str
    images: set = field(default_factory=set)
    cameras: Counter = field(default_factory=Counter)
    latest_at: datetime | None = None
    latest_image_id: uuid.UUID | None = None

    def add(self, image_id: uuid.UUID, captured_at: datetime, camera: str) -> None:
        if image_id in self.images:
            return  # two animals in one frame are one sighting
        self.images.add(image_id)
        self.cameras[camera] += 1
        if self.latest_at is None or captured_at > self.latest_at:
            self.latest_at = captured_at
            self.latest_image_id = image_id


def _cursor(db: Session) -> datetime | None:
    row = db.get(AppSetting, CURSOR_KEY)
    if row is None:
        return None
    return datetime.fromisoformat(row.value["after"])


def _set_cursor(db: Session, at: datetime) -> None:
    row = db.get(AppSetting, CURSOR_KEY)
    if row is None:
        db.add(AppSetting(key=CURSOR_KEY, value={"after": at.isoformat()}))
    else:
        row.value = {"after": at.isoformat()}


def group_by_species(rows) -> dict[str, SpeciesDigest]:
    """rows: (species_id, common_name, image_id, captured_at, camera_name)."""
    out: dict[str, SpeciesDigest] = {}
    for sid, name, image_id, captured_at, camera in rows:
        d = out.get(sid)
        if d is None:
            d = out[sid] = SpeciesDigest(species_id=sid, name=name)
        d.add(image_id, captured_at, camera)
    return out


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return names[0] if names else ""
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    if len(names) == 3:
        return f"{names[0]}, {names[1]} and {names[2]}"
    return f"{names[0]}, {names[1]} and {len(names) - 2} more"


def compose(d: SpeciesDigest, tz: ZoneInfo) -> tuple[str, str]:
    """(title, body) for one species in one run.

    Reads like a text from a friend: "Wild boar at PL19" / "2 photos, last one 22:14."
    Camera in the title when there is one, the count when there are several.
    """
    cams = [c for c, _ in d.cameras.most_common()]
    n = len(d.images)
    when = d.latest_at.astimezone(tz).strftime("%H:%M") if d.latest_at else "just now"
    if n == 1:
        return f"{d.name} at {cams[0]}", f"1 photo at {when}."
    photos = f"{n} photos"
    if len(cams) == 1:
        return f"{d.name} at {cams[0]}", f"{photos}, last one {when}."
    return f"{d.name} on {len(cams)} cameras", f"{photos} at {_join(cams)}, last one {when}."


def compose_summary(digests: list[SpeciesDigest], tz: ZoneInfo) -> tuple[str, str]:
    n = sum(len(d.images) for d in digests)
    names = [d.name for d in sorted(digests, key=lambda d: -len(d.images))]
    latest = max((d.latest_at for d in digests if d.latest_at), default=None)
    when = latest.astimezone(tz).strftime("%H:%M") if latest else "just now"
    return (
        f"{n} new sightings, {len(digests)} animals",
        f"{_join(names)}, last one {when}.",
    )


def dispatch_new_sightings(db: Session, now: datetime | None = None) -> dict:
    """Announce detections created since the last run to everyone who asked for them."""
    now = now or datetime.now(timezone.utc)
    since = _cursor(db)
    if since is None:
        # First run ever: everything already in the database is history. Start
        # counting from here rather than announcing a season of old photos.
        _set_cursor(db, now)
        db.commit()
        return {"status": "primed"}

    newest = db.scalar(select(func.max(Detection.created_at)).where(Detection.created_at > since))
    if newest is None:
        return {"status": "nothing_new", "notifications": 0}

    lookback = now - timedelta(hours=settings.notify_lookback_hours)
    rows = db.execute(
        select(Detection.species_id, Species.common_name, Image.id, Image.captured_at, Camera.name)
        .select_from(Detection)
        .join(Image, Image.id == Detection.image_id)
        .join(Species, Species.id == Detection.species_id)
        .join(Camera, Camera.id == Image.camera_id)
        .where(
            Detection.created_at > since,
            Detection.created_at <= newest,
            Detection.species_id.isnot(None),
            Image.captured_at > lookback,
        )
        .order_by(Image.captured_at)
    ).all()
    digests = group_by_species(rows)

    created = pushed = 0
    if digests:
        tz = ZoneInfo(settings.estate_timezone)
        prefs = db.scalars(
            select(NotificationPref).where(NotificationPref.enabled.is_(True))
        ).all()
        for pref in prefs:
            wanted_ids = set(pref.species_ids or [])
            wanted = [d for sid, d in digests.items() if sid in wanted_ids]
            if not wanted:
                continue
            wanted.sort(key=lambda d: d.latest_at or now, reverse=True)

            notes: list[Notification] = []
            if len(wanted) > MAX_PER_USER:
                title, body = compose_summary(wanted, tz)
                notes.append(Notification(
                    user_id=pref.user_id, kind="sighting", title=title, body=body,
                    url=FEED_URL, created_at=now,
                ))
            else:
                for d in wanted:
                    title, body = compose(d, tz)
                    notes.append(Notification(
                        user_id=pref.user_id, kind="sighting", title=title, body=body,
                        url=sighting_url(d.species_id, d.latest_image_id),
                        species_id=d.species_id, image_id=d.latest_image_id,
                        created_at=now,
                    ))
            db.add_all(notes)
            db.flush()

            for n in notes:
                result = push.send_to_user(db, pref.user_id, {
                    "title": n.title, "body": n.body, "url": n.url,
                    # Same tag per species: a second sounder an hour later replaces the
                    # first banner instead of stacking under it.
                    "tag": f"sighting-{n.species_id or 'summary'}",
                    "at": now.isoformat(),
                })
                if result["sent"]:
                    n.push_status = "sent"
                elif result["subscriptions"] == 0:
                    n.push_status = "no_subscription"
                else:
                    n.push_status = "failed"
                pushed += result["sent"]
            created += len(notes)

    _set_cursor(db, newest)
    db.commit()
    result = {
        "status": "ok", "species": len(digests), "notifications": created, "pushed": pushed,
    }
    log.info("notify.dispatched", **result)
    return result
