"""Flag empty frames with MegaDetector.

Conservative (per the hunter's request): only mark a frame empty when the
detector finds NO animal even at a low confidence. Stores the max confidence so
the threshold can be re-tuned without re-scanning, and never overrides a frame
the user has manually reviewed: the write itself checks, so a hunter's tap that
lands while the detector is looking at the same photo still wins.

The same look records the people and vehicles in the frame (person_conf,
vehicle_conf): they are not the hunter's call, so they are stored whatever the
photo was flagged as (api/visibility.PEOPLE decides what they mean).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from app.ai.detector import DETECT_CONF, detect, split
from app.core.logging import get_logger
from app.models import Image

log = get_logger(__name__)

# Low on purpose: keep faint/partial animals. Below this with no boxes => empty.
ANIMAL_THRESHOLD = 0.10
# How long a photo with no file waits for its download to be retried before it is
# passed as unreadable rather than left "not checked yet" (see no_file_given_up).
MISSING_FILE_GRACE = timedelta(hours=24)


def judge(boxes: list[dict]) -> tuple[bool, float]:
    """(empty, the surest box's confidence) for the detector's boxes in one frame."""
    max_conf = max((b["confidence"] for b in boxes), default=0.0)
    return max_conf < ANIMAL_THRESHOLD, round(max_conf, 4)


def _write(db: Session, image: Image, values: dict) -> bool:
    """Store the detector's call unless a hunter has flagged the photo meanwhile.

    The row is updated only while it is still unreviewed, in one statement, so a flag
    committed a moment ago (or waiting on this row) is never overwritten. False when
    the hunter got there first; the photo then shows what they said.
    """
    done = db.execute(
        update(Image).where(Image.id == image.id, Image.reviewed.is_(False)).values(**values)
        .execution_options(synchronize_session="fetch")
    ).rowcount
    if not done:
        db.refresh(image)
    return bool(done)


def note_people(db: Session, image: Image, person: float, vehicle: float) -> None:
    """Store the surest person and vehicle the detector saw in the frame (0 for none)."""
    db.execute(
        update(Image).where(Image.id == image.id)
        .values(person_conf=person, vehicle_conf=vehicle)
        .execution_options(synchronize_session="fetch")
    )


def scan_image(db: Session, image: Image, boxes: list[dict] | None = None) -> bool:
    """Set is_empty_frame / animal_conf / processed_at. Returns True if kept (animal present).

    `boxes` are the detector's answer when the caller already has it (the AI pass
    detects once per frame and hands the boxes on to the species step): detector.detect's,
    people and vehicles included. A detector failure is raised to the caller, which
    counts it against the photo: it is never stored as a judgement.
    """
    if image.reviewed:  # user has decided — never override
        return not bool(image.is_empty_frame)
    now = datetime.now(UTC)
    if not image.original_path:
        values = {"processed_at": now, "is_empty_frame": None, "animal_conf": None}
        kept = False
    else:
        if boxes is None:
            boxes = detect(image.original_path)
        animals, person, vehicle = split(boxes)
        note_people(db, image, person, vehicle)
        empty, conf = judge(animals)
        values = {"processed_at": now, "is_empty_frame": empty, "animal_conf": conf,
                  "detector_conf": DETECT_CONF}
        kept = not empty
    if not _write(db, image, values):
        return not bool(image.is_empty_frame)
    return kept


def old_rule_empty(image: Image) -> bool:
    """Judged empty at the detector's old 0.25 cut-off, and nobody has said otherwise."""
    return image.is_empty_frame is True and not image.reviewed and image.detector_conf is None


def rescan_image(db: Session, image: Image, boxes: list[dict], *,
                 animals_too: bool = True) -> bool:
    """A frame looked at again: for the people and vehicles in it (a frame checked
    before they were looked for), and, when it was judged empty at the detector's
    old 0.25 cut-off (old_rule_empty) and `animals_too` (a recent one), for an animal
    at DETECT_CONF. True when there is an animal after all: it is kept, and stamped as
    checked now, so it shows as new on the map (routes_map.shown_after)."""
    animals, person, vehicle = split(boxes)
    note_people(db, image, person, vehicle)
    if not animals_too or not old_rule_empty(image):
        return False
    empty, conf = judge(animals)
    values = {"animal_conf": conf, "detector_conf": DETECT_CONF}
    if not empty:
        values.update(is_empty_frame=False, processed_at=datetime.now(UTC))
    return _write(db, image, values) and not empty


def no_file_given_up():
    """SQL: a photo with no file that the fetch has stopped trying to download.

    A photo whose file never downloaded is retried by the fetch for a while
    (ingestion.sync). Once the fetch has given up on it (or has no link to try), or
    past a day, the AI pass stops waiting for it and lets it through as "no file".
    Its night still counts as not watched (checking.NOT_CHECKED): nobody knows what
    triggered it, so it is never a night with nothing in it. If the file does come in
    later, the fetch sends the photo back to be checked.
    """
    from app.ingestion.sync import MAX_DOWNLOAD_ATTEMPTS

    return and_(Image.original_path.is_(None), or_(
        Image.download_attempts >= MAX_DOWNLOAD_ATTEMPTS,
        Image.cdn_url.is_(None), Image.cdn_url == "",
        Image.created_at < datetime.now(UTC) - MISSING_FILE_GRACE,
    ))
