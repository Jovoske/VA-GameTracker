"""Native (no-Docker) service entrypoint.

Docker's compose loaded .env into the container environment; there is no such step in
the native Windows build. pydantic-settings reads .env for its own fields, but it does
NOT populate os.environ — so values read directly from the environment (FRONTEND_DIST in
app.main, ANTHROPIC_API_KEY in the Anthropic SDK) would be missing. This entrypoint loads
.env into os.environ first, then starts uvicorn, so every consumer sees the same config.

It is how Db01 runs the API, so it is also where the server stops running on the
secrets published in this repository (app.core.startup): a published or short
JWT_SECRET is replaced with a fresh one before the app loads, and an admin still on
the published password is named in the service log. Neither stops it starting.

    python serve.py          start the server
    python serve.py check    what starting would do about those, and whether the app
                             loads at all, changing nothing (deploy/update.ps1 asks
                             this before it deploys a new version)
"""
import os
import sys
from pathlib import Path

ENV_FILE = Path(__file__).with_name(".env")


def load_env(path: Path = ENV_FILE) -> None:
    """.env into os.environ, read as pydantic-settings, alembic and the FTP importer
    read it: quotes around a value and a trailing "# note" are not part of it. A
    value already in the environment wins (audit H-15)."""
    from dotenv import load_dotenv

    load_dotenv(path, override=False, encoding="utf-8")


def uvicorn_options() -> dict:
    return {
        "host": os.environ.get("API_HOST", "0.0.0.0"),
        "port": int(os.environ.get("API_PORT", "8090")),
        "log_level": "info",
        # The app reads the visitor's address itself, from CF-Connecting-IP, and only
        # from the tunnel (app.api.throttle.client_ip). uvicorn's own X-Forwarded-For
        # rewrite would hide which peer a request came from, and with it whether the
        # header can be believed.
        "proxy_headers": False,
    }


def prepare(*, dry_run: bool = False) -> list[str]:
    """What the server does about the published secrets as it starts, in words
    (app.core.startup). The database part is left out when it can't be reached: the
    app then says so itself."""
    from app.core import startup

    notes = [startup.replace_published_secret(ENV_FILE, dry_run=dry_run)]
    try:
        from app.core.db import SessionLocal

        with SessionLocal() as db:
            notes += startup.password_notes(db)
    except Exception as e:  # the database is down, or has no users table yet
        notes.append(f"Could not check the admin passwords: {type(e).__name__}")
    return [n for n in notes if n]


def check() -> int:
    """`serve.py check`: 0 when this version would start (what it would do printed),
    1 when the app doesn't even load."""
    for note in prepare(dry_run=True):
        print(note)
    try:
        import app.main  # noqa: F401  (everything the service would load)
    except Exception:
        import traceback

        traceback.print_exc()
        print("This version of GameSense does not load; it would not start.")
        return 1
    return 0


if __name__ == "__main__":
    load_env()
    if sys.argv[1:] == ["check"]:
        sys.exit(check())
    for note in prepare():
        print(f"GameSense: {note}", file=sys.stderr)

    import uvicorn

    uvicorn.run("app.main:app", **uvicorn_options())
