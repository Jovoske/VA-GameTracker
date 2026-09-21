"""Notifications — what each person wants to hear about, their devices, and the log.

Every route is per-user and open to every role: a guest choosing to hear about boar
is not an admin action. Admins manage people; people manage their own alerts.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import Detection, Notification, NotificationPref, PushSubscription, Species, User
from app.notifications.prefs import effective_prefs
from app.notifications.push import send_to_user
from app.notifications.vapid import get_vapid

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _subscription_count(db: Session, user: User) -> int:
    return int(
        db.scalar(
            select(func.count(PushSubscription.id)).where(PushSubscription.user_id == user.id)
        ) or 0
    )


@router.get("/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """The user's preferences plus everything the settings screen needs to act on them."""
    enabled, selected = effective_prefs(db, user.id)
    chosen = set(selected)
    counts = dict(
        db.execute(
            select(Detection.species_id, func.count(Detection.id)).group_by(Detection.species_id)
        ).all()
    )
    species = [
        {
            "id": s.id,
            "common_name": s.common_name,
            "selected": s.id in chosen,
            "detections": int(counts.get(s.id, 0)),
        }
        for s in db.scalars(select(Species).where(Species.hidden.is_(False))).all()
    ]
    # most-seen first — the animals that actually turn up sit at the top
    species.sort(key=lambda r: (-r["detections"], r["common_name"]))
    return {
        "enabled": enabled,
        "configured": db.get(NotificationPref, user.id) is not None,
        "species": species,
        "public_key": get_vapid(db).public_key,
        "subscriptions": _subscription_count(db, user),
    }


class SettingsBody(BaseModel):
    enabled: bool | None = None
    species_ids: list[str] | None = None


@router.put("/settings")
def put_settings(
    body: SettingsBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Partial update: either field may be omitted and keeps its value (or default)."""
    row = db.get(NotificationPref, user.id)
    if row is None:
        enabled, selected = effective_prefs(db, user.id)
        row = NotificationPref(user_id=user.id, enabled=enabled, species_ids=selected)
        db.add(row)
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.species_ids is not None:
        known = set(db.scalars(select(Species.id)).all())
        unknown = sorted(set(body.species_ids) - known)
        if unknown:
            raise HTTPException(400, f"Unknown species: {', '.join(unknown)}")
        row.species_ids = sorted(set(body.species_ids))
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"enabled": row.enabled, "species_ids": row.species_ids}


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeBody(BaseModel):
    endpoint: str
    keys: SubscriptionKeys
    user_agent: str | None = None


@router.post("/subscriptions")
def subscribe(
    body: SubscribeBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Register this browser's push endpoint. Re-posting the same endpoint updates it."""
    if not body.endpoint.startswith("https://"):
        raise HTTPException(400, "Push endpoint must be an https URL")
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=body.endpoint, user_id=user.id, p256dh="", auth="")
        db.add(sub)
    # A phone that signs in as someone else re-homes its subscription: pushes go to
    # whoever is signed in on that device, never to the previous person.
    sub.user_id = user.id
    sub.p256dh = body.keys.p256dh
    sub.auth = body.keys.auth
    sub.user_agent = (body.user_agent or "")[:300] or None
    sub.failures = 0
    db.commit()
    return {"status": "subscribed", "subscriptions": _subscription_count(db, user)}


class UnsubscribeBody(BaseModel):
    endpoint: str


@router.delete("/subscriptions")
def unsubscribe(
    body: UnsubscribeBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub is not None and sub.user_id == user.id:
        db.delete(sub)
        db.commit()
    return {"status": "removed", "subscriptions": _subscription_count(db, user)}


@router.get("")
def feed(
    limit: int = Query(30, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """What this user has been sent, newest first — the record behind every push."""
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    ).all()
    unread = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    ) or 0
    return {
        "unread": int(unread),
        "items": [
            {
                "id": str(n.id),
                "kind": n.kind,
                "title": n.title,
                "body": n.body,
                "url": n.url,
                "species_id": n.species_id,
                "image_id": str(n.image_id) if n.image_id else None,
                "push_status": n.push_status,
                "created_at": n.created_at,
                "read_at": n.read_at,
            }
            for n in rows
        ],
    }


@router.post("/read")
def mark_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    res = db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    db.commit()
    return {"marked": int(res.rowcount or 0)}


@router.post("/test")
def send_test(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Push a test message to every device this user has subscribed."""
    if _subscription_count(db, user) == 0:
        raise HTTPException(
            400, "No phone is getting alerts yet. Turn alerts on from that phone first."
        )
    now = datetime.now(timezone.utc)
    n = Notification(
        user_id=user.id, kind="test", title="Test alert",
        body="Alerts are working on this phone.", url="/settings", created_at=now,
    )
    db.add(n)
    db.flush()
    result = send_to_user(db, user.id, {
        "title": n.title, "body": n.body, "url": n.url, "tag": "test", "at": now.isoformat(),
    })
    n.push_status = "sent" if result["sent"] else "failed"
    db.commit()
    return result
