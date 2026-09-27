"""The server never runs on the secrets published in this repository.

.env.example, the README and the code's own defaults are public. A server that
signs its sessions with one of them lets anyone mint a working admin sign-in; an
admin still on the published password is one guess away (audit H-14, D-06).

Neither stops the server from starting: an auto-deploy that took the estate's app
down until someone reached the server would be worse than the hole. Instead
serve.py (how Db01 runs the API), as it starts:

* replaces a published or short JWT_SECRET in backend/.env with a fresh one, keeping
  the saved camera logins readable (app.manage.rotate_secret). Everyone signs in
  again once.
* says in the service log which admins still have the published password. That
  password doesn't sign in from the internet (routes_auth.login); on the server's
  own network it does, so the owner can change it in Settings there, or run
  `python -m app.manage set-password EMAIL` on the server.

deploy/update.ps1 runs `serve.py check` before it deploys a new version: the same
report, changing nothing. APP_ENV=development skips all of it, for a laptop or the
Docker stack.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings

# Every JWT secret this repository has ever shipped or suggested, and the password
# its first admin is seeded with.
PUBLISHED_SECRETS = frozenset({
    "dev-secret-change-me", "dev-secret-change-me-please", "change-me", "changeme",
    "change-me-in-production", "secret",
})
PUBLISHED_PASSWORDS = ("changeme",)
MIN_SECRET_LEN = 32


def development() -> bool:
    return settings.app_env.strip().lower() in {"development", "dev"}


def secret_problem(secret: str | None) -> str | None:
    """What is wrong with `secret` as a JWT_SECRET, in words, or None."""
    secret = secret or ""
    if secret in PUBLISHED_SECRETS:
        return "was the one published with GameSense, so anyone could sign in as anyone"
    if len(secret) < MIN_SECRET_LEN:
        return f"was shorter than {MIN_SECRET_LEN} characters, short enough to guess"
    return None


def _use(values: dict[str, str]) -> None:
    """Make this process run on `values` (JWT_SECRET, ...) from here on."""
    os.environ.update(values)
    for name, value in values.items():
        setattr(settings, name.lower(), value)


def replace_published_secret(env_file: Path, *, dry_run: bool = False) -> str | None:
    """Replace a published or short JWT_SECRET before the server starts; what was
    done, in words, or None when the secret is fine."""
    from app.manage import env_value, rotate_secret

    if development():
        return None
    problem = secret_problem(settings.jwt_secret)
    if problem is None:
        return None
    in_file = env_value(env_file, "JWT_SECRET")
    if in_file and secret_problem(in_file) is None:
        # The service's own environment holds a published one over a good one in
        # the file (serve.py doesn't override the environment): the file's is used.
        if not dry_run:
            _use({"JWT_SECRET": in_file})
        return (f"JWT_SECRET in the service's environment {problem}; the one in {env_file} "
                "is used instead. Remove JWT_SECRET from the service's environment.")
    if dry_run:
        return (f"JWT_SECRET {problem}. GameSense writes a fresh one when it restarts: "
                "everyone signs in again once, saved camera logins keep working.")
    try:
        written = rotate_secret(env_file)
    except OSError as e:
        return (f"JWT_SECRET {problem}, and a fresh one couldn't be written to {env_file} "
                f"({e.strerror or e}). Run: python -m app.manage new-secret, then restart "
                "GameSense.")
    _use(written)
    return (f"JWT_SECRET {problem}: a fresh one was written to {env_file}. Everyone signs "
            "in again once; saved camera logins keep working.")


def published_password_admins(db: Session) -> list[str]:
    """The emails of admins whose password is the published one. Plain SQL on the
    columns every version of the schema has, so update.ps1 can ask before migrating."""
    from app.core.security import verify_password

    rows = db.execute(text(
        "SELECT email, password_hash FROM users WHERE role = 'admin' ORDER BY created_at"
    )).all()
    return [email for email, hashed in rows
            if any(verify_password(p, hashed or "") for p in PUBLISHED_PASSWORDS)]


def password_notes(db: Session) -> list[str]:
    """Admins on the published password, or the seed about to make one, in words."""
    if development():
        return []
    out = [
        f"The admin {email} still has the password published with GameSense. It doesn't "
        "sign in from the internet: change it in Settings on the server's own network, "
        f"or run: python -m app.manage set-password {email}"
        for email in published_password_admins(db)
    ]
    has_admin = db.execute(text("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1")).first()
    if not has_admin and settings.admin_password in PUBLISHED_PASSWORDS:
        out.append(
            "ADMIN_PASSWORD in backend\\.env is the one published with GameSense. The first "
            "admin is made with it and can sign in only on the server's own network: change "
            "it in Settings there."
        )
    return out
