"""Serve stored image files (the original and a small copy); let the user flag a frame."""
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from PIL import Image as PImage
from PIL import ImageOps
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.security import decode_token
from app.models import Camera, Image, User

router = APIRouter(prefix="/images", tags=["images"])
log = get_logger(__name__)

# auto_error=False so a missing header falls through to the ?token= fallback.
_optional_bearer = HTTPBearer(auto_error=False)

# Grids, strips and the map show photos at 56-150px. A 320px-wide WebP is sharp at
# twice that on a phone screen and a few tens of KB, where the original can be
# several MB on the estate's weak signal (audit C-04, I-18, J-14).
THUMB_WIDTH = 320
THUMB_QUALITY = 70
# A photo never changes once taken, so its small copy never does either.
THUMB_CACHE = "private, max-age=31536000, immutable"


def download_name(camera_name: str | None, captured_at) -> str:
    """`Ridge_2025-10-04_22-00.jpg`: the camera and the moment, which is what anyone
    sorting a folder of these later actually wants to know."""
    stem = re.sub(r"[^A-Za-z0-9]+", "-", camera_name or "camera").strip("-") or "camera"
    return f"{stem}_{captured_at:%Y-%m-%d_%H-%M}.jpg"


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
        )
    return FileResponse(image.original_path, media_type="image/jpeg")


def thumb_path(image_id: uuid.UUID) -> Path:
    """Where a photo's small copy lives: MEDIA_ROOT/thumbs/ab/<id>.webp.

    Keyed by the photo's id, so it can be found again without the database, and
    fanned out by the first two characters so no one folder holds a season.
    """
    name = str(image_id)
    return Path(settings.media_root) / "thumbs" / name[:2] / f"{name}.webp"


def make_thumb(source: str, dest: Path) -> None:
    """Write a THUMB_WIDTH-wide WebP of `source` to `dest`, upright.

    Written to a temporary file and renamed into place, so a request that reads it
    at the same moment never gets half a file, and two requests making the same one
    at once both end with a whole one.
    """
    with PImage.open(source) as im:
        # JPEG can decode at 1/2, 1/4 or 1/8 scale for nearly free, which matters
        # for 4608px UBox frames. Asking for a square keeps both sides >= the target,
        # so a photo that EXIF then turns on its side is still wide enough.
        im.draft("RGB", (THUMB_WIDTH, THUMB_WIDTH))
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        if im.width > THUMB_WIDTH:
            height = max(1, round(im.height * THUMB_WIDTH / im.width))
            im = im.resize((THUMB_WIDTH, height), PImage.Resampling.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dest.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as out:
                im.save(out, "WEBP", quality=THUMB_QUALITY, method=4)
            os.chmod(tmp, 0o644)  # mkstemp makes it owner-only; the originals are not
            os.replace(tmp, dest)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise


@router.get("/{image_id}/thumb")
def image_thumb(
    image_id: uuid.UUID,
    token: str | None = None,
    creds: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session = Depends(get_db),
) -> FileResponse:
    """A 320px-wide WebP of the photo, made the first time anyone asks for it.

    For every grid and strip and the map; the photo viewer keeps the original. If
    the small copy cannot be made the original is sent instead, uncached, so the
    tile still shows and the next request tries again.
    """
    image, _ = _estate_image(db, image_id, _require_user(db, creds, token))
    cached = Path(image.thumbnail_path) if image.thumbnail_path else thumb_path(image.id)
    # The small copy may outlive the original (originals are pruned after a while).
    if cached.is_file():
        return FileResponse(
            cached, media_type="image/webp", headers={"Cache-Control": THUMB_CACHE}
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
    return FileResponse(dest, media_type="image/webp", headers={"Cache-Control": THUMB_CACHE})


class FlagBody(BaseModel):
    is_empty: bool


@router.post("/{image_id}/flag")
def flag_image(
    image_id: uuid.UUID,
    body: FlagBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Manual override of the detector. Sticky — the auto-scan won't touch it again."""
    image, _ = _estate_image(db, image_id, user)
    if not body.is_empty and image.is_empty_frame is not False:
        # Kept by hand: it shows on the map from now, so it is new to whoever hasn't
        # opened its camera since (routes_map.shown_after).
        image.processed_at = datetime.now(UTC)
    image.is_empty_frame = body.is_empty
    image.reviewed = True
    db.commit()
    return {"id": str(image.id), "is_empty_frame": image.is_empty_frame, "reviewed": True}
