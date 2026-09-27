"""Server chores that can't wait for a sign-in (app.core.startup names them).

    python -m app.manage new-secret            a fresh JWT_SECRET in backend/.env
    python -m app.manage set-password EMAIL    set someone's password

Run from the backend folder, with the server's Python (C:\\GameSense\\venv on Db01),
then restart the GameSense service.
"""
from __future__ import annotations

import getpass
import secrets
import sys
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def _read_env(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _value(lines: list[str], key: str) -> str | None:
    for line in lines:
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


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


def new_secret(path: Path = ENV_FILE) -> str:
    """Write a fresh JWT_SECRET into `path`.

    Everyone signs in again afterwards: sessions were signed with the old secret.
    Saved camera-login passwords were encrypted with a key made from the old secret
    (unless CREDENTIALS_KEY was set), so it is kept as PREVIOUS_JWT_SECRET, which
    app.core.crypto still reads with; a fresh CREDENTIALS_KEY takes over, and each
    login is saved again under it on its next fetch. Nothing has to be typed again.
    """
    lines = _read_env(path)
    old = _value(lines, "JWT_SECRET") or ""
    lines = _set(lines, "JWT_SECRET", secrets.token_urlsafe(48))
    if not _value(lines, "CREDENTIALS_KEY"):
        if old:
            lines = _set(lines, "PREVIOUS_JWT_SECRET", old)
        lines = _set(lines, "CREDENTIALS_KEY", secrets.token_urlsafe(48))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return (
        f"New JWT_SECRET written to {path}. Restart the GameSense service; everyone "
        "signs in again once. Saved camera logins keep working."
    )


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
        # Signs out every phone that had the old one, as a change in Settings does.
        user.token_version = (user.token_version or 0) + 1
        db.commit()
        return f"Password set for {user.email}. They sign in with it from now on."


def main(argv: list[str]) -> int:
    if len(argv) >= 1 and argv[0] == "new-secret":
        print(new_secret())
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
