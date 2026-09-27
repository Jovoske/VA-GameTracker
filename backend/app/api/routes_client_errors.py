"""Crashes on hunters' phones, reported by the app itself.

A blank screen in a valley leaves no trace anywhere: the hunter kills the app,
opens it again and maybe mentions it a week later. The app now posts what broke
(the error, where it was, which build) here. Every report goes to the server log;
reports from a signed-in phone are also kept, the newest few hundred, so an admin
can read the last few in Settings without opening a log file.

Anyone can post, signed in or not (the login screen can break too), so it is
rate-limited per person and, for everyone not signed in, all together. A phone
stuck in a crash loop costs a handful of rows, not a full disk.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.security import decode_token
from app.models import ClientError, User
from app.people import name_for

router = APIRouter(tags=["client-errors"])
log = get_logger(__name__)

KINDS = {"error", "rejection", "render", "chunk"}
KEEP = 200  # rows kept; older ones go as new ones arrive
WINDOW_S = 600
PER_PERSON = 10  # reports per person per window
ANONYMOUS = 20  # reports per window from everyone not signed in, together
MAX_BODY = 16_000  # bytes; a report is a message and a stack, never more

_hits: dict[str, deque[float]] = {}
_lock = threading.Lock()


def _allow(key: str, limit: int, now: float | None = None) -> bool:
    """Sliding window: at most `limit` reports per WINDOW_S for this key."""
    now = time.monotonic() if now is None else now
    with _lock:
        q = _hits.setdefault(key, deque())
        while q and now - q[0] > WINDOW_S:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def _reset_limits() -> None:
    """For tests: forget every window."""
    with _lock:
        _hits.clear()


def _cut(n: int):
    def clean(v):
        if v is None:
            return None
        return str(v)[:n]
    return clean


class ClientErrorIn(BaseModel):
    """What the phone sends. Long fields are cut to fit rather than refused: a report
    turned away for being too long is a crash nobody hears about."""

    kind: str = "error"
    message: str
    stack: str | None = None
    route: str | None = None
    build: str | None = None

    _message = field_validator("message", mode="before")(_cut(500))
    _stack = field_validator("stack", mode="before")(_cut(4000))
    _route = field_validator("route", mode="before")(_cut(200))
    _build = field_validator("build", mode="before")(_cut(64))

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v):
        return v if v in KINDS else "error"


_optional_bearer = HTTPBearer(auto_error=False)


def _reporter(creds: HTTPAuthorizationCredentials | None, db: Session) -> User | None:
    """The signed-in person, if the report carried a good token. A bad or expired
    token is not refused: the report is still worth having, just without a name."""
    if creds is None:
        return None
    try:
        sub = decode_token(creds.credentials).get("sub")
        return db.get(User, uuid.UUID(sub)) if sub else None
    except (jwt.PyJWTError, ValueError, TypeError, AttributeError):
        return None


def device_of(user_agent: str | None) -> str:
    """"iPhone", "Android", "Windows"...: enough to tell phones apart in a list."""
    ua = user_agent or ""
    for needle, name in (
        ("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
        ("Windows", "Windows"), ("Macintosh", "Mac"), ("Linux", "Linux"),
    ):
        if needle in ua:
            return name
    return "Unknown device"


@router.post("/client-errors", status_code=202)
def report(
    body: ClientErrorIn,
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise HTTPException(413, "Report too large")
    user = _reporter(creds, db)
    key = f"user:{user.id}" if user else "anonymous"
    if not _allow(key, PER_PERSON if user else ANONYMOUS):
        raise HTTPException(429, "Too many reports. Later ones are dropped.")

    ua = (request.headers.get("user-agent") or "")[:300] or None
    log.warning(
        "client_error",
        kind=body.kind,
        message=body.message,
        route=body.route,
        build=body.build,
        user=str(user.id) if user else None,
        device=device_of(ua),
        stack=(body.stack or "")[:2000] or None,
    )
    if user is None:
        return {"status": "logged"}

    db.add(ClientError(
        user_id=user.id, kind=body.kind, message=body.message or "(no message)",
        stack=body.stack, route=body.route, build=body.build, user_agent=ua,
    ))
    db.flush()
    db.execute(delete(ClientError).where(ClientError.id.in_(
        select(ClientError.id).order_by(ClientError.created_at.desc(), ClientError.id)
        .offset(KEEP)
    )))
    db.commit()
    return {"status": "saved"}


@router.get("/client-errors")
def recent(
    _: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> list[dict]:
    """The newest reports, for the admin's Settings screen."""
    rows = db.execute(
        select(ClientError, User)
        .outerjoin(User, User.id == ClientError.user_id)
        .order_by(ClientError.created_at.desc(), ClientError.id)
        .limit(limit)
    ).all()
    return [
        {
            "id": str(e.id),
            "at": e.created_at.isoformat() if isinstance(e.created_at, datetime) else None,
            "kind": e.kind,
            "message": e.message,
            "stack": e.stack,
            "route": e.route,
            "build": e.build,
            "device": device_of(e.user_agent),
            "who": name_for(u) if u is not None else "Removed person",
        }
        for e, u in rows
    ]
