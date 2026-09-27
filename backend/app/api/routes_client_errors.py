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
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ValidationError, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, user_from_token
from app.core.db import get_db
from app.core.logging import get_logger
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
# A report that waited on the phone for signal says when it happened. A phone
# whose clock is far out is not believed: the report keeps its arrival time.
OLDEST_CLAIM = timedelta(days=30)
CLOCK_SLACK = timedelta(minutes=10)

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
    # When it happened, by the phone's clock. Anything unreadable is dropped, not refused.
    at: datetime | None = None

    _message = field_validator("message", mode="before")(_cut(500))
    _stack = field_validator("stack", mode="before")(_cut(4000))
    _route = field_validator("route", mode="before")(_cut(200))
    _build = field_validator("build", mode="before")(_cut(64))

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v):
        return v if v in KINDS else "error"

    @field_validator("at", mode="before")
    @classmethod
    def _at(cls, v):
        if not isinstance(v, str):
            return None
        try:
            t = datetime.fromisoformat(v)
        except ValueError:
            return None
        return t if t.tzinfo else None


async def _report_body(request: Request) -> ClientErrorIn:
    """The report, read with a cap before anything is parsed.

    Declared as a body parameter, FastAPI would read and parse the whole body before
    the handler could look at its size, and a chunked upload has no length to look
    at. This endpoint is open to anyone, so the stream is cut off at MAX_BODY.
    """
    declared = request.headers.get("content-length") or ""
    if declared.isdigit() and int(declared) > MAX_BODY:
        raise HTTPException(413, "Report too large")
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY:
            raise HTTPException(413, "Report too large")
    try:
        return ClientErrorIn.model_validate_json(bytes(raw))
    except ValidationError as e:
        raise HTTPException(422, "That isn't a crash report.") from e


def happened_at(claimed: datetime | None, now: datetime) -> datetime | None:
    """The phone's own time for the crash, when it is believable."""
    if claimed is None or claimed < now - OLDEST_CLAIM or claimed > now + CLOCK_SLACK:
        return None
    return min(claimed, now)


_optional_bearer = HTTPBearer(auto_error=False)


def _reporter(creds: HTTPAuthorizationCredentials | None, db: Session) -> User | None:
    """The signed-in person, if the report carried a good token. A bad or expired
    token is not refused: the report is still worth having, just without a name."""
    if creds is None:
        return None
    try:
        return user_from_token(creds.credentials, db)[0]
    except HTTPException:
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
    body: Annotated[ClientErrorIn, Depends(_report_body)],
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    user = _reporter(creds, db)
    key = f"user:{user.id}" if user else "anonymous"
    if not _allow(key, PER_PERSON if user else ANONYMOUS):
        raise HTTPException(429, "Too many reports. Later ones are dropped.")

    ua = (request.headers.get("user-agent") or "")[:300] or None
    when = happened_at(body.at, datetime.now(UTC))
    log.warning(
        "client_error",
        kind=body.kind,
        happened_at=when.isoformat() if when else None,
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
        happened_at=when,
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
    """The newest reports, for the admin's Settings screen. `at` is when it happened
    on the phone; `reported_at` when it reached the server, later if it waited for
    signal."""
    when = func.coalesce(ClientError.happened_at, ClientError.created_at)
    rows = db.execute(
        select(ClientError, User)
        .outerjoin(User, User.id == ClientError.user_id)
        .order_by(when.desc(), ClientError.id)
        .limit(limit)
    ).all()

    def iso(t: datetime | None) -> str | None:
        return t.isoformat() if isinstance(t, datetime) else None

    return [
        {
            "id": str(e.id),
            "at": iso(e.happened_at or e.created_at),
            "reported_at": iso(e.created_at),
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
