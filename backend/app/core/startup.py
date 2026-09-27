"""The server refuses to start with the secrets published in this repository.

.env.example, the README and the code's own defaults are public. A server that
signs its sessions with one of them lets anyone mint a working admin sign-in; an
admin still on the published password is one guess away (audit H-14, D-06).
serve.py (how Db01 runs the API) asks refusals() before it starts and stops with
the fix in words if there are any. APP_ENV=development skips the check, for a
laptop or the Docker stack.

The fixes are one command each (app.manage): `new-secret` writes a fresh
JWT_SECRET into backend/.env, keeping the saved camera logins readable, and
`set-password EMAIL` sets a password without signing in.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_password

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


def secret_refusals() -> list[str]:
    secret = settings.jwt_secret or ""
    if secret in PUBLISHED_SECRETS:
        return [
            "JWT_SECRET in backend\\.env is the one published with GameSense, so anyone "
            "can sign in as anyone. Run: python -m app.manage new-secret"
        ]
    if len(secret) < MIN_SECRET_LEN:
        return [
            f"JWT_SECRET in backend\\.env is shorter than {MIN_SECRET_LEN} characters, "
            "short enough to guess. Run: python -m app.manage new-secret"
        ]
    return []


def password_refusals(db: Session) -> list[str]:
    """Admins whose password is the published one, or the seed about to make one."""
    from app.models import User

    admins = db.scalars(select(User).where(User.role == "admin").order_by(User.created_at)).all()
    out = [
        f"The admin {u.email} still has the password published with GameSense. "
        f"Run: python -m app.manage set-password {u.email}"
        for u in admins
        if any(verify_password(p, u.password_hash) for p in PUBLISHED_PASSWORDS)
    ]
    if not admins and settings.admin_password in PUBLISHED_PASSWORDS:
        out.append(
            "ADMIN_PASSWORD in backend\\.env is the one published with GameSense, and the "
            "first admin would be made with it. Set ADMIN_PASSWORD to a password of your own."
        )
    return out


def refusals(db: Session | None = None) -> list[str]:
    """Why this server must not start, in words; [] to go ahead."""
    if development():
        return []
    out = secret_refusals()
    if db is not None:
        out += password_refusals(db)
    return out
