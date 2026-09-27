"""Serve stored image files (the original and a small copy); let the user flag a frame
or say what is in it."""
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated
from zoneinfo import ZoneInfo

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import species as species_ai
from app.ai.checking import hunter_decided
from app.ai.classifier import ESTATE_KEYS
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.security import decode_token
from app.forecasting.model import class_label
from app.models import Camera, Detection, Image, Species, User
from app.thumbs import make_thumb, thumb_path

router = APIRouter(prefix="/images", tags=["images"])
log = get_logger(__name__)

# auto_error=False so a missing header falls through to the ?token= fallback.
_optional_bearer = HTTPBearer(auto_error=False)

# A photo never changes once taken (its file is written whole, once), so neither it
# nor its small copy (app.thumbs) does: the phone keeps both, and paging back through
# a night on a weak signal costs nothing the second time.
PHOTO_CACHE = "private, max-age=31536000, immutable"

VIEWERS_LOOK = "Viewers can look at the photos but can't change them."


def download_name(camera_name: str | None, captured_at) -> str:
    """`Ridge_2025-10-04_22-00-15.jpg`: the camera and the moment, which is what anyone
    sorting a folder of these later actually wants to know.

    On the estate's clock, whatever zone the database answers in: a 22:05 photo was
    saved as 20-05 where Postgres runs in UTC. With the seconds, so the hour the
    clocks go back (02:00-03:00 twice on the last Sunday of October) doesn't give
    two photos one name.
    """
    stem = re.sub(r"[^A-Za-z0-9]+", "-", camera_name or "camera").strip("-") or "camera"
    if captured_at.tzinfo is not None:
        captured_at = captured_at.astimezone(ZoneInfo(settings.estate_timezone))
    return f"{stem}_{captured_at:%Y-%m-%d_%H-%M-%S}.jpg"


def _require_user(
    db: Session, creds: HTTPAuthorizationCredentials | None, token: str | None,
) -> User:
    # Trail cameras photograph people, not only animals, so photos are not open to
    # anyone holding a UUID. An <img> tag cannot send an Authorization header, so
    # the token may arrive as ?token= instead. Query-string tokens can leak via proxy
    # logs and Referer, so this is a deliberate trade rather than a clean win;
    # short-lived per-image signed URLs remain the better answer.
    raw = (creds.credentials if creds else None) or token
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to view photos.")
    expired = HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Sign in again.")
    try:
        user_id = uuid.UUID(decode_token(raw).get("sub"))
    except (jwt.PyJWTError, ValueError, TypeError, AttributeError):
        raise expired from None
    # A login the admin removed stops working for photos too, as it does everywhere.
    user = db.get(User, user_id)
    if user is None:
        raise expired
    return user


def _estate_image(db: Session, image_id: uuid.UUID, user: User) -> tuple[Image, Camera]:
    """The photo and its camera, if it is on this person's estate; 404 otherwise."""
    row = db.execute(
        select(Image, Camera)
        .join(Camera, Camera.id == Image.camera_id)
        .where(Image.id == image_id, Camera.estate_id == user.estate_id)
    ).first()
    if row is None:
        raise HTTPException(404, "Photo not found.")
    return row[0], row[1]


@router.get("/{image_id}/file")
def image_file(
    image_id: uuid.UUID,
    token: str | None = None,
    download: bool = False,
    creds: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session = Depends(get_db),
) -> FileResponse:
    image, cam = _estate_image(db, image_id, _require_user(db, creds, token))
    if not image.original_path or not os.path.exists(image.original_path):
        raise HTTPException(404, "Photo not found.")
    if download:
        # Content-Disposition: attachment, so the lightbox's Download button saves
        # a file instead of opening the photo in a tab the user then has to leave.
        return FileResponse(
            image.original_path,
            media_type="image/jpeg",
            filename=download_name(cam.name, image.captured_at),
            headers={"Cache-Control": PHOTO_CACHE},
        )
    return FileResponse(image.original_path, media_type="image/jpeg",
                        headers={"Cache-Control": PHOTO_CACHE})


@router.get("/{image_id}/thumb")
def image_thumb(
    image_id: uuid.UUID,
    token: str | None = None,
    creds: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session = Depends(get_db),
) -> FileResponse:
    """A 320px-wide WebP of the photo (app.thumbs): made by the AI pass once it has
    found an animal in it, or here the first time anyone asks for it.

    For every grid and strip and the map; the photo viewer keeps the original. If
    the small copy cannot be made the original is sent instead, uncached, so the
    tile still shows and the next request tries again.
    """
    image, _ = _estate_image(db, image_id, _require_user(db, creds, token))
    cached = Path(image.thumbnail_path) if image.thumbnail_path else thumb_path(image.id)
    # The small copy may outlive the original (originals are pruned after a while).
    if cached.is_file():
        return FileResponse(
            cached, media_type="image/webp", headers={"Cache-Control": PHOTO_CACHE}
        )
    if not image.original_path or not os.path.exists(image.original_path):
        raise HTTPException(404, "Photo not found.")

    dest = thumb_path(image.id)
    try:
        make_thumb(image.original_path, dest)
    except Exception as e:  # a corrupt upload, an odd format, a full disk
        log.warning("thumb.failed", image_id=str(image.id), error=f"{type(e).__name__}: {e}")
        return FileResponse(
            image.original_path, media_type="image/jpeg",
            headers={"Cache-Control": "private, no-cache"},
        )
    if image.thumbnail_path != str(dest):
        image.thumbnail_path = str(dest)
        db.commit()
    return FileResponse(dest, media_type="image/webp", headers={"Cache-Control": PHOTO_CACHE})


class FlagBody(BaseModel):
    is_empty: bool


@router.post("/{image_id}/flag")
def flag_image(
    image_id: uuid.UUID,
    body: FlagBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Manual override of the detector. Sticky — the auto-scan won't touch it again.
    Members and admins: it hides the photo (or brings it back) for everyone."""
    if user.role == "viewer":
        raise HTTPException(403, VIEWERS_LOOK)
    image, _ = _estate_image(db, image_id, user)
    if not body.is_empty and image.is_empty_frame is not False:
        # Kept by hand: it shows on the map from now, so it is new to whoever hasn't
        # opened its camera since (routes_map.shown_after).
        image.processed_at = datetime.now(UTC)
    elif image.processed_at is None:
        # Decided by a hunter before the detector got to it: the detector never will
        # now, and without this its night stayed "not checked" for good.
        image.processed_at = datetime.now(UTC)
    image.is_empty_frame = body.is_empty
    image.reviewed = True
    # A photo the AI gave up on is judged now: not "couldn't check" any more.
    hunter_decided(image, keep=not body.is_empty)
    db.commit()
    return {"id": str(image.id), "is_empty_frame": image.is_empty_frame, "reviewed": True}


class SpeciesBody(BaseModel):
    species_id: str


def _fixed(db: Session, image: Image, camera: Camera, visit: set | None = None) -> dict:
    """The photo as the feed lists it after a fix (its label as every tile writes it,
    who fixed it), and whether it still shows: `hidden` when the animal is one hidden
    in Settings, `empty` when it is marked "nothing in it". `visit`: the other photos
    of the burst that followed the fix (or its Undo), each the same way, oldest first."""
    from app.api.routes_photos import _items

    others = [] if not visit else [
        _fixed(db, other, camera)
        for other in db.scalars(
            select(Image).where(Image.id.in_(visit)).order_by(Image.captured_at)
        )
    ]
    row = SimpleNamespace(id=image.id, captured_at=image.captured_at, camera_id=camera.id,
                          name=camera.name)
    item = _items(db, [row])[0]
    top = db.execute(
        select(Detection, Species)
        .join(Species, Species.id == Detection.species_id)
        .where(Detection.image_id == image.id)
        .order_by(Detection.species_conf.desc().nullslast())
        .limit(1)
    ).first()
    hidden = top is not None and top[1].hidden and item["species_id"] is None
    if hidden:
        det, sp = top
        item.update(label=class_label(sp.id, sp.common_name, det.sex, det.group_type),
                    species_id=sp.id, group_size=det.group_size)
    return {**item, "hidden": hidden, "empty": image.is_empty_frame is True,
            **({"visit": others} if visit is not None else {})}


@router.post("/{image_id}/species")
def set_species(
    image_id: uuid.UUID,
    body: SpeciesBody,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """"It's a …": a member or admin says what the animal is, from the photo viewer.

    Any animal that can be on the estate (the species list the viewer offers,
    GET /species/choices). The fix is the hunter's and the AI never changes it back;
    every list, count and the forecast read the species from the sighting, so they
    all follow at once. The rest of the burst follows too (species.set_by_hand), and
    `visit` lists those photos as they are now. "Nothing in it" is POST /flag. DELETE
    takes the fix back.
    """
    if user.role == "viewer":
        raise HTTPException(403, VIEWERS_LOOK)
    key = body.species_id.strip()
    if key not in ESTATE_KEYS:
        raise HTTPException(422, "Pick one of the animals on the list.")
    image, camera = _estate_image(db, image_id, user)
    if not image.original_path:
        raise HTTPException(409, "This photo has no picture yet, so there's nothing to fix.")
    visit = species_ai.set_by_hand(db, image, key, user.id)
    db.commit()
    return _fixed(db, image, camera, visit)


@router.delete("/{image_id}/species")
def undo_species(
    image_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Take a hunter's fix back to what the AI had said (the viewer's Undo), the rest
    of its burst with it (`visit`)."""
    if user.role == "viewer":
        raise HTTPException(403, VIEWERS_LOOK)
    image, camera = _estate_image(db, image_id, user)
    visit = species_ai.undo_by_hand(db, image)
    db.commit()
    return _fixed(db, image, camera, visit)
