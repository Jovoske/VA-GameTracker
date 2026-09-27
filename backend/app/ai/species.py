"""Species classification: animal frame → detector boxes → crop → DeepFaune → Detection row.

Three rules keep a misread from reaching the hunter as a sighting:

* Only animals that can be on this estate are named (classifier.ESTATE_CLASSES), and
  only when the model is reasonably sure (SPECIES_FLOOR). Below that the photo is an
  "Animal" nobody has named, and the model's guess is kept with the sighting
  (bbox["guess"]) so the floor can be re-tuned without looking again.
* A burst is one animal: frames of one visit that the model reads differently are
  put to a vote (vote_bursts), so the feed does not flip red deer / fallow deer /
  red deer and one stag does not count as two species.
* A new species is only in the advice when it is the big game the evening advice
  is for (BIG_GAME). Every other animal is tracked but has to be switched into the
  advice in Settings: fox and rabbit are small game here, and badger is protected.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.ai.classifier import ESTATE_KEYS, classify_and_embed
from app.ai.detector import detect_animals
from app.ai.grouping import drop_nested, group_type
from app.core.logging import get_logger
from app.models import Detection, Image, Species

log = get_logger(__name__)

PRIORITY = {"wild_boar", "red_deer", "roe_deer", "fallow_deer", "fox", "mouflon", "ibex", "badger"}
# The big game the evening sits are for, so in the Tonight advice from the first
# sighting. Dogs, sheep, cows, birds (and badger, protected in Spain) used to join the
# advice too, and a farm dog could become a stand's "best species tonight". Fox and
# rabbit are small game here: tracked, and in the advice only if switched on.
BIG_GAME = {"wild_boar", "red_deer", "roe_deer", "fallow_deer", "mouflon", "ibex"}

# Below this the model is guessing: DeepFaune's own tool calls anything under 0.8
# "undefined". Lower here because a burst vote (vote_bursts) rescues the frames of
# a visit the model is sure about elsewhere.
SPECIES_FLOOR = 0.5

# Frames of one camera closer together than this are one visit for the vote. Shorter
# than the 30 minutes that separate visits in the counts, so a fox followed a few
# minutes later by a boar keeps both.
VOTE_GAP = timedelta(minutes=2)
# A frame the model is this sure of keeps its own answer whatever the rest say.
KEEP_OWN = 0.9


def _ensure_species(db: Session, key: str, name: str) -> None:
    if db.get(Species, key) is None:
        db.add(Species(id=key, common_name=name, is_priority=key in PRIORITY,
                       huntable=key in BIG_GAME))
        db.flush()


def classify_crop(image_path: str, bbox: list[float] | None):
    """(key, name, conf) and the crop's embedding; a seam the tests replace."""
    return classify_and_embed(image_path, bbox)


def classify_image(db: Session, image: Image, boxes: list[dict] | None = None) -> str | None:
    """Write the frame's sighting. Returns the species named, or None (none named).

    `boxes` are the detector's answer when the AI pass already has it; without them
    (a frame a hunter kept by hand) the detector runs here.
    """
    # Two runs must never both write one: counts and alerts would double. The photo's
    # row is locked first, so a second run (one that took over a stalled run's lock)
    # waits here until the first has committed its sighting, and then sees it.
    db.execute(select(Image.id).where(Image.id == image.id).with_for_update())
    if db.scalar(select(exists().where(Detection.image_id == image.id))):
        return None
    if boxes is None:
        boxes = detect_animals(image.original_path)
    animals = drop_nested(boxes)
    bbox = max(animals, key=lambda b: b["confidence"])["bbox"] if animals else None
    result = classify_crop(image.original_path, bbox)
    embedding = None
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], tuple):
        result, embedding = result
    if result is None:
        return None
    key, name, conf = result
    named = key if key in ESTATE_KEYS and conf >= SPECIES_FLOOR else None
    if named:
        _ensure_species(db, named, name)
    size, gtype = group_type(boxes, named)  # group composition from all boxes in the frame
    db.add(Detection(
        image_id=image.id, species_id=named, species_conf=conf,
        bbox={
            **({"xyxy": bbox} if bbox else {}),
            "boxes": [{"confidence": round(b["confidence"], 4), "bbox": b["bbox"]}
                      for b in boxes if b.get("bbox")],
            "guess": {"species": key, "name": name, "conf": conf},
        },
        group_size=size, group_type=gtype, embedding=embedding,
    ))
    db.flush()
    return named


def _own(det: Detection) -> tuple[str | None, float]:
    """The frame's own reading, before any vote: what the model said about it alone."""
    info = det.bbox if isinstance(det.bbox, dict) else {}
    own = info.get("own")
    if own is not None:
        return own.get("species"), float(own.get("conf") or 0.0)
    return det.species_id, float(det.species_conf or 0.0)


def _runs(rows: list[tuple[Detection, datetime]]) -> list[list[tuple[Detection, datetime]]]:
    runs: list[list] = []
    for det, at in rows:
        if runs and at - runs[-1][-1][1] <= VOTE_GAP:
            runs[-1].append((det, at))
        else:
            runs.append([(det, at)])
    return runs


def _names(db: Session) -> dict[str, str]:
    return dict(db.execute(select(Species.id, Species.common_name)).all())


def vote_bursts(db: Session, image_ids: list) -> int:
    """Give every frame of a visit the species the visit's frames agree on.

    The frames around each photo just classified (same camera, each within VOTE_GAP
    of the next) vote with their confidence; a species holding most of it wins, and
    frames the model read as something else, or could not name, take its label unless
    the model was sure of its own (KEEP_OWN). The vote is taken from each frame's own
    reading every time, so a frame that joins a visit later can change the outcome
    and nothing drifts. Returns how many sightings changed.
    """
    if not image_ids:
        return 0
    spans = db.execute(
        select(Image.camera_id, Image.captured_at).where(Image.id.in_(image_ids))
    ).all()
    by_camera: dict = {}
    for cam, at in spans:
        lo, hi = by_camera.get(cam, (at, at))
        by_camera[cam] = (min(lo, at), max(hi, at))
    changed = 0
    names: dict[str, str] | None = None
    for cam, (lo, hi) in by_camera.items():
        # Reach back and forward far enough to take in the whole visit.
        lo, hi = lo - VOTE_GAP * 15, hi + VOTE_GAP * 15
        rows = db.execute(
            select(Detection, Image.captured_at)
            .join(Image, Image.id == Detection.image_id)
            .where(Image.camera_id == cam, Image.captured_at >= lo, Image.captured_at <= hi,
                   Image.is_empty_frame.isnot(True))
            .order_by(Image.captured_at)
        ).all()
        for run in _runs([(r[0], r[1]) for r in rows]):
            weight: dict[str, float] = {}
            for det, _ in run:
                sp, conf = _own(det)
                if sp in ESTATE_KEYS:  # an older build's "moose" gets no vote
                    weight[sp] = weight.get(sp, 0.0) + conf
            winner = max(weight, key=weight.get) if weight else None
            # A frame sure of another species (a fox passing through) keeps its own and
            # has no say; the winner needs most of the rest.
            say = sum(c for sp, c in map(_own, (d for d, _ in run))
                      if sp in ESTATE_KEYS and (sp == winner or c < KEEP_OWN))
            if len(run) < 2 or winner is None or weight[winner] <= say / 2:
                winner = None  # no visit, or no majority: every frame keeps its own
            for det, _ in run:
                sp, conf = _own(det)
                keep = winner is None or sp == winner or (sp is not None and conf >= KEEP_OWN)
                label = sp if keep else winner
                if label == det.species_id:
                    continue
                names = names if names is not None else _names(db)
                if label is not None and label not in names:
                    continue  # never happens: a winner was named by some frame
                info = dict(det.bbox) if isinstance(det.bbox, dict) else {}
                info.setdefault("own", {"species": sp, "conf": conf})
                if label == sp:
                    info.pop("vote", None)
                    det.species_conf = conf
                else:
                    info["vote"] = {"species": label, "frames": len(run)}
                    mine = [_own(d)[1] for d, _ in run if _own(d)[0] == label]
                    det.species_conf = round(sum(mine) / len(mine), 4)
                # Stag/hind and boar/sow belong to the species they were judged as: a
                # hind relabelled wild boar is not a sow. The cloud pass looks at it
                # again as what it is now; "own" keeps the vote undoable.
                det.sex, det.sex_conf, det.sex_attempts, det.sex_checked_at = (
                    "unknown", None, 0, None)
                det.species_id = label
                boxes = info.get("boxes")
                if boxes is not None:
                    det.group_size, det.group_type = group_type(boxes, label)
                det.bbox = info
                changed += 1
    if changed:
        db.flush()
        log.info("species.voted", changed=changed)
    return changed
