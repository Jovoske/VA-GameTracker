"""Ruff, as this project uses it: no change may add a finding to a file it touches.

The backend carries findings from before ruff ran anywhere (FastAPI's Depends in
defaults, long lines, datetime.timezone.utc), and fixing them all at once would touch
most files for nothing a hunter would notice. So CI holds the line instead: for every
Python file under backend/ that changed since BASE, the count of each kind of finding
may not go up. A new file starts from nothing, so it must be clean.

    python scripts/ruff_ratchet.py BASE          # BASE: a commit, e.g. origin/main

Run from backend/. It needs git and ruff on the PATH. Exit 1 lists what got worse.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True,
                          text=True).stdout


def _findings(root: Path, files: list[str]) -> dict[str, Counter]:
    """{file: Counter(code)} for `files` (relative to backend/) under `root`."""
    present = [f for f in files if (root / f).is_file()]
    if not present:
        return {}
    run = subprocess.run(["ruff", "check", "--output-format", "json", "--exit-zero", *present],
                         cwd=root, capture_output=True, text=True, check=True)
    out: dict[str, Counter] = {}
    for item in json.loads(run.stdout or "[]"):
        name = Path(item["filename"]).resolve().relative_to(root.resolve()).as_posix()
        out.setdefault(name, Counter())[item["code"] or "syntax"] += 1
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    base = argv[0]
    changed = [p[len("backend/"):] for p in _git("diff", "--name-only", "--diff-filter=AMR",
                                                  base, "HEAD", "--", "backend").split()
               if p.endswith(".py")]
    if not changed:
        print("ruff ratchet: no Python changed under backend/")
        return 0
    now = _findings(BACKEND, changed)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "pyproject.toml").write_text(_git("show", f"{base}:backend/pyproject.toml"))
        for f in changed:
            try:
                old = _git("show", f"{base}:backend/{f}")
            except subprocess.CalledProcessError:
                continue  # new in this change: nothing to compare with
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            (root / f).write_text(old)
        # The same first-party packages, so imports sort the same way in both copies.
        for pkg in ("app", "tests", "scripts"):
            (root / pkg).mkdir(exist_ok=True)
        before = _findings(root, changed)
    worse = []
    for f in changed:
        after, was = now.get(f, Counter()), before.get(f, Counter())
        for code, n in sorted(after.items()):
            if n > was.get(code, 0):
                worse.append(f"backend/{f}: {code} {was.get(code, 0)} -> {n}")
    for line in worse:
        print(line)
    print(f"ruff ratchet: {len(changed)} changed file(s), "
          f"{'no new findings' if not worse else f'{len(worse)} got worse'}")
    return 1 if worse else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
