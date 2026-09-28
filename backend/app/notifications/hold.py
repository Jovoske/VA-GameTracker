"""When a push waits, and the one message it arrives in afterwards.

Two things hold a person's pushes:

  * a sit. A hunter who started a sit and hasn't ended it (routes_stands._live, the
    same "on now" as Tonight's "Back to sit") is in a high seat, where a phone that
    lights up and buzzes is the worst thing it can do (audit J-21). Sit mode goes
    black for the same reason. `silent` is no help, iPhones ignore it, so nothing is
    sent at all;
  * quiet hours, if the person set them (Settings), on the estate's clock.

What waits keeps its record, marked "held", and goes out as one message when the
sit ends (END SIT asks for it straight away, routes_stands.end_sit) or the quiet
hours are over (`pipeline.py notify`, every 15 minutes, or the photo check first if
it has something new for the person): "While you sat" / "Wild boar: 3 visits at
PL19 and Charca, last one 21:40." A sit nobody ended stops holding when it stops
being on (06:00, or 12 hours after it started).

The message is about what is still there when it goes: a photo marked "nothing in
it" while it waited, an animal hidden or no longer picked, or a camera muted since,
is left out as it is everywhere else (still_there), and when nothing is left no
message goes at all.

Several deliverers can run at once (the END SIT request and the scheduled run):
each takes the held rows it sends with SKIP LOCKED and marks them before pushing,
so nothing goes out twice.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.visibility import VISIBLE_SIGHTING
from app.core.config import settings
from app.core.logging import get_logger
from app.i18n import t, use
from app.models import Camera, Detection, Image, Notification, NotificationPref, Sit, Species
from app.notifications import push, words

log = get_logger(__name__)

HELD = "held"
# What waited and is no longer there to tell of when it could go (still_there).
WITHDRAWN = "withdrawn"
SUMMARY_URL = "/photos"


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.estate_timezone)


def quiet_now(pref: NotificationPref | None, now: datetime) -> bool:
    """Inside this person's quiet hours. 22:30 to 07:00 runs over midnight; the same
    time twice is no quiet hours at all."""
    if pref is None or pref.quiet_start is None or pref.quiet_end is None:
        return False
    start, end = pref.quiet_start, pref.quiet_end
    if start == end:
        return False
    t = now.astimezone(_tz()).time().replace(tzinfo=None)
    return start <= t < end if start < end else (t >= start or t < end)


def sitting(db: Session, now: datetime, user_ids=None) -> set[uuid.UUID]:
    """Who is in a stand now: a sit started, not ended, and still on."""
    from app.api.routes_stands import _live

    q = select(Sit.user_id).where(_live(now), Sit.user_id.is_not(None))
    if user_ids is not None:
        q = q.where(Sit.user_id.in_(list(user_ids)))
    return set(db.scalars(q).all())


def reason(pref: NotificationPref | None, user_id, now: datetime, on: set) -> str | None:
    """Why this person's pushes wait now: "sit", "quiet", or None to send."""
    if user_id in on:
        return "sit"
    return "quiet" if quiet_now(pref, now) else None


def has_held(db: Session, user_id) -> bool:
    return db.scalar(
        select(Notification.id)
        .where(Notification.user_id == user_id, Notification.push_status == HELD)
        .limit(1)
    ) is not None


def still_there(db: Session, rows: list[Notification], pref: NotificationPref) -> dict[str, dict]:
    """{species_id: tally} of what the held alerts were about, as it would be told
    now. Each alert kept its photos: they are looked up again under the rules every
    screen uses (api/visibility.py), the animals and cameras the person hears about
    now, and the visits counted again from the photos left. A photo whose animal was
    corrected counts as the animal it is now."""
    from app.notifications.dispatch import group_by_species

    ids: set[uuid.UUID] = set()
    kept: dict[str, list[dict]] = {}
    for r in rows:
        for sid, tally in words.tallies_of(r.species_id, r.detail).items():
            if tally.get("images") is not None:
                ids.update(uuid.UUID(i) for i in tally["images"])
            else:  # counted without its photos: kept as it was counted
                kept.setdefault(sid, []).append(tally)
    out = {sid: words.merge(ts) for sid, ts in kept.items()}
    if not ids:
        return out
    wanted = set(pref.species_ids or [])
    muted = set(pref.muted_camera_ids or [])
    found = db.execute(
        select(Detection.species_id, Species.common_name, Image.id, Image.captured_at,
               Camera.name, Camera.id)
        .select_from(Detection)
        .join(Image, Image.id == Detection.image_id)
        .join(Species, Species.id == Detection.species_id)
        .join(Camera, Camera.id == Image.camera_id)
        .where(Image.id.in_(ids), Detection.species_id.isnot(None), VISIBLE_SIGHTING)
        .order_by(Image.captured_at)
    ).all()
    digests = group_by_species(
        r[:5] for r in found if r[0] in wanted and str(r[5]) not in muted
    )
    for sid, d in digests.items():
        out[sid] = words.merge([out[sid], d.tally()]) if sid in out else d.tally()
    return out


def compose_held(rows: list[Notification], why: str, now: datetime,
                 tallies: dict[str, dict] | None = None) -> tuple[str, str, str, dict] | None:
    """(title, body, url, detail) for the one message about everything that waited,
    or None when nothing in it is left to tell.

    What the cameras saw is added up per animal (`tallies`, from still_there; the
    alerts' own tallies when not given), so three alerts about one sounder read as
    its visits, not as three alerts.
    """
    tz = _tz()
    if tallies is None:
        per: dict[str, list[dict]] = {}
        for r in rows:
            for sid, tally in words.tallies_of(r.species_id, r.detail).items():
                per.setdefault(sid, []).append(tally)
        tallies = {sid: words.merge(ts) for sid, ts in per.items()}
    tallies = {sid: tally for sid, tally in tallies.items() if tally.get("visits")}
    order = sorted(tallies, key=lambda s: (-tallies[s]["visits"], tallies[s]["name"]))
    notes = [r for r in rows if r.kind == "team_note"]
    # An alert kept from before alerts counted (no tally) still says it was there.
    bare = [r for r in rows
            if r.kind == "sighting" and not words.tallies_of(r.species_id, r.detail)]
    if not order and not notes and not bare:
        return None

    parts: list[str] = []
    if len(order) == 1 and not notes and not bare:
        one = tallies[order[0]]
        cams = [c for c, _ in sorted(one["cameras"].items(), key=lambda kv: -kv[1])]
        parts.append(t("held.one", name=words.name(order[0], one),
                       visits=words.visits(one["visits"]), cameras=words.join(cams)))
    else:
        said = words.names([(s, tallies[s]) for s in order])
        parts += [t("held.each", name=said[i], visits=words.visits(tallies[s]["visits"]))
                  for i, s in enumerate(order)]
        parts += [r.title for r in bare]
        if notes:
            parts.append(t("held.worth_a_look", n=len(notes)))
    times = [words.latest(x) for x in tallies.values()] + [r.created_at for r in notes + bare]
    last = max((x for x in times if x), default=None)
    title = t("held.title.sit") if why == "sit" else t("held.title.quiet")
    body = t("held.body", parts=words.join(parts), when=words.said_at(last, tz, now))

    if order:
        url = f"{SUMMARY_URL}?{urlencode({'species': ','.join(order)})}"
    else:
        url = next((r.url for r in reversed(rows) if r.url), SUMMARY_URL)
    return title, body, url, {"species": tallies, "held_for": why, "alerts": len(rows)}


def deliver_held(db: Session, now: datetime | None = None, user_ids=None) -> dict:
    """Send each person whose sit or quiet hours are over one message about what waited."""
    now = now or datetime.now(UTC)
    q = select(Notification.user_id).where(Notification.push_status == HELD).distinct()
    if user_ids is not None:
        q = q.where(Notification.user_id.in_(list(user_ids)))
    waiting = list(db.scalars(q).all())
    out = {"summaries": 0, "pushed": 0, "still_waiting": 0}
    if not waiting:
        return out
    on = sitting(db, now, waiting)
    for user_id in waiting:
        pref = db.get(NotificationPref, user_id)
        if reason(pref, user_id, now, on):
            out["still_waiting"] += 1
            continue
        rows = db.scalars(
            select(Notification)
            .where(Notification.user_id == user_id, Notification.push_status == HELD)
            .order_by(Notification.created_at)
            .with_for_update(skip_locked=True)
        ).all()
        if not rows:
            db.rollback()
            continue  # another deliverer has them
        if pref is None or not pref.enabled:
            # Alerts turned off while they waited: kept in the list, never sent.
            for r in rows:
                r.push_status = "skipped"
            db.commit()
            continue
        whys = [(r.detail or {}).get("held") for r in rows]
        why = "sit" if "sit" in whys else "quiet"
        with use(push.languages(db, [user_id]).get(user_id)):
            told = compose_held(rows, why, now, still_there(db, rows, pref))
        if told is None:
            # Everything that waited was marked "nothing in it", hidden or muted
            # since: no message about an animal no other screen shows.
            for r in rows:
                r.push_status = WITHDRAWN
            db.commit()
            out["withdrawn"] = out.get("withdrawn", 0) + 1
            continue
        title, body, url, detail = told
        for r in rows:
            r.push_status = "in_summary"
        n = Notification(user_id=user_id, kind="summary", title=title, body=body, url=url,
                         detail=detail, created_at=now)
        db.add(n)
        db.commit()  # marked before the push: a second deliverer finds nothing to send
        result = push.send_to_user(db, user_id, {
            "title": title, "body": body, "url": url, "tag": "held-summary",
            "renotify": True, "at": now.isoformat(),
        })
        n.push_status = push.delivery(result)
        db.commit()
        out["summaries"] += 1
        out["pushed"] += result["sent"]
    log.info("notify.held_delivered", **out)
    return out


def deliver_held_in_background(user_id: uuid.UUID) -> None:
    """deliver_held() for one person on its own session, after END SIT has answered."""
    from app.core import db as core_db

    try:
        with core_db.SessionLocal() as db:
            deliver_held(db, user_ids=[user_id])
    except Exception as e:  # a push service being down is not the sit's problem
        log.warning("notify.held_failed", error=f"{type(e).__name__}: {e}"[:200])
