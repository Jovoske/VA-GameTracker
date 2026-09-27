"""Flag empty frames with MegaDetector.

Conservative (per the hunter's request): only mark a frame empty when the
detector finds NO animal even at a low confidence. Stores the max confidence so
the threshold can be re-tuned without re-scanning, and never overrides a frame
the user has manually reviewed: the write itself checks, so a hunter's tap that
lands while the detector is looking at the same photo still wins.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from app.ai.detector import DETECT_CONF, detect_animals
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


def scan_image(db: Session, image: Image, boxes: list[dict] | None = None) -> bool:
    """Set is_empty_frame / animal_conf / processed_at. Returns True if kept (animal present).

    `boxes` are the detector's answer when the caller already has it (the AI pass
    detects once per frame and hands the boxes on to the species step). A detector
    failure is raised to the caller, which counts it against the photo: it is never
    stored as a judgement.
    """
    if image.reviewed:  # user has decided — never override
        return not bool(image.is_empty_frame)
    now = datetime.now(UTC)
    if not image.original_path:
        values = {"processed_at": now, "is_empty_frame": None, "animal_conf": None}
        kept = False
    else:
        if boxes is None:
            boxes = detect_animals(image.original_path)
        empty, conf = judge(boxes)
        values = {"processed_at": now, "is_empty_frame": empty, "animal_conf": conf,
                  "detector_conf": DETECT_CONF}
        kept = not empty
    if not _write(db, image, values):
        return not bool(image.is_empty_frame)
    return kept


def rescan_image(db: Session, image: Image, boxes: list[dict]) -> bool:
    """A frame judged empty at the detector's old 0.25 cut-off, looked at again at
    DETECT_CONF. True when there is an animal after all: it is kept, and stamped as
    checked now, so it shows as new on the map (routes_map.shown_after)."""
    empty, conf = judge(boxes)
    values = {"animal_conf": conf, "detector_conf": DETECT_CONF}
    if not empty:
        values.update(is_empty_frame=False, processed_at=datetime.now(UTC))
    return _write(db, image, values) and not empty


def no_file_given_up():
    """SQL: a photo with no file that the fetch has stopped trying to download.

    A photo whose file never downloaded is retried by the fetch for a while
    (ingestion.sync). Once the fetch has given up on it (or has no link to try), or
    past a day, it is let through as "no file", so one lost frame stops holding its
    whole night as "not checked yet"; if the file does come in later, the fetch sends
    the photo back to be checked.
    """
    from app.ingestion.sync import MAX_DOWNLOAD_ATTEMPTS

    return and_(Image.original_path.is_(None), or_(
        Image.download_attempts >= MAX_DOWNLOAD_ATTEMPTS,
        Image.cdn_url.is_(None), Image.cdn_url == "",
        Image.created_at < datetime.now(UTC) - MISSING_FILE_GRACE,
    ))
