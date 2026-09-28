"""The AI pass: every new photo checked once, frame by frame, newest first.

For each photo the detector looks once; an empty frame is marked so, and a kept one
goes straight on to the species model with the same boxes (it used to be detected
twice, in two passes). The sighting is committed with the photo, and every batch
of BATCH photos the visit vote runs and new sightings are announced, so tonight's
boar is labelled and pushed within seconds rather than after the whole backlog.

What used to go wrong, and what happens now:

* A model that cannot load (missing library, bad weights, no network for the
  download) used to fail once per photo, and each failure was stored as "checked,
  animal kept, no species": a broken model read as nights watched with nothing in
  them. Now both models load before any photo is touched; if one cannot, the pass
  stops at once, touches nothing, and says why (the admin status shows it).
* A failure on one photo is counted against it (ai_attempts) and tried again on the
  next runs; after MAX_AI_ATTEMPTS it is given up on (ai_failed_at) and shows as
  "couldn't check". It is never stored as a judgement, and its night stays "not
  checked" in the exposure table, never "watched, nothing seen".
* BREAKER photos failing in a row (or failures the run ends on) may be the models,
  not the photos: the models are tried on a plain test picture, and if they fail
  there too the pass stops without counting those failures against the photos.
* A run takes at most RUN_LIMIT photos or RUN_BUDGET of time, newest first, so a
  backlog (a new login's two months, a 13-month backfill) never holds the pipeline
  lock for hours: the next fetch comes, and the backlog drains a run at a time.
* A hunter's word is a check: flagging a photo the pass gave up on ("nothing in it"
  or Keep) clears the failure (hunter_decided), and a kept photo the species model
  still can't read becomes an "Animal" nobody has named, never "couldn't check".
* A run that lost its lock (it stalled and another run took over) stops at the next
  photo rather than checking the same photos alongside the new owner.
* A photo with an animal in it gets its small copy for the grids (app.thumbs) as soon
  as it is checked, so the Photos grid at dusk is quick from the first look (E-24).
* The same look records the people and vehicles in the frame (feature 25). Photos
  checked before that are looked at again for them, all of them back to the first,
  newest first, a few a run in daylight, like the frames judged at the old cut-off
  (those only the last RESCAN_DAYS).
"""
from __future__ import annotations

import os
import tempfile
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app import jobs, thumbs
from app.ai import empty_filter, species
from app.ai.detector import DETECT_CONF, detect, detect_animals, split
from app.core.config import settings
from app.core.logging import get_logger
from app.i18n import stored
from app.models import Detection, Image

log = get_logger(__name__)

STATUS = "ai_status"  # app_settings key the admin status reads
MAX_AI_ATTEMPTS = 3
BREAKER = 5
BATCH = 20
RUN_LIMIT = int(os.environ.get("AI_LIMIT_PER_RUN", "300"))
RUN_BUDGET = timedelta(minutes=int(os.environ.get("AI_MINUTES_PER_RUN", "10")))

# Frames the detector judged empty at its old 0.25 cut-off (detector_conf NULL) are
# looked at again at DETECT_CONF, the last RESCAN_DAYS; frames checked before people
# and vehicles were looked for (person_conf NULL) are looked at for them, however old:
# a walker from last spring is in the team's feed until then (R6BE-4). Newest first,
# a few a run, in daylight only, so it never slows the photos that matter at dusk.
RESCAN_DAYS = 30
RESCAN_PER_RUN = 100
RESCAN_HOURS = range(8, 16)

_HAS_DETECTION = exists().where(Detection.image_id == Image.id)

# SQL predicates on Image. Waiting: the detector or the species model still has to
# look at it. Not checked: waiting, given up on, or anything else the exposure table
# must not count as a watched night (a photo with no file yet, one a hunter kept
# that has no sighting yet).
AWAITING_DETECTOR = and_(
    Image.processed_at.is_(None), Image.reviewed.is_(False), Image.original_path.isnot(None),
    Image.ai_failed_at.is_(None),
)
AWAITING_SPECIES = and_(
    Image.is_empty_frame.is_(False), Image.original_path.isnot(None), ~_HAS_DETECTION,
    Image.ai_failed_at.is_(None),
)
WAITING = or_(AWAITING_DETECTOR, AWAITING_SPECIES)
# Judged empty at the detector's old 0.25 cut-off (empty_filter.old_rule_empty).
OLD_RULE_EMPTY = and_(Image.is_empty_frame.is_(True), Image.reviewed.is_(False),
                      Image.detector_conf.is_(None))
LOST_FILE = and_(Image.original_path.is_(None), Image.spypoint_photo_id.isnot(None),
                 Image.reviewed.is_(False))
NOT_CHECKED = or_(
    Image.processed_at.is_(None), Image.ai_failed_at.isnot(None),
    and_(Image.is_empty_frame.is_(False), Image.original_path.isnot(None), ~_HAS_DETECTION),
    # A SPYPOINT photo whose file never came (a download given up on, or still being
    # tried): nobody knows what triggered it, so its night is not one watched with
    # nothing in it (E-01). UBox keeps no row for a snapshot it couldn't fetch, and
    # an FTP or email photo always arrives with its file.
    LOST_FILE,
)


def _short(e: BaseException) -> str:
    text = str(e).strip().splitlines()[0] if str(e).strip() else ""
    return f"{type(e).__name__}: {text}"[:300] if text else type(e).__name__


def load_models() -> str | None:
    """Load both models once. None when they are ready, else why not, in words."""
    from app.ai import classifier, detector

    for what, load in (("ai.detector_failed", detector.load),
                       ("ai.classifier_failed", classifier.load)):
        try:
            load()
        except Exception as e:  # ImportError, a failed download, weights that won't load
            return stored(what, error=_short(e))
    return None


def models_work() -> str | None:
    """Both models on a plain grey test picture: None when they answer, else why not."""
    from PIL import Image as PILImage

    fd, path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    try:
        PILImage.new("RGB", (320, 240), (90, 90, 90)).save(path)
        detect_animals(path)
        species.classify_crop(path, None)
        return None
    except Exception as e:
        return stored("ai.models_broken", error=_short(e))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def let_through_missing(db: Session) -> int:
    """Photos with no file that the fetch has given up on: nothing for the models to
    look at, so they are passed as "no file" (no model needed)."""
    images = db.scalars(
        select(Image).where(
            Image.processed_at.is_(None), Image.reviewed.is_(False),
            empty_filter.no_file_given_up(),
        ).limit(5000)
    ).all()
    for image in images:
        empty_filter.scan_image(db, image)
    db.commit()
    return len(images)


def check_image(db: Session, image: Image) -> str:
    """Detector, then species, for one photo. What came of it: "empty", "skipped"
    (a hunter got there first), the species named, or "animal" (none named)."""
    animals = None
    if image.processed_at is None and not image.reviewed:
        boxes = detect(image.original_path)
        if not empty_filter.scan_image(db, image, boxes=boxes):
            return "empty"
        animals = split(boxes)[0]
    if image.is_empty_frame is not False:
        return "skipped"
    return species.classify_image(db, image, boxes=animals) or "animal"


def hunter_decided(image: Image, *, keep: bool) -> None:
    """A hunter flagged the photo ("nothing in it", or Keep): that is a check.

    A photo the pass gave up on used to keep saying "Couldn't check" after a hunter
    had judged it, and its night stayed not checked for good. Now the failure is
    cleared: an empty one is empty, and a kept one gets one more try at naming the
    animal (then it is an "Animal" nobody has named, see _record_failures).
    """
    if image.ai_failed_at is None:
        return
    image.ai_failed_at = None
    image.ai_attempts = MAX_AI_ATTEMPTS - 1 if keep else 0
    if not keep:
        image.ai_error = None


def _record_failures(db: Session, failures: list[tuple], now: datetime) -> int:
    """Count a failed try against each photo; given up on after MAX_AI_ATTEMPTS."""
    given_up = 0
    for image_id, error in failures:
        row = db.execute(
            select(Image.ai_attempts, Image.reviewed, Image.is_empty_frame)
            .where(Image.id == image_id)
        ).first()
        if row is None:
            continue
        attempts = (row.ai_attempts or 0) + 1
        done = attempts >= MAX_AI_ATTEMPTS
        # Kept by a hunter: there is an animal in it, the model just can't say which.
        # It becomes an "Animal" nobody has named (as one under the floor is), and
        # the hunter's word stands, never "couldn't check".
        kept = bool(row.reviewed) and row.is_empty_frame is False
        if done and kept and not db.scalar(
            select(exists().where(Detection.image_id == image_id))
        ):
            db.add(Detection(image_id=image_id, species_id=None,
                             bbox={"boxes": [], "error": error}))
        db.execute(
            update(Image).where(Image.id == image_id).values(
                ai_attempts=attempts, ai_error=error,
                ai_failed_at=now if done and not kept else None,
            ).execution_options(synchronize_session="fetch")
        )
        given_up += done and not kept
        log.warning("ai.photo_failed", image=str(image_id), attempts=attempts, error=error)
    db.commit()
    return given_up


def _thumb(db: Session, image: Image) -> None:
    """The small copy the grids show, made now so the first look at dusk is quick. A
    failure never holds the pass up: the first request for it makes it instead."""
    try:
        if thumbs.ensure_thumb(image):
            db.commit()
    except Exception as e:  # a corrupt file, an odd format, a full disk
        db.rollback()
        log.warning("thumb.failed", image_id=str(image.id), error=_short(e))


def _announce(db: Session) -> None:
    # A sighting exists from this moment, so this is where it is announced. It may
    # never fail the pass: a push service being down is no reason to leave photos
    # unchecked, and the watermark means the next batch picks up anything missed.
    try:
        from app.notifications.dispatch import dispatch_new_sightings

        dispatch_new_sightings(db)
    except Exception as e:
        log.warning("notify.failed", error=str(e)[:300])
        db.rollback()


# What a photo the AI has not finished with is called where its species would be
# (keys: said in the reader's language).
NOT_CHECKED_YET = "photos.not_checked"
COULD_NOT_CHECK = "photos.could_not_check"


def photo_states(db: Session, image_ids: list) -> dict:
    """{image_id: "waiting" | "failed"} for the photos the AI has not finished with.

    Waiting: the detector or the species model has yet to look at it. Failed: it was
    given up on after MAX_AI_ATTEMPTS. The rest are absent. A frame used to show as
    "Animal" / "Unknown animal" in both cases, which read as a sighting nobody could
    name, and when the AI was broken, every photo said so.
    """
    if not image_ids:
        return {}
    rows = db.execute(
        select(Image.id, Image.ai_failed_at.isnot(None), WAITING).where(Image.id.in_(image_ids))
    ).all()
    return {r[0]: "failed" if r[1] else "waiting" for r in rows if r[1] or r[2]}


def waiting_count(db: Session) -> int:
    return db.scalar(select(func.count(Image.id)).where(WAITING)) or 0


def failed_count(db: Session) -> int:
    return db.scalar(select(func.count(Image.id)).where(Image.ai_failed_at.isnot(None))) or 0


# How far back Admin counts photos whose file never came.
LOST_DAYS = 30


def lost_count(db: Session) -> int:
    """Photos of the last LOST_DAYS whose file the fetch gave up on: their nights
    count as not watched rather than as nights with nothing in them."""
    since = datetime.now(UTC) - timedelta(days=LOST_DAYS)
    return db.scalar(select(func.count(Image.id)).where(
        empty_filter.no_file_given_up(), LOST_FILE, Image.captured_at >= since)) or 0


def _rescan_ids(db: Session, now: datetime, room: int) -> list:
    local = now.astimezone(ZoneInfo(settings.estate_timezone))
    if room <= 0 or local.hour not in RESCAN_HOURS:
        return []
    # Checked (by the detector or a hunter) before people were looked for, at any
    # age. One still waiting for the detector is looked at for them on its first look.
    no_people_look = and_(Image.person_conf.is_(None),
                          or_(Image.processed_at.isnot(None), Image.reviewed.is_(True)))
    old_rule = and_(OLD_RULE_EMPTY, Image.captured_at >= now - timedelta(days=RESCAN_DAYS))
    return list(db.scalars(
        select(Image.id).where(
            or_(old_rule, no_people_look), Image.original_path.isnot(None),
            Image.ai_failed_at.is_(None),
        ).order_by(Image.captured_at.desc()).limit(min(room, RESCAN_PER_RUN))
    ).all())


class _Stop(Exception):
    pass


def check_photos(db: Session, *, limit: int | None = None, budget: timedelta | None = None,
                 now: datetime | None = None) -> dict:
    """Check the photos waiting for the AI, newest first, up to `limit` or `budget`."""
    now = now or datetime.now(UTC)
    limit = RUN_LIMIT if limit is None else limit
    deadline = time.monotonic() + (budget or RUN_BUDGET).total_seconds()
    result: dict = {"checked": 0, "empty": 0, "animal": 0, "by_species": {}, "failed": 0,
                    "given_up": 0, "rescanned": 0, "found_on_rescan": 0}
    result["no_file"] = let_through_missing(db)

    ids = list(db.scalars(
        select(Image.id).where(WAITING).order_by(Image.captured_at.desc()).limit(limit)
    ).all())
    rescan = _rescan_ids(db, now, limit - len(ids))
    if not ids and not rescan:
        jobs.note(db, STATUS, last_run_at=now, stopped=None, waiting=0)
        return {**result, "status": "ok", "waiting": 0}

    reason = load_models()
    if reason:
        log.error("ai.stopped", reason=reason)
        jobs.note(db, STATUS, last_run_at=now, stopped=reason, last_error=reason,
                  last_error_at=now, waiting=waiting_count(db))
        return {**result, "status": "stopped", "reason": reason, "waiting": waiting_count(db)}

    streak: list[tuple] = []
    last_error = None
    touched: list = []

    def settle_streak(stop_if_models_broken: bool) -> None:
        nonlocal streak
        if not streak:
            return
        if stop_if_models_broken:
            why = models_work()
            if why:
                raise _Stop(stored("ai.stopped_streak", why=why, n=len(streak)))
        result["failed"] += len(streak)
        result["given_up"] += _record_failures(db, streak, now)
        streak = []

    stopped = None
    lost = False
    try:
        for n, image_id in enumerate(ids, 1):
            if time.monotonic() > deadline:
                break
            if jobs.lock_lost():
                lost = True
                break
            image = db.get(Image, image_id, populate_existing=True)
            if image is None:
                continue
            try:
                outcome = check_image(db, image)
                db.commit()
            except Exception as e:
                db.rollback()
                last_error = _short(e)
                streak.append((image_id, last_error))
                if len(streak) >= BREAKER:
                    settle_streak(stop_if_models_broken=True)
                continue
            # The model works: the photos that failed before this one are the problem.
            settle_streak(stop_if_models_broken=False)
            if image.ai_attempts:
                image.ai_attempts, image.ai_error = 0, None
                db.commit()
            if outcome not in ("empty", "skipped"):
                _thumb(db, image)
            touched.append(image_id)
            result["checked"] += 1
            if outcome == "empty":
                result["empty"] += 1
            elif outcome != "skipped":
                result["animal"] += 1
                if outcome != "animal":
                    result["by_species"][outcome] = result["by_species"].get(outcome, 0) + 1
            if n % BATCH == 0:
                species.vote_bursts(db, touched)
                db.commit()
                _announce(db)
                touched = []
                log.info("ai.progress", done=n, total=len(ids), **{
                    k: result[k] for k in ("empty", "animal", "failed")})
        # Failures with no success after them may be the models: test before counting.
        settle_streak(stop_if_models_broken=True)

        for image_id in rescan:
            if lost or time.monotonic() > deadline or jobs.lock_lost():
                break
            image = db.get(Image, image_id, populate_existing=True)
            if image is None or not image.original_path or (
                image.person_conf is not None and not empty_filter.old_rule_empty(image)
            ):
                continue
            # Older than the old cut-off's window: looked at for people only.
            recent = image.captured_at >= now - timedelta(days=RESCAN_DAYS)
            try:
                boxes = detect(image.original_path)
                if empty_filter.rescan_image(db, image, boxes, animals_too=recent):
                    result["found_on_rescan"] += 1
                    touched.append(image_id)
                    species.classify_image(db, image, boxes=split(boxes)[0])
                db.commit()
                result["rescanned"] += 1
            except Exception as e:
                db.rollback()
                last_error = _short(e)
                why = models_work()
                if why:
                    raise _Stop(why) from e
                # The photo is the problem: leave it as it was judged, and move on.
                db.execute(update(Image).where(Image.id == image_id)
                           .values(detector_conf=case((OLD_RULE_EMPTY, DETECT_CONF),
                                                      else_=Image.detector_conf),
                                   person_conf=func.coalesce(Image.person_conf, 0.0),
                                   vehicle_conf=func.coalesce(Image.vehicle_conf, 0.0))
                           .execution_options(synchronize_session=False))
                db.commit()
    except _Stop as e:
        db.rollback()
        stopped = str(e)
        log.error("ai.stopped", reason=stopped)

    species.vote_bursts(db, touched)
    db.commit()
    _announce(db)
    waiting = waiting_count(db)
    if lost:
        # The run that took the lock over carries on and says how it went.
        log.warning("ai.lock_lost", **{k: result[k] for k in ("checked", "failed")})
        return {**result, "status": "lost", "reason": None, "waiting": waiting}
    fields = {"last_run_at": now, "stopped": stopped, "waiting": waiting,
              "checked": result["checked"]}
    if stopped or last_error:
        fields.update(last_error=stopped or last_error, last_error_at=now)
    if not stopped:
        fields["last_ok_at"] = now
    jobs.note(db, STATUS, **fields)
    log.info("ai.done", waiting=waiting, stopped=stopped, **{
        k: v for k, v in result.items() if k != "by_species"}, by_species=result["by_species"])
    return {**result, "status": "stopped" if stopped else "ok", "reason": stopped,
            "waiting": waiting}


def retry_failed(db: Session) -> int:
    """Give the photos the pass gave up on another round of tries (after a fix)."""
    n = db.execute(
        update(Image).where(Image.ai_failed_at.isnot(None))
        .values(ai_failed_at=None, ai_attempts=0, ai_error=None)
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    return n
