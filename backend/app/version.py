"""The app's version, and the commit the running code was checked out at.

The commit is what a deploy can check: deploy/update.ps1 restarts the service and
then asks /api/health which commit answers, so an old process that never went away
is not taken for the new version. It is read from the repository's .git folder
directly, because the service has no git on its PATH (Db01 keeps git in
C:\\GameSense\\tools), and it is read once as the process starts: that is the code
this process runs, whatever is on disk later.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

__version__ = "0.23.0"

# The repository root: backend/app/version.py -> the folder that holds backend/.
REPO = Path(__file__).resolve().parents[2]
_SHA = re.compile(r"[0-9a-f]{40}")


def _git_dir(root: Path) -> Path | None:
    dot = root / ".git"
    if dot.is_dir():
        return dot
    if dot.is_file():  # a worktree or a submodule: "gitdir: <path>"
        text = dot.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            found = Path(text[len("gitdir:"):].strip())
            return found if found.is_absolute() else (root / found).resolve()
    return None


def read_commit(root: Path = REPO) -> str | None:
    """The commit checked out in `root` now (GAMESENSE_COMMIT wins, for an install
    with no .git), or None when it can't be told."""
    given = os.environ.get("GAMESENSE_COMMIT", "").strip().lower()
    if _SHA.fullmatch(given):
        return given
    try:
        git = _git_dir(root)
        if git is None:
            return None
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head if _SHA.fullmatch(head) else None  # a detached checkout
        ref = head[len("ref:"):].strip()
        common = git
        if (git / "commondir").is_file():
            common = (git / (git / "commondir").read_text(encoding="utf-8").strip()).resolve()
        for base in (git, common):
            if (base / ref).is_file():
                sha = (base / ref).read_text(encoding="utf-8").strip()
                return sha if _SHA.fullmatch(sha) else None
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref and _SHA.fullmatch(parts[0]):
                    return parts[0]
    except (OSError, UnicodeDecodeError):
        return None
    return None


# What this process started with.
COMMIT = read_commit()
