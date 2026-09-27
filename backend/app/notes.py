"""Team notes on photos: "Worth a look", and who said it.

A hunter who sees something in a photo (the big boar, third night running) marks it,
with a short note or without one, and the whole team finds it on Photos and on that
camera's sheet, newest first. Optionally one push tells the others.

Who may write is the API's business (members and admins; the author or an admin
removes). This module reads notes the way every screen shows them and composes the
team's push, which follows the same per-camera mute as the sighting alerts.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Camera, Image, Notification, NotificationPref, PhotoNote, User
from app.notifications import push
from app.people import name_for

log = get_logger(__name__)

MAX_TEXT = 140
PHOTOS_URL = "/photos"


def photo_url(image_id: uuid.UUID) -> str:
    """Where a tap on the team's push lands: that photo, open in the viewer."""
    return f"{PHOTOS_URL}?image={image_id}"


def can_write(user: User) -> bool:
    return user.role in {"admin", "member"}


def can_remove(note: PhotoNote, user: User) -> bool:
    """The author or an admin, and never a viewer (someone demoted keeps no pen)."""
    return can_write(user) and (user.role == "admin" or note.user_id == user.id)


def note_counts(db: Session, image_ids: list) -> dict:
    """{image_id: number of notes}, for the marker on a photo's tile."""
    if not image_ids:
        return {}
    rows = db.execute(
        select(PhotoNote.image_id, func.count(PhotoNote.id))
        .where(PhotoNote.image_id.in_(image_ids))
        .group_by(PhotoNote.image_id)
    ).all()
    return {r[0]: int(r[1]) for r in rows}


def serialize(note: PhotoNote, author: User | None, viewer: User) -> dict:
    return {
        "id": str(note.id),
        "image_id": str(note.image_id),
        "text": note.text,
        "name": name_for(author),
        "created_at": note.created_at,
        "mine": note.user_id is not None and note.user_id == viewer.id,
        "can_remove": can_remove(note, viewer),
    }


def notes_for(db: Session, image_ids: list, viewer: User) -> dict:
    """{image_id: [note, ...]} oldest first, so a photo's notes read as they were said."""
    if not image_ids:
        return {}
    rows = db.execute(
        select(PhotoNote, User)
        .outerjoin(User, User.id == PhotoNote.user_id)
        .where(PhotoNote.image_id.in_(image_ids))
        .order_by(PhotoNote.created_at, PhotoNote.id)
    ).all()
    out: dict = defaultdict(list)
    for note, author in rows:
        out[note.image_id].append(serialize(note, author, viewer))
    return out


def clean_text(value: str | None) -> str | None:
    """One line, trimmed, at most MAX_TEXT characters; None when nothing is said.

    Line breaks and tabs become spaces, since the note is shown as one line under the
    photo and in the strip. Other invisible characters stay: emoji are built from them.
    """
    if value is None:
        return None
    text = " ".join("".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in value).split())
    if len(text) > MAX_TEXT:
        raise ValueError(f"Keep the note to {MAX_TEXT} characters.")
    return text or None


def compose(label: str, camera: str, author: User, text: str | None) -> tuple[str, str]:
    """("Worth a look: Wild boar at Charca", "Pedro: Big boar, third night running")."""
    name = name_for(author)
    body = f"{name}: {text}" if text else f"{name} marked a photo"
    return f"Worth a look: {label} at {camera}", body


def told_about(db: Session, note: PhotoNote) -> list[Notification]:
    """The team alerts this note already made, if any.

    tell_team stamps them with the note's own time, which is how a note saved twice
    (the phone heard nothing back and tried again) is told about once.
    """
    return list(db.scalars(
        select(Notification).where(
            Notification.kind == "team_note",
            Notification.image_id == note.image_id,
            Notification.created_at == note.created_at,
        )
    ).all())


def tell_team(
    db: Session, note: PhotoNote, author: User, image: Image, camera: Camera, label: str,
    species_id: str | None = None, now: datetime | None = None,
) -> list[Notification]:
    """One in-app record for every other person who has alerts on, ready to push.

    Everyone on the estate with alerts switched on hears it, whichever animals they
    picked: a teammate pointing at a photo is not a species alert. Not the author,
    and not anyone who muted this camera. Nothing is pushed here (see deliver): a
    phone that doesn't answer must not hold up the person saving the note. The
    records carry the note's time (see told_about).
    """
    now = now or note.created_at or datetime.now(UTC)
    title, body = compose(label, camera.name, author, note.text)
    prefs = db.execute(
        select(NotificationPref.user_id, NotificationPref.muted_camera_ids)
        .join(User, User.id == NotificationPref.user_id)
        .where(
            NotificationPref.enabled.is_(True),
            NotificationPref.user_id != author.id,
            User.estate_id == camera.estate_id,
        )
    ).all()
    out = [
        Notification(
            user_id=user_id, kind="team_note", title=title, body=body,
            url=photo_url(image.id), species_id=species_id, image_id=image.id, created_at=now,
        )
        for user_id, muted in prefs
        if str(camera.id) not in set(muted or [])
    ]
    db.add_all(out)
    db.flush()
    return out


def deliver(db: Session, notification_ids: list) -> dict:
    """Push each record to its person's devices and note how it went."""
    sent = 0
    for n in db.scalars(select(Notification).where(Notification.id.in_(notification_ids))).all():
        result = push.send_to_user(db, n.user_id, {
            "title": n.title, "body": n.body, "url": n.url,
            # One banner per photo: a second note on it replaces the first.
            "tag": f"note-{n.image_id}",
            "at": n.created_at.isoformat(),
        })
        if result["sent"]:
            n.push_status = "sent"
        elif result["subscriptions"] == 0:
            n.push_status = "no_subscription"
        else:
            n.push_status = "failed"
        sent += result["sent"]
    db.commit()
    log.info("notes.told_team", notifications=len(notification_ids), pushed=sent)
    return {"pushed": sent}


def deliver_in_background(notification_ids: list) -> None:
    """deliver() on its own session, after the response has gone back."""
    from app.core import db as core_db

    try:
        with core_db.SessionLocal() as db:
            deliver(db, notification_ids)
    except Exception as e:  # a push service being down is not the note's problem
        log.warning("notes.push_failed", error=f"{type(e).__name__}: {e}"[:200])
