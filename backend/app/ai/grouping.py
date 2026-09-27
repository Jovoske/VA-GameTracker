"""Group-composition typing from per-frame animal detections.

What night-IR trail-cam frames *can* tell us reliably: how many animals share a
frame, and whether a much-smaller (juvenile-sized) animal is among them. That
yields honest, useful classes — "sow with piglets" / "hind with calf" (breeding
groups) and sounder / herd sizes — without pretending to sex a lone adult, which
these images don't support. The species pipeline previously kept only the single
largest animal per frame and threw the rest away; this recovers the group signal.

Two things make a small box look like a youngster when it is not, and both used to
turn a lone boar into "Sow + piglets": the detector boxing the head or forequarters
of a close animal as well as the whole of it (a box inside a box), and a second adult
standing further back (smaller because it is further away). Boxes mostly inside a
bigger one are dropped before counting, and a smaller animal is only juvenile-sized
when it stands on about the same ground line as the big one.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.detector import detect_animals
from app.core.logging import get_logger
from app.models import Detection, Image

log = get_logger(__name__)

CONF = 0.2          # ignore low-confidence boxes when counting a group
JUV_RATIO = 0.4     # a box under 40% of the largest animal's area = juvenile-sized
NESTED = 0.8        # a box this much inside a bigger one is part of that animal
# A smaller animal whose feet are further up the frame than the big one's by more than
# this (in heights of the big one) is further away, not younger.
SAME_GROUND = 0.25

_BOAR = {"wild_boar"}
_DEER = {"red_deer", "roe_deer", "fallow_deer"}


def _area(b: list[float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inside(small: list[float], big: list[float]) -> float:
    """How much of `small` lies inside `big`, 0..1."""
    w = min(small[2], big[2]) - max(small[0], big[0])
    h = min(small[3], big[3]) - max(small[1], big[1])
    area = _area(small)
    return max(0.0, w) * max(0.0, h) / area if area > 0 else 1.0


def drop_nested(boxes: list[dict]) -> list[dict]:
    """The boxes that are animals of their own: a box mostly inside a bigger one (the
    head or forequarters of the same animal) is dropped. Biggest first."""
    kept: list[dict] = []
    for b in sorted(boxes, key=lambda b: _area(b["bbox"]), reverse=True):
        if not any(_inside(b["bbox"], k["bbox"]) >= NESTED for k in kept):
            kept.append(b)
    return kept


def _young_beside(small: list[float], big: list[float]) -> bool:
    """Juvenile-sized and standing beside (or in front of) the big one, not further back."""
    if _area(big) <= 0 or _area(small) / _area(big) >= JUV_RATIO:
        return False
    height = big[3] - big[1]
    return height > 0 and small[3] >= big[3] - SAME_GROUND * height


def group_type(boxes: list[dict], species_key: str | None) -> tuple[int, str]:
    """Return (group_size, group_type) from all animal boxes in one frame."""
    real = drop_nested([b for b in boxes if b.get("confidence", 1.0) >= CONF and b.get("bbox")])
    n = len(real)
    if n < 2:
        return max(n, 1), "solitary"
    biggest = real[0]["bbox"]
    juvenile = any(_young_beside(b["bbox"], biggest) for b in real[1:])
    if species_key in _BOAR:
        return n, "sow_with_piglets" if juvenile else "sounder"
    if species_key in _DEER:
        return n, "hind_with_calf" if juvenile else "herd"
    return n, "group"


def type_groups(db: Session, *, limit: int = 5000) -> dict:
    """Backfill group_size/group_type on existing detections: from the boxes the
    species pass stored with them, or by re-detecting frames stored before it did."""
    rows = db.execute(
        select(Detection.id, Detection.species_id, Detection.bbox, Image.original_path)
        .join(Image, Detection.image_id == Image.id)
        .where(Image.original_path.isnot(None))
        .limit(limit)
    ).all()
    counts: dict[str, int] = {}
    for i, (det_id, sp, bbox, path) in enumerate(rows, 1):
        try:
            stored = bbox.get("boxes") if isinstance(bbox, dict) else None
            size, gtype = group_type(stored if stored is not None else detect_animals(path), sp)
            det = db.get(Detection, det_id)
            det.group_size, det.group_type = size, gtype
            counts[gtype] = counts.get(gtype, 0) + 1
        except Exception as e:  # missing file / decode error — skip
            log.warning("group.failed", detection=str(det_id), error=str(e))
        if i % 25 == 0:
            db.commit()
    db.commit()
    log.info("group.typed", **counts)
    return {"typed": len(rows), "by_type": counts}
