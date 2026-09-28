"""Where a photo's file is: written relative to MEDIA_ROOT, found wherever it is now.

Photo and thumbnail paths used to be stored absolute (C:\\GameSense\\data\\media\\...),
so moving the media folder, off a full C: or back from the backup drive after a disk
failure, left every photo "not found" although the files were all there (audit
H-21). New rows store the path under MEDIA_ROOT, with forward slashes
("<estate>/<camera>/2026-09-01/x.jpg"), and resolve() opens either kind:

* a relative path, under today's MEDIA_ROOT;
* an absolute one where it says, when the file is there;
* an absolute one that is not there any more, under today's MEDIA_ROOT from the
  estate's folder on (or from thumbs/), which is where every importer puts them.

So moving the media folder is a change to MEDIA_ROOT and a restart, nothing more.
"""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.core.config import settings

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
THUMBS = "thumbs"


def root() -> Path:
    return Path(settings.media_root)


def stored(path: str | os.PathLike) -> str:
    """How a file is written in the database: relative to MEDIA_ROOT with forward
    slashes when it is under it, as given when it is not."""
    try:
        rel = Path(os.path.abspath(path)).relative_to(os.path.abspath(settings.media_root))
    except ValueError:
        return str(path)
    return rel.as_posix()


def _parts(value: str) -> list[str]:
    return [p for p in re.split(r"[\\/]+", value) if p]


def is_absolute(value: str) -> bool:
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


def rerooted(value: str, base: str | os.PathLike | None = None) -> str | None:
    """An absolute path from another media folder, under `base` (today's MEDIA_ROOT):
    from the estate's folder on (an estate id followed by a camera id), or from thumbs/."""
    parts, into = _parts(value), Path(base) if base is not None else root()
    for i in range(len(parts) - 2, -1, -1):
        if _UUID.fullmatch(parts[i]) and _UUID.fullmatch(parts[i + 1]):
            return str(into.joinpath(*parts[i:]))
    for i in range(len(parts) - 3, -1, -1):
        if parts[i].lower() == THUMBS:
            return str(into.joinpath(*parts[i:]))
    return None


def under(value: str, base: str | os.PathLike) -> str | None:
    """Where a stored path's file would be in a copy of the media folder at `base` (the
    backup's), whichever kind of path it is; None when that can't be told."""
    if not value:
        return None
    if not is_absolute(value):
        return str(Path(base).joinpath(*_parts(value)))
    return rerooted(value, base)


def resolve(value: str | None) -> str | None:
    """The path to open for a stored path, or None when there is none. When the file
    is nowhere to be found this is still the likeliest place, so a caller's own
    "missing" check says so."""
    if not value:
        return None
    if not is_absolute(value):
        return str(root().joinpath(*_parts(value)))
    if os.path.exists(value):
        return value
    moved = rerooted(value)
    return moved if moved is not None and os.path.exists(moved) else value


def same_file(column, path: str | os.PathLike):
    """A filter for rows that store `path`, in either form (relative or absolute)."""
    return column.in_({stored(path), str(path)})
