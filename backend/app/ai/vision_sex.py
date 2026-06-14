"""Sex / class from a vision model — stag vs hind, boar vs sow (opt-in, cloud).

The local species model (DeepFaune) classifies species only; it cannot read antlers
or sexual characteristics. This sends the animal crop to Claude's vision model for the
one cue that's reliable on these images — antlers (stag vs hind) — plus a cautious
attempt at boar sex. It is deliberately conservative: when the deciding feature isn't
visible, it returns 'unknown' rather than guessing. Needs ANTHROPIC_API_KEY in the
environment; nothing else in the app depends on it.
"""
from __future__ import annotations

import base64
import io

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing_extensions import Literal

from app.core.logging import get_logger
from app.models import Detection, Image

log = get_logger(__name__)

MODEL = "claude-opus-4-8"  # best vision / high-res perception; one-time labelling pass
_DEER = {"red_deer", "roe_deer", "fallow_deer"}
_BOAR = {"wild_boar"}

_DEER_PROMPT = (
    "This is a single red deer in a European trail-camera photo — often night-time "
    "infrared (grayscale). Decide if it is a STAG (male) or a HIND (female). The "
    "reliable cue is ANTLERS: stags carry antlers (in June they are growing and "
    "velvet-covered, but still show as branched beams above the head); hinds never have "
    "antlers. Body bulk and neck thickness are weak secondary cues. If the head/antler "
    "area is not clearly visible, or the animal is too distant or blurred to judge, "
    "answer sex='unknown'. Map stag->male, hind->female. Set label to 'stag', 'hind', or "
    "'unknown'. cues = exactly what you saw (e.g. 'branched antlers above head', 'no "
    "antlers, slender head', 'rump only, head out of frame')."
)
_BOAR_PROMPT = (
    "This is a single wild boar in a European trail-camera photo, often night-time "
    "infrared. Decide if it is a male BOAR or a female SOW. This is genuinely hard from "
    "photos — only commit to male/female when a clear cue is visible: males are bulkier "
    "with a pronounced shoulder/shield and may show tusks; females are rounder, may show "
    "a visible udder/teats when nursing, and are often beside striped piglets. With no "
    "clear cue, answer sex='unknown'. Map boar->male, sow->female. Set label to 'boar', "
    "'sow', or 'unknown'. cues = exactly what you saw."
)


class SexCall(BaseModel):
    sex: Literal["male", "female", "unknown"]
    label: str
    confidence: float
    cues: str


def _b64_crop(image_path: str, bbox: list[float] | None) -> str:
    """Padded JPEG crop (extra headroom for antlers), base64-encoded."""
    from PIL import Image as PILImage

    img = PILImage.open(image_path).convert("RGB")
    if bbox:
        x1, y1, x2, y2 = bbox
        w, h = x2 - x1, y2 - y1
        x1, x2 = x1 - 0.20 * w, x2 + 0.20 * w
        y1, y2 = y1 - 0.55 * h, y2 + 0.20 * h  # generous top pad — antlers sit above the box
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img.width, x2), min(img.height, y2)
        img = img.crop((int(x1), int(y1), int(x2), int(y2)))
    img.thumbnail((768, 768))  # enough detail for antlers, keeps token cost modest
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return base64.standard_b64encode(buf.getvalue()).decode()


def classify_sex(image_path: str, bbox: list[float] | None, species_key: str | None) -> SexCall | None:
    """Ask the vision model for sex/class of one animal crop. None if species isn't supported."""
    if species_key in _DEER:
        prompt = _DEER_PROMPT
    elif species_key in _BOAR:
        prompt = _BOAR_PROMPT
    else:
        return None
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    resp = client.messages.parse(
        model=MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg",
                    "data": _b64_crop(image_path, bbox),
                }},
                {"type": "text", "text": prompt},
            ],
        }],
        output_format=SexCall,
    )
    return resp.parsed_output


def _bbox_of(det: Detection) -> list[float] | None:
    return det.bbox.get("xyxy") if isinstance(det.bbox, dict) else None


def sample(db: Session, species_key: str, n: int = 12) -> list[dict]:
    """Classify n crops WITHOUT saving — for eyeballing accuracy before a full run."""
    rows = db.execute(
        select(Detection, Image)
        .join(Image, Detection.image_id == Image.id)
        .where(Detection.species_id == species_key, Image.original_path.isnot(None))
        .order_by(Detection.species_conf.desc().nullslast())
        .limit(n)
    ).all()
    out = []
    for det, img in rows:
        try:
            r = classify_sex(img.original_path, _bbox_of(det), species_key)
            out.append({
                "image_id": str(img.id), "captured_at": img.captured_at.isoformat(),
                "sex": r.sex, "label": r.label,
                "confidence": round(r.confidence, 2), "cues": r.cues,
            })
        except Exception as e:
            out.append({"image_id": str(img.id), "error": str(e)})
    return out


def sex_unclassified(db: Session, species_key: str, *, limit: int = 500) -> dict:
    """Store sex + sex_conf for detections of a species that don't have it yet."""
    rows = db.execute(
        select(Detection, Image)
        .join(Image, Detection.image_id == Image.id)
        .where(
            Detection.species_id == species_key,
            Detection.sex == "unknown",
            Image.original_path.isnot(None),
        )
        .limit(limit)
    ).all()
    counts: dict[str, int] = {}
    for i, (det, img) in enumerate(rows, 1):
        try:
            r = classify_sex(img.original_path, _bbox_of(det), species_key)
            if r and r.sex != "unknown":
                det.sex, det.sex_conf = r.sex, round(r.confidence, 4)
                counts[r.label] = counts.get(r.label, 0) + 1
        except Exception as e:
            log.warning("vision_sex.failed", detection=str(det.id), error=str(e))
        if i % 20 == 0:
            db.commit()
    db.commit()
    log.info("vision_sex.done", species=species_key, **counts)
    return {"processed": len(rows), "by_label": counts}
