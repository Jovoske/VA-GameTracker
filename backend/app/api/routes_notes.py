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
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes_map import latest_photos
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


@router.post("/images/{image_id}/notes", status_code=201)
def add_note(
    image_id: uuid.UUID, body: NoteBody, user: CurrentUser, db: DB, background: BackgroundTasks,
) -> dict:
    """Mark the photo "Worth a look", with an optional note of up to 140 characters.

    With tell_team, everyone else who has alerts on gets one push (unless they muted
    this camera); `told` is how many people that is. The push goes out after this
    answers, so a slow phone never holds up the save.
    """
    if not can_write(user):
        raise HTTPException(403, "Viewers can see notes but not add them.")
    try:
        text = clean_text(body.text)
    except ValueError as e:
        # Said in words, not as a validation list the phone can't show.
        raise HTTPException(422, str(e)) from None
    image, camera = _photo(db, image_id, user)
    note = PhotoNote(image_id=image.id, user_id=user.id, text=text)
    db.add(note)
    db.flush()
    told = []
    if body.tell_team:
        shown = latest_photos(db, [image.id]).get(image.id)
        told = tell_team(
            db, note, user, image, camera,
            label=shown["label"] if shown else "Animal",
            species_id=shown["species_id"] if shown else None,
        )
    db.commit()
    if told:
        background.add_task(deliver_in_background, [n.id for n in told])
    return {
        "note": serialize(note, user, user),
        **_notes(db, image.id, user),
        "told": len(told),
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
