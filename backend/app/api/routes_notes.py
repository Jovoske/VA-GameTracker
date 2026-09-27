"""Team notes on photos: mark one "Worth a look", read the notes, take yours back.

Anyone signed in reads the notes. Members and admins add them; viewers look but
don't write. The author or an admin removes one. The strips that gather them
(Photos, a camera's sheet) are GET /photos/highlights.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes_map import latest_photos
from app.api.visibility import ONLY_HIDDEN_SPECIES
from app.core.db import get_db
from app.models import Camera, Image, PhotoNote, User
from app.notes import (
    can_remove,
    can_write,
    clean_text,
    deliver_in_background,
    notes_for,
    serialize,
    tell_team,
    told_about,
)

router = APIRouter(tags=["notes"])
CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


def _photo(db: Session, image_id: uuid.UUID, user: User) -> tuple[Image, Camera]:
    """The photo and its camera, if it is this estate's; 404 otherwise."""
    row = db.execute(
        select(Image, Camera)
        .join(Camera, Camera.id == Image.camera_id)
        .where(Image.id == image_id, Camera.estate_id == user.estate_id)
    ).first()
    if row is None:
        raise HTTPException(404, "Photo not found.")
    return row[0], row[1]


def _notes(db: Session, image_id: uuid.UUID, user: User) -> dict:
    return {
        "image_id": str(image_id),
        "can_add": can_write(user),
        "notes": notes_for(db, [image_id], user).get(image_id, []),
    }


@router.get("/images/{image_id}/notes")
def photo_notes(image_id: uuid.UUID, user: CurrentUser, db: DB) -> dict:
    """The photo's notes, oldest first, and whether you may add one. Any role."""
    _photo(db, image_id, user)
    return _notes(db, image_id, user)


class NoteBody(BaseModel):
    # Optional: a mark with nothing said is still "Worth a look".
    text: str | None = None
    tell_team: bool = False
    # The phone names the note. Saving it again after hearing nothing back (a weak
    # signal) is then the same note, not a second one and not a second alert.
    id: uuid.UUID | None = None
    # The detector said "nothing in it" and the hunter says there is: keep the photo
    # as an animal photo, as its Keep button does, so the team can see what was marked.
    keep: bool = False


EMPTY_FRAME = "This photo is marked “nothing in it”. Keep it as an animal photo first."
HIDDEN_ONLY = "Only animals hidden from the app are in this photo, so the team can’t see it."


def _markable(db: Session, image: Image, keep: bool) -> bool:
    """Refuse a note on a photo the team would never see; True when `keep` un-flagged it.

    A note sends the team to the photo (the strips, a push), so it goes only on one
    the app shows: never one of nothing but hidden animals, and not one marked
    "nothing in it" unless the hunter says to keep it.
    """
    if db.scalar(select(Image.id).where(Image.id == image.id, ONLY_HIDDEN_SPECIES)) is not None:
        raise HTTPException(409, HIDDEN_ONLY)
    if not image.is_empty_frame:
        return False
    if not keep:
        raise HTTPException(409, EMPTY_FRAME)
    image.is_empty_frame = False
    image.reviewed = True  # sticky, like the Keep button: the auto-scan leaves it be
    return True


@router.post("/images/{image_id}/notes", status_code=201)
def add_note(
    image_id: uuid.UUID, body: NoteBody, user: CurrentUser, db: DB, background: BackgroundTasks,
) -> dict:
    """Mark the photo "Worth a look", with an optional note of up to 140 characters.

    With tell_team, everyone else who has alerts on gets one push (unless they muted
    this camera); `told` is how many people that is. The push goes out after this
    answers, so a slow phone never holds up the save. A second save with the same
    `id` is the same note: its words are updated, and the team is told once.
    """
    if not can_write(user):
        raise HTTPException(403, "Viewers can see notes but not add them.")
    try:
        text = clean_text(body.text)
    except ValueError as e:
        # Said in words, not as a validation list the phone can't show.
        raise HTTPException(422, str(e)) from None
    image, camera = _photo(db, image_id, user)
    kept = _markable(db, image, body.keep)
    note_id = body.id or uuid.uuid4()
    # ON CONFLICT waits for a first save still in flight, so two copies can't both land.
    fresh = db.execute(
        pg_insert(PhotoNote)
        .values(id=note_id, image_id=image.id, user_id=user.id, text=text)
        .on_conflict_do_nothing(index_elements=[PhotoNote.id])
        .returning(PhotoNote.id)
    ).first() is not None
    note = db.get(PhotoNote, note_id)
    if note is None or note.user_id != user.id or note.image_id != image.id:
        db.rollback()
        raise HTTPException(409, "That note couldn’t be saved. Close it and try again.")
    if not fresh:
        note.text = text  # the words on the last try are the ones meant
    told = told_about(db, note)
    new_told = []
    if body.tell_team and not told:
        shown = latest_photos(db, [image.id]).get(image.id)
        new_told = told = tell_team(
            db, note, user, image, camera,
            label=shown["label"] if shown else "Animal",
            species_id=shown["species_id"] if shown else None,
        )
    db.commit()
    if new_told:
        background.add_task(deliver_in_background, [n.id for n in new_told])
    return {
        "note": serialize(note, user, user),
        **_notes(db, image.id, user),
        "told": len(told),
        "kept": kept,
        "again": not fresh,
    }


@router.delete("/photo-notes/{note_id}")
def remove_note(note_id: uuid.UUID, user: CurrentUser, db: DB) -> dict:
    """Take a note back: your own, or anyone's if you are an admin."""
    note = db.get(PhotoNote, note_id)
    if note is None:
        raise HTTPException(404, "That note is already gone.")
    _photo(db, note.image_id, user)  # another estate's note is not found either
    if not can_remove(note, user):
        raise HTTPException(403, "Only the person who wrote it or an admin can remove a note.")
    image_id = note.image_id
    db.delete(note)
    db.commit()
    return _notes(db, image_id, user)
