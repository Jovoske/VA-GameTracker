"""Notifications — what each person wants to hear about, their devices, and the log.

Every route is per-user and open to every role: a guest choosing to hear about boar
is not an admin action. Admins manage people; people manage their own alerts. That
includes muting a camera: it silences it for you, not for the team.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.i18n import species_name, t
from app.models import (
    Camera,
    Detection,
    Notification,
    NotificationPref,
    PushSubscription,
    Species,
    User,
)
from app.notifications.prefs import effective_prefs, locked_prefs, muted_cameras
from app.notifications.push import delivery as push_delivery
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
            "common_name": species_name(s.id, s.common_name),  # "Roe deer", as the app writes it
            "selected": s.id in chosen,
            "detections": int(counts.get(s.id, 0)),
        }
        for s in db.scalars(select(Species).where(Species.hidden.is_(False))).all()
    ]
    # most-seen first — the animals that actually turn up sit at the top
    species.sort(key=lambda r: (-r["detections"], r["common_name"]))
    muted = muted_cameras(db, user.id)
    row = db.get(NotificationPref, user.id)
    return {
        "enabled": enabled,
        "configured": row is not None,
        # Quiet hours ("23:00", "07:00") or none, and tonight's plan before sunset.
        "quiet_start": _hhmm(row.quiet_start) if row else None,
        "quiet_end": _hhmm(row.quiet_end) if row else None,
        "plan_push": bool(row.plan_push) if row else False,
        "species": species,
        "cameras": [
            {"id": str(c.id), "name": c.name, "alerts": str(c.id) not in muted}
            for c in _estate_cameras(db, user)
        ],
        "muted_camera_ids": sorted(muted),
        "public_key": get_vapid(db).public_key,
        "subscriptions": _subscription_count(db, user),
    }


def _hhmm(t: time | None) -> str | None:
    return t.strftime("%H:%M") if t else None


def _estate_cameras(db: Session, user: User) -> list[Camera]:
    return list(db.scalars(
        select(Camera).where(Camera.estate_id == user.estate_id).order_by(Camera.name)
    ).all())


def _camera_ids(db: Session, user: User, ids: list[str]) -> list[str]:
    """`ids` as the estate's camera ids, sorted and once each; 400 for any other."""
    known = {str(c.id) for c in _estate_cameras(db, user)}
    out, unknown = set(), []
    for raw in ids:
        try:
            key = str(uuid.UUID(str(raw)))
        except ValueError:
            key = None
        if key in known:
            out.add(key)
        else:
            unknown.append(str(raw))
    if unknown:
        raise HTTPException(400, t("alerts.unknown_camera", ids=", ".join(sorted(unknown))))
    return sorted(out)


class SettingsBody(BaseModel):
    enabled: bool | None = None
    species_ids: list[str] | None = None
    # The whole list of cameras you hear nothing from; [] turns every camera back on.
    muted_camera_ids: list[str] | None = None
    # Quiet hours on the estate's clock, "23:00" to "07:00"; `quiet: false` clears them.
    quiet: bool | None = None
    quiet_start: time | None = None
    quiet_end: time | None = None
    plan_push: bool | None = None


@router.put("/settings")
def put_settings(
    body: SettingsBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Partial update: any field may be omitted and keeps its value (or default)."""
    if body.species_ids is not None:
        known = set(db.scalars(select(Species.id)).all())
        unknown = sorted(set(body.species_ids) - known)
        if unknown:
            raise HTTPException(400, t("alerts.unknown_species", ids=", ".join(unknown)))
    muted = None
    if body.muted_camera_ids is not None:
        muted = _camera_ids(db, user, body.muted_camera_ids)
    if body.quiet and (body.quiet_start is None or body.quiet_end is None):
        raise HTTPException(400, t("alerts.quiet_needs_both"))
    if body.quiet and body.quiet_start == body.quiet_end:
        raise HTTPException(400, t("alerts.quiet_same"))
    row = locked_prefs(db, user.id)
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.species_ids is not None:
        row.species_ids = sorted(set(body.species_ids))
    if muted is not None:
        row.muted_camera_ids = muted
    if body.quiet is not None:
        row.quiet_start = _minute(body.quiet_start) if body.quiet else None
        row.quiet_end = _minute(body.quiet_end) if body.quiet else None
    if body.plan_push is not None:
        row.plan_push = body.plan_push
    row.updated_at = datetime.now(UTC)
    db.commit()
    # What was saved, whole, so the screen can show the server's copy as confirmed.
    return {
        "enabled": row.enabled, "species_ids": row.species_ids,
        "muted_camera_ids": row.muted_camera_ids,
        "quiet_start": _hhmm(row.quiet_start), "quiet_end": _hhmm(row.quiet_end),
        "plan_push": row.plan_push,
    }


def _minute(t: time | None) -> time | None:
    """To the minute, with no zone: quiet hours are on the estate's clock."""
    return t.replace(second=0, microsecond=0, tzinfo=None) if t else None


class CameraAlertsBody(BaseModel):
    alerts: bool


@router.put("/cameras/{camera_id}")
def put_camera_alerts(
    camera_id: uuid.UUID,
    body: CameraAlertsBody,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """One camera's switch: alerts from it on, or muted for you.

    One camera at a time rather than the whole list, so the switch in Settings and
    the one on the map's camera sheet can't undo each other. `enabled` says whether
    your alerts are on at all, so the screen can say when nothing will come anyway.
    """
    camera = db.scalar(select(Camera.id).where(
        Camera.id == camera_id, Camera.estate_id == user.estate_id,
    ))
    if camera is None:
        raise HTTPException(404, t("cameras.not_found"))
    row = locked_prefs(db, user.id)
    muted = set(row.muted_camera_ids or [])
    key = str(camera_id)
    if body.alerts:
        muted.discard(key)
    else:
        muted.add(key)
    row.muted_camera_ids = sorted(muted)
    row.updated_at = datetime.now(UTC)
    db.commit()
    return {
        "camera_id": key, "alerts": body.alerts, "enabled": row.enabled,
        "muted_camera_ids": row.muted_camera_ids,
    }


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
        raise HTTPException(400, t("alerts.endpoint_https"))
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
    # The app sends its subscription every time it opens (push.ts), so a row lost
    # to anything comes back by itself. The key tells it whether it subscribed under
    # the server's current one, and `enabled` whether anything will come.
    enabled, _ = effective_prefs(db, user.id)
    return {
        "status": "subscribed", "subscriptions": _subscription_count(db, user),
        "public_key": get_vapid(db).public_key, "enabled": enabled,
    }


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
    """What this user has been sent, newest first — the record behind every push.

    A quiet update inside the two-hour cooldown is not listed on its own: it is shown
    as the alert it updates, with the latest running total and how many updates there
    were. One sounder all night used to fill the list with near-identical rows and
    push the plan and the team's notes out of view.
    """
    update_of = Notification.detail["update_of"].astext
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id, update_of.is_(None))
        .order_by(Notification.created_at.desc())
        .limit(limit)
    ).all()
    latest: dict[str, Notification] = {}
    count: dict[str, int] = {}
    if rows:
        for u in db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id, update_of.in_([str(n.id) for n in rows]))
            .order_by(Notification.created_at)
        ).all():
            key = u.detail["update_of"]
            latest[key] = u
            count[key] = count.get(key, 0) + 1
    unread = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    ) or 0

    def item(n: Notification) -> dict:
        last = latest.get(str(n.id), n)
        return {
            "id": str(n.id),
            "kind": n.kind,
            "title": last.title,
            "body": last.body,
            "url": last.url,
            "species_id": n.species_id,
            "image_id": str(last.image_id) if last.image_id else None,
            "push_status": n.push_status,
            "created_at": n.created_at,
            "read_at": n.read_at,
            # Quiet updates folded into this alert, and when the last one was.
            "updates": count.get(str(n.id), 0),
            "updated_at": last.created_at if last is not n else None,
        }

    return {"unread": int(unread), "items": [item(n) for n in rows]}


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
        raise HTTPException(400, t("alerts.no_phone"))
    now = datetime.now(timezone.utc)
    n = Notification(
        user_id=user.id, kind="test", title=t("alerts.test_title"),
        body=t("alerts.test_body"), url="/settings", created_at=now,
    )
    db.add(n)
    db.flush()
    result = send_to_user(db, user.id, {
        "title": n.title, "body": n.body, "url": n.url, "tag": "test", "renotify": True,
        "at": now.isoformat(),
    })
    n.push_status = push_delivery(result)
    db.commit()
    return result
