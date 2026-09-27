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

A hunter has the last word: a species fixed from the photo viewer (set_by_hand) is
never changed by the AI again, and votes in its visit as a sure frame.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from app.ai.classifier import ESTATE_KEYS, classify_and_embed, default_name
from app.ai.detector import detect_animals
from app.ai.grouping import drop_nested, group_type
from app.core.logging import get_logger
from app.models import Detection, DetectionIndividual, Image, Individual, Species

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
    """The frame's own reading, before any vote: what the model said about it alone.
    A frame a hunter fixed reads as they said, and as sure as can be."""
    if det.corrected_at is not None:
        return det.species_id, 1.0
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
                if det.corrected_at is not None:
                    continue  # a hunter's fix: never the vote's to change
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


# What the AI had said about a sighting before a hunter fixed it, kept in its bbox
# JSON under this key so the fix can be taken back ("Put back what the AI said"). A
# sighting the hunter added to a photo the AI had nothing on is marked BY_HAND.
_AI = "ai"
BY_HAND = "by_hand"


def set_by_hand(db: Session, image: Image, key: str, user_id: uuid.UUID | None,
                now: datetime | None = None) -> None:
    """A hunter says the animal in `image` is `key` (the photo viewer's "Wrong?").

    Every sighting on the photo becomes that species and is marked as theirs
    (corrected_at, corrected_by): the AI never changes it again, and every count,
    the forecast included, reads the species from the sighting, so they all follow.
    What the AI had said is kept (bbox["ai"]) so the fix can be undone. A photo with
    no sighting yet (the AI never reached it, or called it empty) gets one. Either
    way it is an animal photo a person has checked from now on.

    A sighting that was grouped with an animal of another species (Animals) leaves
    that group: a fox is not one of the boar's visits.
    """
    now = now or datetime.now(UTC)
    # The AI pass writes a photo's sighting under this same lock (classify_image).
    db.execute(select(Image.id).where(Image.id == image.id).with_for_update())
    _ensure_species(db, key, default_name(key))
    was_empty = image.is_empty_frame is True
    dets = db.scalars(select(Detection).where(Detection.image_id == image.id)).all()
    if not dets:
        det = Detection(image_id=image.id,
                        bbox={"boxes": [], BY_HAND: True, "photo_was_empty": was_empty})
        db.add(det)
        dets = [det]
    for det in dets:
        info = dict(det.bbox) if isinstance(det.bbox, dict) else {}
        if det.corrected_at is None and not info.get(BY_HAND):
            checked = det.sex_checked_at.isoformat() if det.sex_checked_at else None
            info[_AI] = {
                "species": det.species_id, "conf": det.species_conf, "sex": det.sex,
                "sex_conf": det.sex_conf, "sex_checked_at": checked,
                "group_size": det.group_size, "group_type": det.group_type,
                "photo_was_empty": was_empty,
            }
        if det.species_id != key:
            # Stag or hind, boar or sow, belong to what it was judged as.
            det.sex, det.sex_conf, det.sex_attempts, det.sex_checked_at = (
                "unknown", None, 0, None)
        det.species_id = key
        det.species_conf = 1.0
        det.group_size, det.group_type = group_type(info.get("boxes") or [], key)
        det.corrected_at, det.corrected_by = now, user_id
        det.bbox = info
    db.flush()
    other = select(Individual.id).where(Individual.species_id != key).scalar_subquery()
    db.execute(delete(DetectionIndividual).where(
        DetectionIndividual.detection_id.in_([d.id for d in dets]),
        DetectionIndividual.individual_id.in_(other),
    ))
    if image.is_empty_frame is not False:
        # Kept by hand: it shows on the map from now (routes_map.shown_after).
        image.processed_at = now
    image.is_empty_frame = False
    image.reviewed = True
    image.ai_failed_at, image.ai_attempts, image.ai_error = None, 0, None


def undo_by_hand(db: Session, image: Image) -> bool:
    """Take a hunter's fix back, to what the AI had said: its species (or "an animal
    nobody named") returns, a sighting the hunter added goes, and a photo that was
    marked "nothing in it" before the fix is again. False when nobody had fixed it."""
    db.execute(select(Image.id).where(Image.id == image.id).with_for_update())
    dets = db.scalars(select(Detection).where(
        Detection.image_id == image.id, Detection.corrected_at.isnot(None))).all()
    was_empty = False
    for det in dets:
        info = dict(det.bbox) if isinstance(det.bbox, dict) else {}
        ai = info.pop(_AI, None) or {}
        was_empty = was_empty or bool(ai.get("photo_was_empty") or info.get("photo_was_empty"))
        if info.get(BY_HAND) or not ai:
            db.delete(det)
            continue
        det.species_id, det.species_conf = ai.get("species"), ai.get("conf")
        det.sex, det.sex_conf = ai.get("sex") or "unknown", ai.get("sex_conf")
        checked = ai.get("sex_checked_at")
        det.sex_checked_at = datetime.fromisoformat(checked) if checked else None
        det.sex_attempts = 0
        det.group_size, det.group_type = ai.get("group_size"), ai.get("group_type")
        det.corrected_at, det.corrected_by = None, None
        det.bbox = info
    if was_empty:
        image.is_empty_frame = True
    db.flush()
    return bool(dets)
