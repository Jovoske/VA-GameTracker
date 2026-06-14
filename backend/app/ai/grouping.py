"""Group-composition typing from per-frame animal detections.

What night-IR trail-cam frames *can* tell us reliably: how many animals share a
frame, and whether a much-smaller (juvenile-sized) animal is among them. That
yields honest, useful classes — "sow with piglets" / "hind with calf" (breeding
groups) and sounder / herd sizes — without pretending to sex a lone adult, which
these images don't support. The species pipeline previously kept only the single
largest animal per frame and threw the rest away; this recovers the group signal.
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

_BOAR = {"wild_boar"}
_DEER = {"red_deer", "roe_deer", "fallow_deer"}


def _area(b: list[float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def group_type(boxes: list[dict], species_key: str | None) -> tuple[int, str]:
    """Return (group_size, group_type) from all animal boxes in one frame."""
    real = [b for b in boxes if b.get("confidence", 1.0) >= CONF]
    n = len(real)
    if n < 2:
        return max(n, 1), "solitary"
    areas = sorted(_area(b["bbox"]) for b in real)
    juvenile = areas[-1] > 0 and areas[0] / areas[-1] < JUV_RATIO
    if species_key in _BOAR:
        return n, "sow_with_piglets" if juvenile else "sounder"
    if species_key in _DEER:
        return n, "hind_with_calf" if juvenile else "herd"
    return n, "group"


def type_groups(db: Session, *, limit: int = 5000) -> dict:
    """Backfill group_size/group_type on existing detections by re-detecting frames."""
    rows = db.execute(
        select(Detection.id, Detection.species_id, Image.original_path)
        .join(Image, Detection.image_id == Image.id)
        .where(Image.original_path.isnot(None))
        .limit(limit)
    ).all()
    counts: dict[str, int] = {}
    for i, (det_id, sp, path) in enumerate(rows, 1):
        try:
            size, gtype = group_type(detect_animals(path), sp)
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
