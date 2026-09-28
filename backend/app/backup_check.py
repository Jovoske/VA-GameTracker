"""The weekly restore rehearsal: is the newest dump a database, and are its photos in
the backup? (audit H-10)

A backup nobody has restored is a hope. deploy/restore-check.ps1 restores the newest
dump from the backup drive into a scratch database on the same server, then runs

    python -m app.backup_check --restored-db gamesense_restorecheck ^
        --media D:\\GameSense-Backup\\media --dump <the dump>

which compares it with the live database (the one DATABASE_URL names), looks for a
sample of its photos in the backup's photo folder, and writes restore-check.json
beside the job locks for Settings -> System (app.ops). With --error it records only
why the restore itself failed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.i18n import stored

# What a season is made of: a restored copy with none of these is no copy.
TABLES = ("cameras", "images", "detections", "sits", "harvests", "users", "camera_accounts")
SAMPLE = 50


def _counts(url: str) -> dict[str, int | None]:
    eng = create_engine(url)
    out: dict[str, int | None] = {}
    try:
        with eng.connect() as c:
            for table in TABLES:
                try:
                    out[table] = c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                except Exception:
                    c.rollback()
                    out[table] = None  # not in this database
    finally:
        eng.dispose()
    return out


def _sample_paths(url: str, n: int) -> list[str]:
    eng = create_engine(url)
    try:
        with eng.connect() as c:
            return list(c.execute(text(
                "SELECT original_path FROM images WHERE original_path IS NOT NULL "
                "ORDER BY random() LIMIT :n"), {"n": n}).scalars())
    finally:
        eng.dispose()


def verify(live_url: str, restored_url: str, media_dir: str | os.PathLike,
           sample: int = SAMPLE) -> dict:
    """What the restored copy holds against the live database, and how many of a sample
    of its photos the backup's photo folder has. ok only when nothing is missing."""
    from app import media

    live, restored = _counts(live_url), _counts(restored_url)
    problems = []
    for table in TABLES:
        if restored[table] is None and live[table] is not None:
            problems.append(stored("restore.no_table", table=table))
        elif live[table] and not restored[table]:
            problems.append(stored("restore.no_rows", table=table))
    paths = _sample_paths(restored_url, sample) if restored["images"] else []
    found = sum(1 for p in paths if (f := media.under(p, media_dir)) and os.path.isfile(f))
    if found < len(paths):
        problems.append(stored("restore.photos_missing", n=len(paths) - found, total=len(paths)))
    return {
        "ok": not problems,
        "tables": {t: {"live": live[t], "restored": restored[t]} for t in TABLES},
        "photos_checked": len(paths), "photos_found": found,
        "error": " ".join(problems) or None,
        # Each on its own too, so Settings can say them in its reader's language.
        "problems": problems,
    }


def record(result: dict, dump: str | None) -> dict:
    """Write restore-check.json where app.ops reads it, whole or not at all."""
    from app import jobs, ops

    out = {"finished_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "dump": Path(dump).name if dump else None, **result}
    path = jobs.data_dir() / ops.RESTORE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return out


def main(argv: list[str] | None = None) -> int:
    from app.core.config import settings

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--restored-db", required=True, help="the scratch database's name")
    parser.add_argument("--media", required=True, help="the backup's photo folder")
    parser.add_argument("--dump", help="the dump that was restored")
    parser.add_argument("--error", help="why the restore itself failed")
    args = parser.parse_args(argv)
    if args.error:
        out = record({"ok": False, "error": args.error}, args.dump)
    else:
        restored = make_url(settings.database_url).set(database=args.restored_db)
        try:
            result = verify(settings.database_url,
                            restored.render_as_string(hide_password=False), args.media)
        except Exception as e:
            result = {"ok": False,
                      "error": stored("restore.failed", error=f"{type(e).__name__}: {e}")}
        out = record(result, args.dump)
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
