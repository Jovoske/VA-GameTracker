"""Native (no-Docker) service entrypoint.

Docker's compose loaded .env into the container environment; there is no such step in
the native Windows build. pydantic-settings reads .env for its own fields, but it does
NOT populate os.environ — so values read directly from the environment (FRONTEND_DIST in
app.main, ANTHROPIC_API_KEY in the Anthropic SDK) would be missing. This entrypoint loads
.env into os.environ first, then starts uvicorn, so every consumer sees the same config.

It is how Db01 runs the API, so it is also where the server refuses to start with the
secrets published in this repository (app.core.startup): the fix is printed, and the
service log keeps it. APP_ENV=development skips that, for a laptop.
"""
import os
import sys
from pathlib import Path

_env = Path(__file__).with_name(".env")
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _val = _line.split("=", 1)
        os.environ.setdefault(_key.strip(), _val.strip())


def refusals() -> list[str]:
    """Why the server must not start, in words (the database part is skipped when
    it can't be reached: the app then says so itself)."""
    from app.core.db import SessionLocal
    from app.core.startup import refusals as check

    try:
        with SessionLocal() as db:
            return check(db)
    except Exception as e:  # the database is down or not migrated yet
        print(f"Could not check the admin passwords: {type(e).__name__}", file=sys.stderr)
        return check(None)


if __name__ == "__main__":
    problems = refusals()
    if problems:
        print("GameSense will not start:", file=sys.stderr)
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        print("Then restart the GameSense service.", file=sys.stderr)
        sys.exit(2)

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("API_PORT", "8090")),
        log_level="info",
    )
