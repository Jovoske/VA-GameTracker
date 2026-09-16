"""Deliver a notification to every device a user has subscribed.

Fire-and-forget by design. A push service answering 404 or 410 means the browser has
dropped the subscription (app removed, permission revoked) and the row goes with it;
any other failure is counted, and a subscription that fails MAX_FAILURES times in a
row is dropped too, so one dead phone cannot slow every run forever. Nothing here is
allowed to raise into the caller: a push service being down is not a reason to leave
photos unclassified.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import PushSubscription
from app.notifications.vapid import get_vapid, subject

log = get_logger(__name__)

TTL_SECONDS = 4 * 3600  # a sighting is news for an evening, not a week
MAX_FAILURES = 10


def send_to_user(db: Session, user_id: uuid.UUID, payload: dict) -> dict:
    """Push `payload` (title/body/url/tag) to each of the user's devices.

    Returns counts: sent, failed, removed, subscriptions (how many it started with).
    """
    subs = db.scalars(
        select(PushSubscription).where(PushSubscription.user_id == user_id)
    ).all()
    out = {"sent": 0, "failed": 0, "removed": 0, "subscriptions": len(subs)}
    if not subs:
        return out

    from py_vapid import Vapid
    from pywebpush import WebPushException, webpush

    vapid = Vapid.from_pem(get_vapid(db).private_pem.encode())
    data = json.dumps(payload)
    now = datetime.now(timezone.utc)

    for s in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": s.endpoint,
                    "keys": {"p256dh": s.p256dh, "auth": s.auth},
                },
                data=data,
                vapid_private_key=vapid,
                # A fresh dict every call: pywebpush writes aud/exp into it.
                vapid_claims={"sub": subject()},
                ttl=TTL_SECONDS,
                timeout=10,
            )
            s.failures = 0
            s.last_success_at = now
            out["sent"] += 1
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                log.info("push.subscription_gone", status=status, endpoint=s.endpoint[:60])
                db.delete(s)
                out["removed"] += 1
            else:
                s.failures += 1
                out["failed"] += 1
                log.warning("push.rejected", status=status, error=str(e)[:200])
                if s.failures >= MAX_FAILURES:
                    db.delete(s)
                    out["removed"] += 1
        except Exception as e:  # network, DNS, TLS — count it and move on
            s.failures += 1
            out["failed"] += 1
            log.warning("push.error", error=str(e)[:200])
            if s.failures >= MAX_FAILURES:
                db.delete(s)
                out["removed"] += 1

    db.commit()
    return out
