"""Turn newly classified detections into notifications.

Runs at the end of every classification pass (see app.ai.species), because that is
the first moment a photo has a species and so the first moment there is anything to
say. It keeps a watermark on detections.created_at rather than a flag on each row: the
classifier commits in batches and the watermark is one small write.

Guards keep this an alert rather than a firehose:

  * photos captured more than NOTIFY_LOOKBACK_HOURS ago are never announced — a
    backfill is history, and thirteen months of it arriving as pushes would get the
    app muted in an afternoon;
  * one notification per species per run however many frames a sounder produced,
    and when one run has more than MAX_PER_USER species for a person it collapses
    into a single summary;
  * one buzz per animal per COOLDOWN. The sync runs every 15 minutes, so a sounder
    at the feeder used to buzz the phone every 15 minutes all night (audit K-06).
    Inside the cooldown the push still goes, as a quiet update of the banner already
    on the phone with the running total ("4 visits since 00:55, last one 02:40."):
    nothing is hidden, nothing wakes anyone. Not to an iPhone: Safari sounds every
    push as a new alert whatever it says (push.apple), so an iPhone gets the buzz
    alone, and the running total is in Recent in Settings, where each update is
    folded into the alert it updates (its detail names it, "update_of");
  * nothing is pushed while the person is sitting or inside their quiet hours: it
    waits, and goes out as one message after (app.notifications.hold). When that is
    over and the first new sighting comes in before the notify run has sent the
    message, the message goes first and counts as the buzz, so the hunter isn't
    buzzed twice about one animal minutes apart.

It counts visits, as every other screen does: frames of one species at one camera
within VISIT_GAP of each other are one visit, so a burst of three frames of one
boar reads "1 visit", not "3 photos".

A camera someone muted is left out of what they are told, as if it had seen
nothing: no push and no in-app record, because the reason to mute the busy feeder
is to stop hearing about it. Everyone else still hears from it.
"""
from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.visibility import VISIBLE_SIGHTING
from app.core.config import settings
from app.core.logging import get_logger
from app.forecasting.exposure import VISIT_GAP
from app.forecasting.model import class_label
from app.models import (
    AppSetting,
    Camera,
    Detection,
    Image,
    Notification,
    NotificationPref,
    Species,
)
from app.notifications import hold, push, words

log = get_logger(__name__)

CURSOR_KEY = "notify_cursor"
MAX_PER_USER = 5
FEED_URL = "/photos"
# One buzz per animal this often; inside it, a quiet update of the banner.
COOLDOWN = timedelta(hours=2)

_join = words.join


def sighting_url(species_id: str, image_id: uuid.UUID | None, at: datetime | None = None) -> str:
    """Where a tap on one species' banner lands: that species' gallery, opened on
    the photo the notification is about. Nobody wants to be dropped at the top of
    the app and made to find the picture they were just told about. The photo's time
    rides along, so Photos can open it with the frames around it however many newer
    photos came in since (audit K-07)."""
    query = {"species": species_id}
    if image_id:
        query["image"] = str(image_id)
    if at is not None:
        query["at"] = at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return f"{FEED_URL}?{urlencode(query)}"


def summary_url(species_ids: list[str]) -> str:
    """Photos opened on the animals a summary names. With no animals named it used to
    open under whatever chips the hunter last picked, which could hide them (D-21)."""
    if not species_ids:
        return FEED_URL
    return f"{FEED_URL}?{urlencode({'species': ','.join(species_ids)})}"


@dataclass
class SpeciesDigest:
    species_id: str
    name: str
    images: set = field(default_factory=set)
    # {camera: [captured_at, ...]} of the frames, for counting visits.
    frames: dict = field(default_factory=dict)
    latest_at: datetime | None = None
    latest_image_id: uuid.UUID | None = None
    first_at: datetime | None = None

    def add(self, image_id: uuid.UUID, captured_at: datetime, camera: str) -> None:
        if image_id in self.images:
            return  # two animals in one frame are one sighting
        self.images.add(image_id)
        self.frames.setdefault(camera, []).append(captured_at)
        if self.latest_at is None or captured_at > self.latest_at:
            self.latest_at = captured_at
            self.latest_image_id = image_id
        if self.first_at is None or captured_at < self.first_at:
            self.first_at = captured_at

    @property
    def cameras(self) -> Counter:
        """{camera: visits}: a frame more than VISIT_GAP after the one before is a new arrival."""
        out: Counter = Counter()
        for camera, times in self.frames.items():
            prev = None
            for at in sorted(times):
                if prev is None or at - prev > VISIT_GAP:
                    out[camera] += 1
                prev = at
        return out

    @property
    def visits(self) -> int:
        return sum(self.cameras.values())

    def tally(self) -> dict:
        """What this run counted, kept on the alert (words). The photos are kept too,
        so what waits for a sit or quiet hours can be checked again before it goes
        (hold.still_there)."""
        return {
            "name": self.name, "visits": self.visits, "cameras": dict(self.cameras),
            "images": sorted(str(i) for i in self.images),
            "spans": {c: [min(ts).isoformat(), max(ts).isoformat()]
                      for c, ts in self.frames.items()},
            "first_at": self.first_at.isoformat() if self.first_at else None,
            "latest_at": self.latest_at.isoformat() if self.latest_at else None,
        }


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
    """rows: (species_id, common_name, image_id, captured_at, camera_name).

    Named as the app writes it ("Wild boar", "Roe deer"), not as it is stored.
    """
    out: dict[str, SpeciesDigest] = {}
    for sid, name, image_id, captured_at, camera in rows:
        d = out.get(sid)
        if d is None:
            d = out[sid] = SpeciesDigest(species_id=sid, name=class_label(sid, name, None, None))
        d.add(image_id, captured_at, camera)
    return out


def compose(d: SpeciesDigest, tz: ZoneInfo, now: datetime | None = None) -> tuple[str, str]:
    """(title, body) for one species in one run.

    Reads like a text from a friend: "Wild boar at PL19" / "2 visits, last one 22:14."
    Camera in the title when there is one, the count when there are several. With
    `now`, a time from an earlier day says so ("23:50 yesterday").
    """
    cams = [c for c, _ in d.cameras.most_common()]
    n = d.visits
    when = words.said_at(d.latest_at, tz, now)
    title = words.where_title(d.name, d.cameras)
    if n == 1:
        return title, f"1 visit at {when}."
    if len(cams) == 1:
        return title, f"{words.visits(n)}, last one {when}."
    return title, f"{words.visits(n)} at {_join(cams)}, last one {when}."


def compose_update(tally: dict, tz: ZoneInfo, now: datetime | None = None) -> tuple[str, str]:
    """(title, body) for a quiet update inside the cooldown: the running total since
    the alert that buzzed. "Wild boar at PL19" / "4 visits since 00:55, last one 02:40."
    """
    cams = Counter(tally.get("cameras") or {})
    title = words.where_title(tally.get("name") or "Animal", cams)
    since = words.said_at(words.first(tally), tz, now)
    last = words.said_at(words.latest(tally), tz, now)
    where = "" if len(cams) <= 1 else f" at {_join([c for c, _ in cams.most_common()])}"
    n = words.visits(int(tally.get("visits") or 0))
    return title, f"{n}{where} since {since}, last one {last}."


def compose_summary(digests: list[SpeciesDigest], tz: ZoneInfo,
                    now: datetime | None = None) -> tuple[str, str]:
    n = sum(d.visits for d in digests)
    names = [d.name for d in sorted(digests, key=lambda d: -d.visits)]
    latest = max((d.latest_at for d in digests if d.latest_at), default=None)
    when = words.said_at(latest, tz, now)
    return (
        f"{n} new sightings, {len(digests)} animals",
        f"{_join(names)}, last one {when}.",
    )


def _recent_alerts(db: Session, user_id, now: datetime) -> list[Notification]:
    """This person's sighting alerts inside the cooldown that went out (or were meant
    to: a quiet update a phone didn't take still counts in the running total), oldest
    first."""
    return list(db.scalars(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.kind.in_(("sighting", "summary")),
            Notification.created_at > now - COOLDOWN,
            Notification.push_status.in_(("sent", "updated", "failed")),
        ).order_by(Notification.created_at)
    ).all())


def _running(recent: list[Notification], key: str | None
             ) -> tuple[Notification, list[dict]] | None:
    """The alert that last buzzed for `key` (a species, or None for the many-animals
    summary) inside the cooldown, and the tallies since, its own included; None when
    nothing buzzed for it."""
    def about(n: Notification) -> bool:
        if key is None:
            return n.kind == "sighting" and n.species_id is None
        return key in words.tallies_of(n.species_id, n.detail)

    loud = None
    for i, n in enumerate(recent):
        if about(n) and n.push_status == "sent":
            loud = i
    if loud is None:
        return None
    if key is None:
        return recent[loud], []
    return recent[loud], [words.tallies_of(n.species_id, n.detail)[key]
                          for n in recent[loud:] if about(n)]


def dispatch_new_sightings(db: Session, now: datetime | None = None) -> dict:
    """Announce detections created since the last run to everyone who asked for them."""
    now = now or datetime.now(UTC)
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
        select(
            Detection.species_id, Species.common_name, Image.id, Image.captured_at, Camera.name,
            Camera.id,
        )
        .select_from(Detection)
        .join(Image, Image.id == Detection.image_id)
        .join(Species, Species.id == Detection.species_id)
        .join(Camera, Camera.id == Image.camera_id)
        .where(
            Detection.created_at > since,
            Detection.created_at <= newest,
            Detection.species_id.isnot(None),
            VISIBLE_SIGHTING,
            Image.captured_at > lookback,
        )
        .order_by(Image.captured_at)
    ).all()
    species_seen = {r[0] for r in rows}

    created = pushed = held = quiet = 0
    if rows:
        tz = ZoneInfo(settings.estate_timezone)
        prefs = db.scalars(
            select(NotificationPref).where(NotificationPref.enabled.is_(True))
        ).all()
        on = hold.sitting(db, now, [p.user_id for p in prefs])
        news: dict = {}
        for pref in prefs:
            wanted_ids = set(pref.species_ids or [])
            muted = set(pref.muted_camera_ids or [])
            # Per person: what their unmuted cameras saw of the animals they asked for.
            digests = group_by_species(
                r[:5] for r in rows if r[0] in wanted_ids and str(r[5]) not in muted
            )
            if digests:
                news[pref.user_id] = list(digests.values())
        # A sit or quiet hours just over, and the message about them not sent yet
        # (the notify run sends it within 15 minutes): it goes now, before anything
        # new, and is the buzz for the animals it names, so what this check saw of
        # them is a quiet update rather than a second buzz minutes later. Sent before
        # any row of this run is written, as it commits.
        done = [p.user_id for p in prefs if p.user_id in news
                and not hold.reason(p, p.user_id, now, on) and hold.has_held(db, p.user_id)]
        if done:
            hold.deliver_held(db, now, user_ids=done)
        for pref in prefs:
            wanted = news.get(pref.user_id)
            if not wanted:
                continue
            wanted.sort(key=lambda d: d.latest_at or now, reverse=True)
            why = hold.reason(pref, pref.user_id, now, on)
            recent = [] if why else _recent_alerts(db, pref.user_id, now)

            # (record, whether it buzzes)
            notes: list[tuple[Notification, bool]] = []
            if len(wanted) > MAX_PER_USER:
                title, body = compose_summary(wanted, tz, now)
                running = _running(recent, None)
                detail = {"species": {d.species_id: d.tally() for d in wanted}}
                if running is not None:
                    detail["update_of"] = str(running[0].id)
                notes.append((Notification(
                    user_id=pref.user_id, kind="sighting", title=title, body=body,
                    url=summary_url([d.species_id for d in wanted]), created_at=now,
                    detail=detail,
                ), running is None))
            else:
                for d in wanted:
                    title, body = compose(d, tz, now)
                    detail = d.tally()
                    running = _running(recent, d.species_id)
                    if running is not None:
                        loud_row, tallies = running
                        title, body = compose_update(words.merge([*tallies, detail]), tz, now)
                        # Recent shows it as the alert it updates (routes_notifications),
                        # when that alert is about this animal alone: not one that
                        # named several, whose words it would take the place of.
                        if loud_row.kind == "sighting" and loud_row.species_id == d.species_id:
                            detail["update_of"] = str(loud_row.id)
                    notes.append((Notification(
                        user_id=pref.user_id, kind="sighting", title=title, body=body,
                        url=sighting_url(d.species_id, d.latest_image_id, d.latest_at),
                        species_id=d.species_id, image_id=d.latest_image_id,
                        created_at=now, detail=detail,
                    ), running is None))
            if why:
                # In a stand, or quiet hours: kept, and sent as one message after.
                for n, _ in notes:
                    n.push_status = hold.HELD
                    n.detail = {**(n.detail or {}), "held": why}
            db.add_all([n for n, _ in notes])
            db.flush()
            created += len(notes)
            if why:
                held += len(notes)
                continue

            for n, loud in notes:
                result = push.send_to_user(db, pref.user_id, {
                    "title": n.title, "body": n.body, "url": n.url,
                    # Same tag per species: a second sounder an hour later replaces the
                    # first banner instead of stacking under it. It buzzes only when it
                    # is the first in the cooldown (sw.js takes renotify from here).
                    "tag": f"sighting-{n.species_id or 'summary'}",
                    "renotify": loud, "silent": not loud,
                    "at": now.isoformat(),
                }, quiet=not loud)
                n.push_status = push.delivery(result, sent="sent" if loud else "updated")
                pushed += result["sent"]
                quiet += 0 if loud else result["sent"]

    _set_cursor(db, newest)
    db.commit()
    result = {
        "status": "ok", "species": len(species_seen), "notifications": created, "pushed": pushed,
    }
    if held or quiet:
        result.update(held=held, quiet_updates=quiet)
    log.info("notify.dispatched", **result)
    return result
