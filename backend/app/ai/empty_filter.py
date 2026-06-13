"""Flag empty frames with MegaDetector.

Conservative (per the hunter's request): only mark a frame empty when the
detector finds NO animal even at a low confidence. Stores the max confidence so
the threshold can be re-tuned without re-scanning, and never overrides a frame
the user has manually reviewed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.detector import detect_animals
from app.core.logging import get_logger
from app.models import Image

log = get_logger(__name__)

# Low on purpose: keep faint/partial animals. Below this with no boxes => empty.
ANIMAL_THRESHOLD = 0.10


def scan_image(db: Session, image: Image) -> bool:
    """Set is_empty_frame / animal_conf / processed_at. Returns True if kept (animal present)."""
    if image.reviewed:  # user has decided — never override
        return not bool(image.is_empty_frame)
    image.processed_at = datetime.now(timezone.utc)
    if not image.original_path:
        image.is_empty_frame = None
        image.animal_conf = None
        return False
    try:
        animals = detect_animals(image.original_path)
    except Exception as e:
        log.warning("detector.failed", image=str(image.id), error=str(e))
        image.is_empty_frame = False  # on error, KEEP — never drop on uncertainty
        return True
    max_conf = max((a["confidence"] for a in animals), default=0.0)
    image.animal_conf = round(max_conf, 4)
    image.is_empty_frame = max_conf < ANIMAL_THRESHOLD
    return not image.is_empty_frame


def scan_unprocessed(db: Session, *, limit: int = 5000, only_unprocessed: bool = True) -> dict:
    q = select(Image).where(Image.original_path.isnot(None), Image.reviewed.is_(False))
    if only_unprocessed:
        q = q.where(Image.processed_at.is_(None))
    images = db.scalars(q.order_by(Image.captured_at.desc()).limit(limit)).all()
    animal = empty = 0
    for i, image in enumerate(images, 1):
        if scan_image(db, image):
            animal += 1
        else:
            empty += 1
        if i % 25 == 0:
            db.commit()
            log.info("scan.progress", done=i, total=len(images), animal=animal, empty=empty)
    db.commit()
    return {"scanned": len(images), "animal": animal, "empty": empty}
