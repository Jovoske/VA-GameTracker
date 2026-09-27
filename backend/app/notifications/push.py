"""Deliver a notification to every device a user has subscribed.

Fire-and-forget by design. A push service answering 404 or 410 means the browser has
dropped the subscription (app removed, permission revoked) and the row goes with it.
Any other failure (the server's own internet down, DNS, a push service having a bad
hour) is counted, and says nothing about the phone: ten of them in a row used to
drop the row, so one evening's blip silently ended a hunter's alerts while Settings
still said "This phone gets alerts" (audit D-04). Now a subscription is dropped for
failing only once it has also not taken a push for EXPIRE_AFTER, and the app sends
its subscription again every time it opens (push.ts), which puts back anything lost.
Nothing here is allowed to raise into the caller: a push service being down is not a
reason to leave photos unclassified.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import PushSubscription
from app.notifications.vapid import get_vapid, subject

log = get_logger(__name__)

TTL_SECONDS = 4 * 3600  # a sighting is news for an evening, not a week
# Dropped for failing only after this many failures in a row AND no push taken for
# EXPIRE_AFTER (since it was made, if it never took one): a phone left in a drawer,
# not a night the server's internet was down.
MAX_FAILURES = 10
EXPIRE_AFTER = timedelta(days=14)


def _expired(s: PushSubscription, now: datetime) -> bool:
    if s.failures < MAX_FAILURES:
        return False
    last = s.last_success_at or s.created_at
    return last is None or now - last > EXPIRE_AFTER


def send_to_user(db: Session, user_id: uuid.UUID, payload: dict) -> dict:
    """Push `payload` (title/body/url/tag, and renotify/silent) to each of the user's
    devices. The service worker buzzes again for a replaced banner only when the
    payload says `renotify` (sw.js).

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
    now = datetime.now(UTC)

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
                if _expired(s, now):
                    db.delete(s)
                    out["removed"] += 1
        except Exception as e:  # network, DNS, TLS — count it and move on
            s.failures += 1
            out["failed"] += 1
            log.warning("push.error", error=str(e)[:200])
            if _expired(s, now):
                db.delete(s)
                out["removed"] += 1

    db.commit()
    return out


def delivery(result: dict, sent: str = "sent") -> str:
    """What the record says about a send_to_user() result: `sent` (or the word given
    for a quiet update), no_subscription when the person has no phone set up for
    alerts, failed when every phone they have refused it."""
    if result["sent"]:
        return sent
    return "no_subscription" if result["subscriptions"] == 0 else "failed"
