"""Species classification pipeline: animal frame → detect box → crop → DeepFaune → Detection row."""
from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.ai.classifier import classify_crop
from app.ai.detector import detect_animals
from app.core.logging import get_logger
from app.models import Detection, Image, Species

log = get_logger(__name__)

PRIORITY = {"wild_boar", "red_deer", "roe_deer", "fallow_deer", "fox", "mouflon", "ibex", "badger"}


def _ensure_species(db: Session, key: str, name: str) -> None:
    if db.get(Species, key) is None:
        db.add(Species(id=key, common_name=name, is_priority=key in PRIORITY))
        db.flush()


def classify_image(db: Session, image: Image) -> str | None:
    boxes = detect_animals(image.original_path)
    bbox = max(boxes, key=lambda b: b["confidence"])["bbox"] if boxes else None
    result = classify_crop(image.original_path, bbox)
    if result is None:
        return None
    key, name, conf = result
    _ensure_species(db, key, name)
    db.add(Detection(
        image_id=image.id, species_id=key, species_conf=conf,
        bbox={"xyxy": bbox} if bbox else None,
    ))
    return key


def classify_unclassified(db: Session, *, limit: int = 2000) -> dict:
    has_detection = exists().where(Detection.image_id == Image.id)
    images = db.scalars(
        select(Image)
        .where(Image.is_empty_frame.is_(False), Image.original_path.isnot(None), ~has_detection)
        .order_by(Image.captured_at.desc())
        .limit(limit)
    ).all()
    counts: dict[str, int] = {}
    for i, image in enumerate(images, 1):
        try:
            key = classify_image(db, image)
            if key:
                counts[key] = counts.get(key, 0) + 1
        except Exception as e:
            log.warning("classify.failed", image=str(image.id), error=str(e))
        if i % 20 == 0:
            db.commit()
            log.info("classify.progress", done=i, total=len(images))
    db.commit()
    return {"classified": len(images), "by_species": counts}
