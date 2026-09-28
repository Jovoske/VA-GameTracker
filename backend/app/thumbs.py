"""A photo's small copy: a 320px-wide WebP for every grid, strip and the map.

Made as soon as the AI pass has found an animal in a photo (checking.check_photos),
so the Photos grid at dusk costs a few tens of KB a tile from the first look rather
than the first person paying for it; and on first request for any other photo
(routes_images.image_thumb), such as an empty frame shown on request or one from
before this ran (audit C-04, I-18, J-14, E-24).
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

from PIL import Image as PImage
from PIL import ImageOps

from app import media
from app.core.config import settings

# Grids, strips and the map show photos at 56-150px. A 320px-wide WebP is sharp at
# twice that on a phone screen and a few tens of KB, where the original can be
# several MB on the estate's weak signal.
THUMB_WIDTH = 320
THUMB_QUALITY = 70


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


def ensure_thumb(image) -> bool:
    """Make the photo's small copy if it has none yet and note where it is. False
    when there is no file to make it from."""
    source = media.resolve(image.original_path)
    if not source or not os.path.exists(source):
        return False
    dest = thumb_path(image.id)
    if not dest.is_file():
        make_thumb(source, dest)
    image.thumbnail_path = media.stored(dest)
    return True
