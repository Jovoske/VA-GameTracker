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
never changed by the AI again, and names its visit, so the burst's other frames that
read as what the hunter corrected follow it (and go back with its Undo).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
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


# What the AI had said about a sighting before a hunter fixed it, kept in its bbox
# JSON under this key so the fix can be taken back ("Put back what the AI said"),
# with the photo's own state ("photo": checked or not, kept or empty) and the animals
# (Animals) the fix took it out of. A sighting the hunter added to a photo the AI had
# nothing on is marked BY_HAND and keeps the photo's state under "photo" itself.
_AI = "ai"
BY_HAND = "by_hand"
_PHOTO = "photo"
# A frame of a fixed visit that the hunter's word relabelled (vote_bursts): what it
# was before, so taking the fix back puts it back as it was, sex and animals included.
_BEFORE = "before_hand"


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at else None


def _at(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _hand_vote(run: list[tuple[Detection, datetime]]) -> tuple[str | None, set]:
    """The species a hunter said a visit is, and the ones they said it isn't.

    A burst is one animal, so a fix to one of its frames is a fix to the visit: the
    frames that read as what the hunter corrected (the AI's "boar" on a fox), or that
    the model could not name or was unsure of, take the hunter's word. A frame the
    model is sure is some third animal keeps it. Two frames fixed to different
    species are two animals: then the ordinary vote decides (None).
    """
    said = {det.species_id for det, _ in run if det.corrected_at is not None}
    if len(said) != 1:
        return None, set()
    winner = next(iter(said))
    away = set()
    for det, _ in run:
        info = det.bbox if isinstance(det.bbox, dict) else {}
        was = (info.get(_AI) or {}).get("species") if det.corrected_at is not None else None
        if was is not None and was != winner:
            away.add(was)
    return winner, away


def _leave_other_animals(db: Session, det: Detection, key: str | None) -> list:
    """Take the sighting out of any animal (Animals) of another species than `key`:
    a fox is not one of the boar's visits. What was taken, to put back on Undo."""
    rows = db.scalars(
        select(DetectionIndividual)
        .join(Individual, Individual.id == DetectionIndividual.individual_id)
        .where(DetectionIndividual.detection_id == det.id, Individual.species_id != key)
    ).all()
    out = [[str(r.individual_id), r.match_conf, r.confirmed_by_user] for r in rows]
    for r in rows:
        db.delete(r)
    return out


def _rejoin(db: Session, det: Detection, links: list | None) -> None:
    """Put a sighting back in the animals a fix took it out of, those still there."""
    for ind, conf, confirmed in links or []:
        ind = uuid.UUID(ind)
        if db.get(Individual, ind) is None or db.get(DetectionIndividual, (det.id, ind)):
            continue
        db.add(DetectionIndividual(detection_id=det.id, individual_id=ind,
                                   match_conf=conf, confirmed_by_user=confirmed))


def vote_bursts(db: Session, image_ids: list, changed_images: set | None = None) -> int:
    """Give every frame of a visit the species the visit's frames agree on.

    The frames around each photo just classified (same camera, each within VOTE_GAP
    of the next) vote with their confidence; a species holding most of it wins, and
    frames the model read as something else, or could not name, take its label unless
    the model was sure of its own (KEEP_OWN). A visit a hunter fixed a frame of is what
    they said (_hand_vote). The vote is taken from each frame's own reading every time,
    so a frame that joins a visit later can change the outcome, a fix taken back puts
    the visit back as the AI had it, and nothing drifts. Returns how many sightings
    changed; `changed_images` collects their photos.
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
            hand, away = _hand_vote(run) if len(run) > 1 else (None, set())
            if hand is not None:
                winner = hand
            else:
                weight: dict[str, float] = {}
                for det, _ in run:
                    sp, conf = _own(det)
                    if sp in ESTATE_KEYS:  # an older build's "moose" gets no vote
                        weight[sp] = weight.get(sp, 0.0) + conf
                winner = max(weight, key=weight.get) if weight else None
                # A frame sure of another species (a fox passing through) keeps its own
                # and has no say; the winner needs most of the rest.
                say = sum(c for sp, c in map(_own, (d for d, _ in run))
                          if sp in ESTATE_KEYS and (sp == winner or c < KEEP_OWN))
                if len(run) < 2 or winner is None or weight[winner] <= say / 2:
                    winner = None  # no visit, or no majority: every frame keeps its own
            for det, _ in run:
                if det.corrected_at is not None:
                    continue  # a hunter's fix: never the vote's to change
                sp, conf = _own(det)
                sure = sp is not None and conf >= KEEP_OWN
                if hand is not None:
                    keep = sp == winner or (sure and sp not in away)
                else:
                    keep = winner is None or sp == winner or sure
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
                    info["vote"] = {"species": label, "frames": len(run),
                                    **({"by_hand": True} if hand is not None else {})}
                    mine = [_own(d)[1] for d, _ in run if _own(d)[0] == label]
                    det.species_conf = round(sum(mine) / len(mine), 4)
                before = info.get(_BEFORE)
                if before is not None and before.get("species") == label:
                    # Back to what it was before a hunter's fix moved it: as it was.
                    det.sex, det.sex_conf = before.get("sex") or "unknown", before.get("sex_conf")
                    det.sex_checked_at = _at(before.get("sex_checked_at"))
                    det.sex_attempts = before.get("sex_attempts") or 0
                    _rejoin(db, det, before.get("links"))
                    info.pop(_BEFORE)
                else:
                    if hand is not None and label == hand:
                        if before is None:
                            info[_BEFORE] = {
                                "species": det.species_id, "sex": det.sex,
                                "sex_conf": det.sex_conf,
                                "sex_checked_at": _iso(det.sex_checked_at),
                                "sex_attempts": det.sex_attempts,
                                "links": _leave_other_animals(db, det, label),
                            }
                    else:
                        info.pop(_BEFORE, None)
                    # Stag/hind and boar/sow belong to the species they were judged as:
                    # a hind relabelled wild boar is not a sow. The cloud pass looks at
                    # it again as what it is now; "own" keeps the vote undoable.
                    det.sex, det.sex_conf, det.sex_attempts, det.sex_checked_at = (
                        "unknown", None, 0, None)
                det.species_id = label
                boxes = info.get("boxes")
                if boxes is not None:
                    det.group_size, det.group_type = group_type(boxes, label)
                det.bbox = info
                changed += 1
                if changed_images is not None:
                    changed_images.add(det.image_id)
    if changed:
        db.flush()
        log.info("species.voted", changed=changed)
    return changed


def _photo_state(image: Image) -> dict:
    """The photo as the AI left it: checked or not, kept or empty, failed or not."""
    return {
        "processed_at": _iso(image.processed_at), "reviewed": image.reviewed,
        "is_empty_frame": image.is_empty_frame, "ai_attempts": image.ai_attempts,
        "ai_failed_at": _iso(image.ai_failed_at), "ai_error": image.ai_error,
    }


def set_by_hand(db: Session, image: Image, key: str, user_id: uuid.UUID | None,
                now: datetime | None = None) -> set:
    """A hunter says the animal in `image` is `key` (the photo viewer's "Wrong?").

    Every sighting on the photo becomes that species and is marked as theirs
    (corrected_at, corrected_by): the AI never changes it again, and every count,
    the forecast included, reads the species from the sighting, so they all follow.
    What the AI had said is kept (bbox["ai"], the photo's state with it) so the fix
    can be undone. A photo with no sighting yet (the AI never reached it, or called
    it empty) gets one. Either way it is an animal photo a person has checked now.

    A burst is one animal: the other frames of the visit that read as what the
    hunter corrected follow (vote_bursts), so one boar visit fixed to a fox is one
    fox visit, not a fox and a boar. Returns those other photos.

    A sighting that was grouped with an animal of another species (Animals) leaves
    that group: a fox is not one of the boar's visits.
    """
    now = now or datetime.now(UTC)
    # The AI pass writes a photo's sighting under this same lock (classify_image).
    db.execute(select(Image.id).where(Image.id == image.id).with_for_update())
    _ensure_species(db, key, default_name(key))
    photo = _photo_state(image)
    dets = db.scalars(select(Detection).where(Detection.image_id == image.id)).all()
    if not dets:
        det = Detection(image_id=image.id, bbox={"boxes": [], BY_HAND: True, _PHOTO: photo})
        db.add(det)
        db.flush()
        dets = [det]
    for det in dets:
        info = dict(det.bbox) if isinstance(det.bbox, dict) else {}
        if det.corrected_at is None and not info.get(BY_HAND):
            info[_AI] = {
                "species": det.species_id, "conf": det.species_conf, "sex": det.sex,
                "sex_conf": det.sex_conf, "sex_checked_at": _iso(det.sex_checked_at),
                "sex_attempts": det.sex_attempts,
                "group_size": det.group_size, "group_type": det.group_type,
                _PHOTO: photo, "links": [],
            }
        taken = _leave_other_animals(db, det, key)
        if taken and info.get(_AI) is not None:
            info[_AI] = {**info[_AI], "links": [*(info[_AI].get("links") or []), *taken]}
        if det.species_id != key:
            # Stag or hind, boar or sow, belong to what it was judged as.
            det.sex, det.sex_conf, det.sex_attempts, det.sex_checked_at = (
                "unknown", None, 0, None)
        det.species_id = key
        det.species_conf = 1.0
        det.group_size, det.group_type = group_type(info.get("boxes") or [], key)
        det.corrected_at, det.corrected_by = now, user_id
        det.bbox = info
    if image.is_empty_frame is not False:
        # Kept by hand: it shows on the map from now (routes_map.shown_after).
        image.processed_at = now
    image.is_empty_frame = False
    image.reviewed = True
    image.ai_failed_at, image.ai_attempts, image.ai_error = None, 0, None
    db.flush()
    others: set = set()
    vote_bursts(db, [image.id], others)
    others.discard(image.id)
    return others


def undo_by_hand(db: Session, image: Image) -> set:
    """Take a hunter's fix back, to what the AI had said: its species (or "an animal
    nobody named") returns, a sighting the hunter added goes, and the photo is again
    as the AI left it: "nothing in it", or not checked yet, so the detector looks at
    it after all. The other frames of the visit go back with it. Returns those
    other photos (empty when nobody had fixed it)."""
    db.execute(select(Image.id).where(Image.id == image.id).with_for_update())
    dets = db.scalars(select(Detection).where(
        Detection.image_id == image.id, Detection.corrected_at.isnot(None))).all()
    photo = None
    for det in dets:
        info = dict(det.bbox) if isinstance(det.bbox, dict) else {}
        ai = info.pop(_AI, None) or {}
        photo = photo or ai.get(_PHOTO) or info.get(_PHOTO)
        if info.get(BY_HAND) or not ai:
            db.delete(det)
            continue
        det.species_id, det.species_conf = ai.get("species"), ai.get("conf")
        det.sex, det.sex_conf = ai.get("sex") or "unknown", ai.get("sex_conf")
        det.sex_checked_at = _at(ai.get("sex_checked_at"))
        det.sex_attempts = ai.get("sex_attempts") or 0
        det.group_size, det.group_type = ai.get("group_size"), ai.get("group_type")
        det.corrected_at, det.corrected_by = None, None
        det.bbox = info
        _rejoin(db, det, ai.get("links"))
    if photo:
        image.processed_at = _at(photo.get("processed_at"))
        image.reviewed = bool(photo.get("reviewed"))
        image.is_empty_frame = photo.get("is_empty_frame")
        image.ai_attempts = photo.get("ai_attempts") or 0
        image.ai_failed_at = _at(photo.get("ai_failed_at"))
        image.ai_error = photo.get("ai_error")
    db.flush()
    if not dets:
        return set()
    others: set = set()
    vote_bursts(db, [image.id], others)
    others.discard(image.id)
    return others
