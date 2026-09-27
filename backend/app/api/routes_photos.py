"""One feed of every animal photo across every camera.

The camera gallery answers "what did PL19 see", the species gallery "where were the
boar". Most evenings the question is just "what came through last night", so this
lists everything newest first, filtered by any mix of animals and cameras, and
leaves out empty frames and hidden species. The team's "Worth a look" photos have
their own strip (highlights), and one photo can be asked for by id, which is what a
push opens.
"""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.ai.checking import COULD_NOT_CHECK, NOT_CHECKED_YET, photo_states
from app.api.deps import get_current_user
from app.api.visibility import VISIBLE_ANIMAL
from app.core.db import get_db
from app.forecasting.model import class_label, sentence_case
from app.models import Camera, Detection, Image, PhotoNote, Species, User
from app.notes import note_counts, notes_for
from app.people import name_for

router = APIRouter(prefix="/photos", tags=["photos"])


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


@router.get("/filters")
def filters(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """The chips: every animal that is not hidden and every camera, with photo counts.

    Counted as the feed shows them: a photo marked "nothing in it" (a false alarm)
    or one without its file is not one of the animal's photos.
    """
    shown = (
        select(Detection.image_id, Detection.species_id)
        .join(Image, Image.id == Detection.image_id)
        .where(Image.original_path.isnot(None), Image.is_empty_frame.isnot(True))
        .subquery()
    )
    n_photos = func.count(func.distinct(shown.c.image_id))
    sp_rows = db.execute(
        select(Species.id, Species.common_name, n_photos)
        .outerjoin(shown, shown.c.species_id == Species.id)
        .where(Species.hidden.is_(False))
        .group_by(Species.id, Species.common_name)
        .order_by(n_photos.desc(), Species.common_name)
    ).all()
    # A camera no login fetches any more keeps its chip while it has photos: its
    # history is still worth filtering to.
    cam_rows = db.execute(
        select(Camera.id, Camera.name, Camera.active, func.count(Image.id))
        .outerjoin(Image, (Image.camera_id == Camera.id) & VISIBLE_ANIMAL)
        .group_by(Camera.id, Camera.name, Camera.active)
        .having(or_(Camera.active.is_(True), func.count(Image.id) > 0))
        .order_by(Camera.name)
    ).all()
    return {
        "species": [
            # Written as every tile and the map write it: "Roe deer", not "Roe Deer".
            {"id": sid, "common_name": sentence_case(name), "count": int(n)}
            for sid, name, n in sp_rows if n
        ],
        "cameras": [{"id": str(cid), "name": name, "count": int(n), "connected": bool(active)}
                    for cid, name, active, n in cam_rows],
    }


@router.get("")
def feed(
    species: str | None = Query(None, description="Comma-separated species ids; omit for all"),
    cameras: str | None = Query(None, description="Comma-separated camera ids; omit for all"),
    before: datetime | None = Query(None, description="Only photos taken before this instant"),
    before_id: uuid.UUID | None = Query(
        None, description="With `before`: the last photo of the page before (next_before_id)",
    ),
    limit: int = Query(60, ge=1, le=200),
    checked: bool = Query(
        False, description="Only photos the detector has checked and kept, as on the map",
    ),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Newest first. `next_before` and `next_before_id` page on; null on the last page.

    The page ends at a photo, not a moment: a Suntek burst can stamp three frames
    with one minute, and paging by the time alone skipped whichever of them fell
    past the page break (often the frame that shows the tusks). Asked for with
    `before` alone (an older app), it pages by time as it used to.

    `checked` leaves out frames the detector hasn't reached yet (most turn out
    empty): the camera sheet's strip asks for it so it agrees with the map's photo.
    """
    species_ids = _csv(species)
    camera_ids = []
    for c in _csv(cameras):
        try:
            camera_ids.append(uuid.UUID(c))
        except ValueError:
            continue

    q = (
        select(Image.id, Image.captured_at, Image.camera_id, Camera.name)
        .join(Camera, Camera.id == Image.camera_id)
        .where(Image.original_path.isnot(None), VISIBLE_ANIMAL)
    )
    if species_ids:
        q = q.where(
            select(Detection.id)
            .where(Detection.image_id == Image.id, Detection.species_id.in_(species_ids))
            .exists()
        )
    if camera_ids:
        q = q.where(Image.camera_id.in_(camera_ids))
    if checked:
        q = q.where(Image.is_empty_frame.is_(False))
    q = after_cursor(q, before, before_id)
    rows = db.execute(q.order_by(Image.captured_at.desc(), Image.id.desc()).limit(limit + 1)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": _items(db, rows),
        **next_cursor(rows, more),
    }


def after_cursor(q, before: datetime | None, before_id: uuid.UUID | None):
    """Photos after the page that ended at (`before`, `before_id`), newest first."""
    if before is None:
        return q
    if before_id is None:
        return q.where(Image.captured_at < before)
    return q.where(tuple_(Image.captured_at, Image.id) < tuple_(before, before_id))


def next_cursor(rows, more: bool) -> dict:
    """Where the next page starts: the last photo of this one, by time and id."""
    last = rows[-1] if more and rows else None
    return {
        "next_before": last.captured_at if last else None,
        "next_before_id": str(last.id) if last else None,
    }


def _items(db: Session, rows) -> list[dict]:
    """Feed items for rows of (id, captured_at, camera_id, name), labelled the way
    every tile is: the photo's surest sighting of a species that is not hidden, or
    "Animal" when nobody has named it. `checking` is "waiting" or "failed" while the
    AI has not finished with it, and the label says so. `notes_count` marks the
    team's notes on it. `fixed_by` names the hunter who said what it is (the photo
    viewer's "Wrong?"), when one did."""
    ids = [r.id for r in rows]
    labels: dict[uuid.UUID, tuple[str, str | None, int | None]] = {}
    fixed: dict[uuid.UUID, uuid.UUID | None] = {}
    if ids:
        drows = db.execute(
            select(
                Detection.image_id, Detection.species_id, Species.common_name, Species.hidden,
                Detection.sex, Detection.group_type, Detection.group_size, Detection.species_conf,
                Detection.corrected_at, Detection.corrected_by,
            )
            .join(Species, Species.id == Detection.species_id)
            .where(Detection.image_id.in_(ids))
            .order_by(Detection.species_conf.desc().nullslast())
        ).all()
        for d in drows:
            if d.hidden or d.image_id in labels:
                continue  # first row per image is the surest sighting
            labels[d.image_id] = (
                class_label(d.species_id, d.common_name, d.sex, d.group_type),
                d.species_id,
                d.group_size,
            )
            if d.corrected_at is not None:
                fixed[d.image_id] = d.corrected_by
    fixers = fixed_names(db, fixed.values())
    counts = note_counts(db, ids)
    # A photo nobody has named is "Animal" only once the AI has looked at it.
    states = photo_states(db, [i for i in ids if i not in labels])
    unfinished = {"waiting": NOT_CHECKED_YET, "failed": COULD_NOT_CHECK}

    items = []
    for r in rows:
        unnamed = unfinished.get(states.get(r.id), "Animal")
        label, sid, size = labels.get(r.id, (unnamed, None, None))
        items.append({
            "image_id": str(r.id),
            "file_url": f"/api/images/{r.id}/file",
            "captured_at": r.captured_at,
            "camera": r.name,
            "camera_id": str(r.camera_id),
            "label": label,
            "species_id": sid,
            "group_size": size,
            "notes_count": counts.get(r.id, 0),
            "checking": states.get(r.id),
            "fixed_by": fixers.get(fixed[r.id]) if r.id in fixed else None,
        })
    return items


def fixed_names(db: Session, user_ids) -> dict:
    """{user id: the name "Fixed by …" shows}; a removed login is "a hunter"."""
    ids = {u for u in user_ids if u is not None}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    out: dict = {uid: name_for(u) for uid, u in users.items()}
    out[None] = "a hunter"
    for uid in ids - users.keys():
        out[uid] = "a hunter"
    return out


@router.get("/highlights")
def highlights(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    camera_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict:
    """The team's "Worth a look" photos, the most recently marked first.

    Each is a feed item with its notes (oldest first: who said what, and when, and
    whether it is yours to remove). `camera_id` narrows it to one camera, for its
    sheet on the map. Photos marked "nothing in it" and photos of hidden species
    never show, even with a note on them.
    """
    marked = func.max(PhotoNote.created_at).label("marked_at")
    q = (
        select(Image.id, Image.captured_at, Image.camera_id, Camera.name, marked)
        .join(PhotoNote, PhotoNote.image_id == Image.id)
        .join(Camera, Camera.id == Image.camera_id)
        .where(
            Camera.estate_id == user.estate_id, Image.original_path.isnot(None), VISIBLE_ANIMAL,
        )
        .group_by(Image.id, Camera.id)
        .order_by(marked.desc(), Image.id.desc())
        .limit(limit)
    )
    if camera_id is not None:
        q = q.where(Image.camera_id == camera_id)
    rows = db.execute(q).all()
    notes = notes_for(db, [r.id for r in rows], user)
    items = _items(db, rows)
    for item, r in zip(items, rows, strict=True):
        item["notes"] = notes.get(r.id, [])
        item["marked_at"] = r.marked_at
    return {"items": items}


@router.get("/{image_id}")
def one_photo(
    image_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """One photo as the feed lists it, for a link that names it (a push, a note).

    The feed pages newest first, so the photo a push was about can be pages down by
    the time it is tapped. 404 when it is gone or no longer shown (marked "nothing
    in it", or only a hidden species in it).
    """
    row = db.execute(
        select(Image.id, Image.captured_at, Image.camera_id, Camera.name)
        .join(Camera, Camera.id == Image.camera_id)
        .where(
            Image.id == image_id, Camera.estate_id == user.estate_id,
            Image.original_path.isnot(None), VISIBLE_ANIMAL,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "That photo isn't available any more.")
    return _items(db, [row])[0]
