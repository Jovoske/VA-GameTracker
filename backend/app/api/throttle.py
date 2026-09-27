"""Slowing down password guessing on the public sign-in (audit D-06).

Two rules, both kept in this process's memory (one API process serves the estate):

* Per address: 20 wrong passwords in 15 minutes from one place, and that place
  waits until the oldest of them is 15 minutes old. Production sits behind a
  Cloudflare tunnel, so every request reaches the API from the tunnel's own local
  address; the visitor's address is in CF-Connecting-IP, which is believed only
  when the request came from the tunnel (TRUSTED_PROXIES). Believed from anyone,
  a guesser would just make up a new one each time.
* Per email: a growing wait after a few wrong passwords (2 s, 4 s, 8 s ... up to a
  minute), never a lockout. A lockout would let anyone keep the owner out of their
  own app by guessing wrong on purpose; a wait costs the owner seconds and a
  guesser nearly everything. The right password afterwards works as always.

A refused attempt never checks the password, so it costs no Argon2 hashing either;
and at most a few hashes run at once (HASHING), because each takes 64 MB and a
flood of them in parallel could starve the server of memory.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import HTTPException, Request

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

IP_WINDOW_S = 15 * 60
IP_LIMIT = 20
FREE_TRIES = 3  # wrong passwords for one email before any wait
MAX_WAIT_S = 60
FORGET_S = 60 * 60  # an email with no wrong password for this long starts afresh
MAX_KEYS = 10_000  # addresses and emails remembered, at most

# Password checks running at once, and how long a sign-in waits for its turn.
HASHING = threading.BoundedSemaphore(4)
HASH_WAIT_S = 10


def client_ip(request: Request) -> str:
    """The visitor's address: CF-Connecting-IP when the request came through the
    tunnel (a trusted peer), else the address that connected."""
    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("cf-connecting-ip", "").strip()
    if forwarded:
        if peer in settings.trusted_proxies:
            return forwarded
        log.warning("login.untrusted_forwarded_for", peer=peer)
    return peer or "unknown"


def wait_for(failures: int) -> int:
    """Seconds an email waits after `failures` wrong passwords in a row."""
    if failures < FREE_TRIES:
        return 0
    return min(MAX_WAIT_S, 2 ** (failures - FREE_TRIES + 1))


@dataclass
class _Email:
    failures: int = 0
    last: float = 0.0


@dataclass
class LoginThrottle:
    clock: Callable[[], float] = time.monotonic
    _ips: dict[str, deque] = field(default_factory=dict)
    _emails: dict[str, _Email] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def check(self, ip: str, email: str) -> None:
        """Raise 429 with a Retry-After if this attempt has to wait."""
        now = self.clock()
        with self._lock:
            tries = self._ips.get(ip)
            if tries:
                while tries and now - tries[0] >= IP_WINDOW_S:
                    tries.popleft()
                if len(tries) >= IP_LIMIT:
                    wait = int(IP_WINDOW_S - (now - tries[0])) + 1
                    raise _too_many(
                        f"Too many wrong passwords from here. Try again in {_minutes(wait)}.",
                        wait)
            entry = self._emails.get(email)
            if entry is not None:
                if now - entry.last >= FORGET_S:
                    del self._emails[email]
                else:
                    wait = int(wait_for(entry.failures) - (now - entry.last) + 0.999)
                    if wait > 0:
                        raise _too_many(
                            f"Too many wrong passwords for this email. Try again in "
                            f"{wait} second{'' if wait == 1 else 's'}.", wait)

    def failed(self, ip: str, email: str) -> None:
        now = self.clock()
        with self._lock:
            self._trim(now)
            self._ips.setdefault(ip, deque()).append(now)
            entry = self._emails.setdefault(email, _Email())
            entry.failures += 1
            entry.last = now

    def succeeded(self, email: str) -> None:
        with self._lock:
            self._emails.pop(email, None)

    def reset(self) -> None:
        with self._lock:
            self._ips.clear()
            self._emails.clear()

    def _trim(self, now: float) -> None:
        """Forget old entries once there are many, so a flood of made-up emails and
        addresses can't grow this without end."""
        if len(self._ips) + len(self._emails) < MAX_KEYS:
            return
        for ip in [k for k, v in self._ips.items() if not v or now - v[-1] >= IP_WINDOW_S]:
            del self._ips[ip]
        for email in [k for k, v in self._emails.items() if now - v.last >= FORGET_S]:
            del self._emails[email]
        # Still full of fresh ones: drop the oldest half rather than grow.
        for store in (self._ips, self._emails):
            if len(store) >= MAX_KEYS // 2:
                for key in list(store)[: len(store) // 2]:
                    del store[key]


def _minutes(seconds: int) -> str:
    m = max(1, (seconds + 59) // 60)
    return f"{m} minute{'' if m == 1 else 's'}"


def _too_many(detail: str, wait: int) -> HTTPException:
    return HTTPException(429, detail, headers={"Retry-After": str(max(1, wait))})


throttle = LoginThrottle()
