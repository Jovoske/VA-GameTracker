"""Species — list them, name them, toggle hunting-advice visibility, and browse what
was spotted."""
import unicodedata
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import and_, false, func, or_, select, true
from sqlalchemy.orm import Session

from app.ai.classifier import ESTATE_KEYS, default_name
from app.ai.species import BIG_GAME
from app.api.deps import get_current_admin, get_current_user
from app.api.routes_photos import after_cursor, fixed_names, next_cursor
from app.api.visibility import NO_PEOPLE, VISIBLE_ANIMAL, VISIBLE_SIGHTING
from app.core.db import get_db
from app.forecasting.model import class_label
from app.i18n import DEFAULT, LANGUAGES, current, renamed, species_name, t, tr, use
from app.models import Camera, Detection, Image, Species, User
from app.notes import note_counts

router = APIRouter(prefix="/species", tags=["species"])


@router.get("")
def list_species(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    """Every species with its detection count and whether it shows in hunting advice."""
    counts = dict(
        db.execute(
            select(Detection.species_id, func.count(Detection.id)).group_by(Detection.species_id)
        ).all()
    )
    rows = db.scalars(select(Species)).all()
    out = [
        {
            "id": s.id,
            # What the app calls it, in the reader's language: the admin's own name
            # for it when there is one (`custom`), in every language.
            "common_name": species_name(s.id, s.common_name),
            "custom": renamed(s.id, s.common_name),
            "huntable": s.huntable,
            "hidden": s.hidden,
            "is_priority": s.is_priority,
            # What the app calls it unless an admin names it otherwise (Settings).
            "default_name": species_name(s.id, None),
            # The big game the advice is for (ai.species.BIG_GAME): Settings asks
            # once about any other animal still in the advice from before new ones
            # started off.
            "big_game": s.id in BIG_GAME,
            "detections": int(counts.get(s.id, 0)),
        }
        for s in rows
    ]
    # most-seen first, so the species that actually matter sit at the top of the list
    out.sort(key=lambda r: (-r["detections"], r["common_name"]))
    return out


@router.get("/spotted")
def spotted(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    """Every species seen on the estate, with its class breakdown (Stag/Hind, Boar/Sow…).

    This is the tracking view — it always includes every species, regardless of the
    huntable (advice) toggle. A photo marked "nothing in it" (a false alarm) is not
    one of anything's photos.
    """
    rows = db.execute(
        select(
            Detection.species_id, Species.common_name, Detection.sex, Detection.group_type,
            func.count(func.distinct(Detection.image_id)), func.max(Image.captured_at),
        )
        .join(Image, Image.id == Detection.image_id)
        .join(Species, Species.id == Detection.species_id)
        .where(Image.original_path.isnot(None), VISIBLE_SIGHTING)
        .group_by(Detection.species_id, Species.common_name, Detection.sex, Detection.group_type)
    ).all()

    agg: dict[str, dict] = {}
    for sid, cn, sex, gt, cnt, last in rows:
        s = agg.setdefault(sid, {"id": sid, "name": species_name(sid, cn), "count": 0,
                                 "last_seen": None, "classes": {}})
        s["count"] += int(cnt)
        lbl = class_label(sid, cn, sex, gt)
        s["classes"][lbl] = s["classes"].get(lbl, 0) + int(cnt)
        if last is not None and (s["last_seen"] is None or last > s["last_seen"]):
            s["last_seen"] = last

    out = []
    for sid, s in agg.items():
        thumb = db.scalar(
            select(Image.id)
            .join(Detection, Detection.image_id == Image.id)
            .where(Detection.species_id == sid, Image.original_path.isnot(None),
                   Image.is_empty_frame.isnot(True), NO_PEOPLE)
            .order_by(Image.captured_at.desc())
            .limit(1)
        )
        out.append({
            "id": sid,
            "name": s["name"],
            "count": s["count"],
            "last_seen": s["last_seen"],
            "thumb_image_id": str(thumb) if thumb else None,
            "classes": [
                {"label": lbl, "count": c}
                for lbl, c in sorted(s["classes"].items(), key=lambda kv: -kv[1])
            ],
        })
    out.sort(key=lambda r: -r["count"])
    return out


# Stag / Hind / Hind + calf / Red deer (herd) / Red deer and the boar classes, as SQL,
# so a class gallery pages in the database (forecasting.model.class_label in reverse):
# the young one's group type, then the group's. The labels come from class_label, so
# a species renamed in Settings is found under its new name.
_CLASSES = {
    "red_deer": ("hind_with_calf", "herd"),
    "wild_boar": ("sow_with_piglets", "sounder"),
}


def class_filter(species_id: str, common_name: str | None, label: str | None):
    """SQL on Detection for the photos class_label() calls `label` (all when None),
    in any of the app's languages: the app sends back the label it was shown."""
    if not label:
        return true()

    def names(sex: str | None, gt: str | None) -> set[str]:
        out = set()
        for lang in LANGUAGES:
            with use(lang):
                out.add(class_label(species_id, common_name, sex, gt))
        return out

    classes = _CLASSES.get(species_id)
    if classes is None:
        return true() if label in names(None, None) else false()
    young_type, group_type = classes

    not_young = or_(Detection.group_type.is_(None), Detection.group_type != young_type)
    unsexed = Detection.sex.notin_(("male", "female"))
    # A list, not a dict: a boar renamed "Boar" is the unsexed ones and the males both.
    hits = [where for lbls, where in (
        (names(None, young_type), Detection.group_type == young_type),
        (names("male", None), and_(not_young, Detection.sex == "male")),
        (names("female", None), and_(not_young, Detection.sex == "female")),
        (names(None, group_type), and_(unsexed, Detection.group_type == group_type)),
        (names(None, None), and_(unsexed, or_(
            Detection.group_type.is_(None),
            Detection.group_type.notin_((young_type, group_type)),
        ))),
    ) if label in lbls]
    return or_(*hits) if hits else false()


def _gallery(db: Session, species_id: str, label: str | None, before: datetime | None,
             before_id: uuid.UUID | None, limit: int) -> tuple[list[dict], bool, list]:
    """One page of a species' photos, newest first, and whether there are more.

    One row per photo (a photo with two sightings of the species is one photo), only
    photos that show (not "nothing in it", not a hidden species' alone), paged in SQL
    by (time, id) like the feed: it used to read every sighting of the season and
    stop at 300, while the chip said 684.
    """
    sp = db.get(Species, species_id)
    if sp is not None and sp.hidden:
        # A species hidden in Settings has no gallery, even where it shares a photo
        # with one that shows (api/visibility.VISIBLE_SIGHTING).
        return [], False, []
    # The photo's surest sighting of the species (of the class asked for): one row a photo.
    top = (
        select(Detection.image_id, Detection.sex, Detection.group_type, Detection.group_size,
               Detection.corrected_at, Detection.corrected_by)
        .where(Detection.species_id == species_id,
               class_filter(species_id, sp.common_name if sp else None, label))
        .distinct(Detection.image_id)
        .order_by(Detection.image_id, Detection.species_conf.desc().nullslast())
        .subquery()
    )
    q = (
        select(Image.id, Image.captured_at, Camera.name, top.c.sex, top.c.group_type,
               top.c.group_size, top.c.corrected_at, top.c.corrected_by)
        .join(top, top.c.image_id == Image.id)
        .join(Camera, Camera.id == Image.camera_id)
        .where(Image.original_path.isnot(None), VISIBLE_ANIMAL)
    )
    q = after_cursor(q, before, before_id)
    rows = db.execute(q.order_by(Image.captured_at.desc(), Image.id.desc()).limit(limit + 1)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    counts = note_counts(db, [r.id for r in rows])
    fixers = fixed_names(db, [r.corrected_by for r in rows if r.corrected_at is not None])
    name = sp.common_name if sp else None
    items = [{
        "image_id": str(r.id),
        "file_url": f"/api/images/{r.id}/file",
        "captured_at": r.captured_at,
        "camera": r.name,
        "label": class_label(species_id, name, r.sex, r.group_type),
        "species_id": species_id,
        "group_size": r.group_size,
        "notes_count": counts.get(r.id, 0),
        "fixed_by": fixers.get(r.corrected_by) if r.corrected_at is not None else None,
    } for r in rows]
    return items, more, rows


@router.get("/{species_id}/photos")
def species_photos(
    species_id: str,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    label: Annotated[str | None, Query(description="Only one class (e.g. 'Stag')")] = None,
    before: Annotated[datetime | None, Query(description="next_before, page before")] = None,
    before_id: Annotated[uuid.UUID | None, Query(description="next_before_id")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 60,
) -> dict:
    """A species' photos a page at a time, newest first, optionally one class (Stag,
    Sow + piglets…). `next_before`/`next_before_id` page on, null on the last page."""
    items, more, rows = _gallery(db, species_id, label, before, before_id, limit)
    return {"items": items, **next_cursor(rows, more)}


@router.get("/{species_id}/images")
def species_images(
    species_id: str,
    label: str | None = Query(None, description="Optional class label filter (e.g. 'Stag')"),
    limit: int = Query(300, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """The newest `limit` photos of a species, as one list: what an app from before
    /photos paging asks for. Paged in SQL all the same."""
    return _gallery(db, species_id, label, None, None, limit)[0]


@router.get("/choices")
def choices(
    _: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)],
) -> list[dict]:
    """The animals a hunter can say a photo shows (the photo viewer's "Wrong?"): every
    one that can be on the estate, by the name the app gives it.

    `likely` marks the short list the viewer opens with: the big game, and whatever
    the cameras have seen. The big game comes first, then by how often each is seen.
    `hidden` ones (Settings) are offered too: a photo said to be one leaves the lists.
    """
    rows = {s.id: s for s in db.scalars(select(Species).where(Species.id.in_(ESTATE_KEYS)))}
    seen = dict(db.execute(
        select(Detection.species_id, func.count(Detection.id))
        .where(Detection.species_id.in_(ESTATE_KEYS))
        .group_by(Detection.species_id)
    ).all())
    out = [{
        "id": key,
        "name": species_name(key, rows[key].common_name if key in rows else None),
        "hidden": bool(rows[key].hidden) if key in rows else False,
        "likely": key in BIG_GAME or seen.get(key, 0) > 0,
        "big_game": key in BIG_GAME,
        "seen": int(seen.get(key, 0)),
    } for key in ESTATE_KEYS]
    out.sort(key=lambda c: (not c["big_game"], -c["seen"], c["name"]))
    return out


class HuntableBody(BaseModel):
    huntable: bool | None = None
    hidden: bool | None = None
    # A name for it (admins). An explicit null goes back to the app's own name.
    common_name: str | None = None

    @field_validator("common_name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value):
            raise ValueError(t("species.name_hidden_chars"))
        value = " ".join(value.split())
        if not 1 <= len(value) <= 40:
            raise ValueError(t("species.name_length"))
        # Kept as typed, bar a capital to start it: Settings then shows it as the
        # tiles write it (forecasting.model.sentence_case).
        return value[:1].upper() + value[1:]


@router.patch("/{species_id}")
def set_huntable(
    species_id: str,
    body: HuntableBody,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Admin switches for one species.

    huntable: in or out of the hunting advice; photos and counts unaffected.
    hidden: out of the app altogether (photos, counts, alerts, advice). Hiding also
    takes the species out of the advice; showing it again leaves it out of the
    advice until switched back on, so nothing reappears in Tonight unasked.
    common_name: what the app calls it everywhere ("Hare" for the hares and rabbits
    the model can't tell apart, on an estate with no rabbits); null for the app's own.
    """
    sp = db.get(Species, species_id)
    if sp is None:
        raise HTTPException(404, t("species.not_found"))
    if "common_name" in body.model_fields_set:
        # The app's own name for it, as this admin reads the app (or in English), is
        # no name of theirs: a Finnish admin saving "Villisika" as it was shown keeps
        # it "Wild boar" for the others. "Jabalí" typed by an English reader is theirs.
        own = {tr(lang, f"species.{sp.id}").lower() for lang in {current(), DEFAULT}}
        given = body.common_name
        sp.common_name = default_name(sp.id) if not given or given.lower() in own else given
    if body.huntable is not None:
        sp.huntable = body.huntable
    if body.hidden is not None:
        sp.hidden = body.hidden
        if body.hidden:
            sp.huntable = False
    db.commit()
    return {
        "id": sp.id, "common_name": species_name(sp.id, sp.common_name),
        "custom": renamed(sp.id, sp.common_name),
        "default_name": species_name(sp.id, None),
        "huntable": sp.huntable, "hidden": sp.hidden,
    }
