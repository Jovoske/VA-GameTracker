"""Server chores that can't wait for a sign-in (app.core.startup names them).

    python -m app.manage new-secret            a fresh JWT_SECRET in backend/.env
    python -m app.manage set-password EMAIL    set someone's password

Run from the backend folder, with the server's Python (C:\\GameSense\\venv on Db01),
then restart the GameSense service.
"""
from __future__ import annotations

import getpass
import os
import secrets
import sys
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


# What the server reads its secrets from. Set in the environment, they win over
# backend/.env (pydantic-settings, and serve.py loads .env without overriding), so
# a new value written to the file would never be used.
SECRET_KEYS = ("JWT_SECRET", "CREDENTIALS_KEY", "PREVIOUS_JWT_SECRET")
KEEP_PREVIOUS = 5  # older secrets kept for reading saved camera passwords


def _read_env(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _value(lines: list[str], key: str) -> str | None:
    for line in lines:
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


def env_value(path: Path, key: str) -> str | None:
    """`key` as written in the .env at `path`, or None."""
    return _value(_read_env(path), key)


def _set(lines: list[str], key: str, value: str) -> list[str]:
    out, done = [], False
    for line in lines:
        if line.strip().startswith(f"{key}=") and not done:
            out.append(f"{key}={value}")
            done = True
        elif not line.strip().startswith(f"{key}="):
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    return out


def _write(path: Path, lines: list[str]) -> None:
    """All at once where the system allows, so a job starting meanwhile never reads
    half a file."""
    text = "\n".join(lines) + "\n"
    tmp = path.with_name(path.name + ".new")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except PermissionError:  # Windows, while something has the file open
        tmp.unlink(missing_ok=True)
        path.write_text(text, encoding="utf-8")


def rotate_secret(path: Path = ENV_FILE) -> dict[str, str]:
    """Write a fresh JWT_SECRET into `path`; the values written, by name.

    Everyone signs in again afterwards: sessions were signed with the old secret.
    Saved camera-login passwords may be encrypted with a key made from the old
    secret (app.core.crypto), so it is kept in PREVIOUS_JWT_SECRET with the ones
    before it, which crypto still reads with; a fresh CREDENTIALS_KEY takes over if
    there wasn't one, and each login is saved again under it on its next fetch.
    Nothing has to be typed again.

    The old secret is the one the server runs on: this file's, the environment's,
    or the code's own default when the file has none (that default is the very one
    published with GameSense).
    """
    from app.core.config import Settings
    from app.core.crypto import previous_secrets

    current = Settings(_env_file=path)
    written = {"JWT_SECRET": secrets.token_urlsafe(48)}
    key = current.credentials_key
    if not key:
        key = written["CREDENTIALS_KEY"] = secrets.token_urlsafe(48)
    kept: list[str] = []
    for old in (current.jwt_secret, *previous_secrets(current.previous_jwt_secret)):
        if old and old != key and old not in kept:
            kept.append(old)
    if kept and "," in kept[0]:
        # One set by hand with a comma in it can't share the list: it is kept whole.
        written["PREVIOUS_JWT_SECRET"] = kept[0]
    elif kept:
        written["PREVIOUS_JWT_SECRET"] = ",".join([k for k in kept if "," not in k][:KEEP_PREVIOUS])
    lines = _read_env(path)
    for name, value in written.items():
        lines = _set(lines, name, value)
    _write(path, lines)
    return written


def new_secret(path: Path = ENV_FILE) -> str:
    """`rotate_secret`, in words for whoever ran it."""
    rotate_secret(path)
    return (
        f"New JWT_SECRET written to {path}. Restart the GameSense service; everyone "
        "signs in again once. Saved camera logins keep working."
    )


def secrets_in_environment() -> list[str]:
    return [name for name in SECRET_KEYS if os.environ.get(name)]


def set_password(email: str, password: str) -> str:
    from sqlalchemy import func, select

    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.core.startup import PUBLISHED_PASSWORDS
    from app.models import User

    if len(password) < 8:
        raise SystemExit("The password must be at least 8 characters.")
    if password in PUBLISHED_PASSWORDS:
        raise SystemExit("That is the password published with GameSense. Pick another.")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower())
                         .order_by(User.created_at).limit(1))
        if user is None:
            raise SystemExit(f"No one signs in as {email}.")
        user.password_hash = hash_password(password)
        # Signs out every phone that had the old one, as a change in Settings does,
        # and stops their alerts: a lost phone would keep showing them.
        user.token_version = (user.token_version or 0) + 1
        from app.api.routes_auth import forget_other_phones

        forget_other_phones(db, user)
        db.commit()
        return (f"Password set for {user.email}. They sign in with it from now on; "
                "their alerts come back on each phone when they sign in there again.")


def main(argv: list[str]) -> int:
    if len(argv) >= 1 and argv[0] == "new-secret":
        if found := secrets_in_environment():
            print(f"{', '.join(found)} is set in this machine's environment, which wins over "
                  f"{ENV_FILE}, so a new value written there would not be used. Remove it "
                  "from the environment (System > Environment Variables) and run this again.")
            return 1
        print(new_secret(ENV_FILE))
        return 0
    if len(argv) == 2 and argv[0] == "set-password":
        first = getpass.getpass("New password: ")
        if getpass.getpass("Same again: ") != first:
            print("Those two didn't match. Nothing was changed.")
            return 1
        print(set_password(argv[1], first))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
